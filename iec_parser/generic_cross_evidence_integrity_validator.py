"""Generic integrity checks over structured compliance-pipeline artifacts only."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


class IntegrityFindingType(str, Enum):
    CROSS_EVIDENCE_CONFLICT="CROSS_EVIDENCE_CONFLICT"; PRODUCT_RATING_CONFLICT="PRODUCT_RATING_CONFLICT"
    TEST_CONDITION_MISMATCH="TEST_CONDITION_MISMATCH"; TECHNICAL_LIMIT_VIOLATION="TECHNICAL_LIMIT_VIOLATION"
    CALCULATION_MISMATCH="CALCULATION_MISMATCH"; UNIT_MISMATCH="UNIT_MISMATCH"
    SAMPLE_IDENTITY_CONFLICT="SAMPLE_IDENTITY_CONFLICT"; REPORT_INTERNAL_CONTRADICTION="REPORT_INTERNAL_CONTRADICTION"
    REQUIREMENT_EVIDENCE_CONTRADICTION="REQUIREMENT_EVIDENCE_CONTRADICTION"; PASS_WITH_CONTRADICTORY_EVIDENCE="PASS_WITH_CONTRADICTORY_EVIDENCE"
    PASS_WITH_INVALID_TEST_CONDITION="PASS_WITH_INVALID_TEST_CONDITION"; PASS_WITH_TECHNICAL_VIOLATION="PASS_WITH_TECHNICAL_VIOLATION"
    FAIL_WITH_CONTRADICTORY_EVIDENCE="FAIL_WITH_CONTRADICTORY_EVIDENCE"; TEST_METHOD_INCOMPLETE="TEST_METHOD_INCOMPLETE"
    TEST_PARAMETER_MISSING="TEST_PARAMETER_MISSING"; MEASUREMENT_MISSING="MEASUREMENT_MISSING"
    EVIDENCE_SCOPE_CONFLICT="EVIDENCE_SCOPE_CONFLICT"; UNRESOLVED_CONTRADICTION="UNRESOLVED_CONTRADICTION"


class IntegrityFindingStatus(str, Enum):
    CONFIRMED="CONFIRMED"; PROBABLE="PROBABLE"; POSSIBLE="POSSIBLE"; INSUFFICIENT_DATA="INSUFFICIENT_DATA"; NEEDS_REVIEW="NEEDS_REVIEW"


class IntegritySeverity(str, Enum):
    CRITICAL="CRITICAL"; HIGH="HIGH"; MEDIUM="MEDIUM"; LOW="LOW"; INFORMATIONAL="INFORMATIONAL"


@dataclass
class IntegrityFinding:
    finding_id: str
    finding_type: IntegrityFindingType
    status: IntegrityFindingStatus
    severity: IntegritySeverity
    namespace: str
    clause_id: Optional[str] = None
    requirement_ids: List[str] = field(default_factory=list)
    group_ids: List[str] = field(default_factory=list)
    parameter: Optional[str] = None
    expected: Dict[str, Any] = field(default_factory=dict)
    observed: Dict[str, Any] = field(default_factory=dict)
    source_evidence_refs: List[str] = field(default_factory=list)
    product_fact_refs: List[str] = field(default_factory=list)
    technical_constraint_refs: List[str] = field(default_factory=list)
    reason_code: str = ""
    reason: str = ""
    confidence: float = 0.0


@dataclass
class CrossEvidenceIntegrityResult:
    schema_version: str
    result_id: str
    effective_kb_id: str
    profile_id: str
    report_document_id: str
    findings: List[IntegrityFinding] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    zero_inflation: Dict[str, Any] = field(default_factory=dict)
    notes: Optional[str] = None


class GenericCrossEvidenceIntegrityValidator:
    """Detect contradictions without altering or reinterpreting upstream decisions."""

    _UNIT={
        "V":("voltage",1.0,"V"),"mV":("voltage",.001,"V"),"kV":("voltage",1000.0,"V"),
        "A":("current",1.0,"A"),"mA":("current",.001,"A"),"W":("power",1.0,"W"),"kW":("power",1000.0,"W"),
        "Hz":("frequency",1.0,"Hz"),"kHz":("frequency",1000.0,"Hz"),"s":("time",1.0,"s"),"min":("time",60.0,"s"),
        "mm":("length",1.0,"mm"),"cm":("length",10.0,"mm"),"m":("length",1000.0,"mm"),
    }
    _PARAMETER_ALIASES={
        "rated voltage or rated voltage range in volts":"rated_voltage", "rated voltage":"rated_voltage",
        "rated frequency":"rated_frequency", "frequency is marked":"rated_frequency",
        "rated power input":"rated_power_input", "rated power input in watts or rated current in amperes":"rated_power_input",
        "model number":"model_number", "model":"model_number", "type reference":"type_reference",
        "serial number":"serial_number", "sample identifier":"sample_identifier", "sample id":"sample_identifier",
        "test voltage":"test_voltage",
    }
    _IDENTITY_KEYS={"model_number","type_reference","serial_number","sample_identifier","brand","product_designation"}
    _RELIABLE_SCOPE={"EXACT_GROUP","WHOLE_CLAUSE","MULTIPLE_GROUPS","PARENT_SCOPE","CHILD_SCOPE"}

    def validate(self, effective_kb: Any, product_profile: Any, group_applicability: Any,
                 report_evidence: Any, evidence_match: Any, technical_result: Any,
                 grouping: Any, evidence_scope: Any, na_validation: Any,
                 final_decision: Any, evidence_enrichment: Any = None) -> CrossEvidenceIntegrityResult:
        diagnostics: List[Dict[str,Any]]=[]; findings: List[IntegrityFinding]=[]
        groups=self._requirement_groups(grouping,final_decision); scopes=self._scope_index(evidence_scope)
        verdicts=self._verdict_index(scopes); measurements,evidence_items=self._report_content(report_evidence)
        findings.extend(self._value_findings(product_profile,measurements,diagnostics))
        findings.extend(self._calculation_findings(evidence_items,diagnostics))
        findings.extend(self._technical_findings(technical_result,groups,verdicts,diagnostics))
        findings.extend(self._scope_findings(scopes,diagnostics))
        if not self._identity_values(product_profile,"serial_numbers") and not self._identity_values(product_profile,"sample_identifiers"):
            diagnostics.append({"code":"INTEGRITY_MISSING_SAMPLE_IDENTIFIER","reason":"No structured serial number or sample identifier is available."})
        if evidence_enrichment is not None:
            enriched, enriched_diagnostics = self._enrichment_findings(evidence_enrichment, scopes)
            findings.extend(enriched);diagnostics.extend(enriched_diagnostics)
            resolved_constraints={str(self._get(x,"technical_constraint_id")) for x in self._get(evidence_enrichment,"required_test_conditions",[]) or [] if self._enum(self._get(x,"status"))=="RESOLVED"}
            diagnostics=[x for x in diagnostics if not (x.get("code")=="INTEGRITY_MISSING_EXPECTED_TEST_CONDITION" and str(x.get("constraint_id")) in resolved_constraints)]
            diagnostic_keys=("code","requirement_id","constraint_id","evidence_id","pair_id","calculation_id")
            diagnostics=list({tuple(str(x.get(k,"")) for k in diagnostic_keys):x for x in diagnostics}.values())
        findings=self._deduplicate(findings)
        effective_id=str(self._get(final_decision,"effective_kb_id",self._get(effective_kb,"effective_kb_id","")) or "")
        profile_id=str(self._get(final_decision,"profile_id",self._get(product_profile,"profile_id","")) or "")
        report_id=str(self._get(final_decision,"report_document_id",self._get(report_evidence,"document_id","")) or "")
        identity=json.dumps([effective_id,profile_id,report_id,[x.finding_id for x in findings]],separators=(",",":"))
        result=CrossEvidenceIntegrityResult("1.0","INTEGRITY-"+hashlib.sha256(identity.encode()).hexdigest()[:20].upper(),effective_id,profile_id,report_id,findings,diagnostics=sorted(diagnostics,key=lambda x:(x.get("code",""),json.dumps(x,sort_keys=True))))
        result.summary=self._summary(findings);result.zero_inflation=self._inflation(findings)
        result.notes="Integrity findings preserve reported verdicts and do not rewrite upstream decisions."
        return result

    def _enrichment_findings(self,enrichment:Any,scopes:Sequence[Any])->Tuple[List[IntegrityFinding],List[Dict[str,Any]]]:
        """Consume derived structures without promoting uncertain links."""
        out=[];diagnostics=[];required={str(self._get(x,"condition_id")):x for x in self._get(enrichment,"required_test_conditions",[]) or []};actual={str(self._get(x,"condition_id")):x for x in self._get(enrichment,"actual_test_conditions",[]) or []};facts={str(self._get(x,"fact_id")):x for x in self._get(enrichment,"facts",[]) or []};verdict={str(self._get(x,"report_evidence_id")):self._enum(self._get(x,"reported_verdict")) for x in scopes}
        for pair in self._get(enrichment,"condition_pairs",[]) or []:
            status=self._enum(self._get(pair,"link_status"));rid=str(self._get(pair,"required_condition_id"));aid=str(self._get(pair,"actual_condition_id","") or "");r=required.get(rid);a=actual.get(aid)
            if status=="NO_MATCH" or not r or not a:continue
            clause=self._get(r,"clause_id");reqid=str(self._get(r,"effective_requirement_id","") or "");gid=str(self._get(r,"group_id","") or "");evidence_id=str(self._get(a,"report_evidence_id","") or "");expected=self._condition_snapshot(r,"expected");observed=self._condition_snapshot(a,"observed");common=dict(ns="ENRICHED_CONDITION",clause=clause,requirements=[reqid] if reqid else [],groups=[gid] if gid else [],param=self._enum(self._get(r,"parameter_type")),expected=expected,observed=observed,evidence=[evidence_id] if evidence_id else [],product=[],constraints=[str(self._get(r,"technical_constraint_id"))] if self._get(r,"technical_constraint_id") else [])
            if status in {"POSSIBLE","AMBIGUOUS"}:
                finding_status=IntegrityFindingStatus.INSUFFICIENT_DATA if status=="POSSIBLE" else IntegrityFindingStatus.NEEDS_REVIEW
                out.append(self._finding(IntegrityFindingType.UNRESOLVED_CONTRADICTION,finding_status,IntegritySeverity.MEDIUM,**common,code="INTEGRITY_CONDITION_PAIR_NOT_CONFIRMED",reason=f"{status} enriched condition pair is not eligible for deterministic comparison.",confidence=.5 if status=="POSSIBLE" else .35));diagnostics.append({"code":"INTEGRITY_CONDITION_PAIR_NOT_CONFIRMED","pair_id":self._get(pair,"pair_id"),"link_status":status});continue
            equal,reason=self._condition_equal(r,a)
            if equal is None:diagnostics.append({"code":"INTEGRITY_ENRICHED_CONDITION_INCOMPARABLE","pair_id":self._get(pair,"pair_id"),"reason":reason});continue
            if equal:continue
            out.append(self._finding(IntegrityFindingType.TEST_CONDITION_MISMATCH,IntegrityFindingStatus.CONFIRMED,IntegritySeverity.HIGH,**common,code="INTEGRITY_MATCHED_TEST_CONDITION_MISMATCH",reason="A uniquely MATCHED enriched condition has unequal compatible expected and actual values.",confidence=1.0))
            if verdict.get(evidence_id)=="PASS":out.append(self._finding(IntegrityFindingType.PASS_WITH_INVALID_TEST_CONDITION,IntegrityFindingStatus.CONFIRMED,IntegritySeverity.HIGH,**{**common,"ns":"PASS_INTEGRITY","observed":{**observed,"reported_verdict":"PASS"}},code="INTEGRITY_PASS_WITH_INVALID_TEST_CONDITION",reason="Reliably scoped PASS evidence has a confirmed MATCHED test-condition mismatch.",confidence=1.0))
        for calc in self._get(enrichment,"calculations",[]) or []:
            if not self._get(calc,"recomputable",False):continue
            reported=self._get(self._get(calc,"reported_result",{}),"value");recalculated=self._get(calc,"recalculated_result");tolerance=self._get(calc,"tolerance",0)
            try:difference=abs(float(reported)-float(recalculated));epsilon=float(tolerance or 0)+1e-9
            except (TypeError,ValueError):diagnostics.append({"code":"INTEGRITY_ENRICHED_CALCULATION_INCOMPARABLE","calculation_id":self._get(calc,"calculation_id")});continue
            if difference>epsilon:out.append(self._finding(IntegrityFindingType.CALCULATION_MISMATCH,IntegrityFindingStatus.CONFIRMED,IntegritySeverity.HIGH,"ENRICHED_CALCULATION",self._get(calc,"clause_id"),[],list(self._get(calc,"group_ids",[]) or []),self._enum(self._get(calc,"parameter_type")),{"recalculated_result":recalculated,"representation_epsilon":1e-9},{"reported_result":reported,"difference":difference},[str(self._get(calc,"report_evidence_id"))],[],[],"INTEGRITY_ENRICHED_CALCULATION_MISMATCH","Safely recomputable enriched calculation differs from its reported result.",1.0))
            else:diagnostics.append({"code":"INTEGRITY_ENRICHED_CALCULATION_VERIFIED","calculation_id":self._get(calc,"calculation_id"),"difference":difference})
        for comparison in self._get(enrichment,"comparison_sets",[]) or []:
            if not self._get(comparison,"comparable",False):continue
            members=[facts[x] for x in self._get(comparison,"facts",[]) or [] if x in facts];reliable=[x for x in members if self._enum(self._get(x,"status"))=="RESOLVED"]
            for i,left in enumerate(reliable):
                for right in reliable[i+1:]:
                    if self._enum(self._get(left,"parameter_role"))!=self._enum(self._get(right,"parameter_role")):continue
                    left_raw={self._get(p,"raw_excerpt") for p in self._get(left,"provenance",[]) or [] if self._get(p,"raw_excerpt")};right_raw={self._get(p,"raw_excerpt") for p in self._get(right,"provenance",[]) or [] if self._get(p,"raw_excerpt")}
                    if left_raw and left_raw==right_raw:continue
                    equal,code,e,o=self._equivalent(self._get(left,"normalized_value",{}),self._get(right,"normalized_value",{}))
                    if code or equal:continue
                    role=self._enum(self._get(left,"parameter_role"));ft=IntegrityFindingType.PRODUCT_RATING_CONFLICT if role in {"PRODUCT_RATING","SAMPLE_RATING"} else IntegrityFindingType.CROSS_EVIDENCE_CONFLICT
                    refs=sorted({str(self._get(p,"source_id")) for x in (left,right) for p in self._get(x,"provenance",[]) or [] if self._get(p,"source_id")});out.append(self._finding(ft,IntegrityFindingStatus.CONFIRMED,IntegritySeverity.HIGH,"ENRICHED_COMPARISON",None,[],[],self._enum(self._get(left,"parameter_type")),e,o,refs,[],[],"INTEGRITY_ENRICHED_COMPARISON_CONFLICT","Reliable facts in one comparable semantic set differ.",.98))
        if not any(self._enum(self._get(x,"identifier_type")) in {"SERIAL_NUMBER","SAMPLE_IDENTIFIER"} for x in self._get(enrichment,"sample_identity_evidence",[]) or []):diagnostics.append({"code":"INTEGRITY_MISSING_SAMPLE_IDENTIFIER","reason":"Enriched evidence contains no serial number or distinct sample identifier."})
        return out,diagnostics

    @classmethod
    def _condition_snapshot(cls,item:Any,prefix:str)->Dict[str,Any]:
        value=cls._get(item,prefix+"_value") or {};expression=cls._get(item,prefix+"_expression")
        return {"condition_id":cls._get(item,"condition_id"),"role":cls._get(item,"condition_role"),"value":copy.deepcopy(cls._get(value,"value")),"unit":cls._get(value,"unit_normalized") or cls._get(value,"unit"),"expression":copy.deepcopy(expression)}
    @classmethod
    def _condition_equal(cls,required:Any,actual:Any)->Tuple[Optional[bool],str]:
        rv=cls._get(required,"expected_value");av=cls._get(actual,"observed_value")
        if rv and av and cls._get(rv,"value") is not None and cls._get(av,"value") is not None:
            equal,code,_,_=cls._equivalent(rv,av);return (None,code) if code else (equal,"VALUE_COMPARISON")
        rexp=cls._get(required,"expected_expression");aexp=cls._get(actual,"observed_expression")
        if not rexp or not aexp:return None,"MISSING_COMPARABLE_VALUE_OR_EXPRESSION"
        if cls._enum(cls._get(rexp,"expression_type"))!=cls._enum(cls._get(aexp,"expression_type")):return None,"EXPRESSION_TYPE_INCOMPATIBLE"
        return None,"FORMULA_VARIABLE_EVALUATION_UNAVAILABLE"

    def _technical_findings(self,technical:Any,groups:Mapping[str,List[str]],verdicts:Mapping[str,List[Dict[str,Any]]],diagnostics:List[Dict[str,Any]])->List[IntegrityFinding]:
        out=[]
        for item in self._get(technical,"results",[]) or []:
            decision=self._enum(self._get(item,"decision")); app=self._enum(self._get(item,"applicability_decision")); rid=str(self._get(item,"effective_requirement_id","") or ""); gids=groups.get(rid,[]); clause=self._get(item,"clause_id"); constraint=self._get(item,"constraint",{}) or {}; cid=str(self._get(item,"constraint_id","") or ""); param=self._parameter(self._get(constraint,"parameter") or self._get(constraint,"parameter_text")); scoped_pass=self._scoped_verdicts(gids,str(clause or ""),verdicts,"PASS")
            refs=sorted({str(self._get(m,"measurement_id")) for m in self._get(item,"matched_measurements",[]) or [] if self._get(m,"measurement_id")})
            expected={"operator":self._get(constraint,"operator"),"value":copy.deepcopy(self._get(constraint,"value")),"value_secondary":copy.deepcopy(self._get(constraint,"value_secondary")),"unit":self._get(constraint,"unit_normalized") or self._get(constraint,"unit")}
            observed={"decision":decision,"computed_limit":copy.deepcopy(self._get(item,"computed_limit")),"comparison_details":copy.deepcopy(self._get(item,"comparison_details"))}
            if decision=="VIOLATES":
                out.append(self._finding(IntegrityFindingType.TECHNICAL_LIMIT_VIOLATION,IntegrityFindingStatus.CONFIRMED,IntegritySeverity.HIGH,"TECHNICAL_CONSTRAINT",clause,[rid],gids,param,expected,observed,refs,[],[cid],"INTEGRITY_TECHNICAL_LIMIT_VIOLATION","Step 18 reports a resolved technical violation.",1.0))
                if scoped_pass:out.append(self._finding(IntegrityFindingType.PASS_WITH_TECHNICAL_VIOLATION,IntegrityFindingStatus.CONFIRMED,IntegritySeverity.HIGH,"PASS_INTEGRITY",clause,[rid],gids,param,expected,{**observed,"reported_verdict":"PASS"},sorted(set(refs+scoped_pass)),[],[cid],"INTEGRITY_PASS_WITH_TECHNICAL_VIOLATION","Reliably scoped PASS evidence coexists with a confirmed Step 18 violation.",1.0))
            elif decision=="NO_MEASUREMENT" and app=="APPLICABLE":
                ftype=IntegrityFindingType.TEST_PARAMETER_MISSING if self._enum(self._get(constraint,"constraint_type"))=="TEST_PARAMETER" else IntegrityFindingType.MEASUREMENT_MISSING
                out.append(self._finding(ftype,IntegrityFindingStatus.INSUFFICIENT_DATA,IntegritySeverity.MEDIUM,"TECHNICAL_CONSTRAINT",clause,[rid],gids,param,expected,observed,refs,[],[cid],"INTEGRITY_MISSING_MEASUREMENT","An applicable technical constraint has no reliable observed measurement.",1.0))
                diagnostics.append({"code":"INTEGRITY_MISSING_MEASUREMENT","requirement_id":rid,"constraint_id":cid})
                if scoped_pass:out.append(self._finding(IntegrityFindingType.TEST_METHOD_INCOMPLETE,IntegrityFindingStatus.INSUFFICIENT_DATA,IntegritySeverity.MEDIUM,"PASS_INTEGRITY",clause,[rid],gids,param,expected,{"reported_verdict":"PASS"},scoped_pass,[],[cid],"INTEGRITY_PASS_WITH_MISSING_MEASUREMENT","PASS is preserved, but a required technical measurement is unavailable.",.9))
            elif decision=="VIOLATES" and self._enum(self._get(constraint,"constraint_type"))=="TEST_PARAMETER":
                pass
            elif decision in {"INCOMPARABLE","UNKNOWN","NEEDS_REVIEW"}:
                diagnostics.append({"code":"INTEGRITY_MISSING_PARAMETER_SEMANTICS" if decision=="INCOMPARABLE" else "INTEGRITY_MISSING_EXPECTED_TEST_CONDITION","requirement_id":rid,"constraint_id":cid,"upstream_decision":decision})
            if decision=="VIOLATES" and self._enum(self._get(constraint,"constraint_type"))=="TEST_PARAMETER":
                out.append(self._finding(IntegrityFindingType.TEST_CONDITION_MISMATCH,IntegrityFindingStatus.CONFIRMED,IntegritySeverity.HIGH,"TEST_CONDITION",clause,[rid],gids,param,expected,observed,refs,[],[cid],"INTEGRITY_TEST_CONDITION_MISMATCH","Step 18 confirms that the reported test parameter differs from the required condition.",1.0))
                if scoped_pass:out.append(self._finding(IntegrityFindingType.PASS_WITH_INVALID_TEST_CONDITION,IntegrityFindingStatus.CONFIRMED,IntegritySeverity.HIGH,"PASS_INTEGRITY",clause,[rid],gids,param,expected,{**observed,"reported_verdict":"PASS"},sorted(set(refs+scoped_pass)),[],[cid],"INTEGRITY_PASS_WITH_INVALID_TEST_CONDITION","Reliably scoped PASS evidence used a confirmed invalid test condition.",1.0))
        return out

    def _value_findings(self,profile:Any,measurements:Sequence[Dict[str,Any]],diagnostics:List[Dict[str,Any]])->List[IntegrityFinding]:
        out=[]; facts=self._get(profile,"facts",{}) or {}; profile_values={}
        for key,fact in facts.items():
            if self._enum(self._get(fact,"status")) not in {"CONFIRMED","INFERRED_STRONG"}:continue
            profile_values[self._parameter(key)]=(self._get(fact,"value"),[str(self._get(e,"evidence_id")) for e in self._get(fact,"evidence",[]) or [] if self._get(e,"evidence_id")])
        seen=defaultdict(list)
        for m in measurements:
            param=self._parameter(self._get(m,"parameter") or self._get(m,"parameter_text"));
            if not param:diagnostics.append({"code":"INTEGRITY_MISSING_PARAMETER_SEMANTICS","measurement_id":self._get(m,"measurement_id")});continue
            seen[param].append(m)
            if param not in profile_values:continue
            expected,product_refs=profile_values[param]; equal,code,e,o=self._equivalent(expected,m)
            if code:diagnostics.append({"code":code,"parameter":param,"measurement_id":self._get(m,"measurement_id")});continue
            if not equal:out.append(self._finding(IntegrityFindingType.PRODUCT_RATING_CONFLICT,IntegrityFindingStatus.CONFIRMED,IntegritySeverity.HIGH,"PRODUCT_REPORT",self._get(m,"clause_id"),[],[],param,e,o,[str(self._get(m,"measurement_id"))],product_refs,[],"INTEGRITY_PRODUCT_RATING_CONFLICT","Confirmed product fact conflicts with a semantically equivalent report measurement.",.98))
        for param,items in seen.items():
            if len(items)<2:continue
            base=items[0]
            for other in items[1:]:
                # Multiple numbers extracted from one formula/text fragment are
                # not independent assertions and therefore cannot contradict.
                if self._get(base,"raw_text") and self._get(base,"raw_text")==self._get(other,"raw_text"):continue
                equal,code,e,o=self._equivalent(base,other)
                if not code and not equal:out.append(self._finding(IntegrityFindingType.REPORT_INTERNAL_CONTRADICTION,IntegrityFindingStatus.CONFIRMED,IntegritySeverity.HIGH,"REPORT_INTERNAL",self._get(other,"clause_id"),[],[],param,e,o,[str(self._get(base,"measurement_id")),str(self._get(other,"measurement_id"))],[],[],"INTEGRITY_REPORT_INTERNAL_CONTRADICTION","Two report measurements for the same semantic parameter conflict.",.98))
        return out

    def _calculation_findings(self,items:Sequence[Dict[str,Any]],diagnostics:List[Dict[str,Any]])->List[IntegrityFinding]:
        out=[]
        for item in items:
            calc=self._get(item,"calculation")
            if not calc:continue
            operands=self._get(calc,"operands",[]) or [];operator=str(self._get(calc,"operator","")).upper();reported=self._get(calc,"reported_result")
            try:
                vals=[float(x) for x in operands]
                if not vals or reported is None:raise KeyError
                computed={"ADD":sum(vals),"SUBTRACT":vals[0]-sum(vals[1:]),"MULTIPLY":math.prod(vals),"DIVIDE":vals[0]/math.prod(vals[1:])}[operator]
                tolerance=float(self._get(calc,"tolerance",0) or 0)
            except (ValueError,TypeError,KeyError,ZeroDivisionError):diagnostics.append({"code":"INTEGRITY_UNSAFE_FORMULA","evidence_id":self._get(item,"evidence_id")});continue
            if abs(computed-float(reported))>tolerance+1e-9:
                out.append(self._finding(IntegrityFindingType.CALCULATION_MISMATCH,IntegrityFindingStatus.CONFIRMED,IntegritySeverity.HIGH,"CALCULATION",self._get(item,"clause_id"),[],[],self._get(calc,"parameter"),{"engine_calculated_result":computed,"tolerance":tolerance},{"reported_result":reported},[str(self._get(item,"evidence_id"))],[],[],"INTEGRITY_CALCULATION_MISMATCH","Safely normalized recalculation differs from the reported result.",1.0))
        return out

    def _scope_findings(self,scopes:Sequence[Any],diagnostics:List[Dict[str,Any]])->List[IntegrityFinding]:
        for x in scopes:
            if self._enum(self._get(x,"scope_status"))=="AMBIGUOUS":diagnostics.append({"code":"INTEGRITY_AMBIGUOUS_EVIDENCE_SCOPE","evidence_id":self._get(x,"report_evidence_id"),"candidate_groups":[self._get(g,"group_id") for g in self._get(x,"candidate_groups",[]) or []]})
        return []

    @classmethod
    def _equivalent(cls,left:Any,right:Any)->Tuple[bool,Optional[str],Dict[str,Any],Dict[str,Any]]:
        lv=cls._get(left,"value",left) if isinstance(left,Mapping) else left;lu=cls._get(left,"unit") if isinstance(left,Mapping) else None
        rv=cls._get(right,"value",right) if isinstance(right,Mapping) else right;ru=cls._get(right,"unit_normalized") or cls._get(right,"unit") if isinstance(right,Mapping) else None
        expected={"value":copy.deepcopy(lv),"unit":lu};observed={"value":copy.deepcopy(rv),"unit":ru}
        if lv is None or rv is None:return False,"INTEGRITY_MISSING_REPORT_PARAMETER",expected,observed
        try:
            if isinstance(lv,bool) or isinstance(rv,bool):return lv is rv,None,expected,observed
            a=float(lv);b=float(rv)
            if lu or ru:
                if not lu or not ru:return False,"INTEGRITY_UNRESOLVED_UNIT",expected,observed
                us=cls._UNIT.get(str(lu));ut=cls._UNIT.get(str(ru))
                if not us or not ut or us[0]!=ut[0]:return False,"INTEGRITY_UNRESOLVED_UNIT",expected,observed
                a*=us[1];b*=ut[1]
            return math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-9),None,expected,observed
        except (ValueError,TypeError):return str(lv).strip().casefold()==str(rv).strip().casefold(),None,expected,observed

    @classmethod
    def _report_content(cls,report:Any)->Tuple[List[Dict[str,Any]],List[Dict[str,Any]]]:
        measurements=[];items=[]
        def walk(nodes):
            for node in nodes:
                clause=cls._get(node,"clause_id")
                for e in cls._get(node,"evidence_items",[]) or []:
                    item=copy.deepcopy(e);item.setdefault("clause_id",clause);items.append(item)
                    for m in cls._get(e,"measurements",[]) or []:q=copy.deepcopy(m);q.setdefault("clause_id",clause);measurements.append(q)
                for m in cls._get(node,"measurements",[]) or []:q=copy.deepcopy(m);q.setdefault("clause_id",clause);measurements.append(q)
                walk(cls._get(node,"children",[]) or [])
        walk(cls._get(report,"clauses",[]) or []);unique={str(cls._get(x,"measurement_id")):x for x in measurements if cls._get(x,"measurement_id")};return list(unique.values()),items
    @classmethod
    def _scope_index(cls,scope:Any)->List[Any]:return list(cls._get(scope,"results",[]) or [])
    @classmethod
    def _verdict_index(cls,scopes:Sequence[Any])->Dict[str,List[Dict[str,Any]]]:
        out=defaultdict(list)
        for x in scopes:
            status=cls._enum(cls._get(x,"scope_status"));selected=[str(y) for y in cls._get(x,"selected_groups",[]) or []];entry={"id":str(cls._get(x,"report_evidence_id")),"verdict":cls._enum(cls._get(x,"reported_verdict")),"status":status,"clause":str(cls._get(x,"report_clause_id","") or "")}
            if status in cls._RELIABLE_SCOPE:
                for gid in selected:out[gid].append(entry)
                if status=="WHOLE_CLAUSE":out["CLAUSE:"+entry["clause"]].append(entry)
        return out
    @classmethod
    def _scoped_verdicts(cls,gids:Sequence[str],clause:str,index:Mapping[str,List[Dict[str,Any]]],verdict:str)->List[str]:return sorted({x["id"] for key in list(gids)+["CLAUSE:"+clause] for x in index.get(key,[]) if x["verdict"]==verdict})
    @classmethod
    def _requirement_groups(cls,grouping:Any,final:Any)->Dict[str,List[str]]:
        out=defaultdict(list)
        for g in cls._get(grouping,"groups",[]) or []:
            gid=str(cls._get(g,"group_id"));
            for m in cls._get(g,"members",[]) or []:out[str(cls._get(m,"effective_requirement_id"))].append(gid)
        for g in cls._get(final,"group_decisions",[]) or []:
            gid=str(cls._get(g,"group_id"));
            for rid in cls._get(g,"member_requirement_ids",[]) or []:
                if gid not in out[str(rid)]:out[str(rid)].append(gid)
        return out
    @classmethod
    def _identity_values(cls,profile:Any,key:str)->List[Any]:return list(cls._get(cls._get(profile,"identity",{}),key,[]) or [])
    @classmethod
    def _parameter(cls,value:Any)->str:
        s=re.sub(r"[^a-z0-9]+"," ",str(value or "").casefold()).strip();return cls._PARAMETER_ALIASES.get(s,s.replace(" ","_"))
    @classmethod
    def _finding(cls,ft,st,sev,ns,clause,requirements,groups,param,expected,observed,evidence,product,constraints,code,reason,confidence):
        canonical=json.dumps([ft.value,ns,param,sorted(groups),sorted(evidence),sorted(constraints)],sort_keys=True);fid="INTEGRITY-F-"+hashlib.sha256(canonical.encode()).hexdigest()[:18].upper()
        return IntegrityFinding(fid,ft,st,sev,ns,str(clause) if clause is not None else None,sorted(set(requirements)),sorted(set(groups)),param or None,copy.deepcopy(expected),copy.deepcopy(observed),sorted(set(evidence)),sorted(set(product)),sorted(set(constraints)),code,reason,float(confidence))
    @classmethod
    def _deduplicate(cls,items:Sequence[IntegrityFinding])->List[IntegrityFinding]:
        out={}
        for x in items:
            if x.finding_id not in out:out[x.finding_id]=x;continue
            old=out[x.finding_id];old.requirement_ids=sorted(set(old.requirement_ids+x.requirement_ids));old.group_ids=sorted(set(old.group_ids+x.group_ids));old.source_evidence_refs=sorted(set(old.source_evidence_refs+x.source_evidence_refs))
        return sorted(out.values(),key=lambda x:(x.finding_type.value,x.clause_id or "",x.finding_id))
    @classmethod
    def _summary(cls,findings:Sequence[IntegrityFinding])->Dict[str,int]:
        s=Counter(x.status.value for x in findings);t=Counter(x.finding_type.value for x in findings)
        return {"total_findings":len(findings),"confirmed_findings":s["CONFIRMED"],"probable_findings":s["PROBABLE"],"possible_findings":s["POSSIBLE"],"insufficient_data":s["INSUFFICIENT_DATA"],"needs_review":s["NEEDS_REVIEW"],"technical_violations":t["TECHNICAL_LIMIT_VIOLATION"],"test_condition_mismatches":t["TEST_CONDITION_MISMATCH"],"calculation_mismatches":t["CALCULATION_MISMATCH"],"cross_evidence_conflicts":sum(t[x] for x in ("CROSS_EVIDENCE_CONFLICT","PRODUCT_RATING_CONFLICT","REPORT_INTERNAL_CONTRADICTION")),"sample_identity_conflicts":t["SAMPLE_IDENTITY_CONFLICT"],"pass_integrity_findings":sum(x.namespace=="PASS_INTEGRITY" for x in findings),"affected_requirements":len({r for x in findings for r in x.requirement_ids}),"affected_groups":len({g for x in findings for g in x.group_ids}),"affected_clauses":len({x.clause_id for x in findings if x.clause_id is not None})}
    @classmethod
    def _inflation(cls,findings:Sequence[IntegrityFinding])->Dict[str,int]:return {"atomic_impact_count":sum(len(x.requirement_ids) for x in findings),"logical_group_impact_count":len({g for x in findings for g in x.group_ids}),"unique_clause_impact_count":len({x.clause_id for x in findings if x.clause_id}),"canonical_finding_count":len(findings)}
    @staticmethod
    def _get(v:Any,n:str,d:Any=None)->Any:return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
    @staticmethod
    def _enum(v:Any)->Optional[str]:return None if v is None else str(v.value if isinstance(v,Enum) else v)
    @classmethod
    def _plain(cls,v:Any)->Any:
        if isinstance(v,Enum):return v.value
        if is_dataclass(v):return cls._plain(asdict(v))
        if isinstance(v,Mapping):return {str(k):cls._plain(x) for k,x in v.items()}
        if isinstance(v,(list,tuple)):return [cls._plain(x) for x in v]
        return v
    @classmethod
    def to_dict(cls,v:CrossEvidenceIntegrityResult)->Dict[str,Any]:
        if not is_dataclass(v):raise TypeError("integrity result model required")
        return cls._plain(asdict(v))
    @classmethod
    def to_json(cls,v:CrossEvidenceIntegrityResult,indent:int=2)->str:return json.dumps(cls.to_dict(v),ensure_ascii=False,sort_keys=True,indent=indent)
    @classmethod
    def save_json(cls,v:CrossEvidenceIntegrityResult,p:Any)->Path:
        path=Path(p);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(cls.to_json(v)+"\n",encoding="utf-8");return path
__all__=["CrossEvidenceIntegrityResult","GenericCrossEvidenceIntegrityValidator","IntegrityFinding","IntegrityFindingStatus","IntegrityFindingType","IntegritySeverity"]
