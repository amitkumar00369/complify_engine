"""Deterministically link effective requirements to report-side evidence."""

from __future__ import annotations

import copy
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union
from urllib.parse import quote


PathLike = Union[str, Path]


class RequirementEvidenceMatchStatus(str, Enum):
    """Structural confidence category for a report-evidence association."""

    EXACT_CLAUSE = "EXACT_CLAUSE"
    EXACT_SUBCLAUSE = "EXACT_SUBCLAUSE"
    PARENT_CLAUSE = "PARENT_CLAUSE"
    CHILD_CLAUSE = "CHILD_CLAUSE"
    ANNEX_EXACT = "ANNEX_EXACT"
    MULTIPLE_CANDIDATES = "MULTIPLE_CANDIDATES"
    NO_MATCH = "NO_MATCH"
    NEEDS_REVIEW = "NEEDS_REVIEW"


@dataclass
class ReportEvidenceReference:
    """Concise reference to an immutable Step 16 evidence occurrence."""

    evidence_id: Optional[str] = None
    report_clause_id: Optional[str] = None
    report_result_id: Optional[str] = None
    reported_verdict: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    evidence_type: Optional[str] = None
    measurement_ids: List[str] = field(default_factory=list)
    raw_text_excerpt: Optional[str] = None
    source_order: Optional[int] = None


@dataclass
class RequirementEvidenceMatchResult:
    """Evidence match for one effective requirement without a compliance result."""

    match_id: str
    effective_requirement_id: str
    effective_clause_id: Optional[str]
    source_clause_id: Optional[str]
    effective_status: Optional[str]
    applicability_decision: Optional[str]
    match_status: RequirementEvidenceMatchStatus
    match_score: Optional[float] = None
    matched_report_clauses: List[str] = field(default_factory=list)
    evidence_refs: List[ReportEvidenceReference] = field(default_factory=list)
    candidate_report_clauses: List[str] = field(default_factory=list)
    unmatched_reason: Optional[str] = None
    notes: Optional[str] = None
    match_type: Optional[str] = None
    match_confidence: Optional[str] = None
    match_reason: Optional[str] = None
    evidence_scope: Optional[str] = None


@dataclass
class RequirementEvidenceMatchReport:
    """All requirement/evidence links for one Effective KB and report."""

    effective_kb_id: str
    profile_id: Optional[str]
    report_document_id: str
    matches: List[RequirementEvidenceMatchResult] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "RequirementEvidenceMatchReport":
        """Reconstruct a serialized match report."""

        matches=[]
        for raw in payload.get("matches",[]):
            data=dict(raw); data["match_status"]=RequirementEvidenceMatchStatus(data["match_status"])
            data["evidence_refs"]=[ReportEvidenceReference(**item) for item in data.get("evidence_refs",[])]
            matches.append(RequirementEvidenceMatchResult(**data))
        return cls(payload["effective_kb_id"],payload.get("profile_id"),payload["report_document_id"],
                   matches,dict(payload.get("summary",{})),list(payload.get("diagnostics",[])))


