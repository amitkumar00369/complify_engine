"""Deterministic report-to-effective-standard semantic structure validation."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from .generic_cross_evidence_consistency_validator import GenericCrossEvidenceConsistencyValidator


class ClauseCompatibility(str,Enum):
    MATCH="MATCH";PARTIAL_MATCH="PARTIAL_MATCH";SEMANTIC_MISMATCH="SEMANTIC_MISMATCH"
    INSUFFICIENT_INFORMATION="INSUFFICIENT_INFORMATION";NOT_COMPARABLE="NOT_COMPARABLE"
class ReportStructureCompatibility(str,Enum):
    COMPATIBLE="COMPATIBLE";PARTIALLY_COMPATIBLE="PARTIALLY_COMPATIBLE"
    STRUCTURE_MISMATCH="STRUCTURE_MISMATCH";INSUFFICIENT_INFORMATION="INSUFFICIENT_INFORMATION"


@dataclass
class ClauseStructureFinding:
    finding_id:str;report_clause:str;standard_clause:Optional[str]
    report_topic:Optional[str];standard_topic:Optional[str]
    report_test_families:List[str]=field(default_factory=list)
    standard_test_families:List[str]=field(default_factory=list)
    report_parameters:List[str]=field(default_factory=list)
    standard_parameters:List[str]=field(default_factory=list)
    compatibility:ClauseCompatibility=ClauseCompatibility.INSUFFICIENT_INFORMATION
    confidence:float=0.0;reasons:List[str]=field(default_factory=list)
    evidence_ids:List[str]=field(default_factory=list)
    source_pages:List[int]=field(default_factory=list)


@dataclass
class ParentStructureFinding:
    finding_id:str;finding_type:str="WRONG_REPORT_STANDARD_STRUCTURE"
    status:str="INACTIVE";reason:str=""
    child_finding_ids:List[str]=field(default_factory=list)
    evidence_effect:str="REPORT_EVIDENCE_VALIDITY_REVIEW"
    product_compliance_conclusion:str="NOT_DETERMINED"


@dataclass
class ReportStandardStructureCompatibilityResult:
    schema_version:str;result_id:str;report_id:str
    claimed_standards:List[str];supplied_effective_standard:List[str]
    overall_compatibility:ReportStructureCompatibility;confidence:float
    comparable_clause_count:int;match_count:int;partial_match_count:int
    semantic_mismatch_count:int;insufficient_count:int
    findings:List[ClauseStructureFinding]=field(default_factory=list)
    parent_finding:Optional[ParentStructureFinding]=None
    policy:Dict[str,Any]=field(default_factory=dict)
    quality_audit:Dict[str,int]=field(default_factory=dict)
    def to_dict(self):return asdict(self)
    def to_json(self,indent=2):return json.dumps(self.to_dict(),ensure_ascii=False,sort_keys=True,indent=indent)
    @classmethod
    def from_dict(cls,data):
        findings=[]
        for raw in data.get("findings",[]) or []:
            item=dict(raw);item["compatibility"]=ClauseCompatibility(item["compatibility"]);findings.append(ClauseStructureFinding(**item))
        parent=ParentStructureFinding(**data["parent_finding"]) if data.get("parent_finding") else None
        return cls(str(data.get("schema_version","1.0")),str(data.get("result_id","")),str(data.get("report_id","")),list(data.get("claimed_standards",[]) or []),list(data.get("supplied_effective_standard",[]) or []),ReportStructureCompatibility(data.get("overall_compatibility","INSUFFICIENT_INFORMATION")),float(data.get("confidence",0)),int(data.get("comparable_clause_count",0)),int(data.get("match_count",0)),int(data.get("partial_match_count",0)),int(data.get("semantic_mismatch_count",0)),int(data.get("insufficient_count",0)),findings,parent,dict(data.get("policy",{}) or {}),dict(data.get("quality_audit",{}) or {}))


class GenericReportStandardStructureCompatibilityValidator:
    """Compare bounded same-owner clauses using multiple semantic signals."""
    _STOP={"the","a","an","and","or","of","to","in","for","with","by","on","is","are","be","shall","should","this","that","from","as","at","it","its","test","tests","testing","requirement","requirements","compliance","checked","clause","equipment","device"}
    MIN_SYSTEMATIC_MISMATCHES=3

    def validate(self,effective_kb,report_evidence,standard_validation=None,parameter_ledger=None):
        standard={str(self._get(x,"clause_id")):x for x in self._walk(self._get(effective_kb,"clauses",[]) or [])}
        ledger_index=self._ledger_index(parameter_ledger)
        findings=[]
        for report_clause in self._walk(self._get(report_evidence,"clauses",[]) or []):
            cid=str(self._get(report_clause,"clause_id","") or "")
            if not cid:continue
            findings.append(self.compare_clause(report_clause,standard.get(cid),ledger_index.get(cid,[])))
        counts=Counter(x.compatibility for x in findings)
        comparable=sum(counts[x] for x in (ClauseCompatibility.MATCH,ClauseCompatibility.PARTIAL_MATCH,ClauseCompatibility.SEMANTIC_MISMATCH))
        overall,confidence=self._aggregate(counts,comparable)
        mismatches=[x for x in findings if x.compatibility is ClauseCompatibility.SEMANTIC_MISMATCH]
        parent=ParentStructureFinding(
            "STRUCTURE-PARENT-"+self._digest(*(x.finding_id for x in mismatches)),
            status="ACTIVE" if overall is ReportStructureCompatibility.STRUCTURE_MISMATCH else "INACTIVE",
            reason=("Multiple independently owned clauses show high-confidence semantic incompatibility."
                    if overall is ReportStructureCompatibility.STRUCTURE_MISMATCH else
                    "Minimum systematic-mismatch support was not reached."),
            child_finding_ids=[x.finding_id for x in mismatches])
        report_id=str(self._get(report_evidence,"document_id","") or "")
        claimed=[str(x) for x in self._get(report_evidence,"standard_numbers",[]) or []]
        supplied=[str(x) for x in self._get(standard_validation,"supplied_standards",[]) or []]
        if not supplied:
            supplied=list(self._effective_standard_ids(effective_kb))
        result_id="STRUCTURE-COMPAT-"+self._digest(report_id,overall.value,*(x.finding_id for x in findings))
        return ReportStandardStructureCompatibilityResult("1.0",result_id,report_id,claimed,supplied,overall,confidence,comparable,counts[ClauseCompatibility.MATCH],counts[ClauseCompatibility.PARTIAL_MATCH],counts[ClauseCompatibility.SEMANTIC_MISMATCH],counts[ClauseCompatibility.INSUFFICIENT_INFORMATION],findings,parent,{"minimum_independent_strong_mismatches":self.MIN_SYSTEMATIC_MISMATCHES,"aggregation":"STRUCTURE_MISMATCH requires at least three high-confidence semantic mismatches and more mismatches than strong matches; partial evidence cannot cancel independently proven contradictions, and one weak mismatch never triggers the parent gate."},{"clause_number_only_matches":0,"heading_only_structure_mismatches":0,"unsafe_same_number_matches_blocked":counts[ClauseCompatibility.SEMANTIC_MISMATCH],"product_compliance_decisions_created":0,"special_case_branches":0})

    def compare_clause(self,report_clause,standard_clause,ledger_observations=()):
        cid=str(self._get(report_clause,"clause_id","") or "")
        report_topic=str(self._get(report_clause,"title","") or "")
        standard_topic=str(self._get(standard_clause,"title","") or "") if standard_clause is not None else ""
        report_text=self._report_text(report_clause);standard_text=self._standard_text(standard_clause)
        evidence_ids=sorted(str(self._get(x,"evidence_id")) for x in self._get(report_clause,"evidence_items",[]) or [] if self._get(x,"evidence_id"))
        pages=sorted({int(p) for x in self._get(report_clause,"evidence_items",[]) or [] for p in (self._get(x,"page_start"),self._get(x,"page_end")) if p is not None})
        if standard_clause is None:return self._finding(cid,None,report_topic,None,[],[],[],[],ClauseCompatibility.NOT_COMPARABLE,.9,["NO_EFFECTIVE_STANDARD_CLAUSE_OWNER"],evidence_ids,pages)
        report_parameters=self._report_parameters(report_clause)|{str(self._get(x,"canonical_parameter")) for x in ledger_observations if self._get(x,"canonical_parameter")}
        standard_parameters=self._standard_parameters(standard_clause)
        report_families=self._families(report_text,report_parameters)
        standard_families=self._families(standard_text,standard_parameters)
        topic_score=self._overlap(self._tokens(report_topic or report_text),self._tokens(standard_topic or standard_text))
        parameter_overlap=bool(report_parameters&standard_parameters)
        family_overlap=bool((report_families&standard_families)-{"GENERAL_TECHNICAL"})
        family_conflict=bool(report_families-{"GENERAL_TECHNICAL"} and standard_families-{"GENERAL_TECHNICAL"} and not family_overlap)
        parameter_conflict=bool(report_parameters and standard_parameters and not parameter_overlap)
        ledger_family_rejection=any(str(self._get(x,"evidence_status","")).startswith("WRONG_TEST_FAMILY") for x in ledger_observations)
        informative=bool(self._tokens(report_topic or report_text) and self._tokens(standard_topic or standard_text))
        reasons=[]
        if parameter_overlap:reasons.append("PARAMETER_FAMILY_MATCH")
        if family_overlap:reasons.append("TEST_FAMILY_MATCH")
        if topic_score>=.35:reasons.append("NORMALIZED_TOPIC_MATCH")
        if ledger_family_rejection:
            state=ClauseCompatibility.SEMANTIC_MISMATCH;confidence=.95
            reasons=["TEST_FAMILY_MISMATCH","LEDGER_SEMANTIC_OWNERSHIP_REJECTED"]
        elif family_conflict and parameter_conflict:
            state=ClauseCompatibility.SEMANTIC_MISMATCH;confidence=.92
            reasons=["TEST_FAMILY_MISMATCH","PARAMETER_FAMILY_MISMATCH",*( ["HEADING_MATCH_OVERRIDDEN_BY_TECHNICAL_SEMANTICS"] if topic_score>=.35 else ["NORMALIZED_TOPIC_DIVERGENCE"])]
        elif parameter_overlap and family_overlap or topic_score>=.55:
            state=ClauseCompatibility.MATCH;confidence=min(.99,.7+.2*parameter_overlap+.09*family_overlap)
        elif parameter_overlap or family_overlap or topic_score>=.18:
            state=ClauseCompatibility.PARTIAL_MATCH;confidence=.65+.1*parameter_overlap+.1*family_overlap
        elif not informative and not report_parameters:
            state=ClauseCompatibility.INSUFFICIENT_INFORMATION;confidence=.25;reasons=["REPORT_SEMANTICS_SPARSE"]
        else:
            if topic_score<.12 and (family_conflict or parameter_conflict):
                state=ClauseCompatibility.SEMANTIC_MISMATCH;confidence=.9 if family_conflict and parameter_conflict else .82
                reasons=["NORMALIZED_TOPIC_DIVERGENCE",*( ["TEST_FAMILY_MISMATCH"] if family_conflict else []),*( ["PARAMETER_FAMILY_MISMATCH"] if parameter_conflict else [])]
            else:
                state=ClauseCompatibility.INSUFFICIENT_INFORMATION;confidence=.4;reasons=["SEMANTIC_SIGNALS_INCOMPLETE"]
        return self._finding(cid,cid,report_topic,standard_topic,report_families,standard_families,report_parameters,standard_parameters,state,confidence,reasons,evidence_ids,pages)

    def gate_evidence_matches(self,match_report,compatibility):
        """Reject exact-number reuse only for strongly mismatched clause children."""
        mismatched={x.report_clause:x for x in self._get(compatibility,"findings",[]) or [] if self._enum(self._get(x,"compatibility"))=="SEMANTIC_MISMATCH" and float(self._get(x,"confidence",0) or 0)>=.8}
        blocked=0
        for match in self._get(match_report,"matches",[]) or []:
            clause=str(self._get(match,"effective_clause_id") or self._get(match,"source_clause_id","") or "")
            if clause not in mismatched:
                source_clause=str(self._get(match,"source_clause_id","") or "")
                clause=source_clause if source_clause in mismatched else re.sub(r"^E-C-(?:MAIN|ANNEX-[^-]+)-","",clause)
            finding=mismatched.get(clause)
            if not finding:continue
            self._set(match,"evidence_refs",[])
            self._set(match,"match_type","REJECTED_SEMANTIC_STRUCTURE_MISMATCH")
            self._set(match,"match_confidence","REJECTED")
            self._set(match,"match_reason","Same clause identity was rejected because independent topic/test-family/parameter signals are incompatible.")
            self._set(match,"evidence_scope","EVIDENCE_PRESENT_NOT_SEMANTICALLY_COMPATIBLE")
            self._set(match,"notes","REJECTED_SEMANTIC_STRUCTURE_MISMATCH: "+str(self._get(finding,"finding_id")))
            blocked+=1
        return blocked

    @classmethod
    def _aggregate(cls,counts,comparable):
        mismatch=counts[ClauseCompatibility.SEMANTIC_MISMATCH];strong_matches=counts[ClauseCompatibility.MATCH]
        if comparable<2:return ReportStructureCompatibility.INSUFFICIENT_INFORMATION,.35 if comparable else .15
        if mismatch>=cls.MIN_SYSTEMATIC_MISMATCHES and mismatch>strong_matches:return ReportStructureCompatibility.STRUCTURE_MISMATCH,min(.99,.75+.04*mismatch)
        if counts[ClauseCompatibility.MATCH]>=2 and mismatch==0:return ReportStructureCompatibility.COMPATIBLE,min(.98,.7+.03*counts[ClauseCompatibility.MATCH])
        return ReportStructureCompatibility.PARTIALLY_COMPATIBLE,min(.85,.5+.03*comparable)
    @classmethod
    def _families(cls,text,parameters):
        values={GenericCrossEvidenceConsistencyValidator.test_family(text)}
        values.update(GenericCrossEvidenceConsistencyValidator.test_family(x) for x in parameters)
        return values
    @classmethod
    def _report_parameters(cls,clause):
        return {GenericCrossEvidenceConsistencyValidator.canonical_parameter(cls._get(m,"parameter") or cls._get(m,"parameter_text")) for item in cls._get(clause,"evidence_items",[]) or [] for m in cls._get(item,"measurements",[]) or [] if cls._get(m,"parameter") or cls._get(m,"parameter_text")}
    @classmethod
    def _standard_parameters(cls,clause):
        return {GenericCrossEvidenceConsistencyValidator.canonical_parameter(cls._get(c,"parameter") or cls._get(c,"parameter_text")) for requirement in cls._get(clause,"requirements",[]) or [] for c in cls._get(requirement,"technical_constraints",[]) or [] if cls._get(c,"parameter") or cls._get(c,"parameter_text")}
    @classmethod
    def _report_text(cls,clause):return " ".join(str(x or "") for x in [cls._get(clause,"title"),cls._get(clause,"raw_text"),*[cls._get(i,"raw_text") for i in cls._get(clause,"evidence_items",[]) or []]])
    @classmethod
    def _standard_text(cls,clause):return " ".join(str(x or "") for x in [cls._get(clause,"title"),*[cls._get(r,"text") for r in cls._get(clause,"requirements",[]) or []]]) if clause is not None else ""
    @classmethod
    def _tokens(cls,text):return {x for x in re.findall(r"[^\W\d_]{3,}",str(text or "").casefold(),re.UNICODE) if x not in cls._STOP}
    @staticmethod
    def _overlap(left,right):return len(left&right)/min(len(left),len(right)) if left and right else 0.0
    @classmethod
    def _finding(cls,cid,standard,rt,st,rf,sf,rp,sp,state,confidence,reasons,eids,pages):
        identity="\x1f".join([cid,str(standard),state.value,*sorted(reasons),*eids]);return ClauseStructureFinding("STRUCTURE-CHILD-"+hashlib.sha256(identity.encode()).hexdigest()[:20].upper(),cid,standard,rt or None,st or None,sorted(rf),sorted(sf),sorted(rp),sorted(sp),state,round(confidence,3),reasons,eids,pages)
    @classmethod
    def _ledger_index(cls,ledger):
        output={}
        for entry in ledger or []:
            for observation in cls._get(entry,"observations",[]) or []:
                if str(cls._get(observation,"source_type","") or "")!="REPORT_MEASUREMENT":continue
                clause=str(cls._get(observation,"source_clause","") or "")
                if clause:output.setdefault(clause,[]).append(observation)
        return output
    @classmethod
    def _effective_standard_ids(cls,kb):
        document=cls._get(kb,"document",{}) or {};return [str(x) for x in (cls._get(document,"standard_number"),cls._get(document,"parent_standard")) if x]
    @classmethod
    def _walk(cls,nodes):
        for node in nodes:
            yield node;yield from cls._walk(cls._get(node,"children",[]) or [])
    @staticmethod
    def _digest(*parts):return hashlib.sha256("\x1f".join(map(str,parts)).encode()).hexdigest()[:20].upper()
    @staticmethod
    def _set(value,name,item):setattr(value,name,item) if not isinstance(value,Mapping) else value.__setitem__(name,item)
    @staticmethod
    def _get(value,name,default=None):return value.get(name,default) if isinstance(value,Mapping) else getattr(value,name,default) if value is not None else default
    @staticmethod
    def _enum(value):return str(value.value if isinstance(value,Enum) else value)
    @staticmethod
    def save_json(result,path):
        target=Path(path);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(result.to_json()+"\n",encoding="utf-8")


__all__=["ClauseCompatibility","ClauseStructureFinding","GenericReportStandardStructureCompatibilityValidator","ParentStructureFinding","ReportStandardStructureCompatibilityResult","ReportStructureCompatibility"]
