"""Compact, deterministic projection of the full Step 43 summary context."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


SCHEMA_VERSION = "FINAL_SUMMARY_BRIEF_CONTEXT_V2"
SUMMARY_CONTRACT_VERSION = "STEP44F_V1"


class GenericFinalSummaryBriefBuilder:
    """Project existing deterministic conclusions without re-evaluating them."""

    MAX_PRODUCT_FINDINGS = 30
    MAX_COMPLIANCE_FINDINGS = 10
    MAX_REPRESENTATIVE_CLAUSES = 5
    MAX_NA_DETAIL_ITEMS = 40
    PRIORITY_ORDER = {"DO_FIRST": 0, "DO_NEXT": 1, "MONITOR": 2, None: 3}

    def build_from_run_directory(self, run_directory) -> Dict[str, Any]:
        run = Path(run_directory)
        source = run / "summary/final_summary_context.json"
        if not source.is_file():
            raise FileNotFoundError(f"Step 43 source artifact not found: {source}")
        return self.build(self._read(source), source_path=source)

    def build(self, context: Mapping[str, Any], *, source_path: Optional[Path] = None) -> Dict[str, Any]:
        if not isinstance(context, Mapping):
            raise TypeError("context must be a mapping")
        if context.get("schema_version") != "FINAL_SUMMARY_CONTEXT_V1":
            raise ValueError("Step 44 requires FINAL_SUMMARY_CONTEXT_V1")
        source = copy.deepcopy(dict(context))
        records = source.get("requirement_results") or []
        record_index = {str(x.get("requirement_id")): x for x in records}
        relevant_candidates, _ = self._product_findings(records, (source.get("product_context") or {}).get("canonical_classification"), apply_limit=False)
        relevant_findings, relevant_selection = self._product_relevant_findings(relevant_candidates)
        compliance_findings, compliance_selection = self._compliance_findings(records)
        root_causes = self._root_causes(source.get("root_causes") or [], record_index)
        actions = self._actions(source.get("next_actions") or [])
        priority = self._priority(source.get("priority_findings") or [], actions)
        parameter_findings, parameter_summary = self._parameter_projection(source.get("parameter_findings") or [])
        na_review_details = self._na_review_details(source.get("na_findings") or [], record_index)
        return {
            "schema_version": SCHEMA_VERSION,
            "summary_contract_version": SUMMARY_CONTRACT_VERSION,
            "run": self._run(source.get("run_context") or {}),
            "product": self._product(source.get("product_context") or {}, records),
            "standards": self._standards(source.get("standard_context") or {}, source.get("kb_authority") or {}),
            "overall_assessment": self._assessment(source),
            "requirement_summary": self._requirement_summary(source.get("requirement_population") or {}),
            "product_relevant_clause_findings": relevant_findings,
            "key_compliance_findings": compliance_findings,
            "key_gaps": self._gaps(root_causes, source.get("gap_summary") or {}),
            "na_summary": self._na_summary(source.get("na_findings") or []),
            "na_review_details": na_review_details,
            "parameter_findings": parameter_findings,
            "parameter_summary": parameter_summary,
            "report_validity": self._report_validity(source),
            "root_causes": root_causes,
            "priority_findings": priority,
            "required_actions": actions,
            "metrics": copy.deepcopy(source.get("metrics") or {}),
            "unresolved_summary": self._unresolved(source.get("pre_llm_unresolved") or {}, record_index),
            "traceability": {
                "source_artifact": "summary/final_summary_context.json",
                "source_schema_version": source.get("schema_version"),
                "source_run_id": (source.get("run_context") or {}).get("run_id"),
                "source_final_disposition": (source.get("final_disposition") or {}).get("value"),
                "source_sha256": self._source_hash(source, source_path),
                "source_metric_policy_versions": {"metrics": (source.get("metrics") or {}).get("metrics_policy_version")},
                "projection_policy_version": "STEP44F_PROJECTION_V1",
                "canonical_metric_source": "metrics",
                "product_relevant_selection": relevant_selection,
                "selection_accounting": {"product_relevant": relevant_selection, "key_compliance": compliance_selection},
                "schema_field_semantics": {
                    "product_relevant_clause_findings": {"legacy_compatibility_field": False, "selection": "explicit deterministic product-class, product-fact, construction, component, or linked supporting-method relevance"},
                },
                "large_applicability_id_arrays_included": False,
                "raw_na_records_included": False,
                "raw_evidence_inventory_included": False,
                "raw_gap_requirement_id_arrays_included": False,
                "new_compliance_reasoning_performed": False,
            },
        }

    def build_from_canonical_client(self, detailed: Mapping[str, Any], legacy_brief: Mapping[str, Any]) -> Dict[str, Any]:
        """Overlay authority-bearing summary fields from one detailed projection.

        Presentation-only selections remain available, but no authority field is
        re-evaluated or reconstructed by this compact projection.
        """
        if not isinstance(detailed, Mapping) or not isinstance(legacy_brief, Mapping):
            raise TypeError("detailed and legacy_brief must be mappings")
        source=copy.deepcopy(dict(detailed));out=copy.deepcopy(dict(legacy_brief))
        direct={
            "run_context":"run_context","canonical_runtime_status":"canonical_runtime_status","canonical_identity_authority":"canonical_identity_authority","standard_context":"standard_context","standard_authority":"standard_authority","kb_maturity_authority":"kb_maturity_authority",
            "report_identity":"report_identity","report_structure_compatibility":"report_structure_compatibility",
            "product_identity":"product_identity","product_classification":"product_classification",
            "canonical_product_facts":"canonical_product_facts","identity_relationships":"identity_relationships",
            "requirement_population":"requirement_population","canonical_requirement_state":"canonical_requirement_state",
            "root_causes":"root_causes","metrics":"metrics","confidence":"confidence","report_validity":"report_validity",
            "final_disposition":"final_disposition",
        }
        for target,key in direct.items():out[target]=copy.deepcopy(source.get(key))
        out["run"]=copy.deepcopy(source.get("run_context") or {})
        out["applicability_authority"]={"policy_version":(source.get("traceability") or {}).get("authority_versions",{}).get("applicability"),"results":copy.deepcopy(source.get("applicability_results") or [])}
        out["evidence_sufficiency_authority"]={"policy_version":(source.get("traceability") or {}).get("authority_versions",{}).get("evidence_sufficiency"),"results":copy.deepcopy(source.get("evidence_sufficiency_results") or [])}
        out["technical_execution_references"]=copy.deepcopy((source.get("traceability") or {}).get("technical_execution_ids") or [])
        canonical_na=copy.deepcopy(source.get("na_validation") or [])
        out["na_validation"]=canonical_na
        # Step 50E: compact N/A presentation is a projection of the canonical
        # lifecycle.  Do not retain the legacy INVALID_NA summary vocabulary.
        na_counts=Counter(str(row.get("status") or "UNRESOLVED_NA") for row in canonical_na if row.get("reported_na"))
        out["na_summary"]={
            "reported_na_total":sum(na_counts.values()),
            "justified_na_total":na_counts["JUSTIFIED_NA"],
            "potential_conflict_total":na_counts["POTENTIAL_CONFLICT"],
            "confirmed_invalid_na_total":na_counts["CONFIRMED_INVALID_NA"],
            "unresolved_na_total":na_counts["UNRESOLVED_NA"],
            "canonical_status_counts":dict(sorted(na_counts.items())),
            "authority_source":"canonical_client_detailed.json#/na_validation",
        }
        decision_index={str(row.get("requirement_id")):row for row in source.get("requirement_decisions") or []}
        grouped=defaultdict(list)
        for row in canonical_na:
            if row.get("reported_na") and row.get("status") not in {"JUSTIFIED_NA","NOT_REPORTED_NA"}:
                item=copy.deepcopy(row);item["clause_id"]=(decision_index.get(str(row.get("requirement_id"))) or {}).get("clause_id")
                grouped[str(row.get("status") or "UNRESOLVED_NA")].append(item)
        out["na_review_details"]={key:{"record_count":len(rows),"items":rows} for key,rows in sorted(grouped.items())}
        out["key_gaps"]=[row for row in out.get("key_gaps") or [] if row.get("gap_type")!="INVALID_NA" and "INVALID_NA" not in (row.get("gap_types") or [])]
        canonical_na_index={str(row.get("requirement_id")):row for row in canonical_na}
        canonical_root_index={str(row.get("requirement_id")):row for row in source.get("root_causes") or []}
        for finding in out.get("product_relevant_clause_findings") or []:
            ids=[str(x) for x in (finding.get("traceability") or {}).get("requirement_ids") or []]
            if finding.get("status")=="INVALID_NA" or finding.get("gap")=="INVALID_NA":
                statuses=sorted({canonical_na_index[x].get("status") for x in ids if x in canonical_na_index})
                roots=sorted({(canonical_root_index[x].get("primary_root_cause") or {}).get("type") for x in ids if x in canonical_root_index and canonical_root_index[x].get("primary_root_cause")})
                finding["status"]=statuses[0] if len(statuses)==1 else "UNRESOLVED_NA"
                finding["gap"]=roots[0] if len(roots)==1 else "ENGINE_APPLICABILITY_GAP"
        out["summary_projection_source_map"]={target:"canonical_client_detailed.json#/"+key for target,key in direct.items()}
        out["summary_projection_source_map"].update({"run":"canonical_client_detailed.json#/run_context","canonical_runtime_status":"canonical_client_detailed.json#/canonical_runtime_status","canonical_identity_authority":"canonical_client_detailed.json#/canonical_identity_authority","applicability_authority":"canonical_client_detailed.json#/applicability_results","evidence_sufficiency_authority":"canonical_client_detailed.json#/evidence_sufficiency_results","technical_execution_references":"canonical_client_detailed.json#/traceability/technical_execution_ids","na_validation":"canonical_client_detailed.json#/na_validation","na_summary":"canonical_client_detailed.json#/na_validation","na_review_details":"canonical_client_detailed.json#/na_validation"})
        trace=out.setdefault("traceability",{});trace.update({"source_artifact":"summary/canonical_client_detailed.json","source_run_id":source.get("run_context",{}).get("run_id"),"source_sha256":source.get("projection_sha256"),"canonical_requirement_state_sha256":(source.get("traceability") or {}).get("canonical_requirement_state_sha256"),"source_state_sha256":(source.get("traceability") or {}).get("canonical_requirement_state_sha256"),"canonical_runtime_status_sha256":(source.get("traceability") or {}).get("canonical_runtime_status_sha256"),"canonical_identity_authority_sha256":(source.get("traceability") or {}).get("canonical_identity_authority_sha256"),"projection_policy_version":"STEP50C_CANONICAL_SUMMARY_PROJECTION_V1","summary_recomputed_authority_fields":0,"summary_legacy_authority_overrides":0,"legacy_authority_sources_consumed":0,"canonical_reinterpretation_performed":False})
        out["schema_version"]="FINAL_SUMMARY_BRIEF_CONTEXT_V3"
        out["summary_contract_version"]="STEP50C_CANONICAL_SUMMARY_V1"
        return out

    @staticmethod
    def _run(run):
        return {k: copy.deepcopy(run.get(k)) for k in ("run_id", "report_identifier", "source_report_number", "source_report_document_id", "effective_kb_id", "generation_timestamp", "pipeline_status")}

    @classmethod
    def _product(cls, product, records):
        facts = product.get("confirmed_facts") or {}
        confirmed = []
        for key, fact in sorted(facts.items()):
            if str(fact.get("status")) not in {"CONFIRMED", "INFERRED_STRONG"}:
                continue
            confirmed.append({"fact_key": key, "value": copy.deepcopy(fact.get("normalized_value") if fact.get("normalized_value") is not None else fact.get("value")), "status": fact.get("status"), "confidence": fact.get("confidence")})
        missing = Counter(key for row in records for key in ((row.get("applicability") or {}).get("missing_required_facts") or []))
        for item in product.get("canonical_missing_required_facts") or []:
            key = item.get("fact_key")
            if key:
                missing[key] = max(missing[key], len(set(item.get("requirement_consumers") or [])))
        return {
            "reported_product_name": product.get("reported_product_name"), "canonical_classification": product.get("canonical_classification"),
            "classification_status": product.get("classification_status"), "classification_confidence": product.get("classification_confidence"),
            "classification_basis": copy.deepcopy(product.get("classification_basis") or []), "models": copy.deepcopy(product.get("model_numbers") or []),
            "declared_models": copy.deepcopy(product.get("declared_models") or []), "tested_models": copy.deepcopy(product.get("tested_models") or []),
            "representative_models": copy.deepcopy(product.get("representative_models") or []), "type_references": copy.deepcopy(product.get("type_references") or []),
            "model_relationships": copy.deepcopy(product.get("model_relationships") or []), "manufacturer": product.get("manufacturer"),
            "brand_or_trademark": product.get("brand"), "key_confirmed_facts": confirmed,
            "source_report_identity": copy.deepcopy(product.get("source_report_identity") or {}),
            "missing_product_facts_affecting_applicability": [{"fact_key": k, "affected_requirement_count": n} for k,n in sorted(missing.items(), key=lambda x:(-x[1],x[0]))],
        }

    @staticmethod
    def _standards(standards, authority):
        def compact(value):
            if not value: return None
            return {k: value.get(k) for k in ("standard_id", "standard_number", "title", "edition", "year", "document_type")}
        return {"base_standard":compact(standards.get("base_standard")),"part_2_standard":compact(standards.get("companion_standard")),"effective_kb_id":standards.get("effective_kb_id"),"effective_kb_status":standards.get("effective_kb_status"),"kb_maturity":authority.get("maturity") or standards.get("effective_kb_maturity"),"standard_validation_status":standards.get("standard_validation_status")}

    @staticmethod
    def _assessment(source):
        disposition=source.get("final_disposition") or {};authority=source.get("kb_authority") or {};validity=source.get("report_validity") or {}
        return {"final_disposition":disposition.get("value"),"reason":disposition.get("reason"),"authoritative_pass_allowed":authority.get("authoritative_pass_allowed"),"blocking_conditions":copy.deepcopy(disposition.get("blocking_conditions") or []),"report_validity_status":validity.get("overall_compatibility"),"compliance_score":copy.deepcopy((source.get("metrics") or {}).get("compliance_score")),"evaluation_coverage":copy.deepcopy((source.get("metrics") or {}).get("evaluation_coverage")),"evaluation_confidence":copy.deepcopy((source.get("metrics") or {}).get("evaluation_confidence")),"technical_product_failure_inferred":validity.get("technical_product_failure_inferred",False)}

    @staticmethod
    def _requirement_summary(population):
        return {"effective_requirements":population.get("total_effective_requirements",0),"active":population.get("active_requirements",0),"inactive":population.get("inactive",max(0,population.get("total_effective_requirements",0)-population.get("active_requirements",0))),"applicable":population.get("applicable",0),"not_applicable":population.get("not_applicable",0),"unknown":population.get("unknown_applicability",0),"needs_review":population.get("needs_review",0),"compliant":population.get("compliant",0),"technical_violations":population.get("violated",0),"missing_evidence":population.get("missing_evidence",0),"rejected_evidence":population.get("rejected_evidence",0),"unsupported_rules":population.get("unsupported_rules",0),"other_unresolved":population.get("other_unresolved",0),"canonical_state_counts":copy.deepcopy(population.get("canonical_state_counts") or {}),"canonical_state_policy_version":population.get("canonical_state_policy_version"),"canonical_projection_policy_version":population.get("canonical_projection_policy_version")}

    @classmethod
    def _product_findings(cls, records, canonical_classification=None, apply_limit=True):
        selected=[x for x in records if (x.get("effective_source") not in {None,"BASE"} or (x.get("applicability") or {}).get("product_facts_used") or (x.get("applicability") or {}).get("missing_required_facts")) and x.get("final_requirement_decision")!="INACTIVE"]
        groups=defaultdict(list)
        for row in selected:
            app=row.get("applicability") or {};gap=row.get("gap") or {}
            key=(str(row.get("clause_id")),app.get("status"),row.get("final_requirement_decision"),gap.get("gap_type"),tuple(row.get("root_cause_ids") or []),row.get("priority"))
            groups[key].append(row)
        output=[]
        for key,items in groups.items():
            clause,app,decision,gap,roots,priority=key;first=sorted(items,key=lambda x:str(x.get("requirement_id")))[0];ids=sorted(str(x.get("requirement_id")) for x in items)
            applicability=first.get("applicability") or {};scope=applicability.get("scope_evaluation") or {};fact_ids=[x for x in (applicability.get("product_facts_used") or []) if x!="canonical_product_classification"]
            classification_linked=scope.get("basis")=="CANONICAL_PRODUCT_CLASSIFICATION" and scope.get("relationship")=="MATCH"
            part2=first.get("effective_source") not in {None,"BASE"};annex="ANNEX" in str(first.get("requirement_id") or "");product_fact_linked=bool(fact_ids or applicability.get("missing_required_facts"));supporting=str(first.get("requirement_type") or "").upper() in {"TEST","TEST_METHOD"}
            if annex:finding_scope="ANNEX_METHOD_REQUIREMENT"
            elif product_fact_linked:finding_scope="PRODUCT_CONSTRUCTION_REQUIREMENT"
            elif classification_linked:finding_scope="DIRECT_PRODUCT_REQUIREMENT"
            elif supporting:finding_scope="SUPPORTING_TEST_REQUIREMENT"
            elif part2:finding_scope="DIRECT_PRODUCT_REQUIREMENT"
            else:finding_scope="GENERAL_REQUIREMENT"
            reasons=[]
            if part2:reasons.append("PART2_ORIGIN")
            if classification_linked:reasons.append("PRODUCT_CLASSIFICATION_LINKED")
            if fact_ids:reasons.append("PRODUCT_FACT_GATED")
            if applicability.get("missing_required_facts"):reasons.append("MISSING_PRODUCT_FACT_GATED")
            if annex:reasons.append("ANNEX_ORIGIN")
            if supporting:reasons.append("SUPPORTING_TEST_REQUIREMENT")
            output.append({"clause":clause,"topic":cls._short(first.get("requirement_text")),"applicability":app,"status":gap if gap and gap!="NO_GAP" else decision,"requirement_summary":cls._short(first.get("requirement_text")),"evidence_summary":(first.get("evidence") or {}).get("status"),"gap":gap,"priority":priority,"finding_scope_type":finding_scope,"selection_reasons":reasons,"product_classification_linked":classification_linked,"product_fact_linked":product_fact_linked,"part2_origin":part2,"construction_specific":finding_scope=="PRODUCT_CONSTRUCTION_REQUIREMENT","supporting_test_requirement":supporting,"annex_method_requirement":annex,"scope_evaluation":copy.deepcopy(scope) or None,"next_action":first.get("next_action"),"traceability":{"requirement_ids":ids[:5],"omitted_requirement_id_count":max(0,len(ids)-5),"root_cause_ids":list(roots)}})
        output.sort(key=lambda x:(0 if x.get("product_classification_linked") else 1,cls.PRIORITY_ORDER.get(x.get("priority"),9),cls._clause_key(x.get("clause")),x.get("status") or "",x["traceability"]["requirement_ids"]))
        total=len(output);kept=output[:cls.MAX_PRODUCT_FINDINGS] if apply_limit else output
        return kept,{"candidate_clause_outcome_groups":total,"included":len(kept),"omitted":total-len(kept),"maximum":cls.MAX_PRODUCT_FINDINGS,"selection_basis":"existing source type, applicability facts, priority, clause and outcome"}

    @classmethod
    def _product_relevant_findings(cls, legacy_findings):
        """Filter the broad legacy projection using only existing relevance metadata."""

        candidates = copy.deepcopy(list(legacy_findings or []))
        primary = []
        deferred = []
        excluded_part2_only = 0
        for finding in candidates:
            scope_type = finding.get("finding_scope_type")
            classification = bool(finding.get("product_classification_linked"))
            fact = bool(finding.get("product_fact_linked"))
            construction = scope_type == "PRODUCT_CONSTRUCTION_REQUIREMENT" and fact
            component = scope_type == "COMPONENT_REQUIREMENT" and (
                fact or "COMPONENT_LINKED" in (finding.get("selection_reasons") or [])
            )
            if classification or fact or construction or component:
                reasons = [x for x in (finding.get("selection_reasons") or []) if x != "PART2_ORIGIN"]
                if construction and "PRODUCT_CONSTRUCTION_LINKED" not in reasons:
                    reasons.append("PRODUCT_CONSTRUCTION_LINKED")
                if component and "COMPONENT_LINKED" not in reasons:
                    reasons.append("COMPONENT_LINKED")
                finding["selection_reasons"] = reasons
                primary.append(finding)
            elif finding.get("supporting_test_requirement") or finding.get("annex_method_requirement"):
                deferred.append(finding)
            elif finding.get("part2_origin"):
                excluded_part2_only += 1

        by_clause = defaultdict(list)
        for finding in primary:
            by_clause[str(finding.get("clause"))].append(finding)
        supporting = []
        consolidated = 0
        for finding in deferred:
            parents = by_clause.get(str(finding.get("clause")), [])
            if not parents:
                continue
            compatible = [parent for parent in parents if cls._outcomes_compatible(parent, finding)]
            if finding.get("supporting_test_requirement") and compatible:
                parent = compatible[0]
                methods = parent.setdefault("supporting_methods", [])
                method = {
                    "requirement_summary": finding.get("requirement_summary"),
                    "requirement_ids": copy.deepcopy((finding.get("traceability") or {}).get("requirement_ids") or []),
                    "evidence_summary": finding.get("evidence_summary"),
                }
                if method not in methods:
                    methods.append(method)
                parent["supporting_test_requirement"] = True
                if "SUPPORTING_TEST_FOR_RELEVANT_REQUIREMENT" not in parent["selection_reasons"]:
                    parent["selection_reasons"].append("SUPPORTING_TEST_FOR_RELEVANT_REQUIREMENT")
                consolidated += 1
                continue
            linked = copy.deepcopy(finding)
            linked["parent_product_relevant_clause"] = str(parents[0].get("clause"))
            reason = "ANNEX_METHOD_FOR_RELEVANT_REQUIREMENT" if linked.get("annex_method_requirement") else "SUPPORTING_TEST_FOR_RELEVANT_REQUIREMENT"
            linked["selection_reasons"] = [reason]
            supporting.append(linked)

        output = primary + supporting
        type_order = {"DIRECT_PRODUCT_REQUIREMENT": 0, "PRODUCT_CONSTRUCTION_REQUIREMENT": 1, "COMPONENT_REQUIREMENT": 2, "SUPPORTING_TEST_REQUIREMENT": 3, "ANNEX_METHOD_REQUIREMENT": 4, "GENERAL_REQUIREMENT": 5}
        output.sort(key=lambda x:(cls.PRIORITY_ORDER.get(x.get("priority"),9),type_order.get(x.get("finding_scope_type"),9),0 if x.get("status")=="TECHNICAL_VIOLATION" else 1,0 if x.get("gap") in {"MISSING_EVIDENCE","MISSING_PRODUCT_FACT","HUMAN_REVIEW_REQUIRED"} else 1,cls._clause_key(x.get("clause")),x.get("status") or "",(x.get("traceability") or {}).get("requirement_ids") or []))
        total = len(output)
        kept = output[:cls.MAX_PRODUCT_FINDINGS]
        counts = Counter(x.get("finding_scope_type") for x in kept)
        return kept, {
            "candidate_groups": total, "included": len(kept), "omitted": max(0,total-len(kept)),
            "maximum": cls.MAX_PRODUCT_FINDINGS, "excluded_part2_only": excluded_part2_only,
            "direct_product": counts["DIRECT_PRODUCT_REQUIREMENT"],
            "construction": counts["PRODUCT_CONSTRUCTION_REQUIREMENT"],
            "component": counts["COMPONENT_REQUIREMENT"],
            "supporting": counts["SUPPORTING_TEST_REQUIREMENT"],
            "annex_method": counts["ANNEX_METHOD_REQUIREMENT"],
            "supporting_consolidated": consolidated,
            "selection_basis": "existing classification, product-fact, construction, component, and parent-support metadata",
        }

    @staticmethod
    def _outcomes_compatible(primary, supporting):
        """Allow method consolidation only when atomic outcomes do not conflict."""

        return all(primary.get(key) == supporting.get(key) for key in ("clause", "applicability", "status", "gap"))

    @classmethod
    def _compliance_findings(cls, records):
        selected=[x for x in records if x.get("final_requirement_decision")=="COMPLIANT"]
        selected.sort(key=lambda x:(cls.PRIORITY_ORDER.get(x.get("priority"),9),0 if x.get("effective_source") not in {None,"BASE"} else 1,cls._clause_key(x.get("clause_id")),str(x.get("requirement_id"))))
        output=[{"clause":x.get("clause_id"),"finding":cls._short(x.get("requirement_text")),"status":"COMPLIANT","evidence_status":(x.get("evidence") or {}).get("status"),"technical_results":copy.deepcopy((x.get("technical_evaluation") or {}).get("results") or []),"priority":x.get("priority"),"traceability":{"requirement_id":x.get("requirement_id")}} for x in selected[:cls.MAX_COMPLIANCE_FINDINGS]]
        return output,{"candidates":len(selected),"included":len(output),"omitted":max(0,len(selected)-len(output)),"maximum":cls.MAX_COMPLIANCE_FINDINGS}

    @classmethod
    def _root_causes(cls, roots, records):
        output=[]
        for root in roots:
            ids=root.get("affected_requirement_ids") or [];clauses=sorted({str(records.get(str(x),{}).get("clause_id")) for x in ids if records.get(str(x),{}).get("clause_id")},key=cls._clause_key)
            gap_types=sorted({str((records.get(str(x),{}).get("gap") or {}).get("gap_type")) for x in ids if (records.get(str(x),{}).get("gap") or {}).get("is_gap")})
            output.append({"root_cause_id":root.get("root_cause_id"),"title":root.get("title"),"severity":root.get("severity"),"decision_effect":root.get("decision_effect"),"hierarchy":root.get("hierarchy"),"parent_root_cause_id":root.get("parent_root_cause_id"),"upstream_cause_ids":copy.deepcopy(root.get("upstream_cause_ids") or []),"decision_effect_policy_version":root.get("decision_effect_policy_version"),"dominant_blocker_policy_version":root.get("dominant_blocker_policy_version"),"affected_requirement_count":len(ids),"affected_clause_count":len(clauses),"representative_clauses":clauses[:cls.MAX_REPRESENTATIVE_CLAUSES],"omitted_clause_count":max(0,len(clauses)-cls.MAX_REPRESENTATIVE_CLAUSES),"gap_types":gap_types,"technical_basis":copy.deepcopy(root.get("technical_basis") or {}),"corrective_action":copy.deepcopy(root.get("corrective_action"))})
        output.sort(key=lambda x:(cls._severity(x.get("severity")),-x["affected_requirement_count"],str(x.get("root_cause_id"))))
        return output

    @staticmethod
    def _gaps(roots, gap_summary):
        output=[]
        for root in roots:
            types=list(root.get("gap_types") or ["HUMAN_REVIEW_REQUIRED"])
            output.append({"gap_type":types[0] if len(types)==1 else "MULTIPLE_DETERMINISTIC_GAPS","gap_types":types,"root_cause_id":root.get("root_cause_id"),"finding":root.get("title"),"affected_requirement_count":root.get("affected_requirement_count"),"affected_clause_count":root.get("affected_clause_count"),"representative_clauses":copy.deepcopy(root.get("representative_clauses") or []),"severity":root.get("severity"),"decision_effect":root.get("decision_effect"),"required_action":copy.deepcopy(root.get("corrective_action"))})
        return output

    @staticmethod
    def _na_summary(findings):
        material=[x for x in findings if x.get("reported")]
        counts=Counter(str(x.get("status") or "UNKNOWN") for x in material)
        potential = counts["POTENTIAL_CONFLICT"]
        confirmed_invalid = counts["INVALID_NA"]
        return {"reported_na":len(material),"validated_na":counts["JUSTIFIED"],"invalid_na":confirmed_invalid,"potential_conflict_na":potential,"confirmed_invalid_na":confirmed_invalid,"insufficient_product_data":counts["INSUFFICIENT_PRODUCT_DATA"],"insufficient_report_evidence":counts["INSUFFICIENT_REPORT_EVIDENCE"],"needs_review":counts["NEEDS_REVIEW"],"insufficient_na_evidence":counts["INSUFFICIENT_REPORT_EVIDENCE"],"unknown_na":sum(v for k,v in counts.items() if k in {"NEEDS_REVIEW","INSUFFICIENT_KB_RULE","INSUFFICIENT_PRODUCT_DATA","UNKNOWN"}),"material_status_counts":dict(sorted(counts.items())),"legacy_invalid_na_semantics":"confirmed invalid N/A only; potential conflicts are reported separately"}

    @classmethod
    def _na_review_details(cls, findings, records):
        statuses=("NEEDS_REVIEW","POTENTIAL_CONFLICT","INSUFFICIENT_PRODUCT_DATA","INSUFFICIENT_REPORT_EVIDENCE","INVALID_NA")
        grouped=defaultdict(list)
        for finding in findings:
            if finding.get("reported") and str(finding.get("status")) in statuses:
                grouped[str(finding.get("status"))].append(finding)
        output={}
        for status in statuses:
            rows=sorted(grouped[status],key=lambda x:(cls._clause_key((records.get(str(x.get("requirement_id"))) or {}).get("clause_id")),str(x.get("requirement_id"))))
            clauses=sorted({str((records.get(str(x.get("requirement_id"))) or {}).get("clause_id")) for x in rows if (records.get(str(x.get("requirement_id"))) or {}).get("clause_id")},key=cls._clause_key)
            reasons=Counter(str(x.get("reason") or "") for x in rows)
            detail={"record_count":len(rows),"unique_clause_count":len(clauses),"clause_ids":clauses,"representative_clauses":clauses[:cls.MAX_REPRESENTATIVE_CLAUSES],"omitted_clause_count":max(0,len(clauses)-cls.MAX_REPRESENTATIVE_CLAUSES),"top_reasons":[{"reason":reason,"record_count":count} for reason,count in sorted(reasons.items(),key=lambda x:(-x[1],x[0]))[:3]],"items":[],"omitted_item_count":0}
            if len(rows)<=cls.MAX_NA_DETAIL_ITEMS:
                for finding in rows:
                    requirement=records.get(str(finding.get("requirement_id"))) or {};evidence=requirement.get("evidence") or {};app=requirement.get("applicability") or {}
                    detail["items"].append({"clause_id":requirement.get("clause_id"),"requirement_id":finding.get("requirement_id"),"na_status":status,"reported_result":"N/A","reason":finding.get("reason"),"applicability":finding.get("engine_applicability") or app.get("status"),"evidence_status":evidence.get("status"),"next_action":requirement.get("next_action"),"root_cause_ids":copy.deepcopy(requirement.get("root_cause_ids") or [])})
            else:detail["omitted_item_count"]=len(rows)
            output[status]=detail
        return output

    @classmethod
    def _parameter_projection(cls, findings):
        material_types={"TRUE_CONFLICT","NUMERIC_LIMIT_CONFLICT","DECLARED_VS_MEASURED_CONFLICT","TEST_BASIS_VS_APPLIED_CONFLICT","MATERIAL_ROLE_COMPATIBLE_VARIATION","DECISION_RELEVANT_MISSING_PARAMETER","EVALUATION_BLOCKING_PARAMETER_AMBIGUITY"}
        material=[];groups=defaultdict(list)
        for finding in findings:
            effect=finding.get("effect") or {};reason=(finding.get("reconciliation") or {}).get("reason");parameter=(finding.get("subject") or {}).get("parameter")
            item={"finding_id":finding.get("finding_id"),"finding_type":finding.get("finding_type"),"status":finding.get("status"),"materiality":finding.get("materiality"),"clauses":copy.deepcopy(finding.get("clause_ids") or []),"parameter":parameter,"evaluation_validity":effect.get("evaluation_validity"),"recommended_disposition":effect.get("recommended_disposition"),"reason":reason}
            if finding.get("finding_type") in material_types or str(finding.get("materiality")) in {"MATERIAL","HIGH","CRITICAL"}:material.append(item)
            else:groups[(finding.get("finding_type"),parameter,reason,finding.get("status"),effect.get("recommended_disposition"))].append(item)
        grouped=[]
        for key,items in groups.items():
            finding_type,parameter,reason,status,disposition=key;clauses=sorted({str(c) for item in items for c in item.get("clauses") or []},key=cls._clause_key)
            grouped.append({"finding_type":finding_type,"parameter":parameter,"status":status,"recommended_disposition":disposition,"reason":reason,"affected_finding_count":len(items),"affected_clause_count":len(clauses),"representative_clauses":clauses[:cls.MAX_REPRESENTATIVE_CLAUSES],"omitted_clause_count":max(0,len(clauses)-cls.MAX_REPRESENTATIVE_CLAUSES),"grouped":True})
        material.sort(key=lambda x:(str(x.get("finding_type")),str(x.get("finding_id"))))
        grouped.sort(key=lambda x:(str(x.get("finding_type")),str(x.get("parameter")),str(x.get("status")),str(x.get("recommended_disposition"))))
        raw=len(findings);collapsed=sum(max(0,x["affected_finding_count"]-1) for x in grouped)
        return material+grouped,{"raw_finding_count":raw,"client_material_finding_count":len(material),"grouped_finding_count":len(grouped),"omitted_non_material_count":collapsed}

    @classmethod
    def _parameters(cls, findings):
        return cls._parameter_projection(findings)[0]

    @staticmethod
    def _report_validity(source):
        validity=copy.deepcopy(source.get("report_validity") or {});findings=source.get("structure_findings") or [];detail=findings[0] if findings else {};summary=detail.get("summary") or {}
        validity.update({"semantic_mismatch_count":summary.get("mismatched") or summary.get("semantic_mismatch_count"),"unsafe_same_number_matches_blocked":summary.get("unsafe_matches_blocked"),"evidence_usability_effect":"STRUCTURE_GATE_RESTRICTIONS_RETAINED" if validity.get("overall_compatibility") in {"STRUCTURE_MISMATCH","PARTIALLY_COMPATIBLE"} else "NO_RESTRICTION_REPORTED","structure_finding_count":len(findings)})
        return validity

    @staticmethod
    def _actions(actions):
        unique={}
        for x in actions:
            signature=(x.get("action_type"),x.get("title"),x.get("description"))
            unique.setdefault(signature,{"action_id":x.get("action_id"),"priority":x.get("priority_label") or x.get("priority_level"),"action_type":x.get("action_type"),"title":x.get("title"),"description":x.get("description"),"affected_issue_count":x.get("affected_issue_count"),"affected_clause_count":len(set(x.get("affected_clauses") or [])),"representative_clauses":sorted(set(x.get("affected_clauses") or []),key=GenericFinalSummaryBriefBuilder._clause_key)[:5],"affected_root_cause_ids":copy.deepcopy(x.get("affected_aggregate_group_ids") or [])})
        return sorted(unique.values(),key=lambda x:(GenericFinalSummaryBriefBuilder.PRIORITY_ORDER.get(x.get("priority"),9),str(x.get("action_id"))))

    @staticmethod
    def _priority(priority, actions):
        action_index={x.get("action_id"):x for x in actions}
        return [{"action_id":x.get("action_id"),"priority":x.get("priority"),"finding":x.get("title"),"reason":"Deterministic Step 40 priority retained.","next_action":(action_index.get(x.get("action_id")) or {}).get("title"),"affected_root_cause_ids":copy.deepcopy(x.get("affected_root_cause_ids") or [])} for x in priority]

    @classmethod
    def _unresolved(cls, unresolved, records):
        cases=unresolved.get("cases") or [];counts=Counter(str(x.get("category") or "UNKNOWN") for x in cases);clauses=defaultdict(set)
        for x in cases:
            clause=records.get(str(x.get("effective_requirement_id")),{}).get("clause_id")
            if clause:clauses[str(x.get("category") or "UNKNOWN")].add(str(clause))
        categories=("SEMANTIC_INTERPRETATION_REQUIRED","PRODUCT_FACT_CLARIFICATION_REQUIRED","EVIDENCE_INTERPRETATION_REQUIRED","KB_RULE_REVIEW_REQUIRED","HUMAN_REVIEW_REQUIRED")
        return {"total":len(cases),"categories":{k:{"count":counts[k],"representative_clauses":sorted(clauses[k],key=cls._clause_key)[:5],"omitted_clause_count":max(0,len(clauses[k])-5)} for k in categories},"other_unresolved_count":sum(v for k,v in counts.items() if k not in categories)}

    @staticmethod
    def _source_hash(source, path):
        if path and Path(path).is_file():return hashlib.sha256(Path(path).read_bytes()).hexdigest()
        payload=json.dumps(source,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode();return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _short(value, limit=240):
        text=re.sub(r"\s+"," ",str(value or "")).strip();return text if len(text)<=limit else text[:limit-1].rstrip()+"…"

    @staticmethod
    def _clause_key(value):
        return tuple(int(x) if x.isdigit() else x for x in re.split(r"(\d+)",str(value or "")))

    @staticmethod
    def _severity(value):return {"CRITICAL":0,"HIGH":1,"MEDIUM":2,"LOW":3,None:4}.get(value,4)

    @staticmethod
    def _read(path):return json.loads(Path(path).read_text(encoding="utf-8"))
    @staticmethod
    def to_json(value,indent=2):return json.dumps(value,ensure_ascii=False,sort_keys=True,indent=indent)
    @classmethod
    def save_json(cls,value,path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(cls.to_json(value)+"\n",encoding="utf-8");return path


__all__=["GenericFinalSummaryBriefBuilder","SCHEMA_VERSION","SUMMARY_CONTRACT_VERSION"]
