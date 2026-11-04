"""Models for deterministic evidence enrichment without compliance decisions."""
from dataclasses import asdict,dataclass,field
from enum import Enum
from typing import Any,Dict,List,Optional

class EvidenceParameterRole(str,Enum):
 PRODUCT_RATING="PRODUCT_RATING";SAMPLE_RATING="SAMPLE_RATING";MARKING_VALUE="MARKING_VALUE";TEST_INPUT="TEST_INPUT";TEST_PARAMETER="TEST_PARAMETER";TEST_CONDITION="TEST_CONDITION";OBSERVED_MEASUREMENT="OBSERVED_MEASUREMENT";CALCULATED_VALUE="CALCULATED_VALUE";ACCEPTANCE_LIMIT="ACCEPTANCE_LIMIT";FORMULA_VARIABLE="FORMULA_VARIABLE";IDENTIFIER="IDENTIFIER";OTHER="OTHER"
class EvidenceParameterType(str,Enum):
 VOLTAGE="VOLTAGE";CURRENT="CURRENT";POWER="POWER";FREQUENCY="FREQUENCY";TEMPERATURE="TEMPERATURE";TEMPERATURE_RISE="TEMPERATURE_RISE";TIME="TIME";DISTANCE="DISTANCE";SPEED="SPEED";FORCE="FORCE";FLOW_RATE="FLOW_RATE";AREA="AREA";WIDTH="WIDTH";DIAMETER="DIAMETER";COUNT="COUNT";PERCENTAGE="PERCENTAGE";PHASE_COUNT="PHASE_COUNT";PROTECTION_CLASS="PROTECTION_CLASS";IP_RATING="IP_RATING";MODEL_NUMBER="MODEL_NUMBER";TYPE_REFERENCE="TYPE_REFERENCE";SERIAL_NUMBER="SERIAL_NUMBER";SAMPLE_IDENTIFIER="SAMPLE_IDENTIFIER";PRODUCT_NAME="PRODUCT_NAME";BRAND="BRAND";GENERIC_NUMERIC="GENERIC_NUMERIC";GENERIC_TEXT="GENERIC_TEXT";UNKNOWN="UNKNOWN"
class EnrichmentStatus(str,Enum):RESOLVED="RESOLVED";NEEDS_REVIEW="NEEDS_REVIEW";UNRESOLVED="UNRESOLVED"
class ExpressionType(str,Enum):CONSTANT="CONSTANT";MULTIPLIER="MULTIPLIER";PERCENTAGE="PERCENTAGE";FORMULA="FORMULA";RANGE="RANGE";MINIMUM="MINIMUM";MAXIMUM="MAXIMUM";COMPOUND="COMPOUND";UNKNOWN="UNKNOWN"
class ConditionLinkStatus(str,Enum):MATCHED="MATCHED";POSSIBLE="POSSIBLE";AMBIGUOUS="AMBIGUOUS";NO_MATCH="NO_MATCH"
class TestConditionClassification(str,Enum):ACCEPTANCE_CONSTRAINT="ACCEPTANCE_CONSTRAINT";REQUIRED_TEST_CONDITION="REQUIRED_TEST_CONDITION";TEST_PARAMETER="TEST_PARAMETER";SETUP_PARAMETER="SETUP_PARAMETER";POST_TEST_ACCEPTANCE="POST_TEST_ACCEPTANCE";UNRESOLVED="UNRESOLVED"
class TestConditionRole(str,Enum):TEST_VOLTAGE="TEST_VOLTAGE";TEST_CURRENT="TEST_CURRENT";TEST_POWER="TEST_POWER";TEST_FREQUENCY="TEST_FREQUENCY";TEST_DURATION="TEST_DURATION";TEST_SPEED="TEST_SPEED";TEST_LOAD="TEST_LOAD";TEST_FORCE="TEST_FORCE";TEST_DISTANCE="TEST_DISTANCE";TEST_FLOW="TEST_FLOW";TEST_TEMPERATURE="TEST_TEMPERATURE";TEST_CYCLE_COUNT="TEST_CYCLE_COUNT";TEST_PHASE_CONFIGURATION="TEST_PHASE_CONFIGURATION";OTHER="OTHER"
@dataclass
class NormalizedEvidenceValue:
 value:Any=None;value_secondary:Any=None;value_type:Optional[str]=None;unit:Optional[str]=None;unit_normalized:Optional[str]=None;operator:Optional[str]=None;raw_text:Optional[str]=None;confidence:float=0.0;status:EnrichmentStatus=EnrichmentStatus.UNRESOLVED
