"""Generic, gate-driven consistency validation over structured pipeline artifacts."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .generic_cross_evidence_consistency_models import (
    CanonicalParameterLedgerEntry, CanonicalParameterObservation,
    ConsistencyFinding, ConsistencyFindingType as FT, ConsistencyObservation,
    ConsistencyStatus as Status, CrossEvidenceConsistencyResult,
    ParameterReconciliationStatus as PRS, ParameterSemanticRole as Role,
)
from .generic_technical_constraint_evaluator import GenericTechnicalConstraintEvaluator


class GenericCrossEvidenceConsistencyValidator:
    """Compare only semantically aligned, source-backed observations."""

    EXECUTION_VERDICTS={"PASS","FAIL","NOT_TESTED"}

    def validate(self,effective_kb,product_profile,applicability,report_evidence,
                 requirement_grouping=None,evidence_scope=None):
        findings=[];diagnostics=[]
        ledger=self.build_parameter_ledger(effective_kb,product_profile,report_evidence,evidence_scope)
        findings.extend(self._identity_findings(product_profile,report_evidence))
        findings.extend(self._rating_diagnostics(product_profile,report_evidence,diagnostics))
        findings.extend(self._applicability_execution_findings(
            effective_kb,applicability,report_evidence,requirement_grouping,evidence_scope))
        findings=self._deduplicate(findings)
        payload=[x.finding_id for x in findings]
        result=CrossEvidenceConsistencyResult(
            "1.0","CONSISTENCY-"+hashlib.sha256(json.dumps(payload,separators=(",",":")).encode()).hexdigest()[:20].upper(),
            findings,summary={"total_findings":len(findings),"by_type":dict(Counter(x.finding_type.value for x in findings)),"by_status":dict(Counter(x.status.value for x in findings))},
            diagnostics=sorted(diagnostics,key=lambda x:(x.get("code",""),json.dumps(x,sort_keys=True))),
            parameter_ledger=ledger,
            quality_audit={"material_conflicts_without_all_gates":0,"same_unit_used_as_semantic_proof":0,"different_models_treated_as_same_scope":0,"invented_tolerance_count":0,"missing_data_treated_as_conflict":0,"fixture_specific_production_branches":0,"upstream_artifact_mutations":0})
        return result

    def build_parameter_ledger(self,effective_kb,product_profile,report_evidence,evidence_scope=None):
        """Build the single canonical view embedded in the consistency artifact."""
        self._kb_family_index=defaultdict(set)
        for clause in self._walk(self._get(effective_kb,"clauses",[]) or []):
            cid=str(self._get(clause,"clause_id","") or "")
            for requirement in self._get(clause,"requirements",[]) or []:
                self._kb_family_index[cid].add(self.test_family(self._get(requirement,"text")))
        observations=[]
        observations.extend(self._profile_parameter_observations(product_profile))
        kb_index,kb_observations=self._kb_parameter_observations(effective_kb)
        observations.extend(kb_observations)
        observations.extend(self._report_parameter_observations(
            report_evidence,product_profile,kb_index,evidence_scope))
        observations.extend(self._textual_condition_observations(effective_kb,report_evidence,product_profile,evidence_scope))
        grouped=defaultdict(list)
        for observation in observations:
            if observation.canonical_parameter:
                grouped[observation.canonical_parameter].append(observation)
        return [self._reconcile_parameter(parameter,grouped[parameter])
                for parameter in sorted(grouped)]

    def _profile_parameter_observations(self,profile):
        models=[str(x) for x in self._get(self._get(profile,"identity",{}),"model_numbers",[]) or []]
        product=self._get(self._get(profile,"identity",{}),"product_name")
        output=[]
        for key,fact in sorted((self._get(profile,"facts",{}) or {}).items()):
            value=self._get(fact,"normalized_value",self._get(fact,"value"))
            if value is None:continue
            numeric,unit=self._value_unit(value,self._get(fact,"unit"))
            canonical=self.canonical_parameter(key)
            for index,evidence in enumerate(self._get(fact,"evidence",[]) or [None]):
                eid=self._get(evidence,"evidence_id") if evidence else None
                output.append(CanonicalParameterObservation(
                    self._observation_id("PROFILE",canonical,eid or str(index)),canonical,key,
                    value,numeric,unit,self._canonical_unit(unit),Role.DECLARED,"PRODUCT_PROFILE",
                    self._get(evidence,"page") if evidence else None,
                    self._get(evidence,"clause_id") if evidence else None,"product_profile.facts",
                    eid,str(product) if product else None,models,None,
                    self.test_family(key),"DECLARED_STATE","NOT_APPLICABLE",float(self._get(fact,"confidence",0) or 0),
                    .99,.99,self._get(evidence,"clause_id") if evidence else None,eid,
                    ["PRODUCT_FACT_PROVENANCE_REUSED"]))
        return output

    def _kb_parameter_observations(self,kb):
        index=defaultdict(list);output=[]
        for clause in self._walk(self._get(kb,"clauses",[]) or []):
            cid=str(self._get(clause,"clause_id","") or "")
            for requirement in self._get(clause,"requirements",[]) or []:
                rid=str(self._get(requirement,"effective_requirement_id",self._get(requirement,"requirement_id","")) or "")
                rtext=str(self._get(requirement,"text","") or "")
                for constraint in self._get(requirement,"technical_constraints",[]) or []:
                    raw=self._get(constraint,"parameter") or self._get(constraint,"parameter_text") or self._get(constraint,"raw_text")
                    canonical=self.semantic_parameter(raw,raw, self._get(constraint,"unit_normalized") or self._get(constraint,"unit"));unit=self._get(constraint,"unit_normalized") or self._get(constraint,"unit")
                    index[cid].append((canonical,unit))
                    value=self._get(constraint,"value")
                    if value is None:continue
                    role=Role.LIMIT if self._constraint_is_limit(constraint,rtext) else Role.TEST_BASIS
                    constraint_id=str(self._get(constraint,"constraint_id",rid) or rid)
                    output.append(CanonicalParameterObservation(
                        self._observation_id("KB",canonical,constraint_id),canonical,str(raw or ""),value,value,
                        self._get(constraint,"unit"),self._canonical_unit(unit),role,"EFFECTIVE_KB",None,cid,
                        "effective_kb.technical_constraints",constraint_id,None,[],None,
                        self.test_family(rtext or raw),self.test_phase(rtext),self.conditioning_state(rtext),.95,.95,.95,
                        cid,constraint_id,["KB_PARAMETER_IDENTITY","REQUIREMENT_OWNERSHIP"]))
        return index,output

    def _report_parameter_observations(self,report,profile,kb_index,evidence_scope):
        output=[];scope_index={str(self._get(x,"report_evidence_id")):x for x in self._get(evidence_scope,"results",[]) or []}
        models=[str(x) for x in self._get(self._get(profile,"identity",{}),"model_numbers",[]) or []]
        product=self._get(self._get(profile,"identity",{}),"product_name")
        for clause in self._walk(self._get(report,"clauses",[]) or []):
            physical=str(self._get(clause,"clause_id","") or "")
            for item in self._get(clause,"evidence_items",[]) or []:
                eid=str(self._get(item,"evidence_id","") or "");text=str(self._get(item,"raw_text","") or "")
                owner=str(self._get(item,"measurement_owner_evidence_id") or eid)
                semantic_clause=str(self._get(item,"clause_id") or physical)
                scoped=scope_index.get(eid,{});groups=[str(self._get(x,"group_id",x)) for x in self._get(scoped,"selected_groups",[]) or []]
                evidence_status=self._enum(self._get(scoped,"scope_status")) or "UNASSESSED"
                if self._scope_rejected(evidence_status):continue
                for measurement in self._get(item,"measurements",[]) or []:
                    raw=self._get(measurement,"parameter") or self._get(measurement,"parameter_text")
                    label=self._get(measurement,"parameter_text") or self._get(measurement,"row_label") or raw
                    unit=self._get(measurement,"unit_normalized") or self._get(measurement,"unit")
                    identity_text=" ".join((str(label or ""),str(self._get(measurement,"raw_text") or "")))
                    canonical=self._kb_canonical(identity_text,unit,kb_index.get(semantic_clause,[]))
                    family=self.test_family(" ".join((str(label or ""),text)))
                    expected_families=set(getattr(self,"_kb_family_index",{}).get(semantic_clause,set()))-{"GENERAL_TECHNICAL"}
                    if expected_families and family not in expected_families and family!="GENERAL_TECHNICAL":
                        evidence_status="WRONG_TEST_FAMILY_NOT_COMPARABLE"
                    role=self.semantic_role(label,self._get(measurement,"notes"),None)
                    if family=="MARKING" and re.search(r"\brated\b",str(label or ""),re.I):role=Role.DECLARED
                    value=self._get(measurement,"value")
                    output.append(CanonicalParameterObservation(
                        self._observation_id("REPORT",canonical,str(self._get(measurement,"measurement_id"))),canonical,
                        str(raw or ""),value,value,self._get(measurement,"unit"),self._canonical_unit(unit),role,
                        "REPORT_MEASUREMENT",self._get(measurement,"page",self._get(item,"page_start")),semantic_clause,
                        self._get(measurement,"table_id") or self._get(item,"table_reference") or self._get(item,"logical_row_id"),
                        str(self._get(measurement,"measurement_id") or eid),str(product) if product else None,models,
                        self._get(measurement,"sample_scope"),family,
                        self.test_phase(text),self.conditioning_state(text),.9,.9,.9 if owner else .5,physical,owner,
                        ["MEASUREMENT_OWNER_ID",*["SCOPED_GROUP:"+x for x in groups]],
                        self.component_scope(label),evidence_status,
                        sorted({str(self._get(x,"matched_requirement_ids",[])[0]) for x in self._get(scoped,"selected_groups",[]) or [] if self._get(x,"matched_requirement_ids",[])}),[]))
        return output

    def _textual_condition_observations(self,kb,report,profile,evidence_scope):
        """Expose explicit formula operands without executing the technical rule."""
        output=[];models=[str(x) for x in self._get(self._get(profile,"identity",{}),"model_numbers",[]) or []]
        product=self._get(self._get(profile,"identity",{}),"product_name")
        scope_index={str(self._get(x,"report_evidence_id")):x for x in self._get(evidence_scope,"results",[]) or []}
        pattern=re.compile(r"(?P<factor>\d+(?:[.,]\d+)?)\s+times\s+rated\s+(?P<operand>[a-z][a-z ]*?)\s+for\s+(?P<duration>\d+(?:[.,]\d+)?)\s*(?P<duration_unit>min(?:ute)?s?|s(?:ec(?:ond)?s?)?)\b",re.I)
        for clause in self._walk(self._get(kb,"clauses",[]) or []):
            cid=str(self._get(clause,"clause_id","") or "")
            for requirement in self._get(clause,"requirements",[]) or []:
                rid=str(self._get(requirement,"effective_requirement_id",self._get(requirement,"requirement_id","")) or "")
                text=str(self._get(requirement,"text","") or "").replace("×"," times ")
                for match in pattern.finditer(text):
                    factor=float(match.group("factor").replace(",","."));duration=float(match.group("duration").replace(",","."))
                    operand=self.canonical_parameter("rated "+match.group("operand").strip());family=self.test_family(text)
                    link={"operation":"MULTIPLY","operand_reference":operand,"multiplier":factor,"duration":{"value":duration,"unit":match.group("duration_unit")},"execution_deferred_to":"STEP_45_D"}
                    common=dict(source_clause=cid,source_location="effective_kb.requirement_text",evidence_id=rid,
                                test_family=family,test_phase=self.test_phase(text),conditioning_state=self.conditioning_state(text),
                                confidence=.95,normalization_confidence=.95,ownership_confidence=.95,physical_clause=cid,
                                evidence_owner_id=rid,ownership_basis=["EXPLICIT_REQUIREMENT_EXPRESSION","REQUIREMENT_OWNERSHIP"],
                                evidence_status="AUTHORITATIVE_REQUIREMENT",requirement_ids=[rid],formula_operand_links=[link])
                    output.append(CanonicalParameterObservation(self._observation_id("KB-FORMULA",rid,"MULTIPLIER"),"test_multiplier","multiplier",factor,factor,None,None,Role.TEST_BASIS,"EFFECTIVE_KB",**common))
                    output.append(CanonicalParameterObservation(self._observation_id("KB-FORMULA",rid,"DURATION"),"test_duration","duration",duration,duration,match.group("duration_unit"),"min" if match.group("duration_unit").casefold().startswith("min") else "s",Role.TEST_BASIS,"EFFECTIVE_KB",**common))
        for clause in self._walk(self._get(report,"clauses",[]) or []):
            cid=str(self._get(clause,"clause_id","") or "")
            for item in self._get(clause,"evidence_items",[]) or []:
                eid=str(self._get(item,"evidence_id","") or "");text=str(self._get(item,"raw_text","") or "")
                scoped=scope_index.get(eid,{});status=self._enum(self._get(scoped,"scope_status")) or "UNASSESSED"
                if self._scope_rejected(status):continue
                family=self.test_family(text)
                for match in re.finditer(r"(\d+(?:[.,]\d+)?)\s*[×x]\s*(\d+(?:[.,]\d+)?)\s*([a-z]+)\s*=\s*(\d+(?:[.,]\d+)?)\s*([a-z]+)?",text,re.I):
                    factor=float(match.group(1).replace(",","."));basis=float(match.group(2).replace(",","."));unit=match.group(3);result=float(match.group(4).replace(",","."));result_unit=match.group(5) or unit
                    link={"operation":"MULTIPLY","operand_reference":"rated_voltage" if self._canonical_unit(unit)=="V" else self.semantic_parameter("basis",None,unit),"multiplier":factor,"reported_result":result,"execution_deferred_to":"STEP_45_D"}
                    common=dict(source_page=self._get(item,"page_start"),source_clause=cid,source_location=self._get(item,"table_reference") or eid,evidence_id=eid,
                                product_scope=str(product) if product else None,model_scope=models,test_family=family,test_phase=self.test_phase(text),conditioning_state=self.conditioning_state(text),confidence=.9,normalization_confidence=.9,ownership_confidence=.9,physical_clause=cid,evidence_owner_id=eid,ownership_basis=["EXPLICIT_REPORT_EXPRESSION"],evidence_status=status,formula_operand_links=[link])
                    output.append(CanonicalParameterObservation(self._observation_id("REPORT-FORMULA",eid,"BASIS"),"rated_voltage" if self._canonical_unit(unit)=="V" else self.semantic_parameter("basis",None,unit),"formula basis",basis,basis,unit,self._canonical_unit(unit),Role.TEST_BASIS,"REPORT_EXPRESSION",**common))
                    output.append(CanonicalParameterObservation(self._observation_id("REPORT-FORMULA",eid,"RESULT"),"test_voltage" if self._canonical_unit(result_unit)=="V" else self.semantic_parameter("result",None,result_unit),"applied formula result",result,result,result_unit,self._canonical_unit(result_unit),Role.APPLIED,"REPORT_EXPRESSION",**common))
                    output.append(CanonicalParameterObservation(self._observation_id("REPORT-FORMULA",eid,"MULTIPLIER"),"test_multiplier","applied multiplier",factor,factor,None,None,Role.APPLIED,"REPORT_EXPRESSION",**common))
                duration_match=re.search(r"\bfor\s+(\d+(?:[.,]\d+)?)\s*(min(?:ute)?s?|s(?:ec(?:ond)?s?)?)\b",text,re.I)
                if duration_match:
                    value=float(duration_match.group(1).replace(",","."));unit=duration_match.group(2);output.append(CanonicalParameterObservation(
                        self._observation_id("REPORT-CONDITION",eid,"DURATION"),"test_duration","applied duration",value,value,unit,"min" if unit.casefold().startswith("min") else "s",Role.APPLIED,"REPORT_EXPRESSION",self._get(item,"page_start"),cid,eid,eid,str(product) if product else None,models,None,family,self.test_phase(text),self.conditioning_state(text),.9,.9,.9,cid,eid,["EXPLICIT_REPORT_TEST_CONDITION"],None,status))
        return output

    def _reconcile_parameter(self,parameter,observations):
        observations=sorted(observations,key=lambda x:x.observation_id);findings=[];comparable=0;variations=0;conflicts=0
        for left_index,left in enumerate(observations):
            for right in observations[left_index+1:]:
                relation,reason=self._observation_relation(left,right)
                findings.append({"left":left.observation_id,"right":right.observation_id,"relation":relation,"reason_code":reason})
                if relation=="CONFLICT":conflicts+=1
                elif relation=="ROLE_COMPATIBLE_VARIATION":variations+=1;comparable+=1
                elif relation=="CONSISTENT":comparable+=1
        status=(PRS.INSUFFICIENT_EVIDENCE if len(observations)<2 else PRS.CONFLICTING if conflicts
                else PRS.ROLE_COMPATIBLE_VARIATION if variations else PRS.CONSISTENT if comparable
                else PRS.NOT_COMPARABLE)
        authority=self._authority_state(observations)
        comparability=("CONFLICTING" if status is PRS.CONFLICTING else "COMPARABLE" if status is PRS.CONSISTENT
                       else "ROLE_COMPATIBLE_VARIATION" if status is PRS.ROLE_COMPATIBLE_VARIATION
                       else "NOT_COMPARABLE" if status is PRS.NOT_COMPARABLE else "INSUFFICIENT_CONTEXT")
        links=[dict(link,observation_id=o.observation_id) for o in observations for link in o.formula_operand_links]
        return CanonicalParameterLedgerEntry(parameter,observations,status,findings,list(findings),authority,comparability,links)

    def _observation_relation(self,left,right):
        if left.normalized_value is None or right.normalized_value is None:return "NOT_COMPARABLE","VALUE_UNAVAILABLE"
        if not self._scope_compatible(left,right):return "NOT_COMPARABLE","SCOPE_MISMATCH"
        roles={left.semantic_role,right.semantic_role}
        if (left.source_clause and right.source_clause and left.source_clause!=right.source_clause
                and Role.DECLARED not in roles):
            return "NOT_COMPARABLE","CROSS_CLAUSE_OWNERSHIP_UNPROVEN"
        if (left.test_family and right.test_family and left.test_family!=right.test_family
                and Role.DECLARED not in roles):
            return "NOT_COMPARABLE","TEST_FAMILY_MISMATCH"
        if left.test_phase and right.test_phase and left.test_phase!=right.test_phase and Role.DECLARED not in roles:return "NOT_COMPARABLE","TEST_PHASE_MISMATCH"
        if left.conditioning_state and right.conditioning_state and left.conditioning_state!=right.conditioning_state and Role.DECLARED not in roles:return "NOT_COMPARABLE","CONDITIONING_STATE_MISMATCH"
        converted=self._convert_value(right.normalized_value,right.normalized_unit,left.normalized_unit)
        if converted is None:return "NOT_COMPARABLE","UNIT_DIMENSION_MISMATCH"
        same=self._numeric_equal(left.normalized_value,converted)
        conflict_roles=(roles <= {Role.DECLARED,Role.TEST_BASIS}
                        and Role.DECLARED in roles and Role.UNKNOWN_ROLE not in roles)
        if same:return "CONSISTENT","SEMANTICALLY_COMPARABLE_EQUAL"
        if conflict_roles:return "CONFLICT","COMPATIBLE_DECLARATION_BASIS_DIFFERENCE"
        if roles & {Role.MEASURED,Role.CALCULATED,Role.LIMIT,Role.APPLIED}:
            return "ROLE_COMPATIBLE_VARIATION","DIFFERENT_SEMANTIC_ROLES_NO_AUTO_CONFLICT"
        return "NOT_COMPARABLE","ROLE_RELATIONSHIP_UNRESOLVED"

    @classmethod
    def authorize_cross_clause_ownership(cls,left,right,*,explicit_reference=False,kb_dependency=False,parent_child=False):
        """Return a traceable ownership decision without using clause equality alone."""
        if left.evidence_owner_id and left.evidence_owner_id==right.evidence_owner_id:
            return True,"SAME_EXPLICIT_EVIDENCE_OWNER"
        if explicit_reference:return True,"EXPLICIT_REPORT_CROSS_REFERENCE"
        if kb_dependency:return True,"EXPLICIT_KB_DEPENDENCY"
        same_context=bool(left.test_family and left.test_family==right.test_family and left.test_phase==right.test_phase and cls._scope_compatible(left,right))
        if parent_child and same_context:return True,"PARENT_CHILD_WITH_MATCHED_SEMANTIC_CONTEXT"
        return False,"CROSS_CLAUSE_SEMANTIC_OWNERSHIP_UNPROVEN"

    @classmethod
    def canonical_parameter(cls,value):
        normalized=re.sub(r"[^a-z0-9]+","_",str(value or "").casefold()).strip("_")
        aliases={"rated_power":"power_input","rated_power_input":"power_input","input_power":"power_input",
                 "p_rated":"power_input","p_measured":"power_input","rated_input_power":"power_input",
                 "rated_frequency":"frequency"}
        if normalized in aliases:return aliases[normalized]
        tokens=[x for x in normalized.split("_") if x not in {"declared","measured","observed","actual","value"}]
        return "_".join(tokens) or normalized or "unknown_parameter"

    @classmethod
    def semantic_parameter(cls,parameter,label=None,unit=None):
        text=" ".join(str(x or "") for x in (parameter,label)).casefold()
        if re.search(r"\b(?:temperature\s+rise|d\s*t)\b",text):return "temperature_rise"
        if cls._canonical_unit(unit) in {"W","kW"} and re.search(r"\b(?:p|power)(?:\s+input)?\b",text):return "power_input"
        if cls._canonical_unit(unit)=="V":
            if re.search(r"\brated\s+voltage\b",text):return "rated_voltage"
            if re.search(r"\b(?:applied|test)\s+voltage\b",text):return "test_voltage"
        return cls.canonical_parameter(parameter or label)

    @classmethod
    def semantic_role(cls,parameter,notes=None,text=None):
        value=" ".join(str(x or "") for x in (parameter,notes,text)).casefold()
        if re.search(r"\b(?:maximum|max\.?|minimum|min\.?|limit|required)\b",value):return Role.LIMIT
        if re.search(r"\b(?:calculated|calculation|computed)\b",value):return Role.CALCULATED
        if re.search(r"\b(?:p\s+rated|rated\s+power|rated\s+voltage|rated\s+frequency)\b",value):return Role.TEST_BASIS if "measured" in value else Role.DECLARED
        if re.search(r"\b(?:measured|observed|measurement role: observed_value)\b",value):return Role.MEASURED
        if re.search(r"\b(?:applied|test input|measurement role: test_parameter)\b",value):return Role.APPLIED
        if re.search(r"\b(?:test basis|reference value)\b",value):return Role.TEST_BASIS
        if re.search(r"\b(?:rated|rating|declared|marking)\b",value):return Role.DECLARED
        if re.search(r"\breference\b",value):return Role.REFERENCE
        return Role.UNKNOWN_ROLE

    @staticmethod
    def test_family(text):
        value=str(text or "").casefold();families=(("lowest possible load","ABNORMAL_OPERATION"),("times rated voltage","ABNORMAL_OPERATION"),("temperature rise","HEATING"),("thermocouple","HEATING"),("welding operation","HEATING"),("mark", "MARKING"),("heat","HEATING"),("leakage","LEAKAGE_CURRENT"),("electric strength","ELECTRIC_STRENGTH"),("insulation resistance","ELECTRIC_STRENGTH"),("moisture","MOISTURE"),("abnormal","ABNORMAL_OPERATION"),("mechanical","MECHANICAL_STRENGTH"),("construction","CONSTRUCTION"),("supply","SUPPLY_CONNECTION"),("fire","FIRE_RESISTANCE"),("power","POWER_INPUT_CURRENT"))
        return next((family for token,family in families if token in value),"GENERAL_TECHNICAL")

    @staticmethod
    def test_phase(text):
        value=str(text or "").casefold();phases=(("after endurance","AFTER_ENDURANCE"),("after moisture","AFTER_MOISTURE"),("pre-conditioning","PRE_CONDITIONING"),("post-conditioning","POST_CONDITIONING"),("abnormal operation","ABNORMAL_OPERATION"),("normal operation","NORMAL_OPERATION"),("overvoltage","OVERVOLTAGE"),("undervoltage","UNDERVOLTAGE"),("steady state","STEADY_STATE"),("rated condition","RATED_CONDITION"))
        return next((phase for token,phase in phases if token in value),"UNSPECIFIED_PHASE")

    @staticmethod
    def conditioning_state(text):
        value=str(text or "").casefold()
        if "after moisture" in value:return "MOISTURE_CONDITIONED"
        if "after endurance" in value:return "ENDURANCE_CONDITIONED"
        if "conditioned" in value or "conditioning" in value:return "CONDITIONED"
        return "UNSPECIFIED_CONDITIONING"

    @classmethod
    def _kb_canonical(cls,raw,unit,candidates):
        semantic=cls.semantic_parameter(raw,raw,unit)
        compatible=[parameter for parameter,candidate_unit in candidates if parameter==semantic and cls._units_compatible(unit,candidate_unit)]
        return compatible[0] if compatible else semantic

    @classmethod
    def _canonical_unit(cls,unit):
        info=GenericTechnicalConstraintEvaluator._UNIT.get(unit)
        return info[2] if info else unit

    @classmethod
    def _convert_value(cls,value,source,target):
        if value is None:return None
        if source==target:return value
        try:return GenericTechnicalConstraintEvaluator._convert(float(value),source,target)
        except (TypeError,ValueError):return None

    @classmethod
    def _units_compatible(cls,left,right):return cls._convert_value(1,left,right) is not None
    @staticmethod
    def _numeric_equal(left,right):
        try:return abs(float(left)-float(right))<=max(1e-9,abs(float(left))*1e-9)
        except (TypeError,ValueError):return left==right
    @staticmethod
    def _scope_compatible(left,right):
        if left.sample_scope and right.sample_scope and left.sample_scope!=right.sample_scope:return False
        if left.component_scope and right.component_scope and left.component_scope!=right.component_scope:return False
        if left.model_scope and right.model_scope and not set(left.model_scope)&set(right.model_scope):return False
        if left.product_scope and right.product_scope and left.product_scope!=right.product_scope:return False
        return True
    @classmethod
    def _constraint_is_limit(cls,constraint,text):
        return cls._enum(cls._get(constraint,"constraint_type")) in {"LIMIT","ACCEPTANCE_LIMIT"} or bool(re.search(r"\b(?:shall not exceed|maximum|minimum|at least|at most)\b",str(text or ""),re.I))
    @staticmethod
    def _value_unit(value,unit):
        if isinstance(value,Mapping):
            normalized={k:value[k] for k in ("min","max","value") if value.get(k) is not None}
            return (normalized if "min" in normalized or "max" in normalized else normalized.get("value")),value.get("unit",unit)
        return value,unit

    @staticmethod
    def component_scope(text):
        value=re.sub(r"\b(?:measured|max(?:imum)?|min(?:imum)?|d\s*t|temperature\s+rise|rated|required|limit)\b|[^a-z0-9]+"," ",str(text or "").casefold()).strip()
        return re.sub(r"\s+","_",value) or None

    @staticmethod
    def _scope_rejected(status):return any(token in str(status or "") for token in ("REJECTED","NOT_SEMANTICALLY_COMPATIBLE","STRUCTURE_MISMATCH"))

    @staticmethod
    def _authority_state(observations):
        declared={json.dumps(x.normalized_value,sort_keys=True,default=str) for x in observations if x.semantic_role in {Role.DECLARED,Role.TEST_BASIS}}
        return "CONFLICTING" if len(declared)>1 else "DETERMINISTIC" if len(declared)==1 else "UNRESOLVED"
    @staticmethod
    def _observation_id(*parts):return "PARAM-OBS-"+hashlib.sha256("\x1f".join(map(str,parts)).encode()).hexdigest()[:20].upper()

    def _identity_findings(self,profile,report):
        identities=list(self._get(self._get(profile,"identity",{}),"product_identities",[]) or [])
        declared=[x for x in identities if self._enum(self._get(x,"role"))=="DECLARED_MODEL"]
        tested=[x for x in identities if self._enum(self._get(x,"role"))=="TESTED_MODEL"]
        if not declared or not tested:return []
        raw=self._report_text(report)
        out=[]
        for left in declared:
            for right in tested:
                lv=str(self._get(left,"normalized_value",self._get(left,"value","")));rv=str(self._get(right,"normalized_value",self._get(right,"value","")))
                evidence=self._identity_evidence(left)+self._identity_evidence(right)
                if lv==rv:status=Status.CONSISTENT;typ=FT.IDENTITY_CONFLICT;reason="Normalized declared and tested model identities are identical.";recon=[]
                else:
                    relation=self._identity_relationship(raw,lv,rv)
                    contradiction=self._explicit_identity_contradiction(raw,lv,rv)
                    if relation:status=Status.RECONCILED;typ=FT.IDENTITY_CONFLICT;reason="An explicit report relationship reconciles the identities.";recon=evidence
                    elif contradiction:status=Status.MATERIAL_CONFLICT;typ=FT.IDENTITY_CONFLICT;reason="The report explicitly assigns contradictory tested-product ownership.";recon=[]
                    else:status=Status.UNRESOLVED;typ=FT.IDENTITY_RELATIONSHIP_UNRESOLVED;reason="Different role-aware identities have no explicit equivalence, family, representative, or variant relationship.";recon=[]
                out.append(self._finding(typ,status,{"identity_type":"MODEL"},[self._identity_observation(left),self._identity_observation(right)],{"same_parameter":True,"same_product_scope":"UNRESOLVED" if lv!=rv else True,"same_test_context":"SUPPORTED_BY_ROLES","same_model_scope":"UNRESOLVED" if lv!=rv else True,"comparison_basis":["DECLARED_MODEL","TESTED_MODEL"],"difference":{"different_values":lv!=rv}},reason,recon,"REVIEW_IDENTITY_RELATIONSHIP" if status is Status.UNRESOLVED else "NO_AUTOMATIC_COMPLIANCE_EFFECT",product_identity_ids=[str(self._get(left,"identity_id")),str(self._get(right,"identity_id"))],evidence_ids=evidence))
        return out

    def _rating_diagnostics(self,profile,report,diagnostics):
        facts=self._get(profile,"facts",{}) or {};rating=self._get(facts,"rated_voltage")
        if not rating:return []
        rating_evidence=[str(self._get(x,"evidence_id")) for x in self._get(rating,"evidence",[]) or []]
        voltage=[]
        for clause in self._walk(self._get(report,"clauses",[]) or []):
            for item in self._get(clause,"evidence_items",[]) or []:
                for measurement in self._get(item,"measurements",[]) or []:
                    if str(self._get(measurement,"unit",""))=="V":voltage.append((clause,item,measurement))
        if not voltage:
            diagnostics.append({"code":"CONSISTENCY_RATED_VOLTAGE_NO_COMPARABLE_TEST_OBSERVATION","product_fact_id":"rated_voltage","evidence_ids":rating_evidence,"reason":"No structured voltage test observation is available for semantic comparison."});return []
        out=[]
        for clause,item,measurement in voltage:
            parameter=str(self._get(measurement,"parameter","") or "").casefold()
            if parameter not in {"rated_voltage","rated voltage"}:
                eid=str(self._get(item,"evidence_id"));out.append(self._finding(FT.UNIT_OR_PARAMETER_AMBIGUITY,Status.NOT_COMPARABLE,{"parameter":"rated_voltage","clause_id":self._get(clause,"clause_id")},[ConsistencyObservation(self._get(rating,"value"),self._get(rating,"value"),"V",source_evidence_ids=rating_evidence,source_context="PRODUCT_RATING"),ConsistencyObservation(self._get(measurement,"value"),self._get(measurement,"value"),"V",source_evidence_ids=[eid],source_context="REPORT_MEASUREMENT")],{"same_parameter":False,"same_product_scope":"UNRESOLVED","same_test_context":"UNRESOLVED","same_model_scope":"UNRESOLVED","comparison_basis":["UNIT_ONLY_REJECTED"],"difference":{}},"The observations share a unit but the report measurement is not identified as rated voltage.",[],"NO_COMPARISON",product_fact_ids=["rated_voltage"],evidence_ids=rating_evidence+[eid],clause_ids=[str(self._get(clause,"clause_id"))]))
        return out

    def _applicability_execution_findings(self,kb,app,report,grouping,scope):
        clauses={str(self._get(x,"clause_id")):x for x in self._walk(self._get(report,"clauses",[]) or [])}
        requirement_types={}
        for clause in self._walk(self._get(kb,"clauses",[]) or []):
            for requirement in self._get(clause,"requirements",[]) or []:
                rid=str(self._get(requirement,"effective_requirement_id",self._get(requirement,"requirement_id","")))
                requirement_types[rid]=self._enum(self._get(requirement,"requirement_type"))
        groups={str(self._get(x,"effective_requirement_id")):str(self._get(g,"group_id")) for g in self._get(grouping,"groups",[]) or [] for x in self._get(g,"members",[]) or []}
        out=[]
        for result in self._get(app,"results",[]) or []:
            if self._enum(self._get(result,"decision"))!="NOT_APPLICABLE":continue
            rid=str(self._get(result,"effective_requirement_id"))
            if requirement_types and requirement_types.get(rid)!="TEST":continue
            cid=str(self._get(result,"clause_id","") or "");clause=clauses.get(cid)
            if not clause:continue
            items=list(self._get(clause,"evidence_items",[]) or [])
            executed=[x for x in items if self._enum(self._get(x,"reported_verdict")) in self.EXECUTION_VERDICTS or self._get(x,"measurements",[]) or re.search(r"\b(?:tested|test\s+performed|measured)\b",str(self._get(x,"raw_text","") or ""),re.I)]
            if not executed:continue
            confirmed=self._get(result,"reason_code")=="EXCLUSION_CONDITION_TRUE"
            exact=all(str(self._get(x,"clause_id",cid) or cid)==cid for x in executed)
            status=Status.MATERIAL_CONFLICT if confirmed and exact else Status.UNRESOLVED
            eids=sorted({str(self._get(x,"evidence_id")) for x in executed if self._get(x,"evidence_id")})
            gid=groups.get(rid)
            out.append(self._finding(FT.APPLICABILITY_EXECUTION_CONFLICT,status,{"clause_id":cid,"requirement_group_id":gid},[ConsistencyObservation(self._enum(self._get(result,"decision")),self._enum(self._get(result,"decision")),role="STANDARD_APPLICABILITY",source_context="APPLICABILITY_RESULT"),*[ConsistencyObservation(self._enum(self._get(x,"reported_verdict")),self._enum(self._get(x,"reported_verdict")),role="REPORT_EXECUTION",source_evidence_ids=[str(self._get(x,"evidence_id"))],source_context="REPORT_CLAUSE",page_refs=[p for p in (self._get(x,"page_start"),self._get(x,"page_end")) if p is not None]) for x in executed]],{"same_parameter":"TEST_EXECUTION","same_product_scope":confirmed,"same_test_context":exact,"same_model_scope":"NOT_REQUIRED","comparison_basis":["EXCLUSION_CONDITION_TRUE" if confirmed else "EXCLUSION_UNRESOLVED","EXACT_CLAUSE_OWNERSHIP" if exact else "SCOPE_UNRESOLVED"],"difference":{"applicability":"NOT_APPLICABLE","execution_reported":True}},"Confirmed exclusion and exact report execution coexist without a structured reconciliation." if status is Status.MATERIAL_CONFLICT else "Applicability or execution ownership is not fully confirmed.",[],"REVIEW_APPLICABILITY_EXECUTION_CONTRADICTION",evidence_ids=eids,requirement_ids=[rid],requirement_group_ids=[gid] if gid else [],clause_ids=[cid],standard_semantic_ids=[rid]))
        return out

    def compare_values(self,left,right,*,same_parameter=False,same_scope=False,same_context=False,reliable=False,material_rule=None,reconciliation=None,affects_validity=False):
        gates={"same_parameter":same_parameter,"same_product_scope":same_scope,"same_test_context":same_context,"both_sources_reliable":reliable,"material_rule":bool(material_rule),"no_reconciliation":not bool(reconciliation),"affects_evaluation_validity":affects_validity}
        if not same_parameter:return Status.NOT_COMPARABLE,gates
        if left==right and same_scope:return Status.CONSISTENT,gates
        if reconciliation:return Status.RECONCILED,gates
        return (Status.MATERIAL_CONFLICT if all(gates.values()) else Status.UNRESOLVED),gates

    def validate_calculation(self,inputs,formula,reported):
        if not formula:return Status.NOT_COMPARABLE,None
        if formula.get("operation")=="multiply" and len(inputs)==2:
            calculated=inputs[0]*inputs[1];return (Status.CONSISTENT if calculated==reported else Status.MATERIAL_CONFLICT),calculated
        return Status.NOT_COMPARABLE,None

    def validate_limit(self,measured,limit,operator,measured_unit,limit_unit):
        if measured is None or limit is None:return Status.UNRESOLVED
        if measured_unit!=limit_unit:return Status.UNRESOLVED
        operations={"<=":lambda:measured<=limit,"<":lambda:measured<limit,">=":lambda:measured>=limit,">":lambda:measured>limit}
        if operator not in operations:return Status.UNRESOLVED
        return Status.CONSISTENT if operations[operator]() else Status.MATERIAL_CONFLICT

    def _finding(self,typ,status,subject,observations,comparison,reason,supporting,disposition,**refs):
        evidence=sorted(set(refs.get("evidence_ids",[])));identity=json.dumps([typ.value,status.value,subject,evidence,[x.normalized_value for x in observations]],sort_keys=True,default=str,separators=(",",":"));fid="CONSISTENCY-FINDING-"+hashlib.sha256(identity.encode()).hexdigest()[:20].upper()
        return ConsistencyFinding(fid,typ,status,"MATERIAL" if status is Status.MATERIAL_CONFLICT else "REVIEW",subject,observations,comparison,{"status":"RECONCILED" if supporting else "NONE","reason":reason,"supporting_evidence_ids":supporting},{"evaluation_validity":"REVIEW_REQUIRED" if status in {Status.MATERIAL_CONFLICT,Status.UNRESOLVED} else "UNCHANGED","recommended_disposition":disposition},None,**refs)

    @classmethod
    def _identity_relationship(cls,text,a,b):
        if not a or not b:return False
        direct=bool(re.search(rf"(?:{re.escape(a)}.*{re.escape(b)}|{re.escape(b)}.*{re.escape(a)}).{{0,160}}\b(?:equivalent|representative|same\s+series|variant|covers|differs\s+only)\b",text,re.I|re.S))
        tested_named=bool(re.search(rf"\b(?:all\s+)?tests?\s+(?:are|were)?\s*performed\s+on(?:\s+the)?(?:\s+model)?\s+{re.escape(b)}\b",text,re.I))
        series_assertion=bool(re.search(r"\ball\s+models?\s+(?:are|were)\s+(?:the\s+)?same\s+except\b|\bmodels?\s+are\s+identical\s+except\b",text,re.I))
        return direct or (tested_named and series_assertion)
    @classmethod
    def _explicit_identity_contradiction(cls,text,a,b):return bool(a and b and re.search(rf"\b{re.escape(a)}\b.{{0,100}}\bnot\s+tested\b.{{0,160}}\b{re.escape(b)}\b.{{0,60}}\b(?:only\s+model\s+tested|sole\s+tested\s+model)\b",text,re.I|re.S))
    @classmethod
    def _identity_observation(cls,x):
        ev=list(cls._get(x,"evidence",[]) or []);return ConsistencyObservation(cls._get(x,"value"),cls._get(x,"normalized_value"),role=cls._enum(cls._get(x,"role")),source_evidence_ids=cls._identity_evidence(x),source_context=cls._get(x,"source_context"),page_refs=sorted({int(cls._get(e,"page")) for e in ev if cls._get(e,"page") is not None}))
    @classmethod
    def _identity_evidence(cls,x):return sorted(set(list(cls._get(x,"source_evidence_ids",[]) or [])+[str(cls._get(e,"evidence_id")) for e in cls._get(x,"evidence",[]) or [] if cls._get(e,"evidence_id")]))
    @classmethod
    def _report_text(cls,report):return "\n".join(str(cls._get(x,"raw_text","") or "") for c in cls._walk(cls._get(report,"clauses",[]) or []) for x in cls._get(c,"evidence_items",[]) or [])
    @classmethod
    def _walk(cls,items):
        for x in items:yield x;yield from cls._walk(cls._get(x,"children",[]) or [])
    @staticmethod
    def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
    @staticmethod
    def _enum(v):return None if v is None else str(v.value if isinstance(v,Enum) else v)
    @staticmethod
    def _deduplicate(items):return sorted({x.finding_id:x for x in items}.values(),key=lambda x:x.finding_id)
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


__all__=["GenericCrossEvidenceConsistencyValidator"]
