"""Build a deterministic, non-semantic inventory of report PDF visuals."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .generic_visual_inventory_models import (
    VisualEvidenceInventory, VisualEvidencePage, VisualEvidenceRegion,
    VisualObjectType, VisualProcessingPriority, VisualRegionCategory,
)


class GenericReportVisualInventoryBuilder:
    """Inspect PDF objects and nearby native layout without OCR or vision."""

    SCHEMA_VERSION = "REPORT_VISUAL_INVENTORY_V1"
    COORDINATE_SYSTEM = "PDF_PAGE_TOP_LEFT"

    def __init__(self, *, min_width: float = 12.0, min_height: float = 12.0,
                 min_area_ratio: float = .0004, scanned_area_ratio: float = .72,
                 scanned_text_density: float = .002, max_objects_per_page: int = 2000,
                 max_pages: int = 2000, nearby_text_chars: int = 320) -> None:
        self.min_width = min_width; self.min_height = min_height
        self.min_area_ratio = min_area_ratio
        self.scanned_area_ratio = scanned_area_ratio
        self.scanned_text_density = scanned_text_density
        self.max_objects_per_page = max_objects_per_page
        self.max_pages = max_pages
        self.nearby_text_chars = nearby_text_chars

    def build(self, pdf_path, *, run_id: Optional[str] = None) -> VisualEvidenceInventory:
        path = Path(pdf_path)
        if not path.is_file():
            raise FileNotFoundError(f"Report PDF not found: {path}")
        report_hash = self._file_hash(path)
        rid = run_id or "VISUAL-" + report_hash[:20].upper()
        diagnostics: List[Dict[str, Any]] = []
        pages: List[VisualEvidencePage] = []
        try:
            import fitz
            with fitz.open(path) as pdf:
                page_total = min(len(pdf), self.max_pages)
                if len(pdf) > self.max_pages:
                    diagnostics.append({"code": "PAGE_LIMIT_REACHED", "detected": len(pdf),
                                        "processed": self.max_pages})
                for index in range(page_total):
                    pages.append(self._page(pdf[index], index + 1, report_hash, diagnostics))
        except (OSError, RuntimeError, ValueError) as error:
            raise ValueError(f"Unable to inventory report PDF {path}: {error}") from error
        self._mark_repeated_templates(pages)
        for page in pages:
            page.visual_regions.sort(key=lambda item: (*item.bbox, item.region_id))
        return VisualEvidenceInventory(
            self.SCHEMA_VERSION, rid,
            {"file_name": path.name, "file_hash": report_hash}, "PASS",
            self._summary(pages), pages, diagnostics,
        )

    def _page(self, page: Any, page_number: int, report_hash: str,
              diagnostics: List[Dict[str, Any]]) -> VisualEvidencePage:
        width, height = float(page.rect.width), float(page.rect.height)
        page_area = max(1.0, width * height)
        text = page.get_text("text") or ""
        text_density = round(len(re.sub(r"\s+", "", text)) / page_area, 8)
        blocks = self._text_blocks(page)
        candidates: List[Dict[str, Any]] = []
        try:
            image_info = list(page.get_image_info(xrefs=True) or [])
        except Exception as error:
            image_info = []
            diagnostics.append({"code": "IMAGE_INVENTORY_ERROR", "page_number": page_number,
                                "error": type(error).__name__})
        for order, info in enumerate(image_info[:self.max_objects_per_page]):
            bbox = self._bbox(info.get("bbox"))
            if not bbox:
                continue
            digest = info.get("digest")
            content_hash = (digest.hex() if isinstance(digest, bytes) else
                            hashlib.sha256(json.dumps({"xref": info.get("xref"),
                                "width": info.get("width"), "height": info.get("height"),
                                "bbox": bbox}, sort_keys=True).encode()).hexdigest())
            candidates.append({"bbox": bbox, "object_type": VisualObjectType.RASTER_IMAGE,
                "object_id": f"IMAGE-XREF-{info.get('xref', 0)}-PLACEMENT-{order}",
                "content_hash": content_hash, "pixel_width": info.get("width"),
                "pixel_height": info.get("height")})
        try:
            drawings = list(page.get_drawings() or [])
        except Exception as error:
            drawings = []
            diagnostics.append({"code": "VECTOR_INVENTORY_ERROR", "page_number": page_number,
                                "error": type(error).__name__})
        decorative_vectors = 0
        for order, drawing in enumerate(drawings[:self.max_objects_per_page]):
            if len(drawing.get("items") or []) <= 1:
                decorative_vectors += 1
                continue
            bbox = self._bbox(drawing.get("rect"))
            if not bbox:
                continue
            content_hash = hashlib.sha256(json.dumps({"bbox": bbox,
                "item_count": len(drawing.get("items") or []),
                "types": [str(item[0]) for item in drawing.get("items") or []]},
                sort_keys=True).encode()).hexdigest()
            candidates.append({"bbox": bbox, "object_type": VisualObjectType.VECTOR_DRAWING,
                "object_id": f"VECTOR-{order}", "content_hash": content_hash,
                "item_count": len(drawing.get("items") or [])})
        if decorative_vectors:
            diagnostics.append({"code": "DECORATIVE_VECTOR_OBJECTS_FILTERED",
                                "page_number": page_number, "count": decorative_vectors})
        if len(image_info) + len(drawings) > self.max_objects_per_page:
            diagnostics.append({"code": "OBJECT_LIMIT_REACHED", "page_number": page_number,
                                "detected": len(image_info) + len(drawings),
                                "processed": self.max_objects_per_page})
        merged = self._merge_candidates(candidates)
        detected_regions = [self._region(item, page_number, width, height, text_density, blocks,
                                         bool(text.strip()), report_hash) for item in merged]
        regions = [region for region in detected_regions if not region.filtered]
        page_diagnostics = []
        filtered_count = len(detected_regions) - len(regions)
        if filtered_count:
            page_diagnostics.append({"code": "DECORATIVE_OR_TINY_VISUALS_FILTERED",
                                     "count": filtered_count})
        return VisualEvidencePage(page_number, width, height, bool(text.strip()), text_density,
                                  regions, page_diagnostics)

    def _region(self, item: Dict[str, Any], page_number: int, page_width: float,
                page_height: float, text_density: float, blocks: Sequence[Tuple],
                native_text: bool, report_hash: str) -> VisualEvidenceRegion:
        bbox = item["bbox"]
        width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
        area_ratio = round(max(0.0, width * height) / max(1.0, page_width * page_height), 8)
        normalized = [round(bbox[0] / page_width, 8), round(bbox[1] / page_height, 8),
                      round(bbox[2] / page_width, 8), round(bbox[3] / page_height, 8)]
        nearby, heading = self._nearby_text(bbox, blocks)
        category, confidence, reason = self._classify(
            nearby, heading, item["object_type"], area_ratio, text_density)
        filtered, filter_reason = self._filter(width, height, area_ratio, item)
        if filtered:
            priority, priority_reason = VisualProcessingPriority.IGNORE, filter_reason or "FILTERED"
            ocr, ocr_reason = False, "FILTERED_VISUAL"
            vision, vision_reason = False, "FILTERED_VISUAL"
        else:
            ocr, ocr_reason = self._ocr_route(category)
            vision, vision_reason = self._vision_route(category)
            priority, priority_reason = self._priority(category)
        stable_hash = item["content_hash"]
        identity = json.dumps({"report_hash": report_hash, "page": page_number,
            "bbox": normalized, "object_type": item["object_type"].value,
            "content_hash": stable_hash}, sort_keys=True, separators=(",", ":"))
        region_id = "VISUAL-REGION-" + hashlib.sha256(identity.encode()).hexdigest()[:24].upper()
        return VisualEvidenceRegion(
            region_id, page_number, bbox, normalized, self.COORDINATE_SYSTEM,
            item["object_type"], category, confidence, reason,
            sorted(item["source_object_ids"]), round(width, 4), round(height, 4), area_ratio,
            native_text, nearby, heading, ocr, ocr_reason, vision, vision_reason,
            priority, priority_reason, stable_hash,
            {"authority": "VISUAL_INVENTORY", "decision_authority": "NONE",
             "detection_method": "PYMUPDF_NATIVE_OBJECT_LAYOUT",
             "source_object_count": len(item["source_object_ids"])},
            filtered, filter_reason, False,
        )

    def _merge_candidates(self, candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ordered = sorted(candidates, key=lambda item: (*item["bbox"], item["object_id"]))
        groups: List[List[Dict[str, Any]]] = []
        for candidate in ordered:
            matching = next((group for group in groups if any(
                self._iou(candidate["bbox"], item["bbox"]) >= .92 for item in group)), None)
            if matching is None:
                groups.append([candidate])
            else:
                matching.append(candidate)
        output = []
        for group in groups:
            bbox = [min(x["bbox"][0] for x in group), min(x["bbox"][1] for x in group),
                    max(x["bbox"][2] for x in group), max(x["bbox"][3] for x in group)]
            hashes = sorted(x["content_hash"] for x in group)
            output.append({"bbox": bbox,
                "object_type": group[0]["object_type"] if len(group) == 1 else VisualObjectType.MERGED_VISUAL,
                "source_object_ids": [x["object_id"] for x in group],
                "content_hash": (hashes[0] if len(hashes) == 1 else
                    hashlib.sha256("|".join(hashes).encode()).hexdigest()),
                "item_count": sum(int(x.get("item_count", 1)) for x in group)})
        return output

    def _classify(self, nearby: Optional[str], heading: Optional[str],
                  object_type: VisualObjectType, area_ratio: float, text_density: float):
        context = " ".join(x for x in (heading, nearby) if x).casefold()
        patterns = (
            (VisualRegionCategory.NAMEPLATE, r"\b(?:name\s*plate|rating\s+plate)\b"),
            (VisualRegionCategory.MARKING_LABEL, r"\b(?:marking|label|marking\s+plate)\b"),
            (VisualRegionCategory.TEST_SETUP, r"\b(?:test\s+setup|test\s+arrangement)\b"),
            (VisualRegionCategory.MEASUREMENT_SCREENSHOT, r"\b(?:screenshot|display|oscilloscope|screen)\b"),
            (VisualRegionCategory.MEASUREMENT_TABLE, r"\b(?:measurement|measured\s+values?|test\s+results?)\b"),
            (VisualRegionCategory.CIRCUIT_DIAGRAM, r"\b(?:circuit|wiring|schematic)\s+(?:diagram|drawing)\b"),
            (VisualRegionCategory.TECHNICAL_DRAWING, r"\b(?:technical|dimensional|construction)\s+drawing\b"),
            (VisualRegionCategory.PRODUCT_PHOTO, r"\b(?:product|sample|test\s+item)\s+(?:photo|photograph|view|image)\b"),
        )
        if (object_type is VisualObjectType.RASTER_IMAGE
                and area_ratio >= self.scanned_area_ratio
                and text_density <= self.scanned_text_density):
            return VisualRegionCategory.SCANNED_TEXT, .98, "FULL_PAGE_RASTER_LOW_NATIVE_TEXT_DENSITY"
        for category, pattern in patterns:
            if re.search(pattern, context):
                return category, .85, "NEARBY_NATIVE_CAPTION"
        return VisualRegionCategory.UNKNOWN_VISUAL, .25, "NO_DETERMINISTIC_CATEGORY_SIGNAL"

    def _filter(self, width: float, height: float, area_ratio: float, item: Dict[str, Any]):
        if width < self.min_width or height < self.min_height or area_ratio < self.min_area_ratio:
            return True, "BELOW_MIN_REGION_SIZE"
        if item["object_type"] is VisualObjectType.VECTOR_DRAWING and item.get("item_count", 0) <= 1:
            return True, "DECORATIVE_VECTOR"
        return False, None

    @staticmethod
    def _ocr_route(category):
        eligible = {VisualRegionCategory.MARKING_LABEL, VisualRegionCategory.NAMEPLATE,
                    VisualRegionCategory.MEASUREMENT_TABLE,
                    VisualRegionCategory.MEASUREMENT_SCREENSHOT,
                    VisualRegionCategory.SCANNED_TEXT, VisualRegionCategory.TECHNICAL_DRAWING}
        return (category in eligible, "CATEGORY_REQUIRES_TEXT_EXTRACTION_LATER" if category in eligible
                else "NO_DETERMINISTIC_OCR_ROUTING_SIGNAL")

    @staticmethod
    def _vision_route(category):
        eligible = {VisualRegionCategory.PRODUCT_PHOTO, VisualRegionCategory.TEST_SETUP,
                    VisualRegionCategory.CIRCUIT_DIAGRAM, VisualRegionCategory.TECHNICAL_DRAWING,
                    VisualRegionCategory.UNKNOWN_VISUAL}
        return (category in eligible, "CATEGORY_MAY_REQUIRE_VISUAL_UNDERSTANDING_LATER" if category in eligible
                else "NO_DETERMINISTIC_VISION_ROUTING_SIGNAL")

    @staticmethod
    def _priority(category):
        if category in {VisualRegionCategory.NAMEPLATE, VisualRegionCategory.MARKING_LABEL,
                        VisualRegionCategory.MEASUREMENT_TABLE,
                        VisualRegionCategory.MEASUREMENT_SCREENSHOT, VisualRegionCategory.SCANNED_TEXT}:
            return VisualProcessingPriority.HIGH, "HIGH_VALUE_VISUAL_EVIDENCE_CATEGORY"
        if category in {VisualRegionCategory.TEST_SETUP, VisualRegionCategory.CIRCUIT_DIAGRAM,
                        VisualRegionCategory.TECHNICAL_DRAWING, VisualRegionCategory.UNKNOWN_VISUAL}:
            return VisualProcessingPriority.MEDIUM, "REQUIRES_LATER_VISUAL_REVIEW"
        return VisualProcessingPriority.LOW, "LOW_PRIORITY_VISUAL_CONTEXT"

    def _mark_repeated_templates(self, pages: Sequence[VisualEvidencePage]) -> None:
        occurrences = defaultdict(list)
        for page in pages:
            for region in page.visual_regions:
                vertical = "HEADER" if region.normalized_bbox[3] <= .16 else "FOOTER" if region.normalized_bbox[1] >= .84 else "BODY"
                occurrences[(region.stable_content_hash, vertical)].append(region)
        threshold = max(3, int(len(pages) * .2))
        for (_, vertical), regions in occurrences.items():
            if vertical != "BODY" and len({item.page_number for item in regions}) >= threshold:
                for region in regions:
                    region.repeated_template_visual = True
                    region.filtered = True; region.filter_reason = "REPEATED_HEADER_FOOTER"
                    region.processing_priority = VisualProcessingPriority.IGNORE
                    region.priority_reason = "REPEATED_HEADER_FOOTER"
                    region.ocr_candidate = False; region.ocr_candidate_reason = "REPEATED_TEMPLATE_VISUAL"
                    region.vision_candidate = False; region.vision_candidate_reason = "REPEATED_TEMPLATE_VISUAL"

    def _summary(self, pages):
        regions = [region for page in pages for region in page.visual_regions]
        return {"total_pages": len(pages),
            "pages_with_visuals": sum(bool(page.visual_regions) for page in pages),
            "total_visual_regions": len(regions),
            "category_counts": dict(sorted(Counter(x.category.value for x in regions).items())),
            "priority_counts": dict(sorted(Counter(x.processing_priority.value for x in regions).items())),
            "ocr_candidates": sum(x.ocr_candidate for x in regions),
            "vision_candidates": sum(x.vision_candidate for x in regions),
            "scanned_text_pages": len({x.page_number for x in regions if x.category is VisualRegionCategory.SCANNED_TEXT}),
            "repeated_template_visuals": sum(x.repeated_template_visual for x in regions),
            "filtered_regions": sum(x.filtered for x in regions)}

    @staticmethod
    def _text_blocks(page):
        try:
            return [tuple(block) for block in page.get_text("blocks") or [] if len(block) >= 5 and str(block[4]).strip()]
        except Exception:
            return []

    def _nearby_text(self, bbox, blocks):
        ranked = sorted(blocks, key=lambda block: (self._distance(bbox, block[:4]), block[1], block[0]))
        selected = [re.sub(r"\s+", " ", str(block[4])).strip() for block in ranked[:3]]
        nearby = " ".join(selected)[:self.nearby_text_chars] or None
        heading = next((text[:160] for text in selected
                        if len(text) <= 160 and not re.search(r"[.!?]\s", text)), None)
        return nearby, heading

    @staticmethod
    def _distance(a, b):
        dx = max(float(b[0]) - a[2], a[0] - float(b[2]), 0.0)
        dy = max(float(b[1]) - a[3], a[1] - float(b[3]), 0.0)
        return dx * dx + dy * dy

    @staticmethod
    def _bbox(value):
        try:
            values = [round(float(x), 4) for x in value]
            return values if len(values) == 4 and values[2] > values[0] and values[3] > values[1] else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _iou(a, b):
        x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
        intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
        return intersection / union if union else 0.0

    @staticmethod
    def _file_hash(path):
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def save_json(inventory: VisualEvidenceInventory, output_path) -> None:
        Path(output_path).write_text(inventory.to_json(indent=2) + "\n", encoding="utf-8")
