"""Build derived, condition-aware structural link candidates without changing upstream links."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple


class ConditionAwareLinkStatus(str, Enum):
    MATCHED = "MATCHED"
    POSSIBLE = "POSSIBLE"
    AMBIGUOUS = "AMBIGUOUS"
    REJECTED = "REJECTED"
    NO_CANDIDATE = "NO_CANDIDATE"


class ClauseRelation(str, Enum):
    EXACT = "EXACT"
    PARENT = "PARENT"
    CHILD = "CHILD"
    SIBLING = "SIBLING"
    ANNEX_EXACT = "ANNEX_EXACT"
    UNRELATED = "UNRELATED"


class ScopeRelation(str, Enum):
    EXACT_GROUP = "EXACT_GROUP"
    SELECTED_MULTIPLE_GROUP = "SELECTED_MULTIPLE_GROUP"
    WHOLE_CLAUSE = "WHOLE_CLAUSE"
    PARENT_SCOPE = "PARENT_SCOPE"
    AMBIGUOUS = "AMBIGUOUS"
    EXCLUDED = "EXCLUDED"
    NO_SCOPE = "NO_SCOPE"


@dataclass
class ConditionAwareStructureLinkCandidate:
    link_id: str
    standard_structure_id: str
    standard_step_id: str
    required_condition_ids: List[str]
    report_structure_id: str
    report_row_id: str
    actual_condition_ids: List[str]
    clause_id: Optional[str]
    group_id: Optional[str]
    standard_clause_id: Optional[str]
    report_clause_id: Optional[str]
    parameter_type: Optional[str]
    condition_role: Optional[str]
    clause_relation: ClauseRelation
    scope_relation: ScopeRelation
    parameter_alignment: bool
    role_alignment: bool
    provenance_alignment: bool
    text_alignment: float
    order_alignment: bool
    existing_structure_link_ids: List[str]
    candidate_status: ConditionAwareLinkStatus
    confidence: float
    reason_code: str
    reason: str
    diagnostics: List[str] = field(default_factory=list)


@dataclass
class ConditionOwnerLinkResult:
    condition_id: str
    side: str
    structure_id: Optional[str]
    owner_id: Optional[str]
    clause_id: Optional[str]
    group_ids: List[str]
    parameter_type: Optional[str]
    condition_role: Optional[str]
    candidate_link_ids: List[str]
    counterpart_owner_ids: List[str]
    counterpart_condition_ids: List[str]
    result: ConditionAwareLinkStatus
    reason: str


@dataclass
class ExistingStructureLinkReconciliation:
    existing_link_id: str
    existing_status: str
    condition_aware_link_ids: List[str]
    supported_by_condition_data: bool
    reason: str


@dataclass
class ConditionAwareStructureLinkReport:
    effective_kb_id: str
    report_document_id: str
    candidates: List[ConditionAwareStructureLinkCandidate] = field(default_factory=list)
    required_owner_results: List[ConditionOwnerLinkResult] = field(default_factory=list)
    actual_owner_results: List[ConditionOwnerLinkResult] = field(default_factory=list)
    existing_link_reconciliation: List[ExistingStructureLinkReconciliation] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)


class GenericConditionAwareStructureLinkResolver:
    """Resolve links using exact condition ownership plus upstream structural scope."""

    _BOILERPLATE = {"shall", "appliance", "appliances", "compliance", "test", "tested",
                    "checked", "requirement", "requirements", "with", "that", "this",
                    "from", "into", "parts", "part", "having", "have", "under"}
    _STATUS_RANK = {ConditionAwareLinkStatus.MATCHED: 5, ConditionAwareLinkStatus.POSSIBLE: 4,
                    ConditionAwareLinkStatus.AMBIGUOUS: 3, ConditionAwareLinkStatus.REJECTED: 2,
                    ConditionAwareLinkStatus.NO_CANDIDATE: 1}

    def resolve(self, effective_kb, grouping, report_evidence, evidence_scope,
                evidence_enrichment, test_structure, source_conditions,
                ownership_reconciliation, pair_result):
        required = list(self._get(source_conditions, "required_conditions", []) or [])
        actual = list(self._get(source_conditions, "actual_conditions", []) or [])
        standard_meta, report_meta = self._owner_metadata(test_structure)
        row_scopes = {self._s(self._get(x, "row_id")): x for x in self._get(test_structure, "row_scope_candidates", []) or []}
        existing = list(self._get(test_structure, "structure_links", []) or [])
        existing_pairs = defaultdict(list)
        for link in existing:
            for step in self._get(link, "standard_step_ids", []) or []:
                for row in self._get(link, "report_row_ids", []) or []:
                    existing_pairs[(self._s(step), self._s(row))].append(self._s(self._get(link, "link_id")))

        candidates = []
        for req in required:
            sm = standard_meta.get(self._s(self._get(req, "standard_step_id")))
            if not sm: continue
            for act in actual:
                rm = report_meta.get(self._s(self._get(act, "report_row_id")))
                if not rm: continue
                relation = self._clause_relation(sm["clause_id"], rm["clause_id"])
                if not self._safe_boundary(relation): continue
                candidates.append(self._candidate(req, act, sm, rm,
                                  row_scopes.get(rm["owner_id"]),
                                  existing_pairs.get((sm["owner_id"], rm["owner_id"]), [])))
        self._mark_competition(candidates)
        req_results = self._owner_results(required, candidates, "REQUIRED")
        act_results = self._owner_results(actual, candidates, "ACTUAL")
        reconciliation = []
        candidate_by_existing = defaultdict(list)
        for candidate in candidates:
            for link_id in candidate.existing_structure_link_ids: candidate_by_existing[link_id].append(candidate)
        for link in existing:
            link_id = self._s(self._get(link, "link_id")); found = candidate_by_existing.get(link_id, [])
            supported = any(x.candidate_status in {ConditionAwareLinkStatus.MATCHED,ConditionAwareLinkStatus.POSSIBLE} for x in found)
            reconciliation.append(ExistingStructureLinkReconciliation(link_id,
                self._s(self._get(link, "candidate_status")) or "", [x.link_id for x in found], supported,
                "Existing link has compatible condition-aware data." if supported else "Existing link has no compatible condition data."))

        diagnostics=[]
        for candidate in candidates:
            if candidate.candidate_status in {ConditionAwareLinkStatus.MATCHED,ConditionAwareLinkStatus.POSSIBLE}:
                diagnostics.append({"code":"CONDITION_AWARE_FULL_BRIDGE_CANDIDATE","link_id":candidate.link_id})
            if candidate.candidate_status == ConditionAwareLinkStatus.MATCHED:
                diagnostics.append({"code":"CONDITION_AWARE_COMPARABLE_BRIDGE","link_id":candidate.link_id})
        counts=Counter(x.candidate_status.value for x in candidates)
        new=[x for x in candidates if not x.existing_structure_link_ids and x.candidate_status in {ConditionAwareLinkStatus.MATCHED,ConditionAwareLinkStatus.POSSIBLE,ConditionAwareLinkStatus.AMBIGUOUS}]
        summary={
          "required_condition_owners":self._owner_summary(req_results),
          "actual_condition_owners":self._owner_summary(act_results),
          "new_links":{k:sum(x.candidate_status.value==k for x in new) for k in ("MATCHED","POSSIBLE","AMBIGUOUS")},
          "all_candidates":{x.value:counts[x.value] for x in ConditionAwareLinkStatus},
          "full_bridge_candidates":sum(x.candidate_status in {ConditionAwareLinkStatus.MATCHED,ConditionAwareLinkStatus.POSSIBLE} for x in candidates),
          "comparable_bridges":sum(x.candidate_status==ConditionAwareLinkStatus.MATCHED for x in candidates),
          "existing_structure_link_reconciliation":{
            "existing_links_supported_by_condition_data":sum(x.supported_by_condition_data for x in reconciliation),
            "existing_links_without_condition_data":sum(not x.supported_by_condition_data for x in reconciliation),
            "condition_aware_links_not_present_in_step_23a2":len(new)},
        }
        return ConditionAwareStructureLinkReport(
          self._s(self._get(effective_kb,"effective_kb_id")) or "",
          self._s(self._get(report_evidence,"document_id")) or "",
          sorted(candidates,key=lambda x:x.link_id),sorted(req_results,key=lambda x:x.condition_id),
          sorted(act_results,key=lambda x:x.condition_id),sorted(reconciliation,key=lambda x:x.existing_link_id),
          summary,sorted(diagnostics,key=lambda x:json.dumps(x,sort_keys=True)))

    def _candidate(self, req, act, sm, rm, row_scope, existing_ids):
        req_id=self._s(self._get(req,"condition_id"));act_id=self._s(self._get(act,"condition_id"))
        relation=self._clause_relation(sm["clause_id"],rm["clause_id"])
        group=self._s(self._get(req,"group_id"));scope=self._scope_relation(group,row_scope)
        rp=self._enum(self._get(req,"parameter_type"));ap=self._enum(self._get(act,"parameter_type"))
        rr=self._s(self._get(req,"condition_role"));ar=self._s(self._get(act,"condition_role"))
        parameter=bool(rp and rp==ap);role=bool(rr and rr==ar and rr.startswith("TEST_"))
        provenance=scope in {ScopeRelation.EXACT_GROUP,ScopeRelation.SELECTED_MULTIPLE_GROUP}
        text=self._text_alignment(sm["text"],rm["text"])
        order=sm["order"]==rm["order"] if sm["order"] is not None and rm["order"] is not None else False
        diagnostics=[]
        if not parameter:diagnostics.append("PARAMETER_MISMATCH")
        if not role:diagnostics.append("ROLE_MISMATCH")
        if scope==ScopeRelation.EXCLUDED:diagnostics.append("GROUP_EXCLUDED")
        if relation==ClauseRelation.UNRELATED:diagnostics.append("CLAUSE_UNRELATED")
        safe_scope=scope in {ScopeRelation.EXACT_GROUP,ScopeRelation.SELECTED_MULTIPLE_GROUP,ScopeRelation.WHOLE_CLAUSE}
        if not parameter or not role or scope==ScopeRelation.EXCLUDED or not self._safe_boundary(relation):
            status=ConditionAwareLinkStatus.REJECTED;code="CONDITION_AWARE_REJECTED";reason="Hard semantic, scope, or clause gate failed."
        elif scope==ScopeRelation.AMBIGUOUS:
            status=ConditionAwareLinkStatus.AMBIGUOUS;code="CONDITION_AWARE_AMBIGUOUS";reason="Compatible semantics exist, but report scope remains ambiguous."
        elif safe_scope and relation in {ClauseRelation.EXACT,ClauseRelation.ANNEX_EXACT}:
            status=ConditionAwareLinkStatus.MATCHED;code="CONDITION_AWARE_MATCHED";reason="Exact owners, compatible semantics, allowed clause, and safe upstream scope all align."
        else:
            status=ConditionAwareLinkStatus.POSSIBLE;code="CONDITION_AWARE_POSSIBLE";reason="Semantics and clause are plausible, but scope or provenance support is incomplete."
        confidence=round((.24*parameter+.24*role+.22*safe_scope+.14*(relation in {ClauseRelation.EXACT,ClauseRelation.ANNEX_EXACT})+.1*provenance+.06*text),6)
        link_id="CA-LINK-"+hashlib.sha256("\x1f".join([sm["owner_id"],rm["owner_id"],req_id,act_id]).encode()).hexdigest()[:18].upper()
        return ConditionAwareStructureLinkCandidate(link_id,sm["structure_id"],sm["owner_id"],[req_id],rm["structure_id"],rm["owner_id"],[act_id],sm["clause_id"],group,sm["clause_id"],rm["clause_id"],rp,rr,relation,scope,parameter,role,provenance,text,order,sorted(existing_ids),status,confidence,code,reason,diagnostics)

    def _mark_competition(self,candidates):
        by_req=defaultdict(list);by_act=defaultdict(list)
        for x in candidates:
            if x.candidate_status==ConditionAwareLinkStatus.MATCHED:
                by_req[x.required_condition_ids[0]].append(x);by_act[x.actual_condition_ids[0]].append(x)
        ambiguous={id(x) for pool in list(by_req.values())+list(by_act.values()) if len(pool)>1 for x in pool}
        for x in candidates:
            if id(x) in ambiguous:
                x.candidate_status=ConditionAwareLinkStatus.AMBIGUOUS;x.reason_code="CONDITION_AWARE_COMPETING_CANDIDATES";x.reason="Multiple structurally indistinguishable condition-owning counterparts remain.";x.diagnostics.append("COMPETING_CANDIDATE")

    def _owner_results(self,conditions,candidates,side):
        field="required_condition_ids" if side=="REQUIRED" else "actual_condition_ids"
        owner="standard_step_id" if side=="REQUIRED" else "report_row_id"
        structure="standard_structure_id" if side=="REQUIRED" else "report_structure_id"
        out=[]
        for c in conditions:
            cid=self._s(self._get(c,"condition_id"));pool=[x for x in candidates if cid in getattr(x,field)]
            if pool:
                best=max(pool,key=lambda x:(self._STATUS_RANK[x.candidate_status],x.confidence))
                result=best.candidate_status;reason=best.reason
            else:result=ConditionAwareLinkStatus.NO_CANDIDATE;reason="No condition-owning counterpart exists within a safe structural boundary."
            counterparts=sorted({x.report_row_id if side=="REQUIRED" else x.standard_step_id for x in pool})
            counterpart_conditions=sorted({y for x in pool for y in (x.actual_condition_ids if side=="REQUIRED" else x.required_condition_ids)})
            groups=[self._s(self._get(c,"group_id"))] if side=="REQUIRED" else [self._s(x) for x in self._get(c,"group_ids",[]) or []]
            out.append(ConditionOwnerLinkResult(cid,side,self._s(self._get(c,structure)),self._s(self._get(c,owner)),self._s(self._get(c,"clause_id")),[x for x in groups if x],self._enum(self._get(c,"parameter_type")),self._s(self._get(c,"condition_role")),sorted(x.link_id for x in pool),counterparts,counterpart_conditions,result,reason))
        return out

    @classmethod
    def _owner_summary(cls,items):
        counts=Counter(x.result.value for x in items);with_candidate=sum(bool(x.candidate_link_ids) for x in items)
        return {"total":len(items),"with_candidate_link":with_candidate,"without_candidate_link":len(items)-with_candidate,**{x.value:counts[x.value] for x in ConditionAwareLinkStatus}}

    @classmethod
    def _owner_metadata(cls,test_structure):
        standard={};report={}
        for structure in cls._get(test_structure,"standard_test_structures",[]) or []:
            for step in cls._get(structure,"test_method_steps",[]) or []:
                oid=cls._s(cls._get(step,"step_id"));standard[oid]={"owner_id":oid,"structure_id":cls._s(cls._get(structure,"structure_id")),"clause_id":cls._s(cls._get(structure,"clause_id")),"group_id":cls._s(cls._get(structure,"group_id")),"text":cls._s(cls._get(step,"text")) or "","order":cls._get(step,"step_order")}
        for structure in cls._get(test_structure,"report_clause_structures",[]) or []:
            for row in cls._get(structure,"rows",[]) or []:
                oid=cls._s(cls._get(row,"row_id"));report[oid]={"owner_id":oid,"structure_id":cls._s(cls._get(structure,"structure_id")),"clause_id":cls._s(cls._get(structure,"report_clause_id")),"text":cls._s(cls._get(row,"raw_text")) or "","order":cls._get(row,"row_order")}
        return standard,report

    @staticmethod
    def _scope_relation(group,row_scope):
        if not row_scope:return ScopeRelation.NO_SCOPE
        outer=GenericConditionAwareStructureLinkResolver._s(GenericConditionAwareStructureLinkResolver._get(row_scope,"outer_scope_status"))
        narrowed={GenericConditionAwareStructureLinkResolver._s(x) for x in GenericConditionAwareStructureLinkResolver._get(row_scope,"narrowed_group_ids",[]) or []}
        candidates={GenericConditionAwareStructureLinkResolver._s(x) for x in GenericConditionAwareStructureLinkResolver._get(row_scope,"candidate_group_ids",[]) or []}
        if outer in {"NO_RELEVANT_GROUP","EXCLUDED"}:return ScopeRelation.EXCLUDED
        if group and group in narrowed:
            return ScopeRelation.EXACT_GROUP if outer=="EXACT_GROUP" else ScopeRelation.SELECTED_MULTIPLE_GROUP
        if outer=="WHOLE_CLAUSE" and (not candidates or group in candidates):return ScopeRelation.WHOLE_CLAUSE
        if outer=="AMBIGUOUS":return ScopeRelation.AMBIGUOUS
        if group and (group in candidates or group in narrowed):return ScopeRelation.PARENT_SCOPE
        if candidates and group not in candidates:return ScopeRelation.EXCLUDED
        return ScopeRelation.NO_SCOPE

    @staticmethod
    def _clause_relation(a,b):
        if not a or not b:return ClauseRelation.UNRELATED
        annex=lambda x:not bool(re.match(r"^\d",x))
        if a==b:return ClauseRelation.ANNEX_EXACT if annex(a) else ClauseRelation.EXACT
        if annex(a)!=annex(b):return ClauseRelation.UNRELATED
        if b.startswith(a+"."):return ClauseRelation.PARENT
        if a.startswith(b+"."):return ClauseRelation.CHILD
        if "." in a and "." in b and a.rsplit(".",1)[0]==b.rsplit(".",1)[0]:return ClauseRelation.SIBLING
        return ClauseRelation.UNRELATED

    @staticmethod
    def _safe_boundary(relation):return relation in {ClauseRelation.EXACT,ClauseRelation.ANNEX_EXACT}

    @classmethod
    def _text_alignment(cls,a,b):
        tokens=lambda x:{t for t in re.findall(r"[a-z0-9]+",str(x).casefold()) if len(t)>2 and t not in cls._BOILERPLATE}
        aa,bb=tokens(a),tokens(b);return round(len(aa&bb)/max(1,len(aa|bb)),6)

    @staticmethod
    def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
    @staticmethod
    def _s(v):return None if v is None else str(v.value if isinstance(v,Enum) else v)
    _enum=_s
    @classmethod
    def _plain(cls,v):
        if isinstance(v,Enum):return v.value
        if is_dataclass(v):return cls._plain(asdict(v))
        if isinstance(v,dict):return {k:cls._plain(x) for k,x in v.items()}
        if isinstance(v,list):return [cls._plain(x) for x in v]
        return v
    @classmethod
    def to_dict(cls,v):
        if not is_dataclass(v):raise TypeError("condition-aware structure link report required")
        return cls._plain(asdict(v))
    @classmethod
    def to_json(cls,v,indent=2):return json.dumps(cls.to_dict(v),ensure_ascii=False,sort_keys=True,indent=indent)
    @classmethod
    def save_json(cls,v,path):
        p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(cls.to_json(v)+"\n",encoding="utf-8");return p


__all__=["ClauseRelation","ConditionAwareLinkStatus","ConditionAwareStructureLinkCandidate","ConditionAwareStructureLinkReport","ConditionOwnerLinkResult","ExistingStructureLinkReconciliation","GenericConditionAwareStructureLinkResolver","ScopeRelation"]
