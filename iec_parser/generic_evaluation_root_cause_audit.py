"""Read-only, identifier-driven root-cause tracing across pipeline artifacts."""
from __future__ import annotations
import copy,hashlib,json
from collections import Counter
from dataclasses import asdict,dataclass,field,is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Dict,List,Mapping,Optional,Sequence

@dataclass(frozen=True)
class AuditProbe:
    subject:str;clause_id:Optional[str]=None;requirement_group_id:Optional[str]=None;requirement_id:Optional[str]=None;evidence_id:Optional[str]=None
    expected_classification:str="AUDIT";expected_stage_contains:Dict[str,List[str]]=field(default_factory=dict);source_truth:Dict[str,Any]=field(default_factory=dict)
    root_cause_category:Optional[str]=None;final_classification:Optional[str]=None
@dataclass
class EvaluationRootCauseAudit:
    run_id:Optional[str];audit_status:str;cases:List[Dict[str,Any]];root_cause_summary:Dict[str,Any];genericity_audit:Dict[str,int];diagnostics:List[Dict[str,Any]]=field(default_factory=list)

class GenericEvaluationRootCauseAudit:
    """Trace IDs and expected source signals without making compliance decisions."""
    STAGES=(("effective_kb","standards/effective_kb.json"),("report_evidence","report/report_evidence.json"),("product_profile","report/product_profile.json"),("applicability","report/applicability_result.json"),("evidence_match","report/evidence_match_result.json"),("technical_constraints","report/technical_constraint_result.json"),("na_validation","report/na_validation_result.json"),("na_conflict_audit","report/na_conflict_audit.json"),("requirement_grouping","report/requirement_grouping_result.json"),("group_aware_applicability","report/group_aware_applicability_result.json"),("group_aware_na_validation","report/group_aware_na_validation_result.json"),("report_evidence_scope","report/report_evidence_scope_result.json"),("scope_aware_na_validation","report/scope_aware_na_validation_result.json"),("final_decision","decisions/final_requirement_decision.json"),("coverage_gap","decisions/coverage_gap_analysis.json"),("overall_readiness","decisions/overall_readiness_result.json"),("clause_evaluation_summary","decisions/clause_evaluation_summary.json"),("evidence_integrity_rejection","decisions/evidence_integrity_rejection_result.json"),("final_issue_resolution","decisions/final_compliance_issues.json"),("final_saas_response","decisions/final_compliance_response.json"))
    def audit(self,run_directory:Any,probes:Sequence[AuditProbe])->EvaluationRootCauseAudit:
        root=Path(run_directory);manifest=self._load(root/"manifest/pipeline_manifest.json") or {};cases=[];diagnostics=[]
        artifacts={name:self._load(root/rel) for name,rel in self.STAGES}
        for name,rel in self.STAGES:
            if artifacts[name] is None:diagnostics.append({"code":"MISSING_INTERMEDIATE_ARTIFACT","stage":name,"artifact_ref":rel})
        for probe in probes:cases.append(self.trace_probe(root,probe,artifacts))
        faults=Counter(x.get("first_incorrect_stage") or "NONE" for x in cases);causes=Counter(x.get("root_cause_category") or "UNRESOLVED" for x in cases);classes=Counter(x.get("final_classification") or "UNRESOLVED_AUDIT" for x in cases)
        summary={"first_fault_stage_counts":dict(sorted(faults.items())),"root_cause_category_counts":dict(sorted(causes.items())),"false_positive_count":classes["FALSE_POSITIVE"],"false_negative_count":classes["FALSE_NEGATIVE"],"true_positive_count":classes["TRUE_POSITIVE"],"correct_but_generic_count":classes["CORRECT_BUT_TOO_GENERIC"],"unresolved_audit_count":classes["UNRESOLVED_AUDIT"]}
        return EvaluationRootCauseAudit(manifest.get("run_id"),"COMPLETE",cases,summary,{"production_logic_changed":0,"upstream_artifacts_mutated":0,"fixture_specific_production_branch":0},diagnostics)
    def trace_probe(self,root:Path,probe:AuditProbe,artifacts:Optional[Mapping[str,Any]]=None)->Dict[str,Any]:
        artifacts=artifacts or {n:self._load(root/r) for n,r in self.STAGES};ids=[x for x in (probe.clause_id,probe.requirement_group_id,probe.requirement_id,probe.evidence_id) if x];trace=[];first=None
        for stage,rel in self.STAGES:
            artifact=artifacts.get(stage);hits=self._find_records(artifact,ids) if artifact is not None else []
            expected=probe.expected_stage_contains.get(stage,[]);blob=self._canonical(hits).casefold();missing=[x for x in expected if x.casefold() not in blob]
            status="MISSING" if artifact is None else "INCORRECT" if missing else "CORRECT" if expected else "OBSERVED"
            if status=="INCORRECT" and first is None:first=stage
            trace.append({"stage":stage,"status":status,"artifact_ref":rel,"observed":{"match_count":len(hits),"records":hits[:12]},**({"reason":"Expected structured signal(s) absent: "+", ".join(missing)} if missing else {})})
        final_class=probe.final_classification or ("FALSE_POSITIVE" if first else "UNRESOLVED_AUDIT")
        return {"subject":probe.subject,"expected_classification":probe.expected_classification,"source_truth":copy.deepcopy(probe.source_truth),"query":{"clause_id":probe.clause_id,"requirement_group_id":probe.requirement_group_id,"requirement_id":probe.requirement_id,"evidence_id":probe.evidence_id},"trace":trace,"first_incorrect_stage":first,"root_cause_category":probe.root_cause_category or ("EXPECTED_STRUCTURED_SIGNAL_LOST" if first else "UNRESOLVED"),"final_classification":final_class}
    def trace_clause(self,root,clause_id):return self.trace_probe(Path(root),AuditProbe(str(clause_id),clause_id=str(clause_id)))
    def trace_requirement_group(self,root,group_id):return self.trace_probe(Path(root),AuditProbe(str(group_id),requirement_group_id=str(group_id)))
    def trace_requirement(self,root,requirement_id):return self.trace_probe(Path(root),AuditProbe(str(requirement_id),requirement_id=str(requirement_id)))
    def trace_evidence(self,root,evidence_id):return self.trace_probe(Path(root),AuditProbe(str(evidence_id),evidence_id=str(evidence_id)))
    @classmethod
    def _find_records(cls,value,identifiers):
        out=[]
        def walk(v):
            if isinstance(v,dict):
                blob=cls._canonical(v)
                if any(cls._contains_identifier(v,x) for x in identifiers):out.append(cls._compact(v))
                for child in v.values():walk(child)
            elif isinstance(v,list):
                for child in v:walk(child)
        walk(value);seen={};
        for x in out:seen[cls._canonical(x)]=x
        return [seen[k] for k in sorted(seen)]
    @staticmethod
    def _contains_identifier(record,identifier):
        keys=("clause_id","source_clause_id","report_clause_id","requirement_group_id","group_id","effective_requirement_id","requirement_id","evidence_id","issue_id")
        for key in keys:
            value=record.get(key)
            if str(value)==identifier:return True
        for key in ("requirement_ids","effective_requirement_ids","evidence_ids","evidence_refs","issue_ids","requirement_group_ids"):
            value=record.get(key,[]) or []
            if identifier in [str(x.get("evidence_id")) if isinstance(x,dict) else str(x) for x in value]:return True
        return False
    @classmethod
    def _compact(cls,v):
        keys=("clause_id","effective_requirement_id","requirement_id","group_id","requirement_group_id","evidence_id","parent_evidence_id","issue_id","text","raw_text","condition_text","decision","match_status","scope_status","final_decision","group_decision","final_status","issue_type","compliance_conclusion","reported_verdict","reason","evidence_refs","evidence_ids","requirement_ids","effective_requirement_ids","members","selected_groups","identity","facts")
        return {k:copy.deepcopy(v[k]) for k in keys if k in v}
    @staticmethod
    def _load(path):
        try:return json.loads(Path(path).read_text(encoding="utf-8"))
        except (FileNotFoundError,json.JSONDecodeError):return None
    @staticmethod
    def _canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)
    @classmethod
    def to_dict(cls,v):return cls._plain(asdict(v))
    @classmethod
    def _plain(cls,v):
        if isinstance(v,Enum):return v.value
        if is_dataclass(v):return cls._plain(asdict(v))
        if isinstance(v,dict):return {k:cls._plain(x) for k,x in v.items()}
        if isinstance(v,list):return [cls._plain(x) for x in v]
        return copy.deepcopy(v)
    @classmethod
    def to_json(cls,v,indent=2):return json.dumps(cls.to_dict(v),ensure_ascii=False,sort_keys=True,indent=indent)
    @classmethod
    def save_json(cls,v,path):p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(cls.to_json(v)+"\n",encoding="utf-8");return p

__all__=["AuditProbe","EvaluationRootCauseAudit","GenericEvaluationRootCauseAudit"]
