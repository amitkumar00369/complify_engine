"""Causal impact ledger; deterministic consumers remain externally owned."""
from __future__ import annotations
import json
from pathlib import Path
class GenericVisualPromotionImpactBuilder:
 def build(self,promotion,*,before=None,reevaluator=None):
  p=promotion.to_dict() if hasattr(promotion,"to_dict") else promotion;changes=p["summary"]["canonical_changes"]
  if not changes:return {"schema_version":"REPORT_VISUAL_PROMOTION_IMPACT_V1","re_evaluation_status":"NOT_REQUIRED_NO_CANONICAL_CHANGE","direct_promotion_effects":[],"derived_deterministic_effects":[],"summary":self._zero()}
  derived=reevaluator(p["canonical_evidence"],before) if reevaluator else []
  return {"schema_version":"REPORT_VISUAL_PROMOTION_IMPACT_V1","re_evaluation_status":"EXECUTED" if reevaluator else "REVIEW_REQUIRED_NO_REEVALUATOR","direct_promotion_effects":[{"canonical_evidence_id":x["evidence_id"],"cause":x["lineage"]} for x in p["canonical_evidence"]],"derived_deterministic_effects":derived,"summary":self._counts(derived,changes)}
 def _zero(self):return {k:0 for k in ("canonical_facts_changed","applicability_changes","na_changes","evidence_changes","parameter_ledger_changes","technical_changes","root_cause_changes","score_changes","final_disposition_changes")}
 def _counts(self,d,c):
  z=self._zero();z["canonical_facts_changed"]=c
  for x in d:
   key=x.get("change_type");field={"APPLICABILITY":"applicability_changes","NA":"na_changes","EVIDENCE":"evidence_changes","PARAMETER":"parameter_ledger_changes","TECHNICAL":"technical_changes","ROOT_CAUSE":"root_cause_changes","SCORE":"score_changes","DISPOSITION":"final_disposition_changes"}.get(key)
   if field:z[field]+=1
  return z
 @staticmethod
 def save_json(data,path):Path(path).write_text(json.dumps(data,indent=2,sort_keys=True)+"\n")