class GenericRequirementEvidenceMatcher:
    """Match by namespace and structure before conservative text similarity."""

    _STOP = {
        "the","a","an","and","or","of","to","in","is","are","be","shall","should",
        "with","for","by","on","that","this","from","as","at","it","its","compliance",
        "checked","requirement","requirements","test","tests","appliance","appliances",
    }

    def __init__(self) -> None:
        self._diagnostics: List[Dict[str,Any]]=[]

    def match(self,effective_kb:Any,report_evidence:Any,applicability_report:Any=None,
              structure_compatibility:Any=None)->RequirementEvidenceMatchReport:
        """Match every effective requirement while preserving all inputs."""

        self._diagnostics=[]
        app_by_id={self._get(x,"effective_requirement_id"):self._get(x,"decision")
                   for x in self._get(applicability_report,"results",[]) or []}
        main_nodes=self._flatten_report(self._get(report_evidence,"clauses",[]) or [])
        main_index={str(self._get(x,"clause_id")):x for x in main_nodes}
        annex_index=self._report_annex_index(report_evidence)
        results=[]; requirements_by_id={}
        for requirement,container_id,annex_id in self._iter_requirements(effective_kb):
            rid=self._get(requirement,"effective_requirement_id")
            requirements_by_id[str(rid)]=requirement
            results.append(self.match_requirement(requirement,main_index,
                app_by_id.get(rid),container_id,annex_id,annex_index))
        self._mark_grouped_verdicts(results,requirements_by_id)
        report=RequirementEvidenceMatchReport(
            str(self._get(effective_kb,"effective_kb_id","")),
            self._get(applicability_report,"profile_id"),
            str(self._get(report_evidence,"document_id","")),results,
            diagnostics=copy.deepcopy(self._diagnostics))
        if structure_compatibility is not None:
            from .generic_report_standard_structure_compatibility import GenericReportStandardStructureCompatibilityValidator
            blocked=GenericReportStandardStructureCompatibilityValidator().gate_evidence_matches(report,structure_compatibility)
            if blocked:self._diagnostics.append({"code":"REJECTED_SEMANTIC_STRUCTURE_MISMATCH","blocked_matches":blocked})
            report.diagnostics=copy.deepcopy(self._diagnostics)
        report.summary=self.get_summary(report,report_evidence)
        return report

    def _mark_grouped_verdicts(
        self, results: Sequence[RequirementEvidenceMatchResult],
        requirements_by_id: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Mark one logical evidence row reused across atomic requirements."""

        owners:Dict[str,List[RequirementEvidenceMatchResult]]=defaultdict(list)
        for result in results:
            for reference in result.evidence_refs:
                if reference.evidence_id:
                    owners[str(reference.evidence_id)].append(result)
        for evidence_id,matches in owners.items():
            distinct={item.effective_requirement_id for item in matches}
            if len(distinct)<2:continue
            # A report may place several complete normative statements in one
            # independently verdict-bearing row. Reuse is safe only when every
            # matched requirement is textually present as a complete statement;
            # ordinary semantic similarity remains grouped and conservative.
            if requirements_by_id and all(
                self._independent_match(item)
                and self._statement_present(
                    self._get(requirements_by_id.get(item.effective_requirement_id), "text", ""),
                    item.evidence_refs[0].raw_text_excerpt if item.evidence_refs else "",
                )
                for item in matches
            ):
                for item in matches:
                    item.match_type = "EXACT_SHARED_ROW_SEMANTIC"
                    item.match_confidence = "HIGH"
                    item.match_reason = "COMPLETE_REQUIREMENT_TEXT_IN_INDEPENDENT_SHARED_ROW"
                    item.evidence_scope = "INDIVIDUAL_STATEMENT_IN_SHARED_ROW"
                self._diag("MATCH_SHARED_ROW_ATOMIC_STATEMENTS", evidence_id, str(len(distinct)))
                continue
            ranked=sorted(matches,key=lambda item:(self._independent_match(item),item.match_score or 0.0),reverse=True)
            # A single independently owned row may be reused by broad clause
            # matching.  Preserve it for one requirement only when semantic
            # alignment is decisively stronger; the other requirements retain
            # clause presence without borrowing its verdict.
            independent=[item for item in ranked if self._independent_match(item)]
            decisive = (len(independent) > 1
                        and (independent[0].match_score or 0.0)
                        - (independent[1].match_score or 0.0) >= .30)
            if ((len(independent)==1 and (independent[0].match_score or 0.0)>=.30)
                    or decisive):
                ranked=[independent[0],*[item for item in ranked if item is not independent[0]]]
                for item in ranked[1:]:
                    item.evidence_refs=[]
                    item.match_status=RequirementEvidenceMatchStatus.NEEDS_REVIEW
                    item.match_type="CLAUSE_PRESENCE_ONLY"
                    item.match_confidence="UNRESOLVED"
                    item.match_reason="A more strongly aligned requirement owns the independent report verdict."
                    item.evidence_scope="EVIDENCE_PRESENT_NOT_SUFFICIENT"
                    item.notes="Sibling requirement verdict ownership was not inferred."
                continue
            for item in matches:
                item.match_status=RequirementEvidenceMatchStatus.NEEDS_REVIEW
                item.match_type="GROUP_VERDICT"
                item.match_confidence="MEDIUM"
                item.match_reason="One logical report verdict is shared by multiple atomic requirements."
                item.evidence_scope="GROUP_VERDICT"
                item.notes="Evidence is present at grouped scope; atomic sufficiency is not independently proven."
            self._diag("MATCH_GROUP_VERDICT",evidence_id,str(len(distinct)))

    @classmethod
    def _statement_present(cls, requirement_text: Any, evidence_text: Any) -> bool:
        """Require near-verbatim statement containment before sharing a verdict."""

        requirement = re.sub(r"\W+", " ", str(requirement_text).casefold()).strip()
        evidence = re.sub(r"\W+", " ", str(evidence_text).casefold()).strip()
        if len(requirement) < 24 or not evidence:
            return False
        if requirement in evidence:
            return True
        required_tokens = requirement.split()
        evidence_tokens = set(evidence.split())
        return (len(required_tokens) >= 8
                and sum(token in evidence_tokens for token in required_tokens) / len(required_tokens) >= .92)

    def match_requirement(self,requirement:Any,report_index:Mapping[str,Any],
                          applicability_decision:Any=None,effective_clause_id:Optional[str]=None,
                          annex_id:Optional[str]=None,
                          annex_index:Optional[Mapping[str,Mapping[str,Any]]]=None
                          )->RequirementEvidenceMatchResult:
        """Match one requirement against prepared main and annex report indexes."""

        rid=str(self._get(requirement,"effective_requirement_id","")); clause=str(self._get(requirement,"clause_id",""))
        if not rid: raise ValueError("effective requirement has no effective_requirement_id")
        status=self._enum_value(self._get(requirement,"effective_status")); decision=self._enum_value(applicability_decision)
        if annex_id is not None:
            namespace=(annex_index or {}).get(annex_id)
            if not namespace:
                return self._no_match(rid,clause,status,decision,effective_clause_id,"ANNEX_NOT_PRESENT")
            node=namespace.get(clause)
            if node:
                return self._matched(requirement,node,RequirementEvidenceMatchStatus.ANNEX_EXACT,.85,
                                     decision,effective_clause_id)
            return self._no_match(rid,clause,status,decision,effective_clause_id,"NO_REPORT_CLAUSE")
        exact=report_index.get(clause)
        if exact:
            child_match = self._best_direct_child_item(requirement, clause, report_index)
            if child_match is not None:
                owner, item = child_match
                result = self._matched_subrow(requirement, owner, item, decision, effective_clause_id)
                result.match_status = RequirementEvidenceMatchStatus.NEEDS_REVIEW
                result.match_type = "PARENT_REQUIREMENT_SUPPORTED_BY_CHILD_EVIDENCE"
                result.match_confidence = "HIGH"
                result.match_reason = "DIRECT_CHILD_SCOPE + STRONG_SEMANTIC_ALIGNMENT"
                result.evidence_scope = "INDIVIDUAL_CHILD_EVIDENCE"
                self._diag("MATCH_PARENT_REQUIREMENT_CHILD_EVIDENCE", rid, clause)
                return result
            subrow=self._best_subrow(requirement,exact)
            if subrow is not None:
                result=self._matched_subrow(requirement,exact,subrow,decision,effective_clause_id)
                self._diag("MATCH_REQUIREMENT_SUBROW",rid,clause)
                return result
            if self._subrows(exact):
                self._diag("MATCH_SUBROW_ALIGNMENT_UNRESOLVED",rid,clause)
                return self._clause_presence(
                    requirement, exact, decision, effective_clause_id,
                    "Report subrows are present, but no unique compatible subrow was established.",
                )
            independent=self._best_individual_item(requirement,exact)
            if independent is not None:
                result=self._matched_subrow(requirement,exact,independent,decision,effective_clause_id)
                self._diag("MATCH_REQUIREMENT_ROW",rid,clause)
                return result
            verdicts=self._evidence_verdicts(exact)
            if len(verdicts)>1:
                self._diag("MATCH_CONFLICTING_VERDICTS",rid,clause)
                result=self._matched(requirement,exact,RequirementEvidenceMatchStatus.NEEDS_REVIEW,None,
                                     decision,effective_clause_id)
                result.notes="Conflicting verdicts across report evidence occurrences."
                return result
            if self._clear_semantic_mismatch(requirement, exact):
                self._diag("REPORT_STANDARD_CLAUSE_SEMANTIC_MISMATCH",rid,clause)
                result=self._matched(requirement,exact,RequirementEvidenceMatchStatus.NEEDS_REVIEW,None,
                                     decision,effective_clause_id)
                result.match_type="UNMATCHED"
                result.match_confidence="UNRESOLVED"
                result.match_reason="Exact clause number but materially different report and standard subjects."
                result.evidence_scope="CLAUSE_SCOPE_SEMANTIC_ALIGNMENT_UNRESOLVED"
                result.notes="Evidence retained for review but not strongly assigned."
                return result
            match_status=(RequirementEvidenceMatchStatus.EXACT_SUBCLAUSE if "." in clause
                          else RequirementEvidenceMatchStatus.EXACT_CLAUSE)
            score=1.0 if self._distinctive_similarity(self._get(requirement,"text",""),self._get(exact,"raw_text",""))>=.6 else .95
            result=self._matched(requirement,exact,match_status,score,decision,effective_clause_id)
            result.notes="Clause-level report result; requirement-specific evidence not distinguished."
            result.match_type="EXACT_CLAUSE"
            result.match_confidence="HIGH"
            result.match_reason="Exact structural clause ownership with compatible report text."
            result.evidence_scope="EVIDENCE_PRESENT_AT_CLAUSE_SCOPE"
            self._diag("MATCH_CLAUSE_LEVEL_ONLY",rid,clause)
            return result
        parent=self._nearest_parent(clause,report_index)
        if parent and self._supports_aggregation(parent):
            self._diag("MATCH_PARENT_FALLBACK",rid,self._get(parent,"clause_id"))
            if self._subrows(parent):
                return self._clause_presence(
                    requirement,parent,decision,effective_clause_id,
                    "Parent report row provides grouped clause context; sibling verdicts are not inherited.",
                )
            result=self._matched(requirement,parent,RequirementEvidenceMatchStatus.PARENT_CLAUSE,.70,
                                 decision,effective_clause_id)
            result.notes="Nearest structurally aggregating report parent used; descendant-specific evidence was absent."
            return result
        children=[node for key,node in report_index.items() if key.startswith(clause+".")]
        direct=[node for node in children if self._direct_child(clause,str(self._get(node,"clause_id")))]
        if direct:
            verdicts={v for node in direct for v in self._evidence_verdicts(node)}
            if len(verdicts)>1:
                self._diag("MATCH_CONFLICTING_VERDICTS",rid,clause)
                return self._multi_node_presence(requirement,direct,decision,effective_clause_id,
                    "Child report rows have distinct scopes; only grouped evidence presence is retained.")
            self._diag("MATCH_CHILD_FALLBACK",rid,clause)
            return self._multi_node_result(requirement,direct,RequirementEvidenceMatchStatus.CHILD_CLAUSE,
                .65,decision,effective_clause_id,"Direct child report clauses used for a parent requirement.")
        embedded=self._embedded_clause_subrows(requirement,clause,report_index.values())
        if len(embedded)==1:
            owner,item=embedded[0]
            result=self._matched_subrow(requirement,owner,item,decision,effective_clause_id)
            result.match_status=RequirementEvidenceMatchStatus.NEEDS_REVIEW
            result.match_type="EXPLICIT_PARENT_CHILD_REPORT_OWNERSHIP"
            result.match_confidence="MEDIUM"
            result.match_reason="EXPLICIT_CLAUSE_MARKER + STRONG_SUBROW_SEMANTIC_ALIGNMENT"
            result.evidence_scope="INDIVIDUAL_SUBROW_RETAINED_FOR_REVIEW"
            self._diag("MATCH_EMBEDDED_CLAUSE_SUBROW",rid,clause)
            return result
        cross_referenced=[node for node in report_index.values()
                          if self._explicit_cross_reference(node,clause)
                          and not self._clear_semantic_mismatch(requirement,node)]
        if len(cross_referenced)==1:
            result=self._multi_node_result(requirement,cross_referenced,
                RequirementEvidenceMatchStatus.NEEDS_REVIEW,.75,decision,effective_clause_id,
                "Explicit report cross-reference retained for review.")
            result.match_type="EXPLICIT_CROSS_REFERENCE"
            result.match_confidence="MEDIUM"
            result.match_reason="Report text explicitly references the source clause."
            result.evidence_scope="EXPLICIT_CROSS_REFERENCE"
            return result
        reason="NO_RELIABLE_PARENT_MATCH" if parent else "NO_REPORT_CLAUSE"
        self._diag("MATCH_NO_REPORT_EVIDENCE",rid,clause)
        return self._no_match(rid,clause,status,decision,effective_clause_id,reason)

    @classmethod
    def _best_direct_child_item(
        cls, requirement: Any, clause: str, report_index: Mapping[str, Any]
    ) -> Optional[Tuple[Any, Any]]:
        """Return one semantically unique, independently verdicted direct child."""

        candidates: List[Tuple[float, Any, Any]] = []
        text = cls._get(requirement, "text", "")
        for child_id, node in report_index.items():
            if not cls._direct_child(clause, str(child_id)):
                continue
            items = [item for item in cls._get(node, "evidence_items", []) or []
                     if cls._independent_item(item) or cls._sole_clause_row(
                         item, cls._get(node, "evidence_items", []) or [])]
            for item in items:
                score, _ = cls._semantic_alignment(text, cls._get(item, "raw_text", ""), item)
                if score >= .45:
                    candidates.append((score, node, item))
        candidates.sort(key=lambda value: value[0], reverse=True)
        if not candidates:
            return None
        if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < .10:
            return None
        return candidates[0][1], candidates[0][2]

    @classmethod
    def to_dict(cls,value:Union[RequirementEvidenceMatchReport,RequirementEvidenceMatchResult])->Dict[str,Any]:
        if not is_dataclass(value): raise TypeError("value must be a matcher result model")
        return cls._safe(asdict(value))

    @classmethod
    def to_json(cls,value:Union[RequirementEvidenceMatchReport,RequirementEvidenceMatchResult],indent:Optional[int]=2)->str:
        return json.dumps(cls.to_dict(value),ensure_ascii=False,sort_keys=True,indent=indent)

    @classmethod
    def save_json(cls,report:RequirementEvidenceMatchReport,output_path:PathLike)->Path:
        path=Path(output_path); path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(cls.to_json(report,2)+"\n",encoding="utf-8"); return path

    @staticmethod
    def get_summary(report:RequirementEvidenceMatchReport,report_evidence:Any=None)->Dict[str,Any]:
        counts=Counter(x.match_status.value for x in report.matches)
        with_evidence=lambda x:bool(x.evidence_refs)
        used={c for x in report.matches for c in x.matched_report_clauses}
        all_report={str(GenericRequirementEvidenceMatcher._get(x,"clause_id"))
                    for x in GenericRequirementEvidenceMatcher._flatten_report(
                        GenericRequirementEvidenceMatcher._get(report_evidence,"clauses",[]) or [])} if report_evidence else set()
        return {
            "total_effective_requirements":len(report.matches),
            **{status.value:counts[status.value] for status in RequirementEvidenceMatchStatus},
            "active_requirements_with_match":sum(x.effective_status=="ACTIVE" and with_evidence(x) for x in report.matches),
            "active_requirements_without_match":sum(x.effective_status=="ACTIVE" and not with_evidence(x) for x in report.matches),
            "inactive_requirements_with_match":sum(x.effective_status=="INACTIVE" and with_evidence(x) for x in report.matches),
            "inactive_requirements_without_match":sum(x.effective_status=="INACTIVE" and not with_evidence(x) for x in report.matches),
            "applicability_with_evidence":{decision:sum(x.applicability_decision==decision and with_evidence(x) for x in report.matches)
                for decision in ("APPLICABLE","NOT_APPLICABLE","UNKNOWN","NEEDS_REVIEW","INACTIVE")},
            "report_clauses_used":sorted(used),"report_clauses_unused":sorted(all_report-used),
            "measurements_attached":sum(len(ref.measurement_ids) for x in report.matches for ref in x.evidence_refs),
        }

    def get_diagnostics(self)->List[Dict[str,Any]]: return copy.deepcopy(self._diagnostics)

    def _matched(self,requirement:Any,node:Any,status:RequirementEvidenceMatchStatus,score:Optional[float],
                 decision:Optional[str],effective_clause_id:Optional[str])->RequirementEvidenceMatchResult:
        rid=str(self._get(requirement,"effective_requirement_id")); clause=str(self._get(requirement,"clause_id"))
        refs=self._references(node,requirement)
        return RequirementEvidenceMatchResult(self._match_id(rid),rid,effective_clause_id,clause,
            self._enum_value(self._get(requirement,"effective_status")),decision,status,score,
            [str(self._get(node,"clause_id"))],refs,[])

    def _matched_subrow(self,requirement:Any,node:Any,item:Any,decision:Optional[str],
                        effective_clause_id:Optional[str])->RequirementEvidenceMatchResult:
        rid=str(self._get(requirement,"effective_requirement_id"));clause=str(self._get(requirement,"clause_id"))
        score,reasons=self._semantic_alignment(self._get(requirement,"text",""),self._get(item,"raw_text",""),item)
        ref=ReportEvidenceReference(self._get(item,"evidence_id"),clause,self._get(node,"result_id"),
            self._enum_value(self._get(item,"reported_verdict")),self._get(item,"page_start"),
            self._get(item,"page_end"),self._enum_value(self._get(item,"evidence_type")),
            self._compatible_measurement_ids(requirement,self._get(item,"measurements",[]) or []),
            self._excerpt(self._get(item,"raw_text")),self._get(item,"source_order"))
        return RequirementEvidenceMatchResult(self._match_id(rid),rid,effective_clause_id,clause,
            self._enum_value(self._get(requirement,"effective_status")),decision,
            RequirementEvidenceMatchStatus.EXACT_SUBCLAUSE if "." in clause else RequirementEvidenceMatchStatus.EXACT_CLAUSE,
            score,[str(self._get(node,"clause_id"))],[ref],[],match_type="EXACT_SUBROW_SEMANTIC",
            match_confidence="HIGH" if score>=.70 else "MEDIUM",
            match_reason=" + ".join(["EXACT_CLAUSE",*reasons]),
            evidence_scope="INDIVIDUAL")

    def _clause_presence(
        self, requirement: Any, node: Any, decision: Optional[str],
        effective_clause_id: Optional[str], reason: str,
    ) -> RequirementEvidenceMatchResult:
        """Represent clause-row presence without borrowing sibling verdicts."""

        rid=str(self._get(requirement,"effective_requirement_id"));clause=str(self._get(requirement,"clause_id"))
        parents=[item for item in self._get(node,"evidence_items",[]) or []
                 if self._enum_value(self._get(item,"evidence_type"))=="CLAUSE_ROW"]
        refs=[ReportEvidenceReference(
            self._get(item,"evidence_id"),clause,self._get(node,"result_id"),"NOT_STATED",
            self._get(item,"page_start"),self._get(item,"page_end"),"CLAUSE_ROW",[],
            self._excerpt(self._get(item,"raw_text")),self._get(item,"source_order"),
        ) for item in parents]
        return RequirementEvidenceMatchResult(
            self._match_id(rid),rid,effective_clause_id,clause,
            self._enum_value(self._get(requirement,"effective_status")),decision,
            RequirementEvidenceMatchStatus.NEEDS_REVIEW,None,[clause],refs,[],notes=reason,
            match_type="CLAUSE_PRESENCE_ONLY",match_confidence="UNRESOLVED",
            match_reason=reason,evidence_scope="EVIDENCE_PRESENT_NOT_SUFFICIENT",
        )

    @classmethod
    def _subrows(cls,node:Any)->List[Any]:
        return [item for item in cls._get(node,"evidence_items",[]) or []
                if cls._enum_value(cls._get(item,"evidence_type"))=="SUBROW"]

    @classmethod
    def _best_subrow(cls,requirement:Any,node:Any)->Any:
        items=[item for item in cls._subrows(node) if cls._independent_item(item)]
        if not items:return None
        text=str(cls._get(requirement,"text","") or "")
        exact=[item for item in items if cls._statement_present(
            text, cls._get(item,"raw_text","") or "")]
        if len(exact)==1:return exact[0]
        scored=sorted(((cls._semantic_alignment(text,str(cls._get(item,"raw_text","") or ""),item)[0],item)
                       for item in items),key=lambda pair:pair[0],reverse=True)
        if not scored or scored[0][0] < .10:return None
        if len(scored)>1 and scored[0][0]-scored[1][0] < .10:return None
        return scored[0][1]

    @classmethod
    def _best_individual_item(cls,requirement:Any,node:Any)->Any:
        all_items=cls._get(node,"evidence_items",[]) or []
        items=[item for item in all_items
               if (cls._independent_item(item) or cls._sole_clause_row(item,all_items))
               and cls._enum_value(cls._get(item,"reported_verdict")) not in {None,"NOT_STATED"}]
        if not items:return None
        text=str(cls._get(requirement,"text","") or "")
        scored=sorted(((cls._semantic_alignment(text,str(cls._get(item,"raw_text","") or ""),item)[0],item)
                       for item in items),key=lambda pair:pair[0],reverse=True)
        return scored[0][1] if scored and scored[0][0]>=.30 else None

    @classmethod
    def _embedded_clause_subrows(cls,requirement:Any,clause:str,nodes:Iterable[Any])->List[Tuple[Any,Any]]:
        found=[]
        marker=re.compile(rf"^\s*{re.escape(clause)}(?:\s+[A-Z])?\b",re.I)
        for node in nodes:
            for item in cls._subrows(node):
                raw=str(cls._get(item,"raw_text","") or "")
                if not marker.search(raw) or not cls._independent_item(item):continue
                score,_=cls._semantic_alignment(cls._get(requirement,"text",""),raw,item)
                if score>=.30:found.append((node,item))
        found.sort(key=lambda pair:cls._semantic_alignment(cls._get(requirement,"text",""),cls._get(pair[1],"raw_text",""),pair[1])[0],reverse=True)
        if len(found)>1:
            first=cls._semantic_alignment(cls._get(requirement,"text",""),cls._get(found[0][1],"raw_text",""),found[0][1])[0]
            second=cls._semantic_alignment(cls._get(requirement,"text",""),cls._get(found[1][1],"raw_text",""),found[1][1])[0]
            if first-second>=.10:return found[:1]
        return found

    @classmethod
    def _independent_item(cls,item:Any)->bool:
        eid=str(cls._get(item,"evidence_id","") or "")
        owner=str(cls._get(item,"verdict_owner_evidence_id","") or "")
        scope=str(cls._get(item,"verdict_scope","") or "")
        logical=cls._get(item,"logical_row_id")
        return scope=="INDIVIDUAL_VERDICT" and bool(logical) and (not owner or owner==eid)

    @classmethod
    def _sole_clause_row(cls,item:Any,items:Sequence[Any])->bool:
        """Treat one verdict-bearing physical row with no children as atomic."""
        return (cls._enum_value(cls._get(item,"evidence_type"))=="CLAUSE_ROW"
                and bool(cls._get(item,"logical_row_id"))
                and not (cls._get(item,"child_evidence_ids",[]) or [])
                and sum(cls._enum_value(cls._get(x,"evidence_type"))=="CLAUSE_ROW" for x in items)==1
                and not any(cls._enum_value(cls._get(x,"evidence_type"))=="SUBROW" for x in items))

    @staticmethod
    def _independent_match(item:RequirementEvidenceMatchResult)->bool:
        return item.evidence_scope=="INDIVIDUAL"

    @classmethod
    def _semantic_alignment(cls,left:Any,right:Any,item:Any=None)->Tuple[float,List[str]]:
        """Rank compatible row semantics without deciding compliance."""
        a=str(left or "");b=str(right or "");lexical=cls._distinctive_similarity(a,b)
        reasons=[];bonus=0.0
        av=cls._quantities(a);bv=cls._quantities(b)
        shared=set(av)&set(bv)
        a_parameters={unit for _,unit in av if unit!="time"};b_parameters={unit for _,unit in bv if unit!="time"}
        if a_parameters and b_parameters and a_parameters.isdisjoint(b_parameters):
            return 0.0,["PARAMETER_CONFLICT"]
        if shared:
            reasons.append("PARAMETER_VALUE_MATCH");bonus+=.25
            if any(unit=="time" for _,unit in shared):reasons.append("DURATION_MATCH");bonus+=.10
            if any(unit=="%" for _,unit in shared):reasons.append("PERCENTAGE_MATCH");bonus+=.10
        at=cls._table_refs(a);bt=cls._table_refs(b)
        if at and bt and at&bt:reasons.append("TABLE_REFERENCE_MATCH");bonus+=.15
        if at and bt and not at&bt:return 0.0,["TABLE_REFERENCE_CONFLICT"]
        aa=cls._test_actions(a);ba=cls._test_actions(b)
        if aa&ba:reasons.append("TEST_ACTION_MATCH");bonus+=.10
        if lexical>=.35:reasons.insert(0,"SUBJECT_MATCH")
        # Conflicting structured values for the same unit are a strong guard.
        common_units={unit for _,unit in av}&{unit for _,unit in bv}
        for unit in common_units:
            if {value for value,u in av if u==unit}.isdisjoint({value for value,u in bv if u==unit}):
                return 0.0,["STRUCTURED_VALUE_CONFLICT"]
        score=min(1.0,lexical+bonus)
        return score,reasons or ["NORMALIZED_SEMANTIC_MATCH"]

    @classmethod
    def _quantities(cls,text:Any)->Set[Tuple[str,str]]:
        normalized=str(text or "").casefold().replace("minutes","min").replace("minute","min").replace("seconds","s").replace("second","s")
        values=set()
        for value,unit in re.findall(r"(?<![a-z0-9.])(\d+(?:[.,]\d+)?)\s*(%|mm|cm|m|n|nm|v|a|w|hz|khz|min|ms|s|h)(?![a-z])",normalized,re.I):
            number=float(value.replace(",","."));unit=unit.casefold()
            if unit in {"ms","s","min","h"}:
                number*=({"ms":.001,"s":1,"min":60,"h":3600}[unit]);unit="time"
            rendered=str(int(number)) if number.is_integer() else str(number)
            values.add((rendered,unit))
        return values

    @staticmethod
    def _table_refs(text:Any)->Set[str]:
        return {x.casefold().strip(".-") for x in re.findall(r"\btable\s+([a-z0-9.-]+)",str(text or ""),re.I)}

    @staticmethod
    def _test_actions(text:Any)->Set[str]:
        action_map={"apply":"appl","applied":"appl","applying":"appl","measure":"meas","measured":"meas","measurement":"meas","inspect":"inspect","inspection":"inspect","withstand":"withstand","withstood":"withstand","viewed":"view","rubbing":"rub","rubbed":"rub","tested":"test","test":"test","operated":"operate","maintained":"maintain","checked":"check"}
        return {action_map[token] for token in re.findall(r"[a-z]+",str(text or "").casefold()) if token in action_map}

    def _multi_node_result(self,requirement:Any,nodes:Sequence[Any],status:RequirementEvidenceMatchStatus,
                           score:Optional[float],decision:Optional[str],effective_clause_id:Optional[str],notes:str
                           )->RequirementEvidenceMatchResult:
        rid=str(self._get(requirement,"effective_requirement_id")); clause=str(self._get(requirement,"clause_id"))
        ids=sorted({str(self._get(x,"clause_id")) for x in nodes})
        return RequirementEvidenceMatchResult(self._match_id(rid),rid,effective_clause_id,clause,
            self._enum_value(self._get(requirement,"effective_status")),decision,status,score,
            ids,[ref for node in nodes for ref in self._references(node,requirement)],ids,notes=notes)

    def _multi_node_presence(self,requirement:Any,nodes:Sequence[Any],decision:Optional[str],
                             effective_clause_id:Optional[str],notes:str)->RequirementEvidenceMatchResult:
        rid=str(self._get(requirement,"effective_requirement_id"));clause=str(self._get(requirement,"clause_id"));refs=[]
        for node in nodes:
            parents=[item for item in self._get(node,"evidence_items",[]) or []
                     if self._enum_value(self._get(item,"evidence_type"))=="CLAUSE_ROW"]
            refs.extend(ReportEvidenceReference(self._get(item,"evidence_id"),self._get(node,"clause_id"),
                self._get(node,"result_id"),"NOT_STATED",self._get(item,"page_start"),
                self._get(item,"page_end"),"CLAUSE_ROW",[],self._excerpt(self._get(item,"raw_text")),
                self._get(item,"source_order")) for item in parents)
        return RequirementEvidenceMatchResult(self._match_id(rid),rid,effective_clause_id,clause,
            self._enum_value(self._get(requirement,"effective_status")),decision,
            RequirementEvidenceMatchStatus.NEEDS_REVIEW,None,
            sorted({str(self._get(x,"clause_id")) for x in nodes}),refs,[],notes=notes,
            match_type="GROUP_EVIDENCE_PRESENCE",match_confidence="UNRESOLVED",
            match_reason=notes,evidence_scope="EVIDENCE_PRESENT_GROUPED")

    def _no_match(self,rid:str,clause:str,status:Optional[str],decision:Optional[str],
                  effective_clause_id:Optional[str],reason:str)->RequirementEvidenceMatchResult:
        return RequirementEvidenceMatchResult(self._match_id(rid),rid,effective_clause_id,clause,status,
            decision,RequirementEvidenceMatchStatus.NO_MATCH,None,[],[],[],reason)

    @classmethod
    def _references(cls,node:Any,requirement:Any=None)->List[ReportEvidenceReference]:
        items=cls._get(node,"evidence_items",[]) or []
        if not items:
            return [ReportEvidenceReference(None,cls._get(node,"clause_id"),cls._get(node,"result_id"),
                cls._enum_value(cls._get(node,"reported_verdict")),cls._get(node,"page_start"),
                cls._get(node,"page_end"),"CLAUSE_RESULT",
                cls._compatible_measurement_ids(requirement,cls._get(node,"measurements",[]) or []),
                cls._excerpt(cls._get(node,"raw_text")),cls._get(node,"source_order"))]
        return [ReportEvidenceReference(cls._get(item,"evidence_id"),cls._get(node,"clause_id"),
            cls._get(node,"result_id"),cls._enum_value(cls._get(item,"reported_verdict")),
            cls._get(item,"page_start"),cls._get(item,"page_end"),
            cls._enum_value(cls._get(item,"evidence_type")),
            cls._compatible_measurement_ids(requirement,cls._get(item,"measurements",[]) or []),
            cls._excerpt(cls._get(item,"raw_text")),cls._get(item,"source_order")) for item in items]

    @classmethod
    def _compatible_measurement_ids(cls,requirement:Any,measurements:Sequence[Any])->List[str]:
        """Expose only measurements compatible with an executable constraint."""
        if requirement is None:return [cls._get(m,"measurement_id") for m in measurements]
        if measurements and all(not (cls._get(m,"parameter") or cls._get(m,"parameter_text")
                                     or cls._get(m,"unit") or cls._get(m,"unit_normalized"))
                                for m in measurements):
            # Preserve legacy opaque measurement references; the evaluator
            # still refuses to compare values without parameter/unit data.
            return [cls._get(m,"measurement_id") for m in measurements]
        constraints=cls._get(requirement,"technical_constraints",[]) or []
        executable=[c for c in constraints if cls._get(c,"operator") and cls._get(c,"parameter")]
        if not executable:return []
        def norm(value):return re.sub(r"[^a-z0-9]+","_",str(value or "").casefold()).strip("_")
        unit_groups={
            "current":{"A","mA","µA"},"voltage":{"V","mV","kV"},
            "length":{"m","cm","mm"},"time":{"h","min","s","ms"},
            "temperature":{"°C"},"rise":{"K"},"force":{"N"},
            "resistance":{"MΩ","kΩ","Ω"},"energy":{"J","mJ"},
            "charge":{"C","µC"},"power":{"W","kW"},"percent":{"%"},
        }
        def dimension(unit):
            return next((key for key,values in unit_groups.items() if unit in values),unit)
        output=[]
        for measurement in measurements:
            mp=norm(cls._get(measurement,"parameter") or cls._get(measurement,"parameter_text"))
            mu=cls._get(measurement,"unit_normalized") or cls._get(measurement,"unit")
            for constraint in executable:
                cp=norm(cls._get(constraint,"parameter") or cls._get(constraint,"parameter_text"))
                cu=cls._get(constraint,"unit_normalized") or cls._get(constraint,"unit")
                if mp==cp and dimension(mu)==dimension(cu):
                    output.append(cls._get(measurement,"measurement_id"));break
        return output

    @classmethod
    def _evidence_verdicts(cls,node:Any)->Set[str]:
        refs=cls._references(node)
        return {r.reported_verdict for r in refs if r.reported_verdict not in {None,"NOT_STATED"}}

    @classmethod
    def _supports_aggregation(cls,node:Any)->bool:
        verdicts=cls._evidence_verdicts(node)
        has_stated_result=bool(verdicts-{"UNKNOWN"})
        structural=bool(cls._get(node,"children",[]) or re.search(
            r"\b(?:general|requirements|tests|classification)\b",
            str(cls._get(node,"title","") or ""),re.I))
        return has_stated_result and structural

    @classmethod
    def _nearest_parent(cls,clause:str,index:Mapping[str,Any])->Any:
        parts=clause.split(".")
        for size in range(len(parts)-1,0,-1):
            found=index.get(".".join(parts[:size]))
            if found:return found
        return None

    @staticmethod
    def _direct_child(parent:str,child:str)->bool:
        return child.startswith(parent+".") and child.count(".")==parent.count(".")+1

    @classmethod
    def _semantic_candidates(cls,requirement:Any,nodes:Iterable[Any])->List[Any]:
        text=str(cls._get(requirement,"text","") or "")
        scored=[(cls._distinctive_similarity(text,str(cls._get(node,"raw_text","") or "")),node) for node in nodes]
        return [node for score,node in scored if score>=.65]

    @classmethod
    def _clear_semantic_mismatch(cls, requirement: Any, node: Any) -> bool:
        """Detect only strong subject mismatch; short/generic text stays unresolved."""

        standard = cls._tokens(str(cls._get(requirement, "text", "") or ""))
        report = cls._tokens(str(cls._get(node, "raw_text", "") or ""))
        # Eight distinctive tokens on both sides provide enough subject signal.
        # Fewer tokens cannot safely establish a mismatch.
        if len(standard) < 8 or len(report) < 8:
            return False
        overlap = standard & report
        # Fewer than six shared subject tokens and less than one fifth of the
        # smaller vocabulary is a deliberately conjunctive, conservative gate.
        return len(overlap) < 6 and len(overlap) / min(len(standard), len(report)) < 0.20

    @classmethod
    def _explicit_cross_reference(cls, node: Any, clause: str) -> bool:
        raw = str(cls._get(node, "raw_text", "") or "")
        return bool(re.search(
            rf"\b(?:see|refer(?:red)?\s+to|in\s+accordance\s+with|according\s+to)"
            rf"(?:\s+(?:clause|subclause))?\s+{re.escape(clause)}\b",
            raw, re.IGNORECASE,
        ))

    @classmethod
    def _distinctive_similarity(cls,left:str,right:str)->float:
        a=cls._tokens(left); b=cls._tokens(right)
        if len(a)<4 or len(b)<4:return 0.0
        overlap=a&b
        return len(overlap)/len(a) if len(overlap)>=4 else 0.0

    @classmethod
    def _tokens(cls,text:str)->Set[str]:
        return {x for x in re.findall(r"[a-z0-9]+",text.casefold()) if len(x)>2 and x not in cls._STOP}

    @classmethod
    def _iter_requirements(cls,kb:Any)->Iterable[Tuple[Any,Optional[str],Optional[str]]]:
        def walk(items:Sequence[Any]):
            for clause in items:
                cid=cls._get(clause,"effective_clause_id")
                for requirement in cls._get(clause,"requirements",[]) or []:yield requirement,cid,None
                yield from walk(cls._get(clause,"children",[]) or [])
        yield from walk(cls._get(kb,"clauses",[]) or [])
        for annex in cls._get(kb,"annexes",[]) or []:
            aid=str(cls._get(annex,"annex_id")); container=cls._get(annex,"effective_annex_id")
            for requirement in cls._get(annex,"requirements",[]) or []:yield requirement,container,aid

    @classmethod
    def _flatten_report(cls,items:Sequence[Any])->List[Any]:
        output=[]
        for item in items:output.append(item);output.extend(cls._flatten_report(cls._get(item,"children",[]) or []))
        return output

    @classmethod
    def _report_annex_index(cls,report:Any)->Dict[str,Dict[str,Any]]:
        output={}
        for annex in cls._get(report,"annexes",[]) or []:
            aid=str(cls._get(annex,"annex_id")); nodes=cls._flatten_report(cls._get(annex,"clauses",[]) or [])
            output[aid]={str(cls._get(node,"clause_id")):node for node in nodes}
        return output

    def _diag(self,code:str,requirement_id:str,clause_id:Any)->None:
        self._diagnostics.append({"code":code,"effective_requirement_id":requirement_id,"clause_id":clause_id})

    @staticmethod
    def _get(value:Any,name:str,default:Any=None)->Any:
        return value.get(name,default) if isinstance(value,Mapping) else getattr(value,name,default)

    @staticmethod
    def _enum_value(value:Any)->Optional[str]:
        if value is None:return None
        return str(value.value if isinstance(value,Enum) else value)

    @staticmethod
    def _excerpt(value:Any)->Optional[str]:
        if value is None:return None
        return re.sub(r"\s+"," ",str(value)).strip()[:1000] or None

    @staticmethod
    def _match_id(requirement_id:str)->str:
        return "MATCH-"+quote(requirement_id,safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-")

    @classmethod
    def _safe(cls,value:Any)->Any:
        if isinstance(value,Enum):return value.value
        if isinstance(value,dict):return {k:cls._safe(v) for k,v in value.items()}
        if isinstance(value,list):return [cls._safe(v) for v in value]
        return value


__all__=["GenericRequirementEvidenceMatcher","ReportEvidenceReference",
         "RequirementEvidenceMatchReport","RequirementEvidenceMatchResult",
         "RequirementEvidenceMatchStatus"]
