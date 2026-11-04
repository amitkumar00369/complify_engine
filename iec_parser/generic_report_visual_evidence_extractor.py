"""Step 46-L governed extraction from Step 46-K visual inventory regions."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .generic_visual_extraction_adapters import (
    DisabledVisualSemanticExtractor, LocalTesseractTextExtractor, VisualRegionInput,
    VisualSemanticExtractor, VisualTextExtractor,
)
from .generic_visual_extraction_models import (
    OCRExtractionResult, VisualEvidenceCandidate, VisualEvidenceExtraction,
    VisualExtractionStatus, VisualRegionExtractionResult, VisualRoutingAction,
)


@dataclass(frozen=True)
class VisualExtractionConfig:
    ocr_enabled: bool = True
    vision_enabled: bool = False
    max_regions_per_report: int = 200
    max_ocr_regions: int = 24
    max_vision_regions: int = 0
    render_dpi: int = 200
    max_rendered_pixels: int = 12_000_000
    max_image_bytes: int = 20_000_000
    timeout_seconds: float = 20.0
    max_retries: int = 0
    low_confidence_threshold: float = .55


class GenericReportVisualEvidenceExtractor:
    SCHEMA_VERSION = "REPORT_VISUAL_EVIDENCE_EXTRACTION_V1"
    POLICY_VERSION = "STEP46L_EXTRACTION_POLICY_V1"
    OCR_CATEGORIES = {"NAMEPLATE", "MARKING_LABEL", "MEASUREMENT_TABLE",
                      "MEASUREMENT_SCREENSHOT", "SCANNED_TEXT"}
    VISION_CATEGORIES = {"CIRCUIT_DIAGRAM", "TECHNICAL_DRAWING", "TEST_SETUP"}

    def __init__(self, *, config: Optional[VisualExtractionConfig] = None,
                 ocr_extractor: Optional[VisualTextExtractor] = None,
                 vision_extractor: Optional[VisualSemanticExtractor] = None) -> None:
        self.config = config or VisualExtractionConfig()
        self.ocr_extractor = ocr_extractor or LocalTesseractTextExtractor()
        self.vision_extractor = vision_extractor or DisabledVisualSemanticExtractor()

    def extract(self, pdf_path, inventory, *, run_id: Optional[str] = None) -> VisualEvidenceExtraction:
        path = Path(pdf_path)
        payload, inventory_hash = self._inventory(inventory)
        if payload.get("schema_version") != "REPORT_VISUAL_INVENTORY_V1":
            raise ValueError("Unsupported or missing Step 46-K inventory schema")
        report_hash = self._file_hash(path)
        expected_hash = payload.get("source_report", {}).get("file_hash")
        if expected_hash != report_hash:
            raise ValueError("Source inventory report hash mismatch")
        regions = sorted(self._regions(payload), key=self._priority_key)
        config_hash = hashlib.sha256(json.dumps(asdict(self.config), sort_keys=True,
                                                   separators=(",", ":")).encode()).hexdigest()
        results: List[VisualRegionExtractionResult] = []
        extracted_by_hash: Dict[str, VisualRegionExtractionResult] = {}
        ocr_count = vision_count = 0
        try:
            import fitz
            document = fitz.open(path)
        except Exception as error:
            raise ValueError(f"Unable to open source PDF: {type(error).__name__}") from error
        try:
            for sequence, region in enumerate(regions):
                action, reason = self.route(region)
                content_hash = str(region.get("stable_content_hash") or "")
                if content_hash and content_hash in extracted_by_hash:
                    results.append(self._duplicate(region, extracted_by_hash[content_hash]))
                    continue
                if sequence >= self.config.max_regions_per_report:
                    results.append(self._result(region, VisualRoutingAction.SKIP, "RESOURCE_LIMIT",
                                                VisualExtractionStatus.RESOURCE_LIMIT))
                    continue
                if action is VisualRoutingAction.OCR:
                    if ocr_count >= self.config.max_ocr_regions:
                        results.append(self._result(region, action, "RESOURCE_LIMIT",
                                                    VisualExtractionStatus.RESOURCE_LIMIT))
                        continue
                    ocr_count += 1
                    result = self._ocr(document, region, action, reason, report_hash)
                elif action is VisualRoutingAction.VISION:
                    if not self.config.vision_enabled:
                        result = self._result(region, VisualRoutingAction.REVIEW_REQUIRED,
                                              "VISION_PROVIDER_DISABLED",
                                              VisualExtractionStatus.REVIEW_REQUIRED)
                    elif vision_count >= self.config.max_vision_regions:
                        result = self._result(region, action, "RESOURCE_LIMIT",
                                              VisualExtractionStatus.RESOURCE_LIMIT)
                    else:
                        vision_count += 1
                        result = self._vision(document, region, action, reason, report_hash)
                else:
                    status = (VisualExtractionStatus.REVIEW_REQUIRED
                              if action is VisualRoutingAction.REVIEW_REQUIRED
                              else VisualExtractionStatus.SKIPPED)
                    result = self._result(region, action, reason, status)
                results.append(result)
                if content_hash and result.extraction_status in {
                        VisualExtractionStatus.SUCCESS, VisualExtractionStatus.EMPTY,
                        VisualExtractionStatus.LOW_CONFIDENCE}:
                    extracted_by_hash[content_hash] = result
        finally:
            document.close()
        results.sort(key=lambda item: (item.page_number, *item.source_bbox, item.region_id))
        summary = self._summary(results, len(regions), ocr_count, vision_count)
        return VisualEvidenceExtraction(
            self.SCHEMA_VERSION, run_id or payload.get("run_id") or "VISUAL-EXTRACTION",
            {"schema_version": payload["schema_version"], "inventory_hash": inventory_hash,
             "report_hash": report_hash}, self.POLICY_VERSION, config_hash, "PASS",
            summary, results, [],
        )

    def route(self, region: Dict[str, Any]) -> Tuple[VisualRoutingAction, str]:
        category = str(region.get("category") or "UNKNOWN_VISUAL")
        priority = str(region.get("processing_priority") or "LOW")
        if region.get("filtered") or category == "DECORATIVE" or priority == "IGNORE":
            return VisualRoutingAction.SKIP, "DECORATIVE"
        if region.get("repeated_template_visual"):
            return VisualRoutingAction.SKIP, "REPEATED_TEMPLATE"
        if region.get("provenance", {}).get("native_text_equivalent") is True:
            return VisualRoutingAction.SKIP, "NATIVE_TEXT_SUFFICIENT"
        if category in self.OCR_CATEGORIES and region.get("ocr_candidate"):
            if not self.config.ocr_enabled:
                return VisualRoutingAction.REVIEW_REQUIRED, "OCR_PROVIDER_DISABLED"
            return VisualRoutingAction.OCR, ("NAMEPLATE_OR_MARKING" if category in {"NAMEPLATE", "MARKING_LABEL"}
                                             else "HIGH_PRIORITY_OCR_CANDIDATE")
        if category in self.VISION_CATEGORIES and region.get("vision_candidate"):
            return VisualRoutingAction.VISION, "DIAGRAM_REQUIRES_VISUAL_INTERPRETATION"
        if category == "PRODUCT_PHOTO":
            return VisualRoutingAction.SKIP, "LOW_PRIORITY"
        if category == "UNKNOWN_VISUAL" and priority in {"LOW", "MEDIUM"}:
            return VisualRoutingAction.SKIP, "LOW_PRIORITY"
        return VisualRoutingAction.SKIP, "EXTRACTION_NOT_REQUIRED"

    def _ocr(self, document, region, action, reason, report_hash):
        image, render = self._crop(document, region)
        if image is None:
            return self._result(region, action, render, VisualExtractionStatus.RESOURCE_LIMIT)
        request = VisualRegionInput(region["region_id"], image, self._bounded_metadata(region, render))
        raw = self.ocr_extractor.extract(request, timeout_seconds=self.config.timeout_seconds)
        if not isinstance(raw, OCRExtractionResult):
            return self._result(region, action, "MALFORMED_EXTRACTION_RESPONSE",
                                VisualExtractionStatus.ERROR, errors=["MALFORMED_OCR_RESPONSE"])
        normalized = self.normalize(raw.raw_text) if raw.raw_text is not None else None
        candidates = self._candidates(normalized or "", region, raw.confidence, report_hash)
        return self._result(region, action, reason, raw.status, self.ocr_extractor.provider_name,
                            raw.raw_text, normalized, raw.confidence, candidates,
                            raw.warnings, raw.errors, render)

    def _vision(self, document, region, action, reason, report_hash):
        image, render = self._crop(document, region)
        if image is None:
            return self._result(region, action, render, VisualExtractionStatus.RESOURCE_LIMIT)
        request = VisualRegionInput(region["region_id"], image, self._bounded_metadata(region, render))
        response = self.vision_extractor.extract(request, timeout_seconds=self.config.timeout_seconds)
        if not isinstance(response, dict) or response.get("status") not in {x.value for x in VisualExtractionStatus}:
            return self._result(region, action, "MALFORMED_EXTRACTION_RESPONSE",
                                VisualExtractionStatus.ERROR, errors=["MALFORMED_VISION_RESPONSE"])
        status = VisualExtractionStatus(response["status"])
        raw = response.get("raw_text")
        normalized = self.normalize(raw) if isinstance(raw, str) else None
        return self._result(region, action, reason, status, self.vision_extractor.provider_name,
                            raw, normalized, response.get("confidence"),
                            self._candidates(normalized or "", region, response.get("confidence"), report_hash),
                            response.get("warnings", []), response.get("errors", []), render)

    def _crop(self, document, region):
        import fitz
        page_number = int(region["page_number"])
        if page_number < 1 or page_number > len(document):
            return None, "UNSAFE_REGION"
        bbox = region.get("bbox") or []
        if len(bbox) != 4:
            return None, "UNSAFE_REGION"
        rect = fitz.Rect(*[float(x) for x in bbox]) & document[page_number - 1].rect
        if rect.is_empty or rect.is_infinite:
            return None, "UNSAFE_REGION"
        scale = self.config.render_dpi / 72.0
        pixels = int(rect.width * scale) * int(rect.height * scale)
        if pixels <= 0 or pixels > self.config.max_rendered_pixels:
            return None, "RESOURCE_LIMIT"
        pixmap = document[page_number - 1].get_pixmap(matrix=fitz.Matrix(scale, scale),
                                                      clip=rect, alpha=False)
        image = pixmap.tobytes("png")
        if len(image) > self.config.max_image_bytes:
            return None, "RESOURCE_LIMIT"
        return image, {"crop_width": pixmap.width, "crop_height": pixmap.height,
                       "render_dpi": self.config.render_dpi, "source_bbox": list(rect),
                       "transform": "PDF_POINTS_TO_RASTER_TOP_LEFT"}

    @staticmethod
    def normalize(text: str) -> str:
        return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()

    def _candidates(self, text, region, confidence, report_hash):
        definitions = (
            ("rated_voltage", r"(?<!\d)(\d{1,4}(?:[.,]\d+)?(?:\s*[-–/]\s*\d{1,4}(?:[.,]\d+)?)?)\s*(V)\b"),
            ("rated_frequency", r"(?<!\d)(\d{1,4}(?:[.,]\d+)?)\s*(Hz)\b"),
            ("rated_power_input", r"(?<!\d)(\d{1,7}(?:[.,]\d+)?)\s*(k?W)\b"),
            ("rated_current", r"(?<!\d)(\d{1,5}(?:[.,]\d+)?)\s*(m?A)\b"),
            ("ip_rating", r"\b(IP[0-6X][0-9X])\b"),
            ("temperature", r"(?<!\d)([-+]?\d{1,4}(?:[.,]\d+)?)\s*(?:°\s*)?(C)\b"),
        )
        output = []
        for kind, pattern in definitions:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                raw_value = match.group(1)
                unit = None if kind == "ip_rating" else match.group(2)
                normalized = raw_value.replace(",", ".")
                identity = json.dumps({"report_hash": report_hash, "region_id": region["region_id"],
                    "candidate_type": kind, "value": normalized, "unit": unit,
                    "span": match.span()}, sort_keys=True, separators=(",", ":"))
                output.append(VisualEvidenceCandidate(
                    "VISUAL-CANDIDATE-" + hashlib.sha256(identity.encode()).hexdigest()[:24].upper(),
                    kind, raw_value, normalized, unit, "POSITIVE", "UNKNOWN", region["region_id"],
                    int(region["page_number"]), list(region["bbox"]),
                    self.ocr_extractor.provider_name, confidence, text))
        for match in re.finditer(r"\bwithout\s+(plug|switch|motor|capacitor|relay)\b", text, re.IGNORECASE):
            kind = "has_" + match.group(1).casefold()
            identity = json.dumps({"report_hash": report_hash, "region_id": region["region_id"],
                "candidate_type": kind, "value": False, "unit": None, "span": match.span()},
                sort_keys=True, separators=(",", ":"))
            output.append(VisualEvidenceCandidate(
                "VISUAL-CANDIDATE-" + hashlib.sha256(identity.encode()).hexdigest()[:24].upper(),
                kind, match.group(0), False, None, "NEGATIVE", "UNKNOWN", region["region_id"],
                int(region["page_number"]), list(region["bbox"]),
                self.ocr_extractor.provider_name, confidence, text))
        return sorted(output, key=lambda item: item.candidate_id)

    def _result(self, region, action, reason, status, method=None, raw=None, normalized=None,
                confidence=None, candidates=None, warnings=None, errors=None, render=None):
        return VisualRegionExtractionResult(
            region.get("region_id", "UNKNOWN"), int(region.get("page_number", 0)),
            list(region.get("bbox") or []), str(region.get("stable_content_hash") or ""),
            str(region.get("category") or "UNKNOWN_VISUAL"),
            str(region.get("processing_priority") or "LOW"), action, reason, status, method,
            raw, normalized, confidence, candidates or [], None, warnings or [], errors or [],
            {"authority": "EXTRACTED_VISUAL_EVIDENCE", "decision_authority": "NONE",
             "source_inventory_region_id": region.get("region_id"),
             "source_page": region.get("page_number"), "source_bbox": region.get("bbox"),
             "render": render})

    def _duplicate(self, region, original):
        result = self._result(region, VisualRoutingAction.SKIP, "DUPLICATE_CONTENT",
                              VisualExtractionStatus.SKIPPED)
        result.duplicate_of_region_id = original.region_id
        result.provenance["canonical_extraction_region_id"] = original.region_id
        return result

    @staticmethod
    def _bounded_metadata(region, render):
        return {"region_id": region.get("region_id"), "page_number": region.get("page_number"),
                "bbox": region.get("bbox"), "category": region.get("category"),
                "nearby_native_text": (region.get("nearby_native_text") or "")[:320],
                "render": render, "source_content_is_untrusted": True}

    @staticmethod
    def _inventory(inventory):
        if isinstance(inventory, (str, Path)):
            raw = Path(inventory).read_bytes(); return json.loads(raw), hashlib.sha256(raw).hexdigest()
        payload = inventory.to_dict() if hasattr(inventory, "to_dict") else inventory
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return payload, hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _regions(payload) -> Iterable[Dict[str, Any]]:
        for page in payload.get("pages", []):
            for region in page.get("visual_regions", []):
                yield region

    @staticmethod
    def _priority_key(region):
        rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "IGNORE": 3}
        category = {"NAMEPLATE": 0, "MARKING_LABEL": 1, "MEASUREMENT_TABLE": 2,
                    "MEASUREMENT_SCREENSHOT": 3, "SCANNED_TEXT": 4}.get(region.get("category"), 5)
        return (rank.get(region.get("processing_priority"), 9), category,
                int(region.get("page_number", 0)), *(region.get("bbox") or [0, 0, 0, 0]),
                region.get("region_id", ""))

    @staticmethod
    def _summary(results, inventory_count, ocr_count, vision_count):
        status = lambda value: sum(item.extraction_status is value for item in results)
        return {"inventory_regions": inventory_count,
                "selected_regions": ocr_count + vision_count,
                "skipped_regions": status(VisualExtractionStatus.SKIPPED),
                "ocr_attempted": ocr_count,
                "ocr_success": status(VisualExtractionStatus.SUCCESS),
                "ocr_empty": status(VisualExtractionStatus.EMPTY),
                "ocr_low_confidence": status(VisualExtractionStatus.LOW_CONFIDENCE),
                "vision_attempted": vision_count, "vision_success": 0,
                "review_required": status(VisualExtractionStatus.REVIEW_REQUIRED),
                "resource_limited": status(VisualExtractionStatus.RESOURCE_LIMIT),
                "extraction_errors": status(VisualExtractionStatus.ERROR) + status(VisualExtractionStatus.TIMEOUT),
                "structured_candidate_count": sum(len(item.structured_candidates) for item in results)}

    @staticmethod
    def _file_hash(path):
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def save_json(extraction: VisualEvidenceExtraction, output_path) -> None:
        Path(output_path).write_text(extraction.to_json(indent=2) + "\n", encoding="utf-8")
