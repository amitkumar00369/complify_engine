"""Generic source-preserving standard and report test-structure models."""
from dataclasses import dataclass,field
from enum import Enum
from typing import Any,Dict,List,Optional

class StructureStatus(str,Enum):RESOLVED="RESOLVED";NEEDS_REVIEW="NEEDS_REVIEW";UNRESOLVED="UNRESOLVED"
class StandardTestStepType(str,Enum):PRECONDITION="PRECONDITION";SETUP="SETUP";APPLY_INPUT="APPLY_INPUT";OPERATE="OPERATE";WAIT="WAIT";MEASURE="MEASURE";OBSERVE="OBSERVE";REPEAT="REPEAT";ACCEPTANCE_CHECK="ACCEPTANCE_CHECK";POST_TEST_CHECK="POST_TEST_CHECK";RESET="RESET";OTHER="OTHER"
class ReportRowLevel(str,Enum):CLAUSE="CLAUSE";SUBCLAUSE="SUBCLAUSE";ROW="ROW";SUBROW="SUBROW";BULLET="BULLET";TABLE_ROW="TABLE_ROW";MEASUREMENT_ROW="MEASUREMENT_ROW";REMARK_ROW="REMARK_ROW";UNKNOWN="UNKNOWN"
class StructureLinkStatus(str,Enum):MATCHED="MATCHED";POSSIBLE="POSSIBLE";AMBIGUOUS="AMBIGUOUS";NO_MATCH="NO_MATCH"
@dataclass
class StructureProvenance:
 source_artifact:str;source_id:Optional[str]=None;clause_id:Optional[str]=None;requirement_id:Optional[str]=None;group_id:Optional[str]=None;page_start:Optional[int]=None;page_end:Optional[int]=None;raw_excerpt:Optional[str]=None
@dataclass
class StandardTestStep:
 step_id:str;step_order:int;step_type:StandardTestStepType;text:str;parameter_type:Optional[str]=None;condition_role:Optional[str]=None;expression:Any=None;value:Any=None;unit:Optional[str]=None;references:List[str]=field(default_factory=list);status:StructureStatus=StructureStatus.UNRESOLVED;provenance:List[StructureProvenance]=field(default_factory=list)
@dataclass
class StandardTestStructure:
 structure_id:str;namespace:str;clause_id:Optional[str];group_id:str;primary_requirement_id:Optional[str];member_requirement_ids:List[str];primary_obligation_text:Optional[str];test_method_steps:List[StandardTestStep]=field(default_factory=list);required_conditions:List[str]=field(default_factory=list);measurement_expectations:List[str]=field(default_factory=list);acceptance_criteria:List[str]=field(default_factory=list);post_test_criteria:List[str]=field(default_factory=list);exceptions:List[str]=field(default_factory=list);source_order:Optional[int]=None;status:StructureStatus=StructureStatus.UNRESOLVED;confidence:float=0.0;provenance:List[StructureProvenance]=field(default_factory=list)
@dataclass
class ReportResultRow:
 row_id:str;row_order:int;parent_row_id:Optional[str];row_level:ReportRowLevel;row_label:Optional[str];requirement_text:Optional[str];test_method_text:Optional[str];actual_conditions:List[str]=field(default_factory=list);measurements:List[str]=field(default_factory=list);calculation_refs:List[str]=field(default_factory=list);remarks:List[str]=field(default_factory=list);reported_verdict:Optional[str]=None;raw_text:Optional[str]=None;status:StructureStatus=StructureStatus.UNRESOLVED;provenance:List[StructureProvenance]=field(default_factory=list)
@dataclass
class ReportClauseStructure:
 structure_id:str;namespace:str;report_clause_id:str;page_start:Optional[int];page_end:Optional[int];rows:List[ReportResultRow]=field(default_factory=list);status:StructureStatus=StructureStatus.UNRESOLVED;provenance:List[StructureProvenance]=field(default_factory=list)
@dataclass
class TestStructureLinkCandidate:
 link_id:str;standard_structure_id:str;standard_step_ids:List[str];report_structure_id:str;report_row_ids:List[str];group_id:str;clause_id:Optional[str];parameter_alignment:bool;role_alignment:bool;text_alignment:float;scope_alignment:bool;order_alignment:bool;candidate_status:StructureLinkStatus;reason:str;confidence:float
@dataclass
class RowScopeCandidate:
 row_id:str;report_evidence_id:Optional[str];outer_scope_status:Optional[str];candidate_group_ids:List[str];narrowed_group_ids:List[str];status:StructureLinkStatus;reason:str
@dataclass
class TestStructureEnrichmentReport:
 effective_kb_id:str;report_document_id:str;standard_test_structures:List[StandardTestStructure]=field(default_factory=list);report_clause_structures:List[ReportClauseStructure]=field(default_factory=list);structure_links:List[TestStructureLinkCandidate]=field(default_factory=list);row_scope_candidates:List[RowScopeCandidate]=field(default_factory=list);summary:Dict[str,Any]=field(default_factory=dict);diagnostics:List[Dict[str,Any]]=field(default_factory=list)
__all__=[x for x in list(globals()) if not x.startswith("_") and x not in {"Any","Dict","List","Optional","Enum","dataclass","field"}]
