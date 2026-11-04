"""Generic deterministic issue ownership, stable IDs, and semantic deduplication."""
from __future__ import annotations
import hashlib,json
from collections import defaultdict
from typing import Any,Dict,List
from iec_parser.generic_llm_candidate_models import *

class GenericLLMCandidateSelector:
    ACTION_OWNER={"PROVIDE_PRODUCT_INFORMATION":Ownership.CLIENT_EVIDENCE_REQUIRED,
      "LAB_CLARIFICATION":Ownership.LAB_CLARIFICATION_REQUIRED,"PROVIDE_EVIDENCE":Ownership.LAB_CLARIFICATION_REQUIRED,
      "PROVIDE_NA_JUSTIFICATION":Ownership.LAB_CLARIFICATION_REQUIRED,"TECHNICAL_REVIEW":Ownership.TECHNICAL_REVIEW_REQUIRED}
    FORBIDDEN=["technical_result","parameter_authority","na_state","metrics","report_validity","final_disposition",
               "canonical_classification","deterministic_applicability"]
    def stable_id(self,family,kind,subject):
        raw="|".join([family,kind,subject]).casefold().encode(); return "LLM-CAND-"+hashlib.sha256(raw).hexdigest()[:20].upper()
    def classify_gap(self,gap):
        action=(gap.get("required_action") or {}).get("type")
        return self.ACTION_OWNER.get(action,Ownership.TECHNICAL_REVIEW_REQUIRED)
    def select(self,family,brief,semantic_seeds=None,limitations=None):
        considered=[]
        for gap in brief.get("key_gaps",[]):
            owner=self.classify_gap(gap); issue_id=gap.get("root_cause_id") or self.stable_id(family,"gap",gap.get("finding",''))
            considered.append({"issue_id":issue_id,"ownership":owner.value,"reason":gap.get("finding"),"emitted":False,
              "exclusion_reason":self.exclusion(owner),"requirement_ids":[],"clause_ids":gap.get("representative_clauses",[])})
        for finding in brief.get("key_compliance_findings",[]):
            considered.append({"issue_id":finding.get("traceability",{}).get("requirement_id"),"ownership":Ownership.DETERMINISTIC_RESOLVED.value,
              "reason":"Existing deterministic compliance result","emitted":False,"exclusion_reason":"DETERMINISTICALLY_RESOLVED",
              "requirement_ids":[finding.get("traceability",{}).get("requirement_id")],"clause_ids":[finding.get("clause")]})
        for lim in limitations or []:
            considered.append({"issue_id":lim["limitation_id"],"ownership":Ownership.NON_BLOCKING_LIMITATION.value,
              "reason":lim.get("description"),"emitted":False,"exclusion_reason":"NON_BLOCKING","requirement_ids":[],"clause_ids":[]})
        pre=[]
        for seed in semantic_seeds or []:
            refs=seed.get("source_evidence_refs") or []
            if not refs:
                considered.append({"issue_id":seed["candidate_id"],"ownership":Ownership.TECHNICAL_REVIEW_REQUIRED.value,
                  "reason":"Semantic seed lacks traceability","emitted":False,"exclusion_reason":"INSUFFICIENT_TRACEABILITY",
                  "requirement_ids":[],"clause_ids":[]}); continue
            subject=seed["unresolved_question"].strip().casefold(); key=f"{seed['candidate_type']}|{subject}"
            candidate=CandidateRecord(self.stable_id(family,seed["candidate_type"],subject),CandidateType.REQUIREMENT_EVIDENCE_RELATIONSHIP,
              Ownership.LLM_ELIGIBLE,[seed["candidate_id"]],[],[],seed["unresolved_question"],
              {"state":seed.get("current_deterministic_state")},["product"],["standards"],list(refs),[],[],[],list(refs),
              ["deterministic_unresolved","semantic_interpretation_primary","source_context_exists","bounded_proposal"],
              list(self.FORBIDDEN),True,key,"P3",ContextBudget(1,0,0,len(refs),1,0,len(refs),0,0),Sufficiency.SUFFICIENT)
            pre.append(candidate); considered.append({"issue_id":seed["candidate_id"],"ownership":Ownership.LLM_ELIGIBLE.value,
              "reason":seed["unresolved_question"],"emitted":True,"exclusion_reason":None,"requirement_ids":[],"clause_ids":[]})
        return considered,self.deduplicate(pre)
    def deduplicate(self,candidates):
        groups=defaultdict(list)
        for c in candidates: groups[c.deduplication_key].append(c)
        out=[]
        for key,items in sorted(groups.items()):
            first=items[0]
            merge=lambda attr:sorted({x for item in items for x in getattr(item,attr) if x})
            out.append(CandidateRecord(first.candidate_id,first.candidate_type,first.ownership,merge("source_issue_ids"),
              merge("requirement_ids"),merge("clause_ids"),first.question,first.deterministic_state,merge("product_context_refs"),
              merge("standard_context_refs"),merge("report_evidence_refs"),merge("parameter_refs"),merge("na_refs"),
              merge("root_cause_refs"),merge("traceability_refs"),first.why_llm_eligible,first.forbidden_authority_changes,True,key,
              first.priority,first.context_budget,first.context_sufficiency))
        return out
    def exclusion(self,owner):
        return {Ownership.DETERMINISTIC_RESOLVED:"DETERMINISTICALLY_RESOLVED",Ownership.CLIENT_EVIDENCE_REQUIRED:"MISSING_CLIENT_EVIDENCE",
          Ownership.LAB_CLARIFICATION_REQUIRED:"MISSING_LAB_EVIDENCE",Ownership.TECHNICAL_REVIEW_REQUIRED:"TECHNICAL_REVIEW_REQUIRED",
          Ownership.M3_REQUIRED:"M3_ONLY",Ownership.NON_BLOCKING_LIMITATION:"NON_BLOCKING"}.get(owner)
