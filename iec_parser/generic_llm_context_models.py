"""Serializable models for deterministic Step 32-C context payloads."""
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GenericLLMContext:
    llm_context_id: str
    context_signature: str
    source_context_id: str
    final_issue_id: str
    primary_task: str
    allowed_tasks: List[str]
    route_reason: str
    decision_authority: str
    policy_locks: Dict[str, Any]
    standard_context: Dict[str, Any]
    requirement_context: Dict[str, Any]
    product_context: Dict[str, Any]
    report_context: Dict[str, Any]
    deterministic_context: Dict[str, Any]
    provenance_context: Dict[str, Any]
    allowed_ids: Dict[str, List[str]]
    output_contract: Dict[str, Any]
    integrity: Dict[str, Any]
    size_metrics: Dict[str, int] = field(default_factory=dict)


@dataclass
class GenericLLMContextBundle:
    schema_version: str
    context_builder_version: str
    run_id: Optional[str]
    accounting: Dict[str, Any]
    contexts: List[GenericLLMContext]
    exclusions: List[Dict[str, Any]]

    def to_dict(self): return asdict(self)


__all__ = ["GenericLLMContext", "GenericLLMContextBundle"]
