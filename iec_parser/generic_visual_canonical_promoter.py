"""Atomic, feature-flagged materialization of already-eligible reconciled evidence."""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from .generic_visual_canonical_promotion_models import CanonicalVisualEvidenceRecord,VisualPromotionResult
from .generic_visual_canonical_target_registry import GenericVisualCanonicalTargetRegistry
class GenericVisualCanonicalPromoter:
 SCHEMA_VERSION="REPORT_VISUAL_EVIDENCE_PROMOTION_V1"
 def __init__(self,*,canonical_visual_promotion_enabled=False,registry=None):self.enabled=canonical_visual_promotion_enabled;self.registry=registry or GenericVisualCanonicalTargetRegistry()
 def promote(self,reconciliation,*,existing_canonical=None,expected_report_hash=None):
  data,source_hash=self._load(reconciliation);existing=list(existing_canonical or []);working=list(existing);records=[];created=[];report_hash=data.get("source_lineage",{}).get("report_hash")
  for rec in sorted(data.get("reconciliations",[]),key=lambda x:x.get("reconciliation_id","")):
   v=rec.get("visual_candidate",{});decision=rec.get("promotion",{});blockers=list(decision.get("promotion_blockers",[]));status="BLOCKED";reason="UPSTREAM_NOT_ELIGIBLE";target=None
   if decision.get("promotion_eligible"):
    target=self.registry.resolve(v.get("candidate_type"));structural=self._validate(data,rec,target,expected_report_hash)
    if not self.enabled:structural.append("FEATURE_DISABLED")
    if structural:status="REJECTED" if self.enabled else "BLOCKED";reason=structural[0];blockers=sorted(set(blockers+structural))
    else:
     canonical=self._canonical_record(report_hash,rec,target);equivalent=next((x for x in working if self._same_key(x,canonical) and self._equivalent(x,canonical)),None);conflict=next((x for x in working if self._same_key(x,canonical) and not self._equivalent(x,canonical)),None)
     if equivalent:status="NO_OP_EQUIVALENT";reason="EXISTING_CANONICAL_EQUIVALENT"
     elif conflict:status="REJECTED";reason="CANONICAL_CONFLICT";blockers.append(reason)
     else:status="PROMOTED";reason="ALL_GOVERNED_GATES_PASSED";working.append(canonical);created.append(canonical)
   records.append(self._record(rec,target,status,reason,blockers))
  summary={"candidates_considered":len(records),"eligible":sum(r.get("promotion_eligible",False) for r in records),"promoted":sum(r["promotion_status"]=="PROMOTED" for r in records),"rejected":sum(r["promotion_status"]=="REJECTED" for r in records),"blocked":sum(r["promotion_status"]=="BLOCKED" for r in records),"no_op_existing_equivalent":sum(r["promotion_status"]=="NO_OP_EQUIVALENT" for r in records),"canonical_changes":len(created)}
  return VisualPromotionResult(self.SCHEMA_VERSION,"CANONICAL_VISUAL_EVIDENCE",data.get("schema_version"),source_hash,report_hash,self.enabled,summary,records,created)
 def _validate(self,data,rec,target,expected):
  v=rec.get("visual_candidate",{});line=rec.get("lineage",{});bad=[]
  if not target:bad.append("UNSUPPORTED_TARGET")
  if not v.get("candidate_id") or line.get("visual_candidate_id")!=v.get("candidate_id"):bad.append("INVALID_CANDIDATE_LINEAGE")
  if expected and line.get("report_hash")!=expected:bad.append("CROSS_REPORT_LINEAGE")
  if line.get("report_hash")!=data.get("source_lineage",{}).get("report_hash") or not line.get("visual_extraction_hash"):bad.append("INVALID_LINEAGE")
  if v.get("normalized_value") in (None,""):bad.append("MISSING_NORMALIZED_VALUE")
  if v.get("scope") in (None,"UNKNOWN"):bad.append("INSUFFICIENT_SCOPE")
  if target and target["role_required"] and v.get("role") in (None,"UNKNOWN"):bad.append("UNKNOWN_PARAMETER_ROLE")
  if target and (v.get("canonical_unit") or None) not in target["units"]:bad.append("MALFORMED_UNIT")
  if v.get("polarity") in (None,"UNKNOWN"):bad.append("UNKNOWN_POLARITY")
  if v.get("page") is None or v.get("bbox") is None or not line.get("visual_region_id"):bad.append("INCOMPLETE_PROVENANCE")
  if rec.get("reconciliation_status") in ("CONFLICT","VISUAL_LOW_CONFIDENCE"):bad.append("UNSAFE_RECONCILIATION_STATUS")
  if rec.get("source_relationship")=="SAME_SOURCE":bad.append("SAME_SOURCE_DUPLICATION")
  if v.get("candidate_type")=="model_identifier" and not re.search(r"\b(?:model|type|mod)\b",v.get("source_text") or "",re.I):bad.append("MODEL_CONTEXT_REQUIRED")
  return bad
 def _canonical_record(self,report_hash,rec,target):
  v=rec["visual_candidate"];seed=json.dumps([report_hash,v["candidate_id"],target["target"],v["scope"],v.get("role")],sort_keys=True);eid="CVE-"+hashlib.sha256(seed.encode()).hexdigest()[:24].upper()
  return CanonicalVisualEvidenceRecord(eid,v["candidate_type"],target["target"],v["normalized_value"],v.get("canonical_unit"),v["polarity"],v.get("role","UNKNOWN"),v["scope"],"VISUAL_PROMOTED","CANONICAL_VISUAL_EVIDENCE",{"report_hash":report_hash,"promotion_source":rec["reconciliation_id"],**rec["lineage"]})
 def _record(self,rec,target,status,reason,blockers):
  v=rec.get("visual_candidate",{});pid="PROMOTION-"+hashlib.sha256((rec.get("reconciliation_id","")+"|"+v.get("candidate_id","")).encode()).hexdigest()[:24].upper()
  return {"promotion_id":pid,"visual_candidate_id":v.get("candidate_id"),"reconciliation_id":rec.get("reconciliation_id"),"candidate_type":v.get("candidate_type"),"canonical_target":target and target["target"],"raw_visual_value":v.get("raw_value"),"normalized_value":v.get("normalized_value"),"canonical_value":v.get("normalized_value"),"unit":v.get("canonical_unit"),"polarity":v.get("polarity"),"parameter_role":v.get("role"),"scope":v.get("scope"),"source_region_id":rec.get("lineage",{}).get("visual_region_id"),"page":v.get("page"),"bbox":v.get("bbox"),"extraction_confidence":v.get("confidence"),"source_authority":v.get("authority"),"promotion_eligible":rec.get("promotion",{}).get("promotion_eligible",False),"promotion_status":status,"promotion_reason":reason,"promotion_blockers":sorted(set(blockers)),"existing_canonical_match":status=="NO_OP_EQUIVALENT","source_lineage":rec.get("lineage",{}),"target_lineage":{"authority":"CANONICAL_VISUAL_EVIDENCE"} if status=="PROMOTED" else None}
 @staticmethod
 def _same_key(x,y):return x.canonical_target==y.canonical_target and x.scope==y.scope and x.parameter_role==y.parameter_role
 @staticmethod
 def _equivalent(x,y):return x.canonical_value==y.canonical_value and x.unit==y.unit and x.polarity==y.polarity
 @staticmethod
 def _load(value):
  if isinstance(value,(str,Path)):raw=Path(value).read_bytes();return json.loads(raw),hashlib.sha256(raw).hexdigest()
  canonical=dict(value);canonical["reconciliations"]=sorted(value.get("reconciliations",[]),key=lambda x:x.get("reconciliation_id",""))
  raw=json.dumps(canonical,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode();return value,hashlib.sha256(raw).hexdigest()
 @staticmethod
 def save_json(result,path):Path(path).write_text(result.to_json(indent=2)+"\n")
