"""Models for the deterministic Step 32-B.1 eligibility gate."""
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ContextIntegrityEligibility:
    context_id: str
    final_issue_id: str
    eligible_for_step_32c: bool
    blocking_reason_codes: List[str] = field(default_factory=list)
    contamination_findings: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class PreLLMIntegrityResult:
    schema_version: str
    run_id: Optional[str]
    accounting: Dict[str, Any]
    contexts: List[ContextIntegrityEligibility]
    provenance_boundary: Dict[str, Any]

    def to_dict(self): return asdict(self)


__all__ = ["ContextIntegrityEligibility", "PreLLMIntegrityResult"]