@dataclass
class EvidenceProvenance:
 source_type:str;source_artifact:str;source_id:Optional[str]=None;clause_id:Optional[str]=None;requirement_id:Optional[str]=None;group_id:Optional[str]=None;page_start:Optional[int]=None;page_end:Optional[int]=None;raw_excerpt:Optional[str]=None
@dataclass
class NormalizedEvidenceFact:
 fact_id:str;parameter_type:EvidenceParameterType;parameter_role:EvidenceParameterRole;canonical_name:str;normalized_value:NormalizedEvidenceValue;provenance:List[EvidenceProvenance]=field(default_factory=list);confidence:float=0.0;status:EnrichmentStatus=EnrichmentStatus.UNRESOLVED;semantic_key:str="";notes:Optional[str]=None
@dataclass
class EvidenceExpression:
 expression_id:str;expression_type:ExpressionType;operator:Optional[str]=None;left:Any=None;right:Any=None;factor:Optional[float]=None;variable:Optional[str]=None;variables:List[str]=field(default_factory=list);constant:Any=None;unit:Optional[str]=None;raw_expression:Optional[str]=None;status:EnrichmentStatus=EnrichmentStatus.UNRESOLVED;provenance:List[EvidenceProvenance]=field(default_factory=list)
@dataclass
class RequiredTestCondition:
 condition_id:str;effective_requirement_id:str;group_id:Optional[str];clause_id:Optional[str];parameter_type:EvidenceParameterType;condition_role:str;operator:Optional[str]=None;expected_value:Optional[NormalizedEvidenceValue]=None;expected_expression:Optional[EvidenceExpression]=None;technical_constraint_id:Optional[str]=None;mandatory:bool=True;status:EnrichmentStatus=EnrichmentStatus.UNRESOLVED;provenance:List[EvidenceProvenance]=field(default_factory=list);notes:Optional[str]=None;classification:TestConditionClassification=TestConditionClassification.UNRESOLVED;unresolved_reason:Optional[str]=None;source_order:Optional[int]=None
@dataclass
class ActualTestCondition:
 condition_id:str;report_evidence_id:str;clause_id:Optional[str];group_ids:List[str];parameter_type:EvidenceParameterType;condition_role:str;observed_value:Optional[NormalizedEvidenceValue]=None;observed_expression:Optional[EvidenceExpression]=None;status:EnrichmentStatus=EnrichmentStatus.UNRESOLVED;provenance:List[EvidenceProvenance]=field(default_factory=list);notes:Optional[str]=None;source_order:Optional[int]=None
@dataclass
class CalculationEvidence:
 calculation_id:str;clause_id:Optional[str];group_ids:List[str];report_evidence_id:str;parameter_type:EvidenceParameterType;input_facts:List[Dict[str,Any]]=field(default_factory=list);reported_expression:Optional[EvidenceExpression]=None;reported_result:Optional[NormalizedEvidenceValue]=None;recomputable:bool=False;recalculated_result:Any=None;difference:Any=None;tolerance:Any=None;status:EnrichmentStatus=EnrichmentStatus.UNRESOLVED;provenance:List[EvidenceProvenance]=field(default_factory=list);notes:Optional[str]=None
@dataclass
class SampleIdentityEvidence:
 identity_id:str;identifier_type:EvidenceParameterType;value:Any;source_role:str;status:EnrichmentStatus;provenance:List[EvidenceProvenance]=field(default_factory=list)
@dataclass
class TestConditionPair:
 pair_id:str;required_condition_id:str;actual_condition_id:Optional[str];semantic_parameter_match:bool;role_match:bool;unit_compatible:bool;scope_compatible:bool;link_status:ConditionLinkStatus;reason:str
@dataclass
class EvidenceComparisonSet:
 comparison_id:str;semantic_key:str;facts:List[str];comparable:bool;reason:str
@dataclass
class EvidenceEnrichmentReport:
 effective_kb_id:str;profile_id:str;report_document_id:str;facts:List[NormalizedEvidenceFact]=field(default_factory=list);required_test_conditions:List[RequiredTestCondition]=field(default_factory=list);actual_test_conditions:List[ActualTestCondition]=field(default_factory=list);calculations:List[CalculationEvidence]=field(default_factory=list);sample_identity_evidence:List[SampleIdentityEvidence]=field(default_factory=list);condition_pairs:List[TestConditionPair]=field(default_factory=list);comparison_sets:List[EvidenceComparisonSet]=field(default_factory=list);summary:Dict[str,Any]=field(default_factory=dict);diagnostics:List[Dict[str,Any]]=field(default_factory=list)
__all__=[x for x in list(globals()) if not x.startswith("_") and x not in {"Any","Dict","List","Optional","Enum","asdict","dataclass","field"}]
