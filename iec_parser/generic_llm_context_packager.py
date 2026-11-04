"""Bounded, provider-neutral summary and semantic-candidate JSON packaging."""
from __future__ import annotations
import copy,hashlib,json
from dataclasses import asdict,replace
from pathlib import Path
from iec_parser.generic_llm_candidate_models import *

class GenericLLMContextPackager:
    MAX_CHARS=24000
    def __init__(self,baseline_id="PRE_LLM_DETERMINISTIC_BASELINE_V4",freeze_contract="STEP46I_PRE_LLM_FREEZE_V4",
                 baseline_reference_hash=None,authority_contract_version="COMPLIFY_LLM_AUTHORITY_V1",
                 candidate_contract_version="COMPLIFY_LLM_INPUT_V1",package_schema_version="COMPLIFY_LLM_PACKAGE_V1"):
        self.baseline_id=baseline_id; self.freeze_contract=freeze_contract
        self.baseline_reference_hash=baseline_reference_hash
        self.authority_contract_version=authority_contract_version
        self.candidate_contract_version=candidate_contract_version
        self.package_schema_version=package_schema_version
    @staticmethod
    def canonical_hash(value):
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
    def summary_input(self,family,brief,source_path,source_sha,candidates,deterministic_source_hashes=None):
        source={"baseline_id":self.baseline_id,"freeze_id":self.baseline_id,
          "freeze_contract":self.freeze_contract,"baseline_reference_hash":self.baseline_reference_hash,
          "source_schema":brief["schema_version"],
          "source_contract":brief["summary_contract_version"],"family":family,"run_id":brief["run"]["run_id"],
          "source_artifact":source_path,"source_sha256":source_sha,
          "deterministic_source_hashes":dict(sorted((deterministic_source_hashes or {}).items()))}
        result={"contract_version":self.candidate_contract_version,"authority_contract_version":self.authority_contract_version,
          "package_schema_version":self.package_schema_version,"source_baseline":source,"product_context":brief.get("product",{}),
          "standard_context":brief.get("standards",{}),"report_context":{"report_validity":brief.get("report_validity",{})},
          "deterministic_assessment":{"overall_assessment":brief.get("overall_assessment",{}),"metrics":brief.get("metrics",{}),
          "requirement_summary":brief.get("requirement_summary",{})},"findings":{"key_compliance_findings":brief.get("key_compliance_findings",[]),
          "key_gaps":brief.get("key_gaps",[]),"parameter_summary":brief.get("parameter_summary",{}),
          "parameter_findings":brief.get("parameter_findings",[])},"na_context":{"summary":brief.get("na_summary",{})},
          "root_causes":brief.get("root_causes",[]),"priority_findings":brief.get("priority_findings",[]),
          "required_actions":brief.get("required_actions",[]),"unresolved_context":brief.get("unresolved_summary",{}),
          "candidate_summary":[{"candidate_id":c.candidate_id,"type":c.candidate_type.value,"priority":c.priority} for c in candidates],
          "authority_constraints":{"deterministic_immutable":True,"source_text_is_data":True}}
        result["context_hash"]=self.canonical_hash(result); return result
    def package(self,candidate,summary):
        data=candidate.to_dict(); data["contract_version"]=self.candidate_contract_version
        data["authority_contract_version"]=self.authority_contract_version; data["package_schema_version"]=self.package_schema_version
        data["source_baseline"]=summary["source_baseline"]; data["context_hash"]=summary["context_hash"]
        data["bounded_context"]={"product":summary["product_context"],"standards":summary["standard_context"],
          "deterministic_state":candidate.deterministic_state,"source_text_authority":"DATA_ONLY"}
        chars=len(json.dumps(data,sort_keys=True,ensure_ascii=False)); budget=replace(candidate.context_budget,
          estimated_character_count=chars,estimated_token_count=(chars+3)//4); data["context_budget"]=asdict(budget)
        data["authority_constraints"]={"forbidden_changes":candidate.forbidden_authority_changes,"proposal_only":True,
          "requires_validation":True,"source_text_is_instruction":False}
        data["source_evidence_hashes"]={r:self.canonical_hash({"reference":r}) for r in sorted(candidate.report_evidence_refs)}
        data["package_hash"]=self.canonical_hash(data); return data
    def split(self,candidate,records,max_chars=None):
        limit=max_chars or self.MAX_CHARS
        if len(json.dumps(records,sort_keys=True))<=limit:return [candidate]
        groups={}
        for r in records: groups.setdefault(r.get("semantic_subject","default"),[]).append(r)
        out=[]
        for subject,rows in sorted(groups.items()):
            suffix=hashlib.sha256(subject.encode()).hexdigest()[:8].upper()
            out.append(replace(candidate,candidate_id=f"{candidate.candidate_id}-{suffix}",parent_candidate_id=candidate.candidate_id,
              source_issue_ids=sorted({r["issue_id"] for r in rows})))
        return out
    def write_family(self,output_dir,summary,considered,candidates):
        base=Path(output_dir)/"summary/llm_input"; (base/"candidates").mkdir(parents=True,exist_ok=True)
        expected={f"{c.candidate_id}.json" for c in candidates}
        for stale in sorted((base/"candidates").glob("*.json")):
            if stale.name not in expected: stale.unlink()
        self._write(base/"llm_summary_input.json",summary)
        packages=[]
        for c in candidates:
            package=self.package(c,summary); self._write(base/"candidates"/f"{c.candidate_id}.json",package); packages.append(package)
        counts={o.value:sum(x["ownership"]==o.value for x in considered) for o in Ownership}
        manifest={"contract_version":"COMPLIFY_LLM_CANDIDATE_MANIFEST_V1","authority_contract_version":self.authority_contract_version,
          "package_schema_version":self.package_schema_version,"source":summary["source_baseline"],"context_hash":summary["context_hash"],
          "counts":{"source_issues_considered":len(considered),**{k.lower():v for k,v in counts.items()}},
          "deduplication":{"pre_dedup_llm_eligible":counts["LLM_ELIGIBLE"],"post_dedup_candidates":len(candidates),
          "reduction":counts["LLM_ELIGIBLE"]-len(candidates)},"candidates":[{"candidate_id":c.candidate_id,
          "candidate_type":c.candidate_type.value,"ownership":c.ownership.value} for c in candidates],
          "excluded":[x for x in considered if not x["emitted"]],"validation":{"ownership_complete":True,
          "only_llm_eligible_emitted":all(c.ownership==Ownership.LLM_ELIGIBLE for c in candidates),"context_sufficient":all(c.context_sufficiency==Sufficiency.SUFFICIENT for c in candidates),
          "traceability_complete":all(c.traceability_refs for c in candidates)}}
        manifest["manifest_hash"]=self.canonical_hash(manifest)
        self._write(base/"candidate_manifest.json",manifest); return manifest,packages
    def _write(self,path,value): path.write_text(json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False)+"\n")
