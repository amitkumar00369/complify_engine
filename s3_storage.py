"""
S3 sync layer for the Complify storage tree.
==============================================

Why this exists
----------------
The deterministic pipeline (rawdata_extractor) reads and writes hundreds of
real local files with plain `Path`/`open()` calls (PyMuPDF needs an actual
file on disk to parse a PDF, `json.dump` writes real files, etc.). Rewriting
all of that to talk to S3 directly would mean touching core, audited engine
code — out of scope and risky.

So the design is: **local disk is pure ephemeral scratch space** — used only
while a single request is being handled — and this module is the write-
through / read-through layer on top of it, at the API layer only:

    - Before anything is *read*, the current S3 copy is downloaded into the
      local scratch area first (every request re-syncs; nothing is assumed
      to already be on local disk from a previous request).
    - After anything gets written locally, it's uploaded to S3 as the
      durable copy, split by file type into two separate top-level S3
      prefixes:
          *.pdf files              -> compliance_file/...
          everything else (JSON)   -> evaluation_engine/...
    - The caller (main.py) then deletes the local scratch folder — nothing
      is meant to persist on local disk between requests. storage/ existing
      on disk at any given moment is just in-flight work, not the source of
      truth.

    local storage/standards/<family>/*.pdf        <-> s3://bucket/compliance_file/standards/<family>/*.pdf
    local storage/standards/<family>/*.json        <-> s3://bucket/evaluation_engine/standards/<family>/*.json
    local storage/runs/<run_id>/**/*.pdf           <-> s3://bucket/compliance_file/reports/<run_id>/**/*.pdf
    local storage/runs/<run_id>/**/* (everything else) <-> s3://bucket/evaluation_engine/reports/<run_id>/**/*

If S3_BUCKET_NAME is not set, every method here is a silent no-op — in that
configuration the service falls back to local disk actually persisting
(there is nowhere else for the data to live).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


EVALUATION_ENGINE_PREFIX = "evaluation_engine"
STANDARDS_PREFIX = f"{EVALUATION_ENGINE_PREFIX}/standards"          # JSON artifacts
REPORTS_PREFIX = f"{EVALUATION_ENGINE_PREFIX}/reports"               # JSON artifacts

COMPLIANCE_FILE_PREFIX = "compliance_file"
COMPLIANCE_FILE_STANDARDS_PREFIX = f"{COMPLIANCE_FILE_PREFIX}/standards"  # PDFs only
COMPLIANCE_FILE_REPORTS_PREFIX = f"{COMPLIANCE_FILE_PREFIX}/reports"       # PDFs only


class S3Storage:
    """Thin recursive-folder sync wrapper around boto3. Safe to import even
    if boto3/credentials aren't configured — it just stays disabled."""

    def __init__(self) -> None:
        self.bucket = os.environ.get("S3_BUCKET_NAME") or os.environ.get("S3_BUCKET")
        self._client = None
        if self.bucket:
            try:
                import boto3  # imported lazily so boto3 is optional if S3 is unused

                kwargs = {}
                endpoint_url = os.environ.get("S3_ENDPOINT_URL")
                if endpoint_url:
                    kwargs["endpoint_url"] = endpoint_url
                region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
                if region:
                    kwargs["region_name"] = region
                self._client = boto3.client("s3", **kwargs)
            except Exception as exc:  # noqa: BLE001
                # Don't crash the app over a storage-tier problem; just run local-only.
                print(f"[s3_storage] S3 disabled — could not create client: {exc}")
                self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None and bool(self.bucket)

    # --------------------------------------------------------------- #
    # low-level helpers
    # --------------------------------------------------------------- #

    def _key(self, prefix: str, relative: str) -> str:
        return f"{prefix.rstrip('/')}/{relative}"

    @staticmethod
    def _route(path: Path, json_prefix: str, pdf_prefix: str) -> str:
        return pdf_prefix if path.suffix.lower() == ".pdf" else json_prefix

    # --------------------------------------------------------------- #
    # split upload/download — PDFs and JSON go to different S3 prefixes
    # but live together in the same local folder
    # --------------------------------------------------------------- #

    def upload_dir_split(
        self, local_dir: Path, json_prefix: str, pdf_prefix: str,
        *, exclude_relative: set[str] | None = None,
    ) -> int:
        """Upload every file under local_dir, routing *.pdf to pdf_prefix and
        everything else to json_prefix (both relative-path-preserving).
        exclude_relative is an optional set of relative (as_posix) paths to
        skip entirely — for internal-only artifacts that are never served by
        any endpoint and would otherwise dominate upload time (e.g. the
        multi-hundred-MB llm/resolved_compliance_context.json).
        Returns the number of files uploaded. No-op (0) if S3 disabled or
        local_dir missing. Raises on failure — use the _safe variant from
        request-handling code."""
        if not self.enabled or not local_dir.is_dir():
            return 0
        skip = exclude_relative or set()
        count = 0
        for path in local_dir.rglob("*"):
            if path.is_file():
                relative = path.relative_to(local_dir).as_posix()
                if relative in skip:
                    continue
                prefix = self._route(path, json_prefix, pdf_prefix)
                key = self._key(prefix, relative)
                self._client.upload_file(str(path), self.bucket, key)
                count += 1
        return count

    def upload_dir_split_safe(
        self, local_dir: Path, json_prefix: str, pdf_prefix: str,
        *, log_filename: str = "s3_upload_failed.txt",
        exclude_relative: set[str] | None = None,
    ) -> int:
        """Same as upload_dir_split, but never raises: on failure it writes a
        plain-text log file INSIDE local_dir explaining what went wrong, so
        the request that triggered this still completes normally instead of
        breaking just because S3 is unreachable. Clears any earlier failure
        log on a later successful upload."""
        if not self.enabled:
            return 0
        marker = local_dir / log_filename
        try:
            count = self.upload_dir_split(local_dir, json_prefix, pdf_prefix, exclude_relative=exclude_relative)
            if marker.is_file():
                marker.unlink(missing_ok=True)
            return count
        except Exception as exc:  # noqa: BLE001
            self._write_upload_failure_log(local_dir, f"{json_prefix} + {pdf_prefix}", exc, log_filename)
            return 0

    def _write_upload_failure_log(
        self, local_dir: Path, s3_prefix: str, exc: Exception, log_filename: str
    ) -> None:
        try:
            from datetime import datetime, timezone

            local_dir.mkdir(parents=True, exist_ok=True)
            text = (
                f"S3 UPLOAD FAILED\n"
                f"When:        {datetime.now(timezone.utc).isoformat()}\n"
                f"Bucket:      {self.bucket}\n"
                f"S3 prefix:   {s3_prefix}\n"
                f"Local dir:   {local_dir}\n"
                f"Error:       {type(exc).__name__}: {exc}\n\n"
                "This folder was about to be deleted locally after syncing to S3 — "
                "since the sync failed, IT WAS NOT DELETED, so the data isn't lost. "
                "Fix the underlying S3 problem and retry the request (re-upload the "
                "standard, or re-run the report) to sync and clean up properly.\n"
            )
            (local_dir / log_filename).write_text(text, encoding="utf-8")
        except Exception:
            pass  # logging must never itself break the request

    def download_dir_split(
        self, json_prefix: str, pdf_prefix: str, local_dir: Path, *, skip_existing: bool = True
    ) -> int:
        """Download objects from BOTH json_prefix and pdf_prefix into the
        same local_dir, merging them back into one working folder — the
        mirror image of upload_dir_split. Returns files downloaded. No-op
        (0) if S3 disabled; degrades to 0 (rather than raising) if S3 is
        unreachable, so read-through callers fall back to 'not found'
        instead of crashing."""
        if not self.enabled:
            return 0
        try:
            count = 0
            count += self._download_prefix_into(json_prefix, local_dir, skip_existing)
            count += self._download_prefix_into(pdf_prefix, local_dir, skip_existing)
            return count
        except Exception as exc:  # noqa: BLE001
            print(f"[s3_storage] download_dir_split failed, treating as not-found: {exc}")
            return 0

    def sync_catalog_metadata_only(self, standards_prefix: str, local_standards_dir: Path) -> int:
        """For catalog listing / report auto-matching, only meta.json files are
        ever actually read (for core_numbers, label, mode) — never delta_kb.json/
        effective_kb.json/base_kb.json. This downloads ONLY the meta.json files
        across the WHOLE catalog (every family, every product), skipping every
        other (often much larger) JSON artifact. This was the biggest hidden
        cost on /reports auto-matching once the catalog has accumulated many
        products: it used to fully download every product's effective_kb.json
        etc. on every single report upload just to check core_numbers."""
        if not self.enabled:
            return 0
        try:
            count = 0
            prefix = standards_prefix.rstrip("/") + "/"
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if not key.endswith("/meta.json"):
                        continue
                    relative = key[len(prefix):]
                    dest = local_standards_dir / relative
                    if dest.is_file() and dest.stat().st_size == obj.get("Size", -1):
                        continue
                    try:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            self._client.download_file(self.bucket, key, str(dest))
                        except Exception:
                            import time

                            time.sleep(0.5)
                            self._client.download_file(self.bucket, key, str(dest))
                        count += 1
                    except Exception as exc:  # noqa: BLE001
                        print(f"[s3_storage] failed to download {key!r}, skipping it: {exc}")
            return count
        except Exception as exc:  # noqa: BLE001
            print(f"[s3_storage] sync_catalog_metadata_only failed: {exc}")
            return 0

    def download_family_shallow_split(
        self, json_prefix: str, pdf_prefix: str, local_dir: Path, *, skip_existing: bool = True
    ) -> int:
        """Download only the files DIRECTLY under json_prefix/pdf_prefix (one
        level deep) — i.e. a family's own base.pdf/base_kb.json/base_validation.json/
        meta.json — WITHOUT pulling down every sibling product subfolder underneath
        it too. This used to be the biggest hidden cost on /reports: a family that
        accumulates many products (e.g. from repeated test uploads) meant every
        single report upload re-downloaded every OTHER product's part2.pdf/
        delta_kb.json/effective_kb.json as well, even though only one product was
        actually needed. Use download_dir_split() separately for the one specific
        product subfolder that's actually needed."""
        if not self.enabled:
            return 0
        try:
            count = 0
            count += self._download_prefix_shallow(json_prefix, local_dir, skip_existing)
            count += self._download_prefix_shallow(pdf_prefix, local_dir, skip_existing)
            return count
        except Exception as exc:  # noqa: BLE001
            print(f"[s3_storage] download_family_shallow_split failed, treating as not-found: {exc}")
            return 0

    def _download_prefix_shallow(self, s3_prefix: str, local_dir: Path, skip_existing: bool) -> int:
        """Like _download_prefix_into, but uses Delimiter="/" so S3 only returns
        keys DIRECTLY under s3_prefix — nested "subfolders" (i.e. sibling
        products) are excluded entirely, not even listed."""
        count = 0
        prefix = s3_prefix.rstrip("/") + "/"
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix, Delimiter="/"):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                relative = key[len(prefix):]
                if not relative or "/" in relative:
                    continue
                dest = local_dir / relative
                if skip_existing and dest.is_file() and dest.stat().st_size == obj.get("Size", -1):
                    continue
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        self._client.download_file(self.bucket, key, str(dest))
                    except Exception:
                        import time

                        time.sleep(0.5)
                        self._client.download_file(self.bucket, key, str(dest))
                    count += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"[s3_storage] failed to download {key!r}, skipping it: {exc}")
        return count

    def _download_prefix_into(self, s3_prefix: str, local_dir: Path, skip_existing: bool) -> int:
        """Downloads every object under s3_prefix. Each file is wrapped in its
        OWN try/except — a single problematic file (e.g. a transient Windows
        temp-file write failure on a large JSON) is skipped and logged rather
        than aborting every remaining file in the batch. Files download in
        the S3 listing's lexicographic key order, so without this, one bad
        file partway through silently starved everything after it
        alphabetically (confirmed: "report/x.json" failing meant every
        "summary/*.json" after it never even got attempted)."""
        count = 0
        paginator = self._client.get_paginator("list_objects_v2")
        prefix = s3_prefix.rstrip("/") + "/"
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                relative = key[len(prefix):]
                if not relative:
                    continue
                dest = local_dir / relative
                if skip_existing and dest.is_file() and dest.stat().st_size == obj.get("Size", -1):
                    continue
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        self._client.download_file(self.bucket, key, str(dest))
                    except Exception:
                        # Windows-specific transient failures (antivirus briefly
                        # locking boto3's temp file, etc.) are common enough on
                        # large files to be worth one quick retry before giving up.
                        import time

                        time.sleep(0.5)
                        self._client.download_file(self.bucket, key, str(dest))
                    count += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"[s3_storage] failed to download {key!r} (after retry), skipping it: {exc}")
        return count

    # --------------------------------------------------------------- #
    # plain (single-prefix) upload/download — still used for things that
    # are genuinely all-JSON already (e.g. nothing PDF-shaped in them)
    # --------------------------------------------------------------- #

    def upload_dir(self, local_dir: Path, s3_prefix: str) -> int:
        if not self.enabled or not local_dir.is_dir():
            return 0
        count = 0
        for path in local_dir.rglob("*"):
            if path.is_file():
                relative = path.relative_to(local_dir).as_posix()
                key = self._key(s3_prefix, relative)
                self._client.upload_file(str(path), self.bucket, key)
                count += 1
        return count

    def upload_dir_safe(self, local_dir: Path, s3_prefix: str, *, log_filename: str = "s3_upload_failed.txt") -> int:
        if not self.enabled:
            return 0
        marker = local_dir / log_filename
        try:
            count = self.upload_dir(local_dir, s3_prefix)
            if marker.is_file():
                marker.unlink(missing_ok=True)
            return count
        except Exception as exc:  # noqa: BLE001
            self._write_upload_failure_log(local_dir, s3_prefix, exc, log_filename)
            return 0

    def download_dir(self, s3_prefix: str, local_dir: Path, *, skip_existing: bool = True) -> int:
        if not self.enabled:
            return 0
        try:
            return self._download_prefix_into(s3_prefix, local_dir, skip_existing)
        except Exception as exc:  # noqa: BLE001
            print(f"[s3_storage] download_dir({s3_prefix!r}) failed, treating as not-found: {exc}")
            return 0

    # --------------------------------------------------------------- #
    # single-file helpers — for small standalone files like the report
    # dedup index, not worth a whole directory sync
    # --------------------------------------------------------------- #

    def upload_file_safe(self, local_path: Path, s3_key: str) -> bool:
        if not self.enabled or not local_path.is_file():
            return False
        try:
            self._client.upload_file(str(local_path), self.bucket, s3_key)
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"[s3_storage] upload_file_safe({s3_key!r}) failed: {exc}")
            return False

    def download_file_safe(self, s3_key: str, local_path: Path) -> bool:
        if not self.enabled:
            return False
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            self._client.download_file(self.bucket, s3_key, str(local_path))
            return True
        except Exception as exc:  # noqa: BLE001
            # Most common case is simply "doesn't exist yet" (NoSuchKey) — not an error.
            return False

    # --------------------------------------------------------------- #
    # misc
    # --------------------------------------------------------------- #

    def prefix_exists(self, s3_prefix: str) -> bool:
        if not self.enabled:
            return False
        try:
            prefix = s3_prefix.rstrip("/") + "/"
            resp = self._client.list_objects_v2(Bucket=self.bucket, Prefix=prefix, MaxKeys=1)
            return resp.get("KeyCount", 0) > 0
        except Exception as exc:  # noqa: BLE001
            print(f"[s3_storage] prefix_exists({s3_prefix!r}) failed, treating as False: {exc}")
            return False

    def list_common_prefixes(self, s3_prefix: str) -> list[str]:
        if not self.enabled:
            return []
        try:
            prefix = s3_prefix.rstrip("/") + "/"
            names = []
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix, Delimiter="/"):
                for cp in page.get("CommonPrefixes", []):
                    p = cp["Prefix"]
                    name = p[len(prefix):].rstrip("/")
                    if name:
                        names.append(name)
            return names
        except Exception as exc:  # noqa: BLE001
            print(f"[s3_storage] list_common_prefixes({s3_prefix!r}) failed, treating as empty: {exc}")
            return []

    def folder_tree(self, s3_prefix: str, *, max_depth: int = 8) -> dict:
        """Recursively list ONLY folder names under s3_prefix — never file
        names, never file contents. Uses the same Delimiter='/' trick as
        list_common_prefixes at every level, so leaf-level objects (actual
        files) never appear, only the 'directories' S3 keys imply. Returns a
        nested dict: {folder_name: {...its subfolders...}, ...}.
        {} at any level means that folder has no subfolders (it may still
        hold files — this call deliberately never reports those)."""
        if not self.enabled:
            return {}

        def _walk(current_prefix: str, depth: int) -> dict:
            if depth > max_depth:
                return {}
            node = {}
            for name in self.list_common_prefixes(current_prefix):
                node[name] = _walk(f"{current_prefix.rstrip('/')}/{name}", depth + 1)
            return node

        return _walk(s3_prefix, 0)

    def list_files(self, s3_prefix: str) -> list[dict]:
        """List every actual FILE (not folder) under s3_prefix, recursively —
        the complement of folder_tree(), which deliberately shows folders
        only. Each entry is {"path": <relative to s3_prefix>, "size_bytes": int,
        "last_modified": <iso str>}. Used to answer "which files exist for
        this run_id" without downloading anything."""
        if not self.enabled:
            return []
        try:
            prefix = s3_prefix.rstrip("/") + "/"
            files = []
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    relative = obj["Key"][len(prefix):]
                    if not relative:  # the "folder marker" object itself, if any
                        continue
                    files.append({
                        "path": relative,
                        "size_bytes": obj["Size"],
                        "last_modified": obj["LastModified"].isoformat(),
                    })
            return files
        except Exception as exc:  # noqa: BLE001
            print(f"[s3_storage] list_files({s3_prefix!r}) failed, treating as empty: {exc}")
            return []

    def delete_prefix(self, s3_prefix: str) -> int:
        if not self.enabled:
            return 0
        try:
            prefix = s3_prefix.rstrip("/") + "/"
            count = 0
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
                if keys:
                    self._client.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})
                    count += len(keys)
            return count
        except Exception as exc:  # noqa: BLE001
            print(f"[s3_storage] delete_prefix({s3_prefix!r}) failed: {exc}")
            return 0


# Single shared instance, same pattern as a module-level singleton config.
s3 = S3Storage()