"""Generic deterministic reconciliation of existing native and Step 46-L evidence."""

from __future__ import annotations

import hashlib,json,re
from pathlib import Path
from typing import Any,Dict,List,Optional,Tuple

from .generic_visual_evidence_promotion_policy import GenericVisualEvidencePromotionPolicy
from .generic_visual_evidence_reconciliation_models import (CandidateReference,ComparisonRelationship,
 EvidenceReconciliationRecord,ReconciliationStatus,SourceRelationship,VisualEvidenceReconciliationResult)


class GenericVisualEvidenceReconciler:
    SCHEMA_VERSION="REPORT_VISUAL_EVIDENCE_RECONCILIATION_V1"
    POLICY_VERSION="STEP46M_RECONCILIATION_POLICY_V1"
    TYPE_MAP={"rated_voltage":"rated_voltage","rated_frequency":"rated_frequency","rated_power_input":"rated_power_input","rated_current":"rated_current","ip_rating":"ip_rating","has_plug":"has_plug"}
    def __init__(self,*,promotion_policy=None):self.promotion_policy=promotion_policy or GenericVisualEvidencePromotionPolicy()
    def reconcile(self,visual_extraction,native_profile,*,native_evidence=None,run_id=None):
        visual,visual_hash=self._load(visual_extraction);profile,native_hash=self._load(native_profile)
        if visual.get("schema_version")!="REPORT_VISUAL_EVIDENCE_EXTRACTION_V1":raise ValueError("Invalid visual extraction schema")
        report_hash=visual.get("source_inventory",{}).get("report_hash")
        if not report_hash:raise ValueError("Missing visual report lineage")
        index=self._native_index(profile);records=[];comparisons=0
        region_ids={r.get("region_id") for r in visual.get("regions",[])}
        for region in visual.get("regions",[]):
            if region.get("extraction_status") not in ("SUCCESS","LOW_CONFIDENCE"):continue
            for raw in region.get("structured_candidates",[]):
                if raw.get("source_region_id") not in region_ids:raise ValueError("Invalid visual candidate region reference")
                candidate=self._visual_ref(raw,region);native=index.get(candidate.candidate_type,[]);comparisons+=len(native)
                relationship,status,confidence=self._relationship(candidate,native,region)
                source=self._source_relationship(candidate,native)
                if source is SourceRelationship.SAME_SOURCE and status is ReconciliationStatus.AGREEMENT:status=ReconciliationStatus.DUPLICATE
                if region.get("extraction_status")=="LOW_CONFIDENCE":status=ReconciliationStatus.VISUAL_LOW_CONFIDENCE
                elif candidate.scope=="UNKNOWN" and status in {ReconciliationStatus.UNMATCHED_VISUAL,ReconciliationStatus.VISUAL_SUPPLEMENTS_NATIVE}:status=ReconciliationStatus.INSUFFICIENT_SCOPE
                promotion=self.promotion_policy.evaluate(candidate,status,True,status is ReconciliationStatus.CONFLICT)
                rid=self._id(report_hash,candidate.candidate_id,[x.candidate_id for x in native],candidate.candidate_type)
                blockers=list(promotion.promotion_blockers)
                records.append(EvidenceReconciliationRecord(rid,candidate.candidate_type,candidate,native,relationship,source,status,confidence,"HIGH" if status is ReconciliationStatus.CONFLICT else None,promotion,blockers,{"report_hash":report_hash,"visual_candidate_id":candidate.candidate_id,"visual_region_id":raw.get("source_region_id"),"visual_extraction_hash":visual_hash,"native_evidence_hash":native_hash}))
        records.sort(key=lambda x:(x.visual_candidate.page or 0,x.visual_candidate.bbox or [],x.reconciliation_id))
        summary=self._summary(records,len(index),comparisons)
        promotions=[{"candidate_id":r.visual_candidate.candidate_id,"promotion_eligible":r.promotion.promotion_eligible,"promotion_target":r.promotion.promotion_target,"promotion_blockers":r.promotion.promotion_blockers,"simulation_only":True} for r in records]
        return VisualEvidenceReconciliationResult(self.SCHEMA_VERSION,run_id or visual.get("run_id") or "RECONCILIATION",{"report_hash":report_hash,"visual_inventory_hash":visual.get("source_inventory",{}).get("inventory_hash"),"visual_extraction_hash":visual_hash,"native_evidence_hash":native_hash,"reconciliation_policy_version":self.POLICY_VERSION,"promotion_policy_version":self.promotion_policy.POLICY_VERSION},summary,records,promotions)
    def _native_index(self,profile):
        index={}
        for key,fact in sorted((profile.get("facts") or {}).items()):
            kind=next((visual for visual,native in self.TYPE_MAP.items() if native==key),None)
            if not kind:continue
            evidence=fact.get("evidence") or [];first=evidence[0] if evidence else {}
            value=fact.get("normalized_value",fact.get("value"));unit=fact.get("unit")
            normalized,canonical=self._canonical(value,unit)
            polarity="NEGATIVE" if value is False else "POSITIVE" if value is not None else "UNKNOWN"
            ref=CandidateReference(str(first.get("evidence_id") or "NATIVE-"+key),kind,value,normalized,unit,canonical,polarity,"PRODUCT_FAMILY","DECLARED" if kind.startswith("rated_") else "UNKNOWN",fact.get("confidence"),"NATIVE_REPORT_EVIDENCE","report/product_profile.json",first.get("page"),None,first.get("raw_text"))
            index.setdefault(kind,[]).append(ref)
        return index
    def _visual_ref(self,raw,region):
        value=raw.get("normalized_value");unit=raw.get("unit");normalized,canonical=self._canonical(value,unit)
        category=region.get("inventory_category")
        role="DECLARED" if raw.get("candidate_type","").startswith("rated_") and category in ("NAMEPLATE","MARKING_LABEL") else "UNKNOWN"
        return CandidateReference(raw["candidate_id"],raw["candidate_type"],raw.get("raw_value"),normalized,unit,canonical,raw.get("polarity","UNKNOWN"),raw.get("scope","UNKNOWN"),role,raw.get("extraction_confidence"),raw.get("authority","EXTRACTED_VISUAL_EVIDENCE"),"report/report_visual_evidence_extraction.json",raw.get("source_page"),raw.get("source_bbox"),raw.get("source_text"))
    def _relationship(self,visual,natives,region):
        if not natives:return ComparisonRelationship.NOT_COMPARABLE,ReconciliationStatus.VISUAL_SUPPLEMENTS_NATIVE,.7
        comparisons=[self.compare(visual,n) for n in natives]
        compatible=(ComparisonRelationship.EXACT_MATCH,ComparisonRelationship.EQUIVALENT_UNIT,
            ComparisonRelationship.RANGE_EQUAL,ComparisonRelationship.SYMBOLIC_EQUIVALENT,
            ComparisonRelationship.MEMBER_OF_NATIVE_SET,ComparisonRelationship.NATIVE_MEMBER_OF_VISUAL_SET,
            ComparisonRelationship.SET_EQUAL,ComparisonRelationship.WITHIN_RANGE,ComparisonRelationship.CONTAINS_RANGE)
        best=next((x for x in comparisons if x in compatible),comparisons[0])
        roles_compatible=all(n.role==visual.role or "UNKNOWN" in (n.role,visual.role) for n in natives)
        scopes_compatible=all(n.scope==visual.scope or "UNKNOWN" in (n.scope,visual.scope) for n in natives)
        polarities_comparable=all("UNKNOWN" not in (n.polarity,visual.polarity) for n in natives)
        polarities_equal=polarities_comparable and all(n.polarity==visual.polarity for n in natives)
        if best in (ComparisonRelationship.EXACT_MATCH,ComparisonRelationship.EQUIVALENT_UNIT,
            ComparisonRelationship.RANGE_EQUAL,ComparisonRelationship.SYMBOLIC_EQUIVALENT,ComparisonRelationship.SET_EQUAL) and polarities_equal:
            return best,ReconciliationStatus.AGREEMENT,.95
        if best in compatible and polarities_equal:return best,ReconciliationStatus.NATIVE_SUPPLEMENTS_VISUAL,.85
        actual_disagreement=best in (ComparisonRelationship.DISJOINT,ComparisonRelationship.SET_DISJOINT)
        polarity_disagreement=polarities_comparable and any(n.polarity!=visual.polarity for n in natives)
        if roles_compatible and scopes_compatible and (actual_disagreement or polarity_disagreement):return best,ReconciliationStatus.CONFLICT,.95
        if best is ComparisonRelationship.INSUFFICIENT_INFORMATION:return best,ReconciliationStatus.REVIEW_REQUIRED,.4
        return best,ReconciliationStatus.REVIEW_REQUIRED,.5
    def compare(self,a,b):
        if a.normalized_value is None or b.normalized_value is None:return ComparisonRelationship.INSUFFICIENT_INFORMATION
        if a.canonical_unit!=b.canonical_unit:return ComparisonRelationship.NOT_COMPARABLE
        av,bv=a.normalized_value,b.normalized_value
        symbolic=self._symbolic(a.candidate_type,av,bv)
        if symbolic is not None:return symbolic
        aset,bset=self._members(av),self._members(bv)
        if aset is not None or bset is not None:
            if aset is None:
                return ComparisonRelationship.MEMBER_OF_NATIVE_SET if any(self._compatible_value(av,x) for x in bset) else ComparisonRelationship.SET_DISJOINT
            if bset is None:
                return ComparisonRelationship.NATIVE_MEMBER_OF_VISUAL_SET if any(self._compatible_value(x,bv) for x in aset) else ComparisonRelationship.SET_DISJOINT
            hits=sum(any(self._compatible_value(x,y) for y in bset) for x in aset)
            if hits==len(aset)==len(bset):return ComparisonRelationship.SET_EQUAL
            return ComparisonRelationship.SET_OVERLAP if hits else ComparisonRelationship.SET_DISJOINT
        if av==bv and not isinstance(av,list):return ComparisonRelationship.EXACT_MATCH if a.raw_unit==b.raw_unit else ComparisonRelationship.EQUIVALENT_UNIT
        ar=self._range(av);br=self._range(bv)
        if ar and br:
            if ar[1]<br[0] or br[1]<ar[0]:return ComparisonRelationship.DISJOINT
            if ar==br:return ComparisonRelationship.RANGE_EQUAL
            if br[0]<=ar[0] and ar[1]<=br[1]:return ComparisonRelationship.WITHIN_RANGE
            if ar[0]<=br[0] and br[1]<=ar[1]:return ComparisonRelationship.CONTAINS_RANGE
            return ComparisonRelationship.RANGE_OVERLAP
        if av==bv:return ComparisonRelationship.EXACT_MATCH if a.raw_unit==b.raw_unit else ComparisonRelationship.EQUIVALENT_UNIT
        return ComparisonRelationship.DISJOINT
    @staticmethod
    def _members(value):
        if isinstance(value,dict) and value.get("representation")=="MULTI_STATE":return value.get("values",[])
        return None
    def _compatible_value(self,a,b):
        av,_=self._canonical(a,a.get("unit") if isinstance(a,dict) else None);bv,_=self._canonical(b,b.get("unit") if isinstance(b,dict) else None)
        if av==bv:return True
        ar=self._range(av);br=self._range(bv)
        return bool(ar and br and br[0]<=ar[0] and ar[1]<=br[1])
    @staticmethod
    def _symbolic(candidate_type,a,b):
        if candidate_type=="ip_rating" and isinstance(a,str) and isinstance(b,str):
            aa,bb=a.upper(),b.upper()
            return ComparisonRelationship.SYMBOLIC_EQUIVALENT if aa==bb else ComparisonRelationship.DISJOINT
        return None
    @staticmethod
    def _canonical(value,unit):
        u=(unit or "").upper();factor=1;canonical=unit
        if u=="KW":factor=1000;canonical="W"
        elif u=="W":canonical="W"
        elif u=="MA":factor=.001;canonical="A"
        elif u=="A":canonical="A"
        elif u in ("V","HZ","C"):canonical=u
        elif not u:canonical=None
        def number(x):
            try:return float(str(x).replace(",","."))*factor
            except:return x
        if isinstance(value,dict):
            if "min" in value and "max" in value:return [number(value["min"]),number(value["max"])],canonical or value.get("unit")
            if "value" in value:return number(value["value"]),canonical or value.get("unit")
        text=str(value)
        match=re.fullmatch(r"\s*([-+]?\d+(?:[.,]\d+)?)\s*(?:[-–]|to)\s*([-+]?\d+(?:[.,]\d+)?)\s*",text,re.I)
        return ([number(match.group(1)),number(match.group(2))] if match else number(value)),canonical
    @staticmethod
    def _range(value):
        if isinstance(value,list) and len(value)==2 and all(isinstance(x,(int,float)) for x in value):return min(value),max(value)
        if isinstance(value,(int,float)):return value,value
        return None
    @staticmethod
    def _source_relationship(visual,natives):
        pages={n.page for n in natives if n.page is not None}
        if visual.page in pages:return SourceRelationship.SAME_SOURCE
        if pages and visual.page is not None:return SourceRelationship.INDEPENDENT_SOURCE
        return SourceRelationship.UNKNOWN
    def _id(self,report_hash,visual_id,native_ids,kind):return "RECONCILIATION-"+hashlib.sha256(json.dumps({"report":report_hash,"visual":visual_id,"native":sorted(native_ids),"type":kind,"policy":self.POLICY_VERSION},sort_keys=True,separators=(",",":")).encode()).hexdigest()[:24].upper()
    @staticmethod
    def _load(value):
        if isinstance(value,(str,Path)):raw=Path(value).read_bytes();return json.loads(raw),hashlib.sha256(raw).hexdigest()
        raw=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode();return value,hashlib.sha256(raw).hexdigest()
    @staticmethod
    def _summary(records,native_types,comparisons):
        count=lambda s:sum(r.reconciliation_status is s for r in records)
        return {"visual_candidates":len(records),"native_candidate_types_indexed":native_types,"comparisons_performed":comparisons,"matched_pairs":sum(bool(r.native_candidates) for r in records),"agreements":count(ReconciliationStatus.AGREEMENT),"visual_supplements":count(ReconciliationStatus.VISUAL_SUPPLEMENTS_NATIVE),"native_supplements":count(ReconciliationStatus.NATIVE_SUPPLEMENTS_VISUAL),"conflicts":count(ReconciliationStatus.CONFLICT),"duplicates":count(ReconciliationStatus.DUPLICATE),"low_confidence":count(ReconciliationStatus.VISUAL_LOW_CONFIDENCE),"insufficient_scope":count(ReconciliationStatus.INSUFFICIENT_SCOPE),"review_required":count(ReconciliationStatus.REVIEW_REQUIRED),"promotion_eligible":sum(r.promotion.promotion_eligible for r in records),"promotion_blocked":sum(not r.promotion.promotion_eligible for r in records)}
    @staticmethod
    def save_json(result,path):Path(path).write_text(result.to_json(indent=2)+"\n",encoding="utf-8")
