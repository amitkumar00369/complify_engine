"""Models for governed, decision-neutral visual canonical promotion."""
from __future__ import annotations
import json
from dataclasses import asdict,dataclass,field
from typing import Any,Dict,List,Optional
@dataclass(frozen=True)
class CanonicalVisualEvidenceRecord:
 evidence_id:str;candidate_type:str;canonical_target:str;canonical_value:Any;unit:Optional[str];polarity:str;parameter_role:str;scope:str;source_type:str;authority:str;lineage:Dict[str,Any]
@dataclass
class VisualPromotionResult:
 schema_version:str;authority:str;source_reconciliation_schema:str;source_reconciliation_hash:str;report_hash:str;feature_enabled:bool;summary:Dict[str,int];promotion_records:List[Dict[str,Any]];canonical_evidence:List[CanonicalVisualEvidenceRecord];diagnostics:List[Dict[str,Any]]=field(default_factory=list)
 def to_dict(self):return asdict(self)
 def to_json(self,indent=None):return json.dumps(self.to_dict(),sort_keys=True,ensure_ascii=False,indent=indent)
