"""
Complify API server
====================

Wraps the existing CLI pipeline in two HTTP endpoints:

1. POST /standards
   Upload standard PDFs — one at a time, or several in one call (e.g. a base
   together with one or many of its Part-2s). Each PDF's role (base/Part-1
   vs Part-2/companion vs standalone) is auto-detected from its own content
   via GenericIECDocumentParser — the SAME classifier the deterministic
   engine itself uses (rawdata_extractor/generic_iec_document_parser.py).

     - Upload a BASE (Part-1) standard, e.g. "IEC 60335-1":
         -> creates/refreshes a FAMILY folder on disk, storage/standards/60335-1/,
            holding base.pdf + base_kb.json + base_validation.json + meta.json
         -> NOT turned into its own catalog entry by default, because most
            families (the whole IEC 60335 series, for one) are never
            evaluated on the base alone — pass also_standalone=true only if
            you know this specific base genuinely stands on its own

     - Upload a PART-2/companion standard, e.g. "IEC 60335-2-8":
         -> its Part-1/base MUST already exist on disk (i.e. already uploaded
            in an earlier or the same call). If it doesn't, the upload is
            REJECTED outright with 400 Bad Request telling the caller to
            upload the Part-1 file first — there is no queue, no silent
            auto-completion later. Upload order matters: Part-1 before Part-2.
         -> if the Part-1 IS already there, it's paired immediately into a
            PRODUCT SUBFOLDER inside that same family folder, e.g.
            storage/standards/60335-1/product_name/

   One base can be shared by many Part-2 uploads — e.g. IEC 60335-1 is the
   base for 60335-2-3, 60335-2-8, 60335-2-14, 60335-2-24, 60335-2-89, etc.
   You never have to re-upload the base for every product; upload it once,
   and every product for that family lives as a subfolder right next to it —
   so the family a product belongs to is visible just by looking at the
   folder tree (see "Storage layout" below).

   Every completed pairing/standalone build becomes its own catalog entry
   with its own standard_id (shaped "<family_core>/<product_slug>", e.g.
   "60335-1/washing_machine"), and returns effective_kb.json.

2. POST /reports
   Upload a report PDF against a previously-created standard_id — or, more
   commonly, with NO standard_id at all: the standard is auto-matched from
   the standard numbers the report itself references, against the catalog
   built by step 1.
   Runs the FULL deterministic pipeline (Steps 1-22) followed by
   Step 32-A (reference resolver), 32-B (routing policy), 32-B.1 (integrity
   gate) and 32-C (context builder) — exactly what the CLI sequence you were
   given does — and returns llm_context_bundle.json.

No LLM is ever called by this service. It only produces the deterministic
JSON artifacts, same as the CLI commands.

Run it with:
    uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload

Storage layout (all under STORAGE_ROOT, default "./storage") — family-based,
so which products belong to which standard family is visible on disk:

    storage/standards/<family_core>/                e.g. "60335-1"
        base.pdf                                     uploaded once
        base_kb.json                                 persisted for inspection
        base_validation.json                         persisted for inspection
        meta.json                                     family-level info

        <product_slug>/                               e.g. "washing_machine"
            part2.pdf
            delta_kb.json          ← this product's own
            delta_validation.json  ← fresh compute, persisted
            pair_validation.json   ← fresh compute, persisted
            effective_kb.json      ← base+delta merge, fresh build
            meta.json               product-level info incl. standard_id

        <another_product_slug>/                       e.g. "submersible_pump"
            part2.pdf, delta_kb.json, delta_validation.json,
            pair_validation.json, effective_kb.json, meta.json

    storage/standards/<family_core_2>/                a NEW family gets its
        base.pdf, base_kb.json, base_validation.json,  own top-level folder,
        meta.json, <product_slug>/...                  same shape as above

    storage/pending/  -- not used. A Part-2 upload with no matching Part-1
        already on disk is rejected outright (400) rather than queued.

    storage/runs/<product_name>/...                  (full pipeline run dir,
                                                        one per report upload)
    storage/runs/.compliance_kb_cache/<hash>.json     (KB reuse cache)

--------------------------------------------------------------------------
How base-vs-Part-2 classification actually works (read this before editing)
--------------------------------------------------------------------------
GenericIECDocumentParser reads the front pages of a PDF, extracts the
standard number (e.g. "IEC 60335-2-7") via regex, and classifies it in
rawdata_extractor/generic_iec_document_parser.py::_classify_document:

    part_number == "1"          -> DocumentType.BASE
    part_number starts with "2-"-> DocumentType.PART_2   (e.g. "2-7", "2-41")
    anything else                -> DocumentType.OTHER
    no standard number found     -> DocumentType.UNKNOWN

This means "IEC 60335-1" -> BASE, "IEC 60335-2-7" -> PART_2. That part is
fully automatic and content-driven, not something this API layer decides.

KNOWN LIBRARY LIMITATION (confirmed by testing, not guessed): a standard
numbered just "IEC 60335-2" (Part 2 with NO further sub-part) has
part_number == "2", which does NOT start with "2-", so it is classified as
OTHER, not PART_2. build_delta_kb() would then reject it with
"build_delta_kb requires a PART_2 standard document" if we tried to pair it.
This API detects that specific shape (OTHER, but part_number starts with
"2") and refuses to silently register it as a base — it returns a clear
422 explaining the gap instead of mis-filing it. Fixing it properly means
relaxing _classify_document itself, which is core, audited pipeline logic,
so we surface it rather than patch around it.
--------------------------------------------------------------------------
"""
from __future__ import annotations

# Load .env into the real process environment BEFORE anything else runs —
# this must happen before `from s3_storage import s3` below, because
# s3_storage.py reads S3_BUCKET_NAME/AWS_* env vars once, at import time,
# into a module-level singleton. If .env hasn't been loaded yet by then,
# S3 stays disabled for the rest of the process even if the file is correct.
# (Docker's `env_file:` already injects these directly as container env
# vars, so this is a no-op there — it only matters for local `uvicorn
# main:app` runs outside Docker.)
from pathlib import Path

try:
    from dotenv import load_dotenv

    # Pass the .env path explicitly, anchored to this file's own folder.
    # load_dotenv() with no argument only searches upward from the process's
    # CURRENT WORKING DIRECTORY — if uvicorn/python is launched from any
    # other folder (a different cwd, an IDE run config, a systemd unit with
    # its own WorkingDirectory), it silently finds nothing and returns
    # False, leaving every AWS_*/S3_* var unset — S3 then reports "not
    # enabled" even though the .env file itself is correct. Anchoring to
    # __file__ makes this independent of however the process was started.
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass  # python-dotenv not installed — fine under Docker's env_file, but
    # add it to requirements.txt for local (non-Docker) runs to pick up .env.

import hashlib
import logging
import json
import re
import shutil
import time
import uuid
from dataclasses import asdict, is_dataclass
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, APIRouter, Query, Depends
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from iec_parser.generic_compliance_pipeline_runner import (
    GenericCompliancePipelineRunner,
    PipelineStatus,
)
#  Middleware
from middleware.logging import LoggingMiddleware
from middleware.ratelimit import RateLimitMiddleware
from middleware.request_id import RequestIDMiddleware
from middleware.response_time import ResponseTimeMiddleware
from middleware.security import SecurityHeadersMiddleware
from middleware.exception import global_exception_handler
from middleware.auth_middleware import jwt_auth
from iec_parser.generic_iec_document_parser import GenericIECDocumentParser
from iec_parser.generic_iec_kb_models import DocumentType
from iec_parser.generic_iec_effective_kb_builder import (
    GenericIECEffectiveKnowledgeBaseBuilder,
)
from iec_parser.generic_iec_kb_builder import GenericIECKnowledgeBaseBuilder
from iec_parser.generic_iec_kb_validator import GenericIECKnowledgeBaseValidator
from iec_parser.generic_iec_standalone_effective_kb_builder import (
    GenericIECStandaloneEffectiveKnowledgeBaseBuilder,
)
from iec_parser.generic_compliance_reference_resolver import (
    GenericComplianceReferenceResolver,
)
from iec_parser.generic_client_compliance_summary_builder import (
    GenericClientComplianceSummaryBuilder,
)
from iec_parser.generic_llm_routing_policy import GenericLLMRoutingPolicy
from iec_parser.generic_pre_llm_context_integrity_gate import (
    GenericPreLLMContextIntegrityGate,
)
from iec_parser.generic_llm_context_builder import GenericLLMContextBuilder
from iec_parser.generic_report_evidence_extractor import GenericReportEvidenceExtractor
from llm_evaluation import service as evaluation_service
from s3_storage import (
    s3,
    STANDARDS_PREFIX,
    REPORTS_PREFIX,
    EVALUATION_ENGINE_PREFIX,
    COMPLIANCE_FILE_PREFIX,
    COMPLIANCE_FILE_STANDARDS_PREFIX,
    COMPLIANCE_FILE_REPORTS_PREFIX,
)

