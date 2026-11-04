"""Canonical, generic product-feature vocabulary for IEC knowledge bases."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class FeatureDataType(str, Enum):
    """Supported value types for canonical product features."""

    BOOLEAN = "BOOLEAN"
    ENUM = "ENUM"
    INTEGER = "INTEGER"
    NUMBER = "NUMBER"
    STRING = "STRING"
    MEASUREMENT = "MEASUREMENT"
    LIST = "LIST"


FeatureDefault = Optional[Union[bool, int, float, str, List[Any], Dict[str, Any]]]


@dataclass
class CanonicalProductFeature:
    """Definition of one stable product-profile feature."""

    key: str
    category: str
    data_type: FeatureDataType
    description: str
    allowed_values: List[str] = field(default_factory=list)
    unit: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    applicability_relevant: bool = True
    report_extractable: bool = True
    default_value: FeatureDefault = None
    notes: Optional[str] = None


class CanonicalProductFeatureRegistry:
    """Load, validate, and query the canonical feature registry."""

    DEFAULT_SOURCE = Path(__file__).with_name("iec_product_feature_registry.json")

    def __init__(self, source_path: Optional[Union[str, Path]] = None) -> None:
        self.schema_version = ""
        self._features: Dict[str, CanonicalProductFeature] = {}
        self._alias_index: Dict[str, List[CanonicalProductFeature]] = {}
        self.load_from_json(source_path or self.DEFAULT_SOURCE)

    def load_from_json(self, source_path: Union[str, Path]) -> None:
        """Replace registry contents with validated definitions from JSON."""

        path = Path(source_path)
        with path.open("r", encoding="utf-8") as source:
            payload = json.load(source)
        if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
            raise ValueError("Registry JSON must contain a features list")
        schema_version = payload.get("schema_version")
        if not isinstance(schema_version, str) or not schema_version.strip():
            raise ValueError("Registry schema_version must be a non-empty string")

        features: Dict[str, CanonicalProductFeature] = {}
        for index, raw in enumerate(payload["features"]):
            feature = self._parse_feature(raw, index)
            if feature.key in features:
                raise ValueError(f"Duplicate feature key: {feature.key}")
            features[feature.key] = feature

        self.schema_version = schema_version
        self._features = features
        self._alias_index = {}
        for feature in features.values():
            for alias in [feature.key, *feature.aliases]:
                normalized = self._normalize_alias(alias)
                matches = self._alias_index.setdefault(normalized, [])
                if feature not in matches:
                    matches.append(feature)

    def get(self, key: str) -> Optional[CanonicalProductFeature]:
        """Return a feature by exact canonical key, or ``None``."""

        return self._features.get(key)

    def exists(self, key: str) -> bool:
        """Return whether an exact canonical key exists."""

        return key in self._features

    def search_alias(self, alias: str) -> List[CanonicalProductFeature]:
        """Return all exact normalized alias matches without resolving ambiguity."""

        if not isinstance(alias, str):
            return []
        return list(self._alias_index.get(self._normalize_alias(alias), []))

    def get_by_category(self, category: str) -> List[CanonicalProductFeature]:
        """Return features in a category, preserving source order."""

        return [feature for feature in self._features.values() if feature.category == category]

    def get_all(self) -> List[CanonicalProductFeature]:
        """Return every feature in source order as an independent list."""

        return list(self._features.values())

    def validate_feature_value(self, key: str, value: Any) -> bool:
        """Check a proposed value against a feature's declared data type."""

        feature = self.get(key)
        if feature is None:
            return False
        kind = feature.data_type
        if kind is FeatureDataType.BOOLEAN:
            return isinstance(value, bool)
        if kind is FeatureDataType.ENUM:
            return isinstance(value, str) and value in feature.allowed_values
        if kind is FeatureDataType.INTEGER:
            return isinstance(value, int) and not isinstance(value, bool)
        if kind is FeatureDataType.NUMBER:
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if kind is FeatureDataType.STRING:
            return isinstance(value, str)
        if kind is FeatureDataType.LIST:
            return isinstance(value, list)
        if kind is FeatureDataType.MEASUREMENT:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return True
            return (
                isinstance(value, dict)
                and isinstance(value.get("value"), (int, float))
                and not isinstance(value.get("value"), bool)
                and value.get("unit", feature.unit) == feature.unit
            )
        return False

    @classmethod
    def _parse_feature(cls, raw: Any, index: int) -> CanonicalProductFeature:
        if not isinstance(raw, dict):
            raise ValueError(f"Feature at index {index} must be an object")
        required_strings = ("key", "category", "data_type", "description")
        for name in required_strings:
            if not isinstance(raw.get(name), str) or not raw[name].strip():
                raise ValueError(f"Feature at index {index} requires non-empty {name}")
        try:
            data_type = FeatureDataType(raw["data_type"])
        except ValueError as error:
            raise ValueError(f"Invalid data type for {raw['key']}: {raw['data_type']}") from error
        allowed_values = raw.get("allowed_values", [])
        aliases = raw.get("aliases", [])
        if not isinstance(allowed_values, list) or not all(isinstance(v, str) for v in allowed_values):
            raise ValueError(f"allowed_values must be a string list for {raw['key']}")
        if not isinstance(aliases, list) or not all(isinstance(v, str) and v.strip() for v in aliases):
            raise ValueError(f"aliases must be a non-empty string list for {raw['key']}")
        normalized_aliases = [cls._normalize_alias(alias) for alias in aliases]
        if len(normalized_aliases) != len(set(normalized_aliases)):
            raise ValueError(f"Duplicate aliases within feature: {raw['key']}")
        if data_type is FeatureDataType.ENUM and not allowed_values:
            raise ValueError(f"ENUM feature requires allowed_values: {raw['key']}")
        if data_type is FeatureDataType.BOOLEAN and allowed_values:
            raise ValueError(f"BOOLEAN feature cannot declare allowed_values: {raw['key']}")
        unit = raw.get("unit")
        if data_type is FeatureDataType.MEASUREMENT and not isinstance(unit, str):
            raise ValueError(f"MEASUREMENT feature requires a unit: {raw['key']}")
        for boolean_name in ("applicability_relevant", "report_extractable"):
            if not isinstance(raw.get(boolean_name, True), bool):
                raise ValueError(f"{boolean_name} must be boolean for {raw['key']}")
        feature = CanonicalProductFeature(
            key=raw["key"], category=raw["category"], data_type=data_type,
            description=raw["description"], allowed_values=list(allowed_values), unit=unit,
            aliases=list(aliases), applicability_relevant=raw.get("applicability_relevant", True),
            report_extractable=raw.get("report_extractable", True),
            default_value=raw.get("default_value"), notes=raw.get("notes"),
        )
        if feature.default_value is not None and not cls._validate_declared_default(feature):
            raise ValueError(f"Invalid default_value for {feature.key}")
        return feature

    @staticmethod
    def _validate_declared_default(feature: CanonicalProductFeature) -> bool:
        value = feature.default_value
        kind = feature.data_type
        if kind is FeatureDataType.BOOLEAN:
            return isinstance(value, bool)
        if kind is FeatureDataType.ENUM:
            return isinstance(value, str) and value in feature.allowed_values
        if kind is FeatureDataType.INTEGER:
            return isinstance(value, int) and not isinstance(value, bool)
        if kind in (FeatureDataType.NUMBER, FeatureDataType.MEASUREMENT):
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if kind is FeatureDataType.STRING:
            return isinstance(value, str)
        return kind is FeatureDataType.LIST and isinstance(value, list)

    @staticmethod
    def _normalize_alias(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).casefold()
        normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
        return " ".join(normalized.split())


__all__ = [
    "CanonicalProductFeature",
    "CanonicalProductFeatureRegistry",
    "FeatureDataType",
]
