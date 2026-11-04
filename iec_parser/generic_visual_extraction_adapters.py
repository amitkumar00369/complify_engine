"""Provider-neutral OCR and vision extraction adapter contracts."""

from __future__ import annotations

import csv
import io
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, Protocol

from .generic_visual_extraction_models import OCRExtractionResult, VisualExtractionStatus


@dataclass(frozen=True)
class VisualRegionInput:
    region_id: str
    image_bytes: bytes
    metadata: Dict[str, Any]


class VisualTextExtractor(Protocol):
    provider_name: str

    def extract(self, region: VisualRegionInput, *, timeout_seconds: float) -> OCRExtractionResult: ...


class VisualSemanticExtractor(Protocol):
    provider_name: str

    def extract(self, region: VisualRegionInput, *, timeout_seconds: float) -> Dict[str, Any]: ...


class LocalTesseractTextExtractor:
    """Local subprocess adapter; source text is untrusted data, never a command."""

    provider_name = "LOCAL_TESSERACT_CLI"

    def __init__(self, executable: str = "tesseract", language: str = "eng") -> None:
        self.executable = executable
        self.language = language

    def extract(self, region: VisualRegionInput, *, timeout_seconds: float) -> OCRExtractionResult:
        try:
            process = subprocess.run(
                [self.executable, "stdin", "stdout", "-l", self.language, "tsv"],
                input=region.image_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=timeout_seconds, check=False,
            )
        except subprocess.TimeoutExpired:
            return OCRExtractionResult(VisualExtractionStatus.TIMEOUT, errors=["OCR_TIMEOUT"])
        except (OSError, ValueError) as error:
            return OCRExtractionResult(VisualExtractionStatus.ERROR,
                                       errors=[f"OCR_ADAPTER_ERROR:{type(error).__name__}"])
        if process.returncode:
            return OCRExtractionResult(VisualExtractionStatus.ERROR,
                                       errors=[f"OCR_PROVIDER_EXIT_{process.returncode}"])
        try:
            rows = list(csv.DictReader(io.StringIO(process.stdout.decode("utf-8", "replace")),
                                       delimiter="\t"))
            tokens = []
            for row in rows:
                text = (row.get("text") or "").strip()
                if not text:
                    continue
                try:
                    confidence = float(row.get("conf", "-1"))
                except ValueError:
                    confidence = -1.0
                tokens.append({"text": text, "confidence": round(max(0.0, confidence) / 100, 4),
                               "left": int(row.get("left") or 0), "top": int(row.get("top") or 0),
                               "width": int(row.get("width") or 0), "height": int(row.get("height") or 0)})
        except (csv.Error, TypeError, ValueError) as error:
            return OCRExtractionResult(VisualExtractionStatus.ERROR,
                                       errors=[f"MALFORMED_OCR_RESPONSE:{type(error).__name__}"])
        raw = " ".join(item["text"] for item in tokens).strip()
        if not raw:
            return OCRExtractionResult(VisualExtractionStatus.EMPTY, raw_text="", confidence=None)
        confidence = round(sum(item["confidence"] for item in tokens) / len(tokens), 4)
        status = VisualExtractionStatus.SUCCESS if confidence >= .55 else VisualExtractionStatus.LOW_CONFIDENCE
        return OCRExtractionResult(status, raw, confidence, tokens, [raw],
                                   provider_metadata={"provider": self.provider_name,
                                                      "language": self.language})


class DisabledVisualSemanticExtractor:
    provider_name = "DISABLED"

    def extract(self, region: VisualRegionInput, *, timeout_seconds: float) -> Dict[str, Any]:
        return {"status": VisualExtractionStatus.UNSUPPORTED.value,
                "errors": ["VISION_PROVIDER_DISABLED"]}


class FakeVisualTextExtractor:
    provider_name = "FAKE_OCR"

    def __init__(self, results: Dict[str, OCRExtractionResult] | None = None,
                 default: OCRExtractionResult | None = None) -> None:
        self.results = results or {}
        self.default = default or OCRExtractionResult(VisualExtractionStatus.EMPTY, raw_text="")
        self.calls = []

    def extract(self, region: VisualRegionInput, *, timeout_seconds: float) -> OCRExtractionResult:
        self.calls.append(region.region_id)
        return self.results.get(region.region_id, self.default)


class FakeVisualSemanticExtractor:
    provider_name = "FAKE_VISION"

    def __init__(self, results: Dict[str, Dict[str, Any]] | None = None) -> None:
        self.results = results or {}
        self.calls = []

    def extract(self, region: VisualRegionInput, *, timeout_seconds: float) -> Dict[str, Any]:
        self.calls.append(region.region_id)
        return self.results.get(region.region_id, {"status": "UNSUPPORTED"})