app = FastAPI(title="Complify Pipeline API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------- #
# Middleware order (VERY IMPORTANT — read before reordering)
# --------------------------------------------------------------------------- #
# Starlette's app.add_middleware() is LIFO: each call wraps OUTSIDE every
# middleware added before it, so the LAST one added is the FIRST one to run
# on an incoming request (and the LAST to touch the outgoing response).
# We want this logical request-time order:
#   1. Request ID   (so every later layer/log line can read it)
#   2. Logging
#   3. Response time
#   4. Security headers
#   5. Rate limit    (closest to the actual route)
# To get that ACTUAL order, they must be *added* in the reverse sequence:
app.add_middleware(RateLimitMiddleware, max_requests=10, window=60)  # 5. added first -> innermost
app.add_middleware(SecurityHeadersMiddleware)                        # 4.
app.add_middleware(ResponseTimeMiddleware)                           # 3.
app.add_middleware(LoggingMiddleware)                                # 2.
app.add_middleware(RequestIDMiddleware)                               # 1. added last -> outermost, runs first
# Global exception handler — only fires for a genuinely unhandled exception;
# FastAPI's own built-in HTTPException handler still takes precedence for
# every `raise HTTPException(...)` in this file (Starlette picks the most
# specific handler by exception type).
app.add_exception_handler(Exception, global_exception_handler)

STORAGE_ROOT = Path("storage").resolve()
STANDARDS_DIR = STORAGE_ROOT / "standards"   # family_core/ -> product_slug/ tree
RUNS_DIR = STORAGE_ROOT / "runs"
KB_CACHE_DIR = RUNS_DIR / ".compliance_kb_cache"
for _d in (STANDARDS_DIR, RUNS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
router = APIRouter(
    prefix="/api/v1/private/compliance-engine",
    tags=["Compliance Engine"],
    # jwt_auth itself depends on the HTTPBearer instance (see
    # middleware/auth_middleware.py) and validates/decodes the token — it
    # doesn't need a separate Depends(security) alongside it. Listing both
    # used to run HTTPBearer's header-shape check twice while never actually
    # feeding its result into jwt_auth.
    dependencies=[Depends(jwt_auth)],
)
app.include_router(router)
def _save_upload(upload: UploadFile, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    if dest.read_bytes()[:5] != b"%PDF-":
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Uploaded file '{upload.filename}' is not a readable PDF.")
    return dest


def _warm_kb_cache(builder: GenericIECKnowledgeBaseBuilder, source: Path, kind: str, value) -> None:
    """Pre-populate the same on-disk cache GenericCompliancePipelineRunner._build_or_reuse_kb
    reads from, so a later /reports call with reuse_kb=True skips re-parsing the standard PDF."""
    config = builder.__class__.__module__ + "." + builder.__class__.__qualname__
    key = GenericCompliancePipelineRunner.sha256(source) + "\x1f" + config + "\x1f" + kind
    digest = hashlib.sha256(key.encode()).hexdigest()
    cache_path = KB_CACHE_DIR / f"{digest}.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    builder.save_json(value, cache_path)


def _slugify(text: str) -> str:
    """'1.washing machine.pdf' -> 'washing_machine', '48.BATTERY (1).pdf' -> 'battery_1'.
    Matches the folder-naming style already used under test_reports/output/
    (product-name slugs, e.g. washing_machine_post_31nh, submersible_pump_post_31nh)."""
    text = text.rsplit(".", 1)[0] if "." in text else text  # drop a trailing extension
    text = re.sub(r"^\s*\d+[\.\)]?\s*", "", text)  # drop a leading index like "1." / "2)"
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    text = re.sub(r"_+", "_", text)
    return text or "run"


def _unique_dir_name(parent: Path, base_slug: str) -> str:
    if not (parent / base_slug).exists():
        return base_slug
    i = 2
    while (parent / f"{base_slug}_{i}").exists():
        i += 1
    return f"{base_slug}_{i}"


def _unique_run_dir_name(base_slug: str) -> str:
    return _unique_dir_name(RUNS_DIR, base_slug)


def _iter_subdirs(path: Path):
    """sorted(path.iterdir()) but self-healing: recreates the directory if it
    was deleted out from under a running process (e.g. someone manually
    cleared storage/ mid-session on Windows) instead of crashing with
    FileNotFoundError."""
    path.mkdir(parents=True, exist_ok=True)
    return sorted(path.iterdir())


def _family_dir(core: str) -> Path:
    return STANDARDS_DIR / core


def _standard_dir(standard_id: str) -> Path:
    """standard_id is '<family_core>/<product_slug>', e.g. '60335-1/washing_machine'.
    Local disk is ephemeral now — always re-sync from S3 rather than trusting
    whatever's already on disk (there normally won't be anything there).
    Syncs ONLY the family-level files (base.pdf/base_kb.json/base_validation.json/
    meta.json) plus THIS ONE product's own subfolder — NOT every sibling
    product under the family. A family that has accumulated many products
    (repeated test uploads, etc.) used to mean every single /reports call
    re-downloaded every OTHER product too — this was the single biggest
    hidden cost on report-upload latency once a family had several products."""
    parts = [p for p in standard_id.replace("\\", "/").split("/") if p]
    if len(parts) != 2 or any(p in (".", "..") for p in parts):
        raise HTTPException(404, f"Unknown standard_id: {standard_id}")
    family_core, product_slug = parts
    family_dir = _family_dir(family_core)
    s3.download_family_shallow_split(
        f"{STANDARDS_PREFIX}/{family_core}",
        f"{COMPLIANCE_FILE_STANDARDS_PREFIX}/{family_core}",
        family_dir,
    )
    d = family_dir / product_slug
    s3.download_dir_split(
        f"{STANDARDS_PREFIX}/{family_core}/{product_slug}",
        f"{COMPLIANCE_FILE_STANDARDS_PREFIX}/{family_core}/{product_slug}",
        d,
    )
    if not d.is_dir():
        raise HTTPException(404, f"Unknown standard_id: {standard_id}")
    return d


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _plain(v):
    if is_dataclass(v):
        return _plain(asdict(v))
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if hasattr(v, "value") and not isinstance(v, (str, int, float, bool)):
        return v.value  # Enum
    return v



def _probe(path: Path):
    """Parse just the front matter to learn standard_number/part/type, cheap and read-only."""
    try:
        return GenericIECDocumentParser(path).parse()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"Could not read standard metadata from '{path.name}': {exc}") from exc


def _document_summary(document) -> dict:
    return {
        "standard_number": document.standard_number,
        "part_number": document.part_number,
        "document_type": document.document_type.value,
        "parent_standard": document.parent_standard,
        "title": document.title,
        "year": document.year,
    }


def _looks_like_misclassified_bare_part2(document) -> bool:
    """OTHER but numbered like a Part-2 (e.g. bare 'IEC 60335-2') — see the
    KNOWN LIBRARY LIMITATION note in the module docstring. Catch this instead
    of silently filing it as a base standard."""
    return (
        document.document_type is DocumentType.OTHER
        and bool(document.part_number)
        and document.part_number.startswith("2")
    )


def _core(number: Optional[str]) -> Optional[str]:
    return GenericCompliancePipelineRunner._core(number) if number else None


kb_builder = GenericIECKnowledgeBaseBuilder()
kb_validator = GenericIECKnowledgeBaseValidator()


def _build_product_entry(
    *,
    family_dir: Path,
    family_core: str,
    base_kb,
    base_doc,
    delta_kb=None,
    delta_doc=None,
    delta_pdf_path: Optional[Path] = None,
    delta_validation_report=None,
    pair_validation_report=None,
    label: Optional[str],
    strict_standard_validation: bool,
) -> dict:
    """Create one product subfolder INSIDE its family folder, e.g.
    storage/standards/60335-1/washing_machine/. Used both for a fresh
    standalone base build and for completing a base+Part-2 pairing (whether
    that happens immediately or later, once the missing base arrives). The
    base.pdf/base_kb.json already live one level up in family_dir — a
    product folder only stores what's unique to it."""
    if delta_kb is not None:
        default_label = delta_doc.standard_number or base_doc.standard_number
    else:
        default_label = "standalone"

    product_slug = _unique_dir_name(family_dir, _slugify(label or default_label))
    pdir = family_dir / product_slug
    pdir.mkdir(parents=True)

    if delta_kb is not None:
        final_part2_path = pdir / "part2.pdf"
        shutil.copy2(delta_pdf_path, final_part2_path)
        effective_builder = GenericIECEffectiveKnowledgeBaseBuilder()
        effective_kb = effective_builder.build(base_kb, delta_kb)
        mode = "BASE_PLUS_COMPANION"
        part2_filename = delta_pdf_path.name
        part2_sha256 = GenericCompliancePipelineRunner.sha256(final_part2_path)
        detected = [_document_summary(base_doc), _document_summary(delta_doc)]
        kb_builder.save_json(delta_kb, pdir / "delta_kb.json")
        if delta_validation_report is not None:
            (pdir / "delta_validation.json").write_text(
                json.dumps(_plain(delta_validation_report), indent=2), encoding="utf-8"
            )
        if pair_validation_report is not None:
            (pdir / "pair_validation.json").write_text(
                json.dumps(_plain(pair_validation_report), indent=2), encoding="utf-8"
            )
        # This product's own part2.pdf is unique to it, so warm its "delta"
        # cache kind here. The base's "primary"/"base" cache kinds were
        # already warmed once when the family/base was registered.
        _warm_kb_cache(kb_builder, final_part2_path, "delta", delta_kb)
    else:
        effective_builder = GenericIECStandaloneEffectiveKnowledgeBaseBuilder()
        effective_kb = effective_builder.build(base_kb)
        mode = "STANDALONE"
        part2_filename = None
        part2_sha256 = None
        detected = [_document_summary(base_doc)]

    effective_path = pdir / "effective_kb.json"
    effective_builder.save_json(effective_kb, effective_path)

    core_numbers = sorted({_core(d["standard_number"]) for d in detected if d.get("standard_number")})
    standard_id = f"{family_core}/{product_slug}"

    meta = {
        "standard_id": standard_id,
        "family_core": family_core,
        "product_slug": product_slug,
        "label": label or default_label,
        "mode": mode,
        "part2_standard_filename": part2_filename,
        "part2_sha256": part2_sha256,  # used to detect a re-upload of the exact same Part-2
        "strict_standard_validation": strict_standard_validation,
        "detected": detected,
        "core_numbers": core_numbers,
    }
    (pdir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return {
        "standard_id": standard_id,
        "label": meta["label"],
        "mode": mode,
        "detected": detected,
        "effective_kb": _load_json(effective_path),
    }


# --------------------------------------------------------------------------- #
# 1) standard upload -> effective_kb.json
#    ONE endpoint: upload one file, or several at once (even a base + one/many
#    of its Part-2s together) — order doesn't matter, bases are always
#    processed before Part-2s in the same call so same-call pairing works.
# --------------------------------------------------------------------------- #

def _find_existing_product_by_hash(family_dir: Path, part2_sha256: str) -> Optional[dict]:
    """Scan this family's product subfolders for one whose part2.pdf already
    has this exact hash — used to detect a re-upload of the same Part-2
    standard so we return the existing entry instead of creating a
    needless duplicate (e.g. washing_machine_2, washing_machine_3, ...)."""
    if not family_dir.is_dir():
        return None
    for product_dir in sorted(p for p in family_dir.iterdir() if p.is_dir()):
        meta_path = product_dir / "meta.json"
        if not meta_path.is_file():
            continue
        meta = _load_json(meta_path)
        if meta.get("part2_sha256") == part2_sha256:
            effective_path = product_dir / "effective_kb.json"
            return {
                "standard_id": meta["standard_id"],
                "label": meta.get("label"),
                "mode": meta["mode"],
                "detected": meta.get("detected", []),
                "effective_kb": _load_json(effective_path) if effective_path.is_file() else None,
            }
    return None


def _process_one_standard(
    doc, temp_path: Path, filename: str, label: Optional[str],
    strict_standard_validation: bool, also_standalone: bool,
) -> dict:
    if doc.document_type is DocumentType.UNKNOWN:
        raise HTTPException(
            422,
            f"'{filename}': could not detect a standard number/part in this PDF's front "
            "matter, so it can't be classified as base, Part-2, or standalone.",
        )

    if _looks_like_misclassified_bare_part2(doc):
        raise HTTPException(
            422,
            f"'{filename}' ('{doc.standard_number}') looks like a bare Part-2 standard (no "
            "further sub-part digit, e.g. plain 'IEC 60335-2' rather than 'IEC 60335-2-7'). "
            "rawdata_extractor's own classifier only recognizes Part-2 numbers shaped like "
            "'2-N' today, so this can't be safely paired as a companion standard yet — see "
            "the KNOWN LIBRARY LIMITATION note in this file. It has NOT been registered.",
        )

    if doc.document_type is DocumentType.PART_2:
        # ---- Part-2 / companion standard: its Part-1/base MUST already
        # exist (on S3 — local disk is ephemeral scratch space now, so we
        # always re-sync down before checking). No queue, no auto-resolve
        # later — reject outright and tell the caller to upload the Part-1 first. ----
        family_core = _core(doc.parent_standard)
        family_dir = _family_dir(family_core) if family_core else None

        if family_dir is not None:
            s3.download_dir_split(
                f"{STANDARDS_PREFIX}/{family_core}",
                f"{COMPLIANCE_FILE_STANDARDS_PREFIX}/{family_core}",
                family_dir,
            )

        if family_dir is None or not (family_dir / "base.pdf").is_file():
            raise HTTPException(
                400,
                f"'{filename}' ({doc.standard_number}) is a Part-2/companion standard, but "
                f"its Part-1/base standard ({doc.parent_standard or 'the family Part-1'}) "
                "has not been uploaded yet. Upload the Part-1 file of this standard first, "
                "then upload this Part-2 again.",
            )

        try:
            # Already-uploaded check: same exact Part-2 file re-sent -> return the
            # existing product, don't create a duplicate and don't treat it as an error.
            incoming_hash = GenericCompliancePipelineRunner.sha256(temp_path)
            existing = _find_existing_product_by_hash(family_dir, incoming_hash)
            if existing is not None:
                return {
                    "filename": filename,
                    "status": "ALREADY_EXISTS",
                    "part1_exists": True,
                    "message": "This exact Part-2 standard is already registered — returning the existing entry.",
                    **existing,
                }

            # Part-1 exists — rebuild it from disk and pair immediately.
            base_pdf_path = family_dir / "base.pdf"
            base_doc = _probe(base_pdf_path)
            base_kb = kb_builder.build_primary_kb(base_pdf_path)
            base_report = kb_validator.validate(base_kb)
            if not getattr(base_report, "valid", False):
                raise HTTPException(422, f"Registered base standard failed re-validation: {_plain(base_report)}")

            delta_kb = kb_builder.build_delta_kb(temp_path)
            delta_report = kb_validator.validate(delta_kb)
            if not getattr(delta_report, "valid", False):
                raise HTTPException(422, f"'{filename}': Part-2 standard failed validation: {_plain(delta_report)}")

            pair_report = kb_validator.validate_pair(base_kb, delta_kb)
            if not getattr(pair_report, "valid", False):
                raise HTTPException(422, f"'{filename}': Base/Part-2 compatibility validation failed: {_plain(pair_report)}")

            product = _build_product_entry(
                family_dir=family_dir,
                family_core=family_core,
                base_kb=base_kb,
                base_doc=base_doc,
                delta_kb=delta_kb,
                delta_doc=doc,
                delta_pdf_path=temp_path,
                delta_validation_report=delta_report,
                pair_validation_report=pair_report,
                label=label,
                strict_standard_validation=strict_standard_validation,
            )
            s3.upload_dir_split_safe(
                family_dir, f"{STANDARDS_PREFIX}/{family_core}", f"{COMPLIANCE_FILE_STANDARDS_PREFIX}/{family_core}"
            )
            return {"filename": filename, "status": "PAIRED_WITH_EXISTING_BASE", "part1_exists": True, **product}
        finally:
            # Local disk is scratch space only — always clean up, success or failure.
            _cleanup_local(family_dir)

    # ---- BASE or OTHER: create/refresh the family folder, then try a
    # standalone build immediately (useful even for families that have no
    # Part-2 at all, e.g. some IEC 60204-1 / IEC 60950-1 use cases). ----
    core = _core(doc.standard_number)
    family_dir = _family_dir(core)
    s3.download_dir_split(
        f"{STANDARDS_PREFIX}/{core}", f"{COMPLIANCE_FILE_STANDARDS_PREFIX}/{core}", family_dir
    )
    was_existing = (family_dir / "base.pdf").is_file()

    # Already-uploaded check: same exact base file re-sent -> skip the rebuild
    # entirely and just confirm what's already there, instead of reprocessing.
    if was_existing:
        incoming_hash = GenericCompliancePipelineRunner.sha256(temp_path)
        existing_hash = GenericCompliancePipelineRunner.sha256(family_dir / "base.pdf")
        if incoming_hash == existing_hash:
            _cleanup_local(family_dir)
            return {
                "filename": filename,
                "status": "ALREADY_EXISTS",
                "part1_exists": True,
                "base_core": core,
                "message": "This exact Part-1/base standard is already registered — no changes made.",
            }

    family_dir.mkdir(parents=True, exist_ok=True)
    base_pdf_path = family_dir / "base.pdf"
    shutil.copy2(temp_path, base_pdf_path)

    try:
        base_kb = kb_builder.build_primary_kb(base_pdf_path)
        base_report = kb_validator.validate(base_kb)
        if not getattr(base_report, "valid", False):
            raise HTTPException(422, f"'{filename}': standard failed validation: {_plain(base_report)}")

        kb_builder.save_json(base_kb, family_dir / "base_kb.json")
        (family_dir / "base_validation.json").write_text(
            json.dumps(_plain(base_report), indent=2), encoding="utf-8"
        )

        _warm_kb_cache(kb_builder, base_pdf_path, "primary", base_kb)
        if doc.document_type is DocumentType.BASE:
            # Same object either way (build_base_kb and build_primary_kb run the
            # identical pipeline for a true BASE doc) — just warm the extra cache
            # key that GenericCompliancePipelineRunner's paired mode looks under.
            _warm_kb_cache(kb_builder, base_pdf_path, "base", base_kb)

        (family_dir / "meta.json").write_text(
            json.dumps({"core": core, "label": label, "detected": _document_summary(doc)}, indent=2),
            encoding="utf-8",
        )

        standalone = None
        if also_standalone:
            standalone = _build_product_entry(
                family_dir=family_dir,
                family_core=core,
                base_kb=base_kb,
                base_doc=doc,
                label=label,
                strict_standard_validation=strict_standard_validation,
            )

        s3.upload_dir_split_safe(
            family_dir, f"{STANDARDS_PREFIX}/{core}", f"{COMPLIANCE_FILE_STANDARDS_PREFIX}/{core}"
        )

        return {
            "filename": filename,
            "status": "BASE_REGISTERED",
            "part1_exists": True,
            "base_core": core,
            "base_was_already_registered": was_existing,
            "standalone": standalone,
            "message": (
                "Part-1/base registered. Upload its Part-2 standard(s) next."
                if standalone is None
                else "Part-1/base registered and a standalone catalog entry was created."
            ),
        }
    finally:
        # Local disk is scratch space only — always clean up, success or failure.
        _cleanup_local(family_dir)


@router.post("/standard")
def upload_standard(
    standard: List[UploadFile] = File(
        ...,
        description=(
            "One or more standard PDFs. Upload just a base, just a Part-2, or "
            "several at once (e.g. a base together with one or many of its "
            "Part-2s) — role is auto-detected per file and bases in the batch "
            "are registered before Part-2s so same-call pairing works."
        ),
    ),
    label: Optional[str] = Form(
        None,
        description=(
            "Optional admin-facing label, e.g. 'IEC 60335-2-8' or 'Washing Machine'. "
            "Defaults to the detected standard number if omitted. Only applied when "
            "uploading a single file — ignored (auto-labeled instead) in a multi-file "
            "batch, since one label can't describe several different products."
        ),
    ),
    strict_standard_validation: bool = Form(False),
    also_standalone: bool = Form(
        False,
        description=(
            "For a base/Part-1 upload only. If true, ALSO immediately create a "
            "STANDALONE catalog entry (its own standard_id + effective_kb.json) "
            "using just this base, with no Part-2. Default is false, because most "
            "families (e.g. the whole IEC 60335 series) are never evaluated on the "
            "base alone — it always needs a product-specific Part-2. Turn this on "
            "only for a base you know is genuinely usable by itself. The base is "
            "ALWAYS registered for future Part-2 pairing either way."
        ),
    ),
):
    if not standard:
        raise HTTPException(400, "Upload at least one standard PDF.")

    saved = []
    for upload in standard:
        temp_path = _save_upload(upload, STORAGE_ROOT / "_incoming_standards" / f"{uuid.uuid4().hex}.pdf")
        saved.append((upload, temp_path))

    try:
        probed = [(upload, temp_path, _probe(temp_path)) for upload, temp_path in saved]
        # Bases/standalone-capable files first, so a Part-2 in the SAME batch
        # can find its base already registered instead of hitting the "Part-1 not found" error.
        probed.sort(key=lambda item: 1 if item[2].document_type is DocumentType.PART_2 else 0)

        # `label` is a per-product name. Apply it to whichever single Part-2
        # file is in this batch (the common "base + its Part-2 together"
        # case), or to the one file if only a base was uploaded alone.
        # With multiple Part-2s in one call it's ambiguous, so it's ignored
        # everywhere rather than mislabeling one of them.
        part2_positions = [i for i, (_, _, d) in enumerate(probed) if d.document_type is DocumentType.PART_2]
        if len(part2_positions) == 1:
            label_target = part2_positions[0]
        elif len(probed) == 1:
            label_target = 0
        else:
            label_target = None

        single_file = len(probed) == 1
        results = []
        for i, (upload, temp_path, doc) in enumerate(probed):
            file_label = label if i == label_target else None
            if single_file:
                results.append(
                    _process_one_standard(
                        doc, temp_path, upload.filename, file_label,
                        strict_standard_validation, also_standalone,
                    )
                )
            else:
                try:
                    results.append(
                        _process_one_standard(
                            doc, temp_path, upload.filename, file_label,
                            strict_standard_validation, also_standalone,
                        )
                    )
                except HTTPException as exc:
                    results.append({"filename": upload.filename, "status": "ERROR", "error": exc.detail})

        return JSONResponse(results[0] if single_file else {"results": results})

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc
    finally:
        for _, temp_path in saved:
            temp_path.unlink(missing_ok=True)
        _cleanup_local(KB_CACHE_DIR)  # transient perf cache — regenerable, no reason to keep it on disk


def _sync_all_standards_from_s3() -> None:
    """Read-through refresh before listing/matching against the catalog.
    Downloads ONLY meta.json for every family/product — never the much
    larger delta_kb.json/effective_kb.json/base_kb.json, and never any PDF —
    since catalog listing and report auto-matching only ever read
    core_numbers/label/mode from meta.json. Cheap no-op if S3 isn't configured."""
    if not s3.enabled:
        return
    s3.sync_catalog_metadata_only(STANDARDS_PREFIX, STANDARDS_DIR)


def _cleanup_local(path: Path) -> None:
    """Delete a local scratch folder — but ONLY if S3 is actually configured
    and enabled, since without S3 there's nowhere else for the data to live
    (local disk would be the sole copy, and deleting it would just be data
    loss). With S3 enabled, this runs after every successful (or failed)
    write, since local disk is pure ephemeral working space in that mode.

    Retries once after a short pause before giving up: a file can still be
    briefly open (antivirus scan, a lingering file handle on Windows, a
    just-finished upload) right when cleanup runs, and rmtree(ignore_errors=True)
    used to swallow that failure silently — the folder would just sit there
    forever with nothing telling you it happened. Now a leftover folder is
    always something you can actually find (via the marker file below)."""
    if not s3.enabled:
        return
    for attempt in range(2):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        if attempt == 0:
            time.sleep(0.5)
    # Still here after a retry — leave a visible marker instead of pretending
    # cleanup succeeded, so a stuck run_dir shows up on disk with a reason
    # attached rather than as an unexplained leftover folder.
    try:
        marker = path / "local_cleanup_failed.txt"
        marker.write_text(
            "This folder could not be deleted after processing (likely a "
            "locked/open file). Its durable copy is already on S3 — this "
            "local copy is safe to delete manually.\n",
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass  # even the marker write failed — nothing more we can do here


def _cleanup_standards_scratch() -> None:
    """Local disk is ephemeral (when S3 is on) — wipe the standards scratch
    area after a read-only listing/lookup completes, so nothing lingers
    between requests. No-op if S3 isn't configured (see _cleanup_local)."""
    if not s3.enabled:
        return
    if STANDARDS_DIR.is_dir():
        for entry in STANDARDS_DIR.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)


def _iter_products():
    """Yields (family_dir, product_dir, meta) for every product subfolder
    across every family — the 2-level walk the catalog/matcher/etc. share."""
    _sync_all_standards_from_s3()
    for family_dir in _iter_subdirs(STANDARDS_DIR):
        if not family_dir.is_dir():
            continue
        for product_dir in sorted(p for p in family_dir.iterdir() if p.is_dir()):
            meta_path = product_dir / "meta.json"
            if meta_path.is_file():
                yield family_dir, product_dir, _load_json(meta_path)


@router.get("/standards/{standard_id:path}/effective-kb")
def get_effective_kb(standard_id: str):
    sdir = _standard_dir(standard_id)
    try:
        path = sdir / "effective_kb.json"
        if not path.is_file():
            raise HTTPException(404, "effective_kb.json not found for this standard_id")
        return _load_json(path)
    finally:
        _cleanup_local(sdir.parent)  # whole family, since _standard_dir synced it all


@router.get("/standards/bases")
def list_bases():
    """Admin visibility: every registered family/base, keyed by core number,
    with the product subfolders it already has."""
    _sync_all_standards_from_s3()
    try:
        out = []
        for family_dir in _iter_subdirs(STANDARDS_DIR):
            if not family_dir.is_dir():
                continue
            meta_path = family_dir / "meta.json"
            if not meta_path.is_file():
                continue
            meta = _load_json(meta_path)
            products = sorted(p.name for p in family_dir.iterdir() if p.is_dir())
            out.append({**meta, "products": products})
        return {"bases": out}
    finally:
        _cleanup_standards_scratch()


# --------------------------------------------------------------------------- #
# admin-facing catalog — what an end-user-facing frontend lists/picks from
# --------------------------------------------------------------------------- #

@router.get("/standards")
def list_standards():
    """Lightweight catalog: no PDFs, no effective_kb payload — just enough for
    a frontend dropdown or for /reports auto-matching. Safe to expose to the
    same layer that serves end users, unlike POST /standards which should
    stay admin-only."""
    try:
        out = []
        for _family_dir_unused, _product_dir_unused, meta in _iter_products():
            out.append(
                {
                    "standard_id": meta["standard_id"],
                    "label": meta.get("label"),
                    "mode": meta["mode"],
                    "core_numbers": meta.get("core_numbers", []),
                    "detected": meta.get("detected", []),
                }
            )
        return {"standards": out}
    finally:
        _cleanup_standards_scratch()


# --------------------------------------------------------------------------- #
# auto-matching a report to the right standard_id (end user never sees IDs)
# --------------------------------------------------------------------------- #

def _match_standards_for_report(report_path: Path):
    """Extract standard references from the report itself and match them
    against every admin-uploaded standard's core numbers. This is the same
    core-number comparison GenericCompliancePipelineRunner.validate_standard_set
    already does internally — we're just running it BEFORE picking a
    standard_id, instead of after."""
    evidence = GenericReportEvidenceExtractor().extract(report_path)
    core = GenericCompliancePipelineRunner._core
    report_cores = {core(x) for x in (evidence.standard_numbers or []) if core(x)}

    matches = []
    for _family_dir_unused, _product_dir_unused, meta in _iter_products():
        standard_cores = set(meta.get("core_numbers", []))
        if report_cores and report_cores.issubset(standard_cores):
            matches.append(meta)
    return report_cores, matches


REPORT_INDEX_PATH = RUNS_DIR / ".report_index.json"
REPORT_INDEX_S3_KEY = f"{REPORTS_PREFIX}/.report_index.json"


def _load_report_index() -> dict:
    """Local disk is ephemeral when S3 is configured, so this index itself
    lives on S3 — pull the current copy down first (single small file, not a
    whole-prefix sync). Without S3 configured, falls back to a plain local
    file (there's nowhere else for it to live)."""
    if s3.enabled:
        s3.download_file_safe(REPORT_INDEX_S3_KEY, REPORT_INDEX_PATH)
    try:
        if REPORT_INDEX_PATH.is_file():
            try:
                return json.loads(REPORT_INDEX_PATH.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return {}
        return {}
    finally:
        if s3.enabled:
            REPORT_INDEX_PATH.unlink(missing_ok=True)


def _save_report_index(index: dict) -> None:
    try:
        REPORT_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_INDEX_PATH.write_text(json.dumps(index, indent=2), encoding="utf-8")
        if s3.enabled:
            s3.upload_file_safe(REPORT_INDEX_PATH, REPORT_INDEX_S3_KEY)
    except Exception:  # noqa: BLE001
        pass  # the index is a convenience cache — never let it break a real request
    finally:
        if s3.enabled:
            REPORT_INDEX_PATH.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# 2) report upload -> llm_context_bundle.json
# --------------------------------------------------------------------------- #

@router.post("/reports")
def upload_report(
    report: UploadFile = File(..., description="Test report PDF"),
    standard_id: Optional[str] = Form(
        None,
        description=(
            "Optional. If omitted (the normal end-user path), the standard is "
            "auto-detected from the standard numbers the report itself references, "
            "matched against every standard an admin has already uploaded via "
            "POST /standards. Only pass this explicitly if the caller already "
            "knows which standard_id to use (e.g. an admin re-running a specific "
            "standard version) or auto-match came back ambiguous."
        ),
    ),
    strict_standard_validation: Optional[bool] = Form(None),
):
    temp_id = uuid.uuid4().hex
    report_path = _save_upload(report, RUNS_DIR / "_incoming" / f"{temp_id}.pdf")

    try:
        # Already-uploaded check: the exact same report file was processed
        # before -> return that existing result instead of re-running the
        # full pipeline (and instead of erroring). Keyed purely by the
        # report's own content hash, since identical bytes will always
        # auto-match to the same standard anyway. If an explicit standard_id
        # is given and it doesn't match what's on record, treat it as a
        # genuinely different request and run fresh.
        report_sha256 = GenericCompliancePipelineRunner.sha256(report_path)
        report_index = _load_report_index()
        cached = report_index.get(report_sha256)
        if cached and (standard_id is None or standard_id == cached.get("standard_id")):
            cached_run_dir = RUNS_DIR / cached["run_id"]
            cached_status = cached.get("pipeline_status")
            # BLOCKED runs never get an llm_context_bundle.json (Step 32-A/B/B.1/C
            # is skipped for BLOCKED — see the comment further below), so using
            # that file alone to decide "is this cache entry still good?" was
            # wrong: every re-upload of an already-processed BLOCKED report kept
            # finding it missing, treating a perfectly valid cache hit as a
            # "stale index entry", and re-running the ENTIRE pipeline from
            # scratch every single time — the dedup never actually worked for
            # BLOCKED reports, which under the canonical-authority engine are
            # the common case. Use summary/final_summary_brief_context.json as
            # the existence check instead — it's written natively for every
            # terminal status (SUCCESS / SUCCESS_WITH_REVIEW / BLOCKED alike).
            cached_bundle_path = cached_run_dir / "llm" / "llm_context_bundle.json"
            cached_brief_path = cached_run_dir / "summary" / "final_summary_brief_context.json"
            marker_path = cached_bundle_path if cached_status != PipelineStatus.BLOCKED.value else cached_brief_path
            if not marker_path.is_file():
                s3.download_dir(f"{REPORTS_PREFIX}/{cached['run_id']}", cached_run_dir)
            if marker_path.is_file():
                response_body = {
                    "run_id": cached["run_id"],
                    "standard_id": cached["standard_id"],
                    "pipeline_status": cached_status,
                    "llm_context_bundle": _load_json(cached_bundle_path) if cached_bundle_path.is_file() else None,
                    "summary_brief": _load_json(cached_brief_path) if cached_brief_path.is_file() else None,
                    "evaluation": _evaluation_response(cached["run_id"], evaluation_service.stored_result(cached_run_dir)),
                    "status": "ALREADY_PROCESSED",
                    "message": "This exact report was already processed — returning the existing result.",
                }
                _cleanup_local(cached_run_dir)
                return JSONResponse(response_body)
            # Stale index entry (run folder gone from both local disk and S3) — drop it and run fresh.
            report_index.pop(report_sha256, None)
            _save_report_index(report_index)

        if standard_id is None:
            report_cores, matches = _match_standards_for_report(report_path)
            if not report_cores:
                raise HTTPException(
                    422,
                    "Could not detect any standard number referenced in this report, "
                    "so the standard can't be auto-selected. Pass standard_id explicitly.",
                )
            if not matches:
                raise HTTPException(
                    404,
                    {
                        "message": "No uploaded standard matches the standard(s) this "
                        "report references. Ask an admin to upload it via POST /standards.",
                        "report_references": sorted(report_cores),
                    },
                )
            if len(matches) > 1:
                raise HTTPException(
                    409,
                    {
                        "message": "More than one uploaded standard matches this report's "
                        "references. Re-submit with an explicit standard_id.",
                        "report_references": sorted(report_cores),
                        "candidates": [
                            {"standard_id": m["standard_id"], "label": m.get("label"), "mode": m["mode"]}
                            for m in matches
                        ],
                    },
                )
            standard_id = matches[0]["standard_id"]
            _cleanup_standards_scratch()  # done with the broad scan; _standard_dir() below re-syncs just the match

        sdir = _standard_dir(standard_id)
        meta = _load_json(sdir / "meta.json")
        base_path = _family_dir(meta["family_core"]) / "base.pdf"
        part2_path = sdir / "part2.pdf" if (sdir / "part2.pdf").is_file() else None

        # Product-name folder, same style as test_reports/output/washing_machine_post_31nh:
        # prefer the report's own filename (that's what's actually product-specific,
        # e.g. "1.washing machine.pdf" -> "washing_machine"), fall back to the
        # standard's admin-set label, then to the standard_id itself.
        base_slug = _slugify(report.filename or "") or _slugify(meta.get("label") or "") or standard_id
        run_id = _unique_run_dir_name(base_slug)
        run_dir = RUNS_DIR / run_id

        strict = (
            meta.get("strict_standard_validation", False)
            if strict_standard_validation is None
            else strict_standard_validation
        )

        runner = GenericCompliancePipelineRunner()
        result = runner.run(
            base_standard=base_path,
            part2_standard=part2_path,
            report=report_path,
            output=run_dir,
            run_id=run_id,
            reuse_kb=True,  # hits the cache warmed in /standards, so the standard PDF isn't re-parsed
            strict_standard_validation=strict,
        )

        # The standard's family scratch (base.pdf/base_kb.json/... plus every
        # sibling product, synced by _standard_dir() above) is no longer
        # needed now that runner.run() has read what it needed from it.
        _cleanup_local(_family_dir(meta["family_core"]))

        if result.pipeline_status is PipelineStatus.FAILED:
            # A genuine execution failure (crash/exception during a step) —
            # nothing usable was produced, so don't upload anything and wipe
            # the local scratch.
            manifest = _load_json(run_dir / "manifest/pipeline_manifest.json")
            _cleanup_local(run_dir)
            raise HTTPException(
                422,
                {
                    "message": "Pipeline did not complete successfully.",
                    "pipeline_status": result.pipeline_status.value,
                    "manifest": manifest,
                },
            )
        # SUCCESS, SUCCESS_WITH_REVIEW, and BLOCKED are all legitimate
        # *terminal* outcomes of the canonical-authority engine — BLOCKED
        # means standard-authority/KB-maturity gates withheld an authoritative
        # compliance conclusion, which is an intentional, conservative result
        # (see the senior's client_delivery_readme.md), not a pipeline error.
        # Only FAILED short-circuits above; all three below still get their
        # local run folder uploaded to S3 further down (canonical_client_detailed
        # / client_compliance_summary / final_summary_brief_context are written
        # natively by the engine's own STEP_ORDER regardless of status).
        #
        # Step 32-A/B/B.1/C (llm_context_bundle) is legacy machinery from
        # before the canonical-authority engine and needs decisions/
        # final_compliance_issues.json etc., which a BLOCKED run never
        # writes (nothing was evaluated) — so it's skipped for BLOCKED,
        # not just "best effort": calling it would raise
        # ComplianceReferenceResolutionError every time.
        if result.pipeline_status is PipelineStatus.BLOCKED:
            loaded_bundle = None
        else:
            # Step 32-A / 32-B / 32-B.1 / 32-C — same as the CLI sequence
            GenericComplianceReferenceResolver().resolve_run(run_dir)
            GenericLLMRoutingPolicy().route_run(run_dir)
            GenericPreLLMContextIntegrityGate().audit_run(run_dir)
            GenericLLMContextBuilder().build_run(run_dir)

            bundle_path = run_dir / "llm/llm_context_bundle.json"
            loaded_bundle = _load_json(bundle_path)

        # Summary generation (Step "final_summary_context" + "final_summary_brief_context")
        # is the LAST 2 steps of STEP_ORDER inside runner.run() above — since we're on the
        # full rawdata_extractor engine, it already ran automatically as part of the
        # pipeline call, no separate build step needed here. Just read what it wrote:
        #   summary/final_summary_context.json        (full detail, large)
        #   summary/final_summary_brief_context.json   (compact, client-facing)
        # Only the brief is embedded directly in the response, same reasoning as why the
        # full effective_kb/report_evidence aren't: keep the payload small, fetch the
        # rest on demand via the GET endpoints below.
        brief_path = run_dir / "summary/final_summary_brief_context.json"
        summary_brief = _load_json(brief_path) if brief_path.is_file() else None

        # New (senior's canonical-authority engine, wired in on top of the above):
        #   summary/canonical_client_detailed.json   (full technical record — written
        #                                              natively by runner.run() above,
        #                                              same as final_summary_context.json)
        #   summary/client_compliance_summary.json   (compact, human-readable)
        # client_compliance_summary.json is NOT written by runner.run() itself —
        # in the senior's own delivered rawdata_extractor, GenericClientComplianceSummaryBuilder
        # is only ever called from their own one-off audit/test scripts
        # (audit/client_summary_compaction/generate_client_compliance_summaries.py),
        # never from generic_compliance_pipeline_runner.py. So we build it here,
        # the same way that script does: load canonical_client_detailed.json and
        # run it through the builder. Runs for every terminal status (BLOCKED
        # included) since canonical_client_detailed.json always exists by this point.
        detailed_path = run_dir / "summary/canonical_client_detailed.json"
        if detailed_path.is_file():
            client_summary = GenericClientComplianceSummaryBuilder().build(_load_json(detailed_path))
            GenericClientComplianceSummaryBuilder().save_json(
                client_summary, run_dir / "summary/client_compliance_summary.json"
            )
        # Neither is embedded in this response — fetch on demand via
        # GET /reports/{run_id}/client-summary and .../client-detailed below,
        # same pattern as final_summary_context.json.

        # Keep a copy of the original report PDF inside the run folder so it
        # becomes part of the sync below (routed to compliance_file/reports/,
        # split from the JSON artifacts which go to evaluation_engine/reports/).
        shutil.copy2(report_path, run_dir / "report.pdf")

        # Technical evaluation: effective_kb.json + report_evidence.json -> PDF / Excel / JSON / MD in
        # run_dir/evaluation/ (uploaded to S3 with the run just below). Runs for SUCCESS,
        # SUCCESS_WITH_REVIEW and BLOCKED alike. A failure never fails the report upload.
        evaluation = _run_evaluation(run_id, run_dir)

        # Full run folder (standards/report/decisions/manifest/llm/summary,
        # plus the report.pdf just copied in) is now complete on local disk —
        # push the durable copy to S3, split by file type.
        # llm/resolved_compliance_context.json is excluded: it's a pure
        # internal intermediate (Step 32-A output consumed locally by
        # 32-B/32-B.1/32-C only, never served by any endpoint) that runs
        # 400-500MB on a real report — uploading it was the actual cause of
        # the multi-minute report-upload slowness.
        s3.upload_dir_split_safe(
            run_dir, f"{REPORTS_PREFIX}/{run_id}", f"{COMPLIANCE_FILE_REPORTS_PREFIX}/{run_id}",
            exclude_relative={"llm/resolved_compliance_context.json"},
        )

        # Record this report's hash -> run_id so a future re-upload of the
        # exact same file returns this result instead of reprocessing it.
        report_index = _load_report_index()
        report_index[report_sha256] = {
            "run_id": run_id,
            "standard_id": standard_id,
            "pipeline_status": result.pipeline_status.value,
        }
        _save_report_index(report_index)

        # Local disk is scratch space only — the durable copy is on S3 now.
        _cleanup_local(run_dir)

        return JSONResponse(
            {
                "run_id": run_id,
                "standard_id": standard_id,
                "pipeline_status": result.pipeline_status.value,
                "llm_context_bundle": loaded_bundle,
                "summary_brief": summary_brief,
                "evaluation": evaluation,
            }
        )

    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc
    finally:
        if report_path is not None:
            report_path.unlink(missing_ok=True)
        _cleanup_local(KB_CACHE_DIR)  # transient perf cache — regenerable, no reason to keep it on disk


# --------------------------------------------------------------------------- #
# Technical evaluation (PDF / Excel / JSON / MD) of a run
# --------------------------------------------------------------------------- #
EVAL_DIR = evaluation_service.OUT_DIR


def _evaluation_response(run_id: str, res: Optional[dict]) -> Optional[dict]:
    if not res:
        return None
    base = f"{router.prefix}/reports/{run_id}/evaluation/download"
    return {
        "status": "DONE",
        "from_cache": res.get("from_cache", False),
        "result": res["result"],
        "usage": res.get("usage"),
        **{f"download_{fmt}": f"{base}/{fmt}" for fmt in evaluation_service.FORMATS},
    }


def _run_evaluation(run_id: str, run_dir: Path, *, force: bool = False) -> dict:
    if not evaluation_service.enabled():
        return {"status": "SKIPPED", "message": "Technical evaluation is switched off."}
    try:
        return _evaluation_response(run_id, evaluation_service.evaluate_run(run_dir, force=force))
    except evaluation_service.EvaluationError as exc:
        return {"status": "FAILED", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001  real reason in the log only
        logging.getLogger(__name__).exception("Evaluation of %s failed: %s", run_id, exc)
        return {"status": "FAILED", "message": evaluation_service.NEUTRAL_ERROR}


def _pull_run_for_evaluation(run_id: str, run_dir: Path) -> None:
    """Read-through from S3: the two inputs, report.pdf (code checks) and the evaluation folder."""
    for sub in ("standards", "report", EVAL_DIR):
        s3.download_dir_split(f"{REPORTS_PREFIX}/{run_id}/{sub}", f"{COMPLIANCE_FILE_REPORTS_PREFIX}/{run_id}/{sub}",
                              run_dir / sub)
    s3.download_file_safe(f"{COMPLIANCE_FILE_REPORTS_PREFIX}/{run_id}/report.pdf", run_dir / "report.pdf")


def _push_evaluation(run_id: str, run_dir: Path) -> None:
    s3.upload_dir_split_safe(run_dir / EVAL_DIR, f"{REPORTS_PREFIX}/{run_id}/{EVAL_DIR}",
                             f"{COMPLIANCE_FILE_REPORTS_PREFIX}/{run_id}/{EVAL_DIR}")


@router.get("/reports/{run_id}/evaluation")
def get_evaluation(run_id: str):
    """Stored evaluation of a run (gap JSON + download links)."""
    run_dir = RUNS_DIR / run_id
    s3.download_dir_split(f"{REPORTS_PREFIX}/{run_id}/{EVAL_DIR}", f"{COMPLIANCE_FILE_REPORTS_PREFIX}/{run_id}/{EVAL_DIR}",
                          run_dir / EVAL_DIR)
    try:
        res = _evaluation_response(run_id, evaluation_service.stored_result(run_dir))
        if res is None:
            raise HTTPException(404, "No evaluation for this run_id. Run POST /reports/{run_id}/evaluation.")
        return {"run_id": run_id, **res}
    finally:
        _cleanup_local(run_dir)


@router.get("/reports/{run_id}/evaluation/download/{fmt}")
def download_evaluation(run_id: str, fmt: str):
    """fmt = pdf | xlsx | json | md"""
    if fmt not in evaluation_service.FORMATS:
        raise HTTPException(400, "format must be pdf, xlsx, json or md")
    run_dir = RUNS_DIR / run_id
    s3.download_dir_split(f"{REPORTS_PREFIX}/{run_id}/{EVAL_DIR}", f"{COMPLIANCE_FILE_REPORTS_PREFIX}/{run_id}/{EVAL_DIR}",
                          run_dir / EVAL_DIR)
    try:
        path = evaluation_service.file_path(run_dir, fmt)
        if path is None:
            raise HTTPException(404, f"No evaluation {fmt} for this run_id.")
        return Response(path.read_bytes(), media_type=evaluation_service.MEDIA[fmt],
                        headers={"Content-Disposition": f'attachment; filename="{path.name}"',
                                 "Cache-Control": "no-store"})
    finally:
        _cleanup_local(run_dir)


@router.post("/reports/{run_id}/evaluation")
def run_evaluation(run_id: str, force: bool = Query(False, description="Evaluate again even if a result exists")):
    """Evaluate an existing run (e.g. one processed before this step existed), or again with force=true."""
    if not evaluation_service.enabled():
        raise HTTPException(503, "Technical evaluation is switched off.")
    run_dir = RUNS_DIR / run_id
    _pull_run_for_evaluation(run_id, run_dir)
    try:
        if not (run_dir / "report" / "report_evidence.json").is_file():
            raise HTTPException(404, f"Run '{run_id}' not found (no report/report_evidence.json).")
        res = _run_evaluation(run_id, run_dir, force=force)
        if res.get("status") != "DONE":
            raise HTTPException(503, res.get("message") or evaluation_service.NEUTRAL_ERROR)
        _push_evaluation(run_id, run_dir)
        return {"run_id": run_id, **res}
    finally:
        _cleanup_local(run_dir)


@router.post("/reports/{run_id}/evaluation/rebuild")
def rebuild_evaluation(
    run_id: str,
    markdown_file: Optional[UploadFile] = File(None, description="Optional edited .md (same structure)"),
):
    """PDF / Excel / JSON / MD again from the stored .md, or from an edited .md - no evaluation cost."""
    run_dir = RUNS_DIR / run_id
    _pull_run_for_evaluation(run_id, run_dir)
    try:
        md = markdown_file.file.read().decode("utf-8-sig") if markdown_file is not None else None
        try:
            res = evaluation_service.rebuild_run(run_dir, md)
        except evaluation_service.EvaluationError as exc:
            raise HTTPException(400, str(exc)) from exc
        _push_evaluation(run_id, run_dir)
        return {"run_id": run_id, **_evaluation_response(run_id, res)}
    finally:
        _cleanup_local(run_dir)


@router.get("/reports/{run_id}/llm-context-bundle")
def get_llm_context_bundle(run_id: str):
    run_dir = RUNS_DIR / run_id
    path = run_dir / "llm" / "llm_context_bundle.json"
    if not path.is_file():
        # Read-through: local disk is ephemeral, so pull this run's JSON down
        # from S3 fresh (no PDF needed for this particular read).
        s3.download_dir(f"{REPORTS_PREFIX}/{run_id}", run_dir)
    try:
        if not path.is_file():
            raise HTTPException(404, "llm_context_bundle.json not found for this run_id")
        return _load_json(path)
    finally:
        _cleanup_local(run_dir)


@router.get("/reports/{run_id}/summary-brief")
def get_summary_brief(run_id: str):
    """The compact, client-facing summary (summary/final_summary_brief_context.json)
    — same read-through-from-S3 behavior as the llm-context-bundle endpoint."""
    run_dir = RUNS_DIR / run_id
    path = run_dir / "summary" / "final_summary_brief_context.json"
    if not path.is_file():
        s3.download_dir(f"{REPORTS_PREFIX}/{run_id}", run_dir)
    try:
        if not path.is_file():
            raise HTTPException(404, "final_summary_brief_context.json not found for this run_id")
        return _load_json(path)
    finally:
        _cleanup_local(run_dir)


@router.get("/reports/{run_id}/summary-context")
def get_summary_context(run_id: str):
    """The full, detailed summary context (summary/final_summary_context.json) —
    the source the brief above was built from. Larger payload, fetched on
    demand rather than embedded in the /reports response."""
    run_dir = RUNS_DIR / run_id
    path = run_dir / "summary" / "final_summary_context.json"
    if not path.is_file():
        s3.download_dir(f"{REPORTS_PREFIX}/{run_id}", run_dir)
    try:
        if not path.is_file():
            raise HTTPException(404, "final_summary_context.json not found for this run_id")
        return _load_json(path)
    finally:
        _cleanup_local(run_dir)


@router.get("/reports/{run_id}/client-summary")
def get_client_summary(run_id: str):
    """The compact, client-facing canonical summary
    (summary/client_compliance_summary.json) — produced natively by the
    canonical-authority pipeline. Same read-through-from-S3 behavior as the
    other /summary* endpoints above. Use this to confirm a report's run
    actually generated this file, without opening the S3 bucket by hand."""
    run_dir = RUNS_DIR / run_id
    path = run_dir / "summary" / "client_compliance_summary.json"
    if not path.is_file():
        s3.download_dir(f"{REPORTS_PREFIX}/{run_id}", run_dir)
    try:
        if not path.is_file():
            raise HTTPException(404, "client_compliance_summary.json not found for this run_id")
        return _load_json(path)
    finally:
        _cleanup_local(run_dir)


@router.get("/reports/{run_id}/client-detailed")
def get_client_detailed(run_id: str):
    """The full technical canonical record (summary/canonical_client_detailed.json)
    — supporting detail behind client-summary above. Larger payload, fetched
    on demand rather than embedded in the /reports response."""
    run_dir = RUNS_DIR / run_id
    path = run_dir / "summary" / "canonical_client_detailed.json"
    if not path.is_file():
        s3.download_dir(f"{REPORTS_PREFIX}/{run_id}", run_dir)
    try:
        if not path.is_file():
            raise HTTPException(404, "canonical_client_detailed.json not found for this run_id")
        return _load_json(path)
    finally:
        _cleanup_local(run_dir)


@router.get("/reports/{run_id}/files")
def list_report_files(run_id: str):
    """List every file that actually exists on S3 for this run_id — both the
    JSON side (evaluation_engine/reports/{run_id}/...) and the PDF side
    (compliance_file/reports/{run_id}/...) — with size and last-modified
    time. Pure listing, nothing is downloaded to local disk. Use this to
    check what a run actually produced without re-uploading the report or
    guessing which of the /client-summary, /client-detailed, /summary-brief,
    /summary-context, /llm-context-bundle endpoints will 404."""
    if not s3.enabled:
        raise HTTPException(503, "S3 is not enabled (no S3_BUCKET_NAME configured) — nothing to list.")
    json_files = s3.list_files(f"{REPORTS_PREFIX}/{run_id}")
    pdf_files = s3.list_files(f"{COMPLIANCE_FILE_REPORTS_PREFIX}/{run_id}")
    if not json_files and not pdf_files:
        raise HTTPException(404, f"No files found on S3 for run_id '{run_id}'.")
    return {
        "run_id": run_id,
        "json_files": sorted(json_files, key=lambda f: f["path"]),
        "pdf_files": sorted(pdf_files, key=lambda f: f["path"]),
        "total_files": len(json_files) + len(pdf_files),
    }



@router.get("/s3-structure")
def get_s3_structure():
    """Folder-name-only view of what's on S3 — no file names, no file
    contents, just the nested folder tree under evaluation_engine/ (JSON
    artifacts) and compliance_file/ (PDFs), so you can see what standards/
    products/reports exist without downloading or listing any actual data."""
    if not s3.enabled:
        return {
            "message": "S3 is not enabled (no S3_BUCKET_NAME configured) — nothing to show.",
            EVALUATION_ENGINE_PREFIX: {},
            COMPLIANCE_FILE_PREFIX: {},
        }
    return {
        "bucket": s3.bucket,
        EVALUATION_ENGINE_PREFIX: s3.folder_tree(EVALUATION_ENGINE_PREFIX),
        COMPLIANCE_FILE_PREFIX: s3.folder_tree(COMPLIANCE_FILE_PREFIX),
    }


@router.delete("/s3-data")
def delete_all_s3_data(
    confirm: str = Query(
        ...,
        description=(
            "Safety guard — must be exactly 'DELETE_ALL' to actually delete anything. "
            "This permanently removes EVERY object under BOTH the evaluation_engine/ "
            "prefix (JSON artifacts — standards/ and reports/) AND the compliance_file/ "
            "prefix (PDFs — standards/ and reports/) for this bucket. It does NOT touch "
            "local disk (storage/) at all — only the S3 copy. Irreversible."
        ),
    ),
):
    if confirm != "DELETE_ALL":
        raise HTTPException(
            400,
            "Refusing to delete without confirmation. Re-send with "
            "?confirm=DELETE_ALL to permanently delete all compliance-engine "
            "data from S3 (local disk is not affected).",
        )
    if not s3.enabled:
        return {
            "message": "S3 is not enabled (no S3_BUCKET_NAME configured) — there is nothing to delete.",
            "bucket": None,
            "deleted_count": 0,
        }
    # Delete BOTH top-level prefixes — evaluation_engine/ (JSON artifacts) AND
    # compliance_file/ (PDFs). These were originally a single prefix; when
    # compliance_file/ was split out later for PDF storage, this endpoint
    # was never updated to also clear it — fixed now.
    deleted_json = s3.delete_prefix(EVALUATION_ENGINE_PREFIX)
    deleted_pdf = s3.delete_prefix(COMPLIANCE_FILE_PREFIX)
    deleted = deleted_json + deleted_pdf
    return {
        "message": (
            f"Deleted {deleted} object(s) from s3://{s3.bucket}/ "
            f"({deleted_json} under {EVALUATION_ENGINE_PREFIX}/, {deleted_pdf} under {COMPLIANCE_FILE_PREFIX}/). "
            "Local disk (storage/) was NOT touched."
        ),
        "bucket": s3.bucket,
        "prefixes": [EVALUATION_ENGINE_PREFIX, COMPLIANCE_FILE_PREFIX],
        "deleted_count": deleted,
        "deleted_count_by_prefix": {
            EVALUATION_ENGINE_PREFIX: deleted_json,
            COMPLIANCE_FILE_PREFIX: deleted_pdf,
        },
    }
"""python -m llm_evaluation <run_dir> [--dry-run] [--force]

  --dry-run   build ai_evaluation/llm_input.md and print size + estimated cost, no OpenAI call
  --force     call OpenAI again even if ai_evaluation/evaluation.json exists
"""
# import argparse
# import json
# from pathlib import Path

# try:
#     from dotenv import load_dotenv
#     load_dotenv(Path(__file__).resolve().parent.parent / ".env")
# except ImportError:
#     pass

# from llm_evaluation.service import dry_run, evaluate_run

# if __name__ == "__main__":
#     ap = argparse.ArgumentParser(description="AI evaluation of an engine run folder")
#     ap.add_argument("run_dir")
#     ap.add_argument("--dry-run", action="store_true")
#     ap.add_argument("--force", action="store_true")
#     a = ap.parse_args()
#     res = dry_run(a.run_dir) if a.dry_run else evaluate_run(a.run_dir, force=a.force)
#     print(json.dumps(res, indent=2, ensure_ascii=False))

@app.get("/health")
def health():
    return {"status": "ok"}