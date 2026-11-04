"""Thin, generic orchestration for the validated compliance pipeline."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .generic_coverage_gap_analyzer import GenericCoverageGapAnalyzer
from .generic_clause_evaluation_summary_builder import GenericClauseEvaluationSummaryBuilder
from .generic_cross_evidence_consistency_validator import GenericCrossEvidenceConsistencyValidator
from .generic_evidence_integrity_rejection_resolver import GenericEvidenceIntegrityRejectionResolver
from .generic_executive_summary_builder import GenericExecutiveSummaryBuilder
from .generic_final_compliance_response_builder import GenericFinalComplianceResponseBuilder
from .generic_final_summary_context_builder import GenericFinalSummaryContextBuilder
from .generic_final_summary_brief_builder import GenericFinalSummaryBriefBuilder, SCHEMA_VERSION as FINAL_SUMMARY_BRIEF_SCHEMA_VERSION
from .generic_final_issue_resolution import (Actionability, ComplianceConclusion,
    FinalActionType, FinalComplianceIssue, FinalIssueProvenance, FinalIssueType,
    FinalNextAction, FinalSeverity, GenericFinalIssueResolver)
from .generic_final_requirement_decision_engine import GenericFinalRequirementDecisionEngine
from .generic_canonical_requirement_state import GenericCanonicalRequirementStateStore
from .generic_canonical_product_foundation import GenericCanonicalProductFoundation
from .generic_canonical_identity_authority import GenericCanonicalIdentityAuthority
from .generic_canonical_product_classifier import GenericCanonicalProductClassifier
from .generic_canonical_applicability_authority import GenericCanonicalApplicabilityAuthority
from .generic_canonical_evidence_sufficiency import GenericCanonicalEvidenceSufficiency
from .generic_canonical_technical_authority import GenericCanonicalTechnicalAuthority
from .generic_canonical_root_authority import GenericCanonicalRootAuthority
from .generic_canonical_metrics_authority import GenericCanonicalMetricsAuthority
from .generic_canonical_dependency_authority import GenericCanonicalDependencyAuthority
from .generic_canonical_standard_authority import (BLOCKING_STATES,
    GenericCanonicalStandardAuthority)
from .generic_canonical_kb_maturity_authority import (
    BLOCKING_MATURITY_STATES, GenericCanonicalKBMaturityAuthority)
from .generic_canonical_runtime_authority import GenericCanonicalRuntimeAuthority
from .generic_canonical_client_projection import GenericCanonicalClientProjection
from .generic_group_aware_applicability_resolver import GenericGroupAwareApplicabilityResolver
from .generic_group_aware_na_validator import GenericGroupAwareNAValidator
from .generic_iec_effective_kb_builder import GenericIECEffectiveKnowledgeBaseBuilder
from .generic_iec_standalone_effective_kb_builder import GenericIECStandaloneEffectiveKnowledgeBaseBuilder
from .generic_iec_kb_builder import GenericIECKnowledgeBaseBuilder
from .generic_iec_kb_validator import GenericIECKnowledgeBaseValidator
from .generic_na_conflict_auditor import GenericNAConflictAuditor
from .generic_overall_readiness_builder import GenericOverallReadinessBuilder
from .generic_overall_report_status import GenericOverallReportStatusEngine
from .generic_next_action_prioritizer import GenericNextActionPrioritizer
from .generic_report_evidence_extractor import GenericReportEvidenceExtractor
from .generic_report_evidence_scope_resolver import GenericReportEvidenceScopeResolver
from .generic_report_na_validator import GenericReportNAValidator
from .generic_report_issue_aggregator import GenericReportIssueAggregator
from .generic_report_product_profile_builder import GenericReportProductProfileBuilder
from .generic_report_visual_evidence_extractor import GenericReportVisualEvidenceExtractor
from .generic_report_visual_inventory_builder import GenericReportVisualInventoryBuilder
from .generic_visual_evidence_reconciler import GenericVisualEvidenceReconciler
from .generic_visual_canonical_promoter import GenericVisualCanonicalPromoter
from .generic_visual_promotion_impact_builder import GenericVisualPromotionImpactBuilder
from .generic_report_standard_structure_compatibility import GenericReportStandardStructureCompatibilityValidator
from .generic_requirement_applicability_evaluator import GenericRequirementApplicabilityEvaluator
from .generic_requirement_evidence_matcher import GenericRequirementEvidenceMatcher
from .generic_requirement_grouping_resolver import GenericRequirementGroupingResolver
from .generic_scope_aware_na_validator import GenericScopeAwareNAValidator
from .generic_technical_constraint_evaluator import GenericTechnicalConstraintEvaluator


class StandardValidationStatus(str, Enum):
    VALID="VALID";PARTIAL_MATCH="PARTIAL_MATCH";STANDARD_SET_INCOMPLETE="STANDARD_SET_INCOMPLETE";STANDARD_MISMATCH="STANDARD_MISMATCH";UNRESOLVED="UNRESOLVED"
class PipelineStatus(str, Enum):
    SUCCESS="SUCCESS";SUCCESS_WITH_REVIEW="SUCCESS_WITH_REVIEW";BLOCKED="BLOCKED";FAILED="FAILED"
class StandardSetMode(str, Enum):
    STANDALONE="STANDALONE";BASE_PLUS_COMPANION="BASE_PLUS_COMPANION"

@dataclass
class StepExecutionRecord:
    step_name:str;status:str;started_at:str;completed_at:Optional[str]=None;output_artifact:Optional[str]=None;error:Optional[str]=None
@dataclass
class StandardValidationResult:
    status:StandardValidationStatus;supplied_standards:List[str]=field(default_factory=list);detected_report_standards:List[str]=field(default_factory=list);diagnostics:List[str]=field(default_factory=list)
@dataclass
class PipelineRunResult:
    run_id:str;pipeline_status:PipelineStatus;output_directory:str;manifest_path:str;final_artifact:Optional[str]=None;standard_validation:Optional[StandardValidationResult]=None

class PipelineBlockedError(RuntimeError):pass

class GenericCompliancePipelineRunner:
    """Call existing Steps 1–22 engines in their dependency order."""
    # Keep the accepted Steps 1-24 contract prefix stable for compatibility;
    # the canonical foundations are dependency preparations for applicability.
    STEP_ORDER=("base_kb","base_validation","delta_kb","delta_validation","pair_validation","effective_kb","report_evidence","standard_validation","product_profile","applicability","evidence_match","technical_constraints","na_validation","na_conflict_audit","requirement_grouping","group_aware_applicability","group_aware_na_validation","report_evidence_scope","scope_aware_na_validation","final_decision","coverage_gap","overall_readiness","canonical_requirement_state","cross_evidence_consistency","canonical_product_fact_ledger","canonical_identity_store","canonical_identity_relationships","canonical_product_foundation_integrity","canonical_product_classification","canonical_product_classification_integrity","legacy_applicability","canonical_applicability","canonical_applicability_integrity","canonical_evidence_sufficiency","canonical_evidence_sufficiency_integrity","canonical_technical_authority","canonical_technical_authority_integrity","canonical_root_cause_authority","canonical_root_cause_integrity","canonical_na_authority","canonical_na_integrity","canonical_product_relevance","canonical_product_relevance_integrity","clause_evaluation_summary","evidence_integrity_rejection","final_issue_resolution","report_issue_aggregation","next_action_prioritization","executive_summary","overall_report_status","final_saas_response","final_summary_context","final_summary_brief_context")
    STEP_ORDER=STEP_ORDER[:43]+("canonical_compliance_metrics","canonical_compliance_metrics_integrity")+STEP_ORDER[43:]
    STEP_ORDER=STEP_ORDER[:45]+("canonical_dependency_manifest","canonical_dependency_integrity","canonical_recompute_plan")+STEP_ORDER[45:]
    STEP_ORDER=STEP_ORDER[:STEP_ORDER.index("canonical_identity_relationships")]+("canonical_identity_authority",)+STEP_ORDER[STEP_ORDER.index("canonical_identity_relationships"):]
    STOP_ALIASES={"report_evidence":"report_evidence","effective_kb":"effective_kb","final_decision":"final_decision"}
    def __init__(self, *, components:Optional[Mapping[str,Any]]=None, clock:Optional[Callable[[],str]]=None):
        self.components=dict(components or {});self.clock=clock or (lambda:datetime.now(timezone.utc).isoformat())
    def run(self,base_standard,part2_standard=None,report=None,output=None,*,run_id=None,force=False,stop_after=None,reuse_kb=False,strict_standard_validation=False,ignore_standard_edition=False):
        if report is None:raise ValueError("report is required")
        if output is None:raise ValueError("output is required")
        mode=StandardSetMode.BASE_PLUS_COMPANION if part2_standard is not None else StandardSetMode.STANDALONE
        inputs={"base_standard":self._require_pdf(base_standard),"report":self._require_pdf(report)}
        if part2_standard is not None:inputs["part2_standard"]=self._require_pdf(part2_standard)
        out=Path(output).expanduser().resolve()
        if out.exists() and not force:raise FileExistsError(f"Output directory already exists: {out}")
        if out.exists() and force:
            self._validate_removal_target(out);shutil.rmtree(out)
        for sub in ("standards","report","decisions","manifest"):(out/sub).mkdir(parents=True,exist_ok=True)
        rid=run_id or self.deterministic_run_id(inputs)
        manifest={"run_id":rid,"started_at":self.clock(),"completed_at":None,"pipeline_status":"RUNNING","standard_set_mode":mode.value,"input_files":{k:self._file_record(v) for k,v in inputs.items()},"detected_standards":[],"supplied_standards":[],"standard_validation_result":None,"report_structure_compatibility_result":None,"step_execution_records":[],"final_result":None,"configuration":{"strict_standard_validation":strict_standard_validation,"ignore_standard_edition":ignore_standard_edition,"edition_override_requested":ignore_standard_edition,"configuration_flag_authority_allowed":False,"edition_override_scope":None,"edition_override_basis":None,"reuse_kb":reuse_kb,"force":force,"stop_after":stop_after}}
        manifest_path=out/"manifest/pipeline_manifest.json";artifacts={};records=[]
        def execute(name,path,fn,save):
            rec=StepExecutionRecord(name,"RUNNING",self.clock(),output_artifact=str(path.relative_to(out)) if path else None);records.append(rec);manifest["step_execution_records"]=[asdict(x) for x in records];self._write_json(manifest_path,manifest)
            try:value=fn();save(value,path) if path else None;rec.status="PASS";rec.completed_at=self.clock();artifacts[name]=value;self._progress(name,"PASS");self._write_json(manifest_path,{**manifest,"step_execution_records":[asdict(x) for x in records]});return value
            except PipelineBlockedError as exc:rec.status="BLOCKED";rec.error=str(exc);rec.completed_at=self.clock();raise
            except Exception as exc:rec.status="FAILED";rec.error=f"{type(exc).__name__}: {exc}";rec.completed_at=self.clock();raise
        try:
            kb_builder=self._component("kb_builder",GenericIECKnowledgeBaseBuilder)
            validator=self._component("kb_validator",GenericIECKnowledgeBaseValidator)
            primary_kind="primary" if mode is StandardSetMode.STANDALONE else "base"
            base=execute("base_kb",out/"standards/base_kb.json",lambda:self._build_or_reuse_kb(kb_builder,validator,inputs["base_standard"],out,primary_kind,reuse_kb and not force),kb_builder.save_json)
            base_validation=execute("base_validation",out/"standards/base_validation.json",lambda:validator.validate(base),self._generic_save)
            if not self._get(base_validation,"valid",False):raise PipelineBlockedError("Base knowledge base validation failed.")
            if self._stop(stop_after,"base_kb"):return self._stopped(manifest,manifest_path,out,rid,records)
            effective_builder=self._component("effective_builder",GenericIECEffectiveKnowledgeBaseBuilder) if mode is StandardSetMode.BASE_PLUS_COMPANION else self._component("standalone_effective_builder",GenericIECStandaloneEffectiveKnowledgeBaseBuilder)
            delta=None
            if mode is StandardSetMode.BASE_PLUS_COMPANION:
                delta=execute("delta_kb",out/"standards/delta_kb.json",lambda:self._build_or_reuse_kb(kb_builder,validator,inputs["part2_standard"],out,"delta",reuse_kb and not force),kb_builder.save_json)
                delta_validation=execute("delta_validation",out/"standards/delta_validation.json",lambda:validator.validate(delta),self._generic_save)
                if not self._get(delta_validation,"valid",False):raise PipelineBlockedError("Delta knowledge base validation failed.")
                pair_validation=execute("pair_validation",out/"standards/pair_validation.json",lambda:validator.validate_pair(base,delta),self._generic_save)
                if not self._get(pair_validation,"valid",False):raise PipelineBlockedError("Base and Part 2 compatibility validation failed.")
            effective=execute("effective_kb",out/"standards/effective_kb.json",lambda:effective_builder.build(base,delta) if delta is not None else effective_builder.build(base),effective_builder.save_json)
            if self._stop(stop_after,"effective_kb"):return self._stopped(manifest,manifest_path,out,rid,records)
            evidence_extractor=self._component("report_evidence_extractor",GenericReportEvidenceExtractor)
            report_evidence=execute("report_evidence",out/"report/report_evidence.json",lambda:evidence_extractor.extract(inputs["report"]),evidence_extractor.save_json)
            validation=self.validate_standard_set(base,delta,report_evidence,strict_standard_validation)
            manifest["supplied_standards"]=validation.supplied_standards;manifest["detected_standards"]=validation.detected_report_standards;manifest["standard_validation_result"]=self._plain(validation)
            execute("standard_validation",out/"standards/standard_validation.json",lambda:validation,self._generic_save)
            standard_authority_engine=self._component("canonical_standard_authority",GenericCanonicalStandardAuthority)
            if ignore_standard_edition:
                standard_authority=standard_authority_engine.evaluate(
                    effective,
                    report_evidence,
                    ignore_editions=True,
                    standard_validation=validation,
                )
            else:
                standard_authority=standard_authority_engine.evaluate(effective,report_evidence)
            standard_authority_integrity=standard_authority_engine.validate(standard_authority)
            standard_authority_engine.save_json(standard_authority,out/"standards/canonical_standard_authority.json")
            standard_authority_engine.save_json(standard_authority_integrity,out/"standards/canonical_standard_authority_integrity.json")
            manifest["canonical_standard_authority_result"]={"artifact_path":"standards/canonical_standard_authority.json","schema_version":standard_authority.get("schema_version"),"policy_version":standard_authority.get("policy_version"),"standard_authority_status":standard_authority.get("standard_authority_status"),"authority_sha256":standard_authority.get("authority_sha256")}
            kb_maturity_engine=self._component("canonical_kb_maturity_authority",GenericCanonicalKBMaturityAuthority)
            kb_maturity_authority=kb_maturity_engine.evaluate(effective,standard_authority)
            kb_maturity_integrity=kb_maturity_engine.validate(kb_maturity_authority)
            kb_maturity_engine.save_json(kb_maturity_authority,out/"standards/canonical_kb_maturity_authority.json")
            kb_maturity_engine.save_json(kb_maturity_integrity,out/"standards/canonical_kb_maturity_authority_integrity.json")
            manifest["canonical_kb_maturity_authority_result"]={"artifact_path":"standards/canonical_kb_maturity_authority.json","schema_version":kb_maturity_authority.get("schema_version"),"policy_id":kb_maturity_authority.get("policy_id"),"authorization_status":kb_maturity_authority.get("authorization_status"),"authority_sha256":kb_maturity_authority.get("authority_sha256")}
            self._write_json(manifest_path,manifest)
            standard_authority_blocked=standard_authority.get("standard_authority_status") in BLOCKING_STATES
            kb_maturity_blocked=(not standard_authority_blocked and kb_maturity_authority.get("authorization_status") in BLOCKING_MATURITY_STATES)
            if standard_authority_blocked or kb_maturity_blocked:
                client_projection_engine=self._component("canonical_client_projection",GenericCanonicalClientProjection)
                blocked_state_engine=self._component("canonical_requirement_state",GenericCanonicalRequirementStateStore)
                blocked_state=execute("canonical_requirement_state",out/"decisions/canonical_requirement_state_store.json",lambda:blocked_state_engine.build_authority_blocked(effective,standard_authority,rid,report_evidence,kb_maturity_authority),blocked_state_engine.save_json)
                blocked_state_integrity=blocked_state_engine.validate(blocked_state,effective)
                blocked_state_engine.save_json(blocked_state_integrity,out/"decisions/canonical_requirement_state_integrity.json")
                manifest["canonical_requirement_state_result"]={"artifact_path":"decisions/canonical_requirement_state_store.json","schema_version":blocked_state.get("schema_version"),"state_policy_version":blocked_state.get("state_policy_version"),"store_sha256":blocked_state.get("store_sha256"),"record_count":blocked_state.get("summary",{}).get("record_count",0)}
                blocked_root_engine=self._component("canonical_root_authority",GenericCanonicalRootAuthority)
                blocked_roots,blocked_na,blocked_relevance=blocked_root_engine.build_authority_blocked(blocked_state,standard_authority,kb_maturity_authority)
                blocked_root_engine.save_json(blocked_roots,out/"report/canonical_root_cause_authority.json")
                blocked_root_engine.save_json(blocked_na,out/"report/canonical_na_authority.json")
                blocked_root_engine.save_json(blocked_relevance,out/"report/canonical_product_relevance.json")
                blocked_root_integrity=blocked_root_engine.validate(blocked_roots,blocked_na,blocked_relevance)
                blocked_root_engine.save_json({**blocked_root_integrity,"validation_scope":"ROOT_CAUSE"},out/"report/canonical_root_cause_integrity.json")
                blocked_root_engine.save_json({**blocked_root_integrity,"validation_scope":"NA"},out/"report/canonical_na_integrity.json")
                blocked_root_engine.save_json({**blocked_root_integrity,"validation_scope":"PRODUCT_RELEVANCE"},out/"report/canonical_product_relevance_integrity.json")
                blocked_metrics_engine=self._component("canonical_metrics_authority",GenericCanonicalMetricsAuthority)
                blocked_metrics=blocked_metrics_engine.build_authority_blocked(blocked_state,standard_authority,rid,kb_maturity_authority)
                blocked_metrics_integrity=blocked_metrics_engine.validate(blocked_metrics)
                blocked_metrics_engine.save_json(blocked_metrics,out/"report/canonical_compliance_metrics.json")
                blocked_metrics_engine.save_json(blocked_metrics_integrity,out/"report/canonical_compliance_metrics_integrity.json")
                blocked_disposition=blocked_state_engine.blocked_disposition(blocked_state,standard_authority,kb_maturity_authority)
                blocked_state_engine.save_json(blocked_disposition,out/"decisions/overall_report_status.json")
                blocking_gate="STANDARD_AUTHORITY" if standard_authority_blocked else "KB_MATURITY_AUTHORITY"
                blocked_runtime=self._save_runtime_authority(
                    manifest,manifest_path,out,rid,PipelineStatus.BLOCKED,
                    standard_authority=standard_authority,
                    kb_maturity_authority=kb_maturity_authority,
                    requirement_state=blocked_state,roots=blocked_roots,
                    metrics=blocked_metrics,final_disposition=blocked_disposition,
                    blocking_gate=blocking_gate,
                    reason_code=f"{blocking_gate}_BLOCKED",
                )
                blocked_profile_builder=self._component("profile_builder",GenericReportProductProfileBuilder)
                blocked_profile=blocked_profile_builder.build(inputs["report"],standard_context=delta or base,effective_kb=effective)
                blocked_parameter_view=GenericCrossEvidenceConsistencyValidator().build_parameter_ledger(effective,blocked_profile,report_evidence)
                blocked_foundation=self._component("canonical_product_foundation",GenericCanonicalProductFoundation)
                blocked_facts=blocked_foundation.build_fact_ledger(blocked_profile,blocked_parameter_view)
                blocked_identity_source=blocked_foundation.build_identity_store(blocked_profile,rid)
                blocked_identity_engine=self._component("canonical_identity_authority",GenericCanonicalIdentityAuthority)
                blocked_identity_pre=blocked_identity_engine.build(blocked_identity_source,blocked_profile,{},rid)
                blocked_identity=blocked_identity_pre["canonical_identity"]
                blocked_relationships=blocked_foundation.build_relationships(blocked_identity,blocked_profile)
                blocked_relationships=blocked_identity_engine.filter_relationships(blocked_relationships,blocked_identity)
                blocked_identity_authority=blocked_identity_engine.build(blocked_identity_source,blocked_profile,blocked_relationships,rid)
                blocked_identity=blocked_identity_authority["canonical_identity"]
                blocked_identity_integrity=blocked_identity_engine.validate(blocked_identity_authority)
                blocked_profile_builder.save_json(blocked_profile,out/"report/product_profile.json")
                if hasattr(blocked_profile_builder,"save_identity_candidate_audit"):
                    blocked_profile_builder.save_identity_candidate_audit(blocked_profile,out/"report/report_identity_candidate_audit.json")
                blocked_foundation.save_json(blocked_identity_source,out/"report/identity_source_store.json")
                blocked_foundation.save_json(blocked_identity,out/"report/canonical_identity_store.json")
                blocked_foundation.save_json(blocked_relationships,out/"report/canonical_identity_relationships.json")
                blocked_identity_engine.save_json(blocked_identity_authority,out/"report/canonical_identity_authority.json")
                blocked_identity_engine.save_json(blocked_identity_integrity,out/"report/canonical_identity_authority_integrity.json")
                manifest["canonical_identity_authority_result"]={"artifact_path":"report/canonical_identity_authority.json","schema_version":blocked_identity_authority.get("schema_version"),"policy_version":blocked_identity_authority.get("policy_version"),"identity_sha256":blocked_identity_authority.get("identity_sha256")}
                blocked_classifier=self._component("canonical_product_classifier",GenericCanonicalProductClassifier)
                blocked_classification=blocked_classifier.classify(effective,blocked_facts,blocked_identity,blocked_relationships,blocked_profile,validation)
                blocked_classifier.save_json(blocked_classification,out/"report/canonical_product_classification.json")
                blocked_projection=client_projection_engine.build_blocked(manifest=manifest,effective_kb=effective,standard_authority=standard_authority,kb_maturity_authority=kb_maturity_authority,runtime_status=blocked_runtime,report_evidence=report_evidence,requirement_state=blocked_state,metrics=blocked_metrics,report_status=blocked_disposition,classification=blocked_classification,roots=blocked_roots,na=blocked_na,relevance=blocked_relevance,identity_authority=blocked_identity_authority,identity_store=blocked_identity,identity_relationships=blocked_relationships)
                client_projection_engine.save_json(blocked_projection,out/"summary/canonical_client_detailed.json")
                blocked_brief_engine=self._component("final_summary_brief_context",GenericFinalSummaryBriefBuilder)
                blocked_brief=blocked_brief_engine.build_from_canonical_client(blocked_projection,{})
                blocked_brief_engine.save_json(blocked_brief,out/"summary/final_summary_brief_context.json")
                manifest["canonical_client_projection_result"]={"artifact_path":"summary/canonical_client_detailed.json","schema_version":blocked_projection.get("schema_version"),"policy_version":blocked_projection.get("policy_version"),"projection_sha256":blocked_projection.get("projection_sha256")}
                manifest["final_summary_brief_context_result"]={"artifact_path":"summary/final_summary_brief_context.json","schema_version":blocked_brief.get("schema_version"),"policy_version":blocked_brief.get("summary_contract_version")}
                self._write_json(manifest_path,manifest)
                block_label=("Canonical standard authority" if standard_authority_blocked else "Canonical KB maturity authority")
                block_status=(standard_authority.get("standard_authority_status") if standard_authority_blocked else kb_maturity_authority.get("authorization_status"))
                raise PipelineBlockedError(f"{block_label} blocked compliance evaluation: {block_status}")
            if strict_standard_validation and validation.status!=StandardValidationStatus.VALID:
                raise PipelineBlockedError("Strict compatibility validation blocked compliance evaluation: "+validation.status.value)
            if self._stop(stop_after,"report_evidence"):return self._stopped(manifest,manifest_path,out,rid,records,validation)
            profile_builder=self._component("profile_builder",GenericReportProductProfileBuilder);profile=execute("product_profile",out/"report/product_profile.json",lambda:profile_builder.build(inputs["report"],standard_context=delta or base,effective_kb=effective),profile_builder.save_json)
            if hasattr(profile_builder,"save_identity_candidate_audit"):
                profile_builder.save_identity_candidate_audit(profile,out/"report/report_identity_candidate_audit.json")
            visual_inventory=self._visual_inventory_sidecar(inputs["report"],out,rid,manifest,manifest_path)
            visual_extraction=self._visual_extraction_sidecar(inputs["report"],visual_inventory,out,rid,manifest,manifest_path)
            self._visual_reconciliation_sidecar(visual_extraction,profile,out,rid,manifest,manifest_path)
            self._visual_promotion_sidecars(out,rid,manifest,manifest_path)
            compatibility_engine=self._component("structure_compatibility",GenericReportStandardStructureCompatibilityValidator)
            early_parameter_view=GenericCrossEvidenceConsistencyValidator().build_parameter_ledger(effective,profile,report_evidence)
            structure_compatibility=compatibility_engine.validate(effective,report_evidence,validation,early_parameter_view)
            compatibility_path=out/"report/report_standard_structure_compatibility.json";compatibility_engine.save_json(structure_compatibility,compatibility_path)
            manifest["report_structure_compatibility_result"]={"overall_compatibility":self._enum(structure_compatibility.overall_compatibility),"confidence":structure_compatibility.confidence,"output_artifact":str(compatibility_path.relative_to(out))}
            # Prepare canonical dependencies before applicability while retaining
            # the accepted execution-record ordering used by existing consumers.
            product_foundation=self._component("canonical_product_foundation",GenericCanonicalProductFoundation)
            fact_ledger=product_foundation.build_fact_ledger(profile,early_parameter_view)
            identity_source_store=product_foundation.build_identity_store(profile,rid)
            identity_authority_engine=self._component("canonical_identity_authority",GenericCanonicalIdentityAuthority)
            identity_authority_pre=identity_authority_engine.build(identity_source_store,profile,{},rid)
            identity_store=identity_authority_pre["canonical_identity"]
            identity_relationships=product_foundation.build_relationships(identity_store,profile)
            identity_relationships=identity_authority_engine.filter_relationships(identity_relationships,identity_store)
            identity_authority=identity_authority_engine.build(identity_source_store,profile,identity_relationships,rid)
            identity_store=identity_authority["canonical_identity"]
            identity_authority_integrity=identity_authority_engine.validate(identity_authority)
            product_foundation_integrity=product_foundation.validate(fact_ledger,identity_store,identity_relationships)
            classifier=self._component("canonical_product_classifier",GenericCanonicalProductClassifier)
            canonical_classification=classifier.classify(effective,fact_ledger,identity_store,identity_relationships,profile,validation)
            classification_integrity=classifier.validate(canonical_classification,effective,fact_ledger,identity_store)
            app_engine=self._component("applicability",GenericRequirementApplicabilityEvaluator);legacy_app=app_engine.evaluate(effective,profile)
            canonical_app_engine=self._component("canonical_applicability",GenericCanonicalApplicabilityAuthority)
            canonical_app=canonical_app_engine.build(effective,legacy_app,canonical_classification,fact_ledger,standard_authority)
            canonical_app_integrity=canonical_app_engine.validate(canonical_app,effective,canonical_classification,fact_ledger)
            app=execute("applicability",out/"report/applicability_result.json",lambda:canonical_app_engine.compatibility_report(canonical_app),canonical_app_engine.save_json)
            matcher=self._component("evidence_matcher",GenericRequirementEvidenceMatcher);matches=execute("evidence_match",out/"report/evidence_match_result.json",lambda:matcher.match(effective,report_evidence,app,structure_compatibility),matcher.save_json)
            tech_engine=self._component("technical",GenericTechnicalConstraintEvaluator);tech=execute("technical_constraints",out/"report/technical_constraint_result.json",lambda:tech_engine.evaluate(effective,app,matches,report_evidence,profile,early_parameter_view,structure_compatibility) if isinstance(tech_engine,GenericTechnicalConstraintEvaluator) else tech_engine.evaluate(effective,app,matches,report_evidence,profile),tech_engine.save_json)
            canonical_evidence_engine=self._component("canonical_evidence_sufficiency",GenericCanonicalEvidenceSufficiency)
            # Compute before final decision so it can act as the preferred
            # authority; register artifacts later to preserve the frozen
            # first-24 execution-record contract.
            canonical_evidence=canonical_evidence_engine.build(canonical_app,matches,identity_store,identity_relationships,structure_compatibility,tech,effective)
            canonical_technical_engine=self._component("canonical_technical_authority",GenericCanonicalTechnicalAuthority)
            canonical_technical=canonical_technical_engine.build(canonical_app,canonical_evidence,tech,fact_ledger)
            technical_authority_projection=canonical_technical_engine.compatibility_report(canonical_technical,tech)
            na_engine=self._component("na_validator",GenericReportNAValidator);na=execute("na_validation",out/"report/na_validation_result.json",lambda:na_engine.validate(effective,profile,app,matches,report_evidence,tech),na_engine.save_json)
            audit_engine=self._component("na_auditor",GenericNAConflictAuditor);audit=execute("na_conflict_audit",out/"report/na_conflict_audit.json",lambda:audit_engine.audit(effective,profile,app,report_evidence,matches,tech,na),audit_engine.save_json)
            grouping_engine=self._component("grouping",GenericRequirementGroupingResolver);grouping_result=execute("requirement_grouping",out/"report/requirement_grouping_result.json",lambda:grouping_engine.resolve(effective,app,matches),grouping_engine.save_json)
            group_app_engine=self._component("group_applicability",GenericGroupAwareApplicabilityResolver);group_app=execute("group_aware_applicability",out/"report/group_aware_applicability_result.json",lambda:group_app_engine.resolve(effective,app,grouping_result),group_app_engine.save_json)
            group_na_engine=self._component("group_na",GenericGroupAwareNAValidator);group_na=execute("group_aware_na_validation",out/"report/group_aware_na_validation_result.json",lambda:group_na_engine.validate(effective,profile,group_app,matches,report_evidence,grouping_result,na),group_na_engine.save_json)
            scope_engine=self._component("scope",GenericReportEvidenceScopeResolver);scope=execute("report_evidence_scope",out/"report/report_evidence_scope_result.json",lambda:scope_engine.resolve(effective,grouping_result,report_evidence,matches,group_app,group_na,audit),scope_engine.save_json)
            scope_na_engine=self._component("scope_na",GenericScopeAwareNAValidator);scope_na=execute("scope_aware_na_validation",out/"report/scope_aware_na_validation_result.json",lambda:scope_na_engine.validate(effective,profile,group_app,grouping_result,report_evidence,matches,scope,na,audit,group_na),scope_na_engine.save_json)
            final_engine=self._component("final",GenericFinalRequirementDecisionEngine);final=execute("final_decision",out/"decisions/final_requirement_decision.json",lambda:final_engine.evaluate(effective,profile,group_app,report_evidence,matches,technical_authority_projection,grouping_result,scope,scope_na,canonical_evidence),final_engine.save_json)
            if self._stop(stop_after,"final_decision"):return self._stopped(manifest,manifest_path,out,rid,records,validation,str(out/"decisions/final_requirement_decision.json"))
            coverage_engine=self._component("coverage",GenericCoverageGapAnalyzer);coverage=execute("coverage_gap",out/"decisions/coverage_gap_analysis.json",lambda:coverage_engine.analyze(final,effective,profile,group_app,report_evidence,matches,tech,grouping_result,scope,scope_na),coverage_engine.save_json)
            readiness_engine=self._component("readiness",GenericOverallReadinessBuilder);readiness=execute("overall_readiness",out/"decisions/overall_readiness_result.json",lambda:readiness_engine.build(effective,profile,final,coverage,group_app,tech,scope_na,grouping_result,scope),readiness_engine.save_json)
            state_engine=self._component("canonical_requirement_state",GenericCanonicalRequirementStateStore);canonical_state=execute("canonical_requirement_state",out/"decisions/canonical_requirement_state_store.json",lambda:state_engine.build(final,effective,rid,standard_authority,kb_maturity_authority),state_engine.save_json)
            consistency_engine=self._component("cross_evidence_consistency",GenericCrossEvidenceConsistencyValidator)
            consistency=execute("cross_evidence_consistency",out/"decisions/cross_evidence_consistency_result.json",lambda:consistency_engine.validate(effective,profile,app,report_evidence,grouping_result,scope),consistency_engine.save_json)
            execute("canonical_product_fact_ledger",out/"report/canonical_product_fact_ledger.json",lambda:fact_ledger,product_foundation.save_json)
            product_foundation.save_json(identity_source_store,out/"report/identity_source_store.json")
            execute("canonical_identity_store",out/"report/canonical_identity_store.json",lambda:identity_store,product_foundation.save_json)
            execute("canonical_identity_authority",out/"report/canonical_identity_authority.json",lambda:identity_authority,identity_authority_engine.save_json)
            identity_authority_engine.save_json(identity_authority_integrity,out/"report/canonical_identity_authority_integrity.json")
            execute("canonical_identity_relationships",out/"report/canonical_identity_relationships.json",lambda:identity_relationships,product_foundation.save_json)
            execute("canonical_product_foundation_integrity",out/"report/canonical_product_fact_integrity.json",lambda:product_foundation_integrity,product_foundation.save_json)
            product_foundation.save_json({**product_foundation_integrity,"validation_scope":"IDENTITY"},out/"report/canonical_identity_integrity.json")
            product_foundation.save_json({"schema_version":"STEP48B_FACT_RECONCILIATION_V1","source_profile_id":fact_ledger.get("source_profile_id"),"fact_schema_version":fact_ledger.get("schema_version"),"identity_schema_version":identity_store.get("schema_version"),"fact_count":fact_ledger.get("summary",{}).get("fact_count",0),"identity_count":len(identity_store.get("models",[])),"relationship_count":len(identity_relationships.get("relationships",[])),"integrity_valid":product_foundation_integrity.get("valid",False),"downstream_semantic_change":False},out/"report/step48b_fact_reconciliation.json")
            execute("canonical_product_classification",out/"report/canonical_product_classification.json",lambda:canonical_classification,classifier.save_json)
            execute("canonical_product_classification_integrity",out/"report/canonical_product_classification_integrity.json",lambda:classification_integrity,classifier.save_json)
            execute("legacy_applicability",out/"report/legacy_applicability_result.json",lambda:legacy_app,app_engine.save_json)
            execute("canonical_applicability",out/"report/canonical_applicability_result.json",lambda:canonical_app,canonical_app_engine.save_json)
            execute("canonical_applicability_integrity",out/"report/canonical_applicability_integrity.json",lambda:canonical_app_integrity,canonical_app_engine.save_json)
            execute("canonical_evidence_sufficiency",out/"report/canonical_evidence_sufficiency.json",lambda:canonical_evidence,canonical_evidence_engine.save_json)
            canonical_evidence_integrity=canonical_evidence_engine.validate(canonical_evidence,final)
            execute("canonical_evidence_sufficiency_integrity",out/"report/canonical_evidence_sufficiency_integrity.json",lambda:canonical_evidence_integrity,canonical_evidence_engine.save_json)
            execute("canonical_technical_authority",out/"report/canonical_technical_authority.json",lambda:canonical_technical,canonical_technical_engine.save_json)
            canonical_technical_integrity=canonical_technical_engine.validate(canonical_technical)
            execute("canonical_technical_authority_integrity",out/"report/canonical_technical_authority_integrity.json",lambda:canonical_technical_integrity,canonical_technical_engine.save_json)
            root_engine=self._component("canonical_root_authority",GenericCanonicalRootAuthority)
            canonical_roots,canonical_na,canonical_relevance=root_engine.build(canonical_state,canonical_app,canonical_evidence,canonical_technical,canonical_classification,scope_na,structure_compatibility,effective)
            root_integrity=root_engine.validate(canonical_roots,canonical_na,canonical_relevance)
            execute("canonical_root_cause_authority",out/"report/canonical_root_cause_authority.json",lambda:canonical_roots,root_engine.save_json)
            execute("canonical_root_cause_integrity",out/"report/canonical_root_cause_integrity.json",lambda:{**root_integrity,"validation_scope":"ROOT_CAUSE"},root_engine.save_json)
            execute("canonical_na_authority",out/"report/canonical_na_authority.json",lambda:canonical_na,root_engine.save_json)
            execute("canonical_na_integrity",out/"report/canonical_na_integrity.json",lambda:{**root_integrity,"validation_scope":"NA"},root_engine.save_json)
            execute("canonical_product_relevance",out/"report/canonical_product_relevance.json",lambda:canonical_relevance,root_engine.save_json)
            execute("canonical_product_relevance_integrity",out/"report/canonical_product_relevance_integrity.json",lambda:{**root_integrity,"validation_scope":"PRODUCT_RELEVANCE"},root_engine.save_json)
            metrics_engine=self._component("canonical_metrics_authority",GenericCanonicalMetricsAuthority)
            canonical_metrics=metrics_engine.build(canonical_state,fact_ledger,canonical_classification,canonical_app,canonical_evidence,canonical_technical,canonical_roots,canonical_na,canonical_relevance,structure_compatibility,identity_store,standard_authority,rid,kb_maturity_authority)
            canonical_metrics_integrity=metrics_engine.validate(canonical_metrics)
            execute("canonical_compliance_metrics",out/"report/canonical_compliance_metrics.json",lambda:canonical_metrics,metrics_engine.save_json)
            execute("canonical_compliance_metrics_integrity",out/"report/canonical_compliance_metrics_integrity.json",lambda:canonical_metrics_integrity,metrics_engine.save_json)
            dependency_engine=self._component("canonical_dependency_authority",GenericCanonicalDependencyAuthority)
            dependency_inputs={"standard_kb":self._plain(effective),"standard_authority":standard_authority,"kb_maturity_authority":kb_maturity_authority,"report_evidence":self._plain(report_evidence),"facts":fact_ledger,"identity":identity_store,"identity_authority":identity_authority,"identity_relationships":identity_relationships,"classification_standard":canonical_classification,"classification_subtype":canonical_classification,"structure":self._plain(structure_compatibility),"applicability":canonical_app,"evidence":canonical_evidence,"technical":canonical_technical,"requirement_state":canonical_state,"root":canonical_roots,"na":canonical_na,"relevance":canonical_relevance,"metrics":canonical_metrics}
            dependency_manifest=dependency_engine.build(rid,dependency_inputs)
            dependency_integrity=dependency_engine.validate(dependency_manifest)
            dependency_plan=dependency_engine.recompute_plan(dependency_manifest)
            execute("canonical_dependency_manifest",out/"report/canonical_dependency_manifest.json",lambda:dependency_manifest,dependency_engine.save_json)
            execute("canonical_dependency_integrity",out/"report/canonical_dependency_integrity.json",lambda:dependency_integrity,dependency_engine.save_json)
            execute("canonical_recompute_plan",out/"report/canonical_recompute_plan.json",lambda:dependency_plan,dependency_engine.save_json)
            summary_builder=self._component("clause_summary",GenericClauseEvaluationSummaryBuilder)
            clause_summary=execute("clause_evaluation_summary",out/"decisions/clause_evaluation_summary.json",lambda:summary_builder.to_dict(summary_builder.build(effective,profile,report_evidence,app,matches,grouping_result,final,coverage,tech,scope_na,group_app,scope,readiness,consistency)),self._generic_save)
            integrity_engine=self._component("evidence_integrity",GenericEvidenceIntegrityRejectionResolver)
            integrity=execute("evidence_integrity_rejection",out/"decisions/evidence_integrity_rejection_result.json",lambda:integrity_engine.resolve(clause_summary,effective,profile,report_evidence,matches,final,tech,scope_na,scope),integrity_engine.save_json)
            issue_engine=self._component("final_issues",GenericFinalIssueResolver);final_issues=execute("final_issue_resolution",out/"decisions/final_compliance_issues.json",lambda:self._propagate_standard_source_gaps(issue_engine.resolve(clause_summary,integrity),validation,effective,report_evidence),issue_engine.save_json)
            aggregate_engine=self._component("issue_aggregator",GenericReportIssueAggregator);aggregated=execute("report_issue_aggregation",out/"decisions/aggregated_compliance_issues.json",lambda:aggregate_engine.aggregate(final_issues,final_decision=final,canonical_requirement_state=canonical_state,coverage_gap_analysis=coverage,effective_kb=effective,structure_compatibility=structure_compatibility,product_profile=profile,technical_constraint_result=tech),aggregate_engine.save_json)
            action_engine=self._component("action_prioritizer",GenericNextActionPrioritizer);action_plan=execute("next_action_prioritization",out/"decisions/prioritized_next_actions.json",lambda:action_engine.prioritize(aggregated),action_engine.save_json)
            executive_engine=self._component("executive_summary",GenericExecutiveSummaryBuilder);executive=execute("executive_summary",out/"decisions/executive_compliance_summary.json",lambda:executive_engine.build(aggregated,action_plan),executive_engine.save_json)
            status_engine=self._component("overall_report_status",GenericOverallReportStatusEngine);report_status=execute("overall_report_status",out/"decisions/overall_report_status.json",lambda:status_engine.resolve(aggregated,action_plan,executive),status_engine.save_json)
            overall_status=self._enum(self._get(report_status,"overall_status")) or "UNRESOLVED";product_conclusion=self._enum(self._get(report_status,"product_compliance_conclusion")) or "NOT_DETERMINED"
            pipeline_status=PipelineStatus.SUCCESS if overall_status=="READY" else PipelineStatus.SUCCESS_WITH_REVIEW
            runtime_status=self._save_runtime_authority(
                manifest,manifest_path,out,rid,pipeline_status,
                standard_authority=standard_authority,
                kb_maturity_authority=kb_maturity_authority,
                requirement_state=canonical_state,roots=canonical_roots,
                metrics=canonical_metrics,final_disposition=self._plain(report_status),
            )
            client_projection_engine=self._component("canonical_client_projection",GenericCanonicalClientProjection)
            client_projection=client_projection_engine.build(manifest=manifest,effective_kb=effective,standard_authority=standard_authority,kb_maturity_authority=kb_maturity_authority,runtime_status=runtime_status,report_evidence=report_evidence,structure=structure_compatibility,identity_authority=identity_authority,identity_store=identity_store,identity_relationships=identity_relationships,classification=canonical_classification,fact_ledger=fact_ledger,applicability=canonical_app,evidence_matches=matches,evidence_sufficiency=canonical_evidence,technical=canonical_technical,final_decision=final,requirement_state=canonical_state,na=canonical_na,roots=canonical_roots,relevance=canonical_relevance,metrics=canonical_metrics,report_status=report_status)
            client_projection_engine.save_json(client_projection,out/"summary/canonical_client_detailed.json")
            manifest["canonical_client_projection_result"]={"artifact_path":"summary/canonical_client_detailed.json","schema_version":client_projection.get("schema_version"),"policy_version":client_projection.get("policy_version"),"projection_sha256":client_projection.get("projection_sha256")}
            response_engine=self._component("final_response",GenericFinalComplianceResponseBuilder);source_paths={"final_compliance_issues":out/"decisions/final_compliance_issues.json","aggregated_compliance_issues":out/"decisions/aggregated_compliance_issues.json","prioritized_next_actions":out/"decisions/prioritized_next_actions.json","executive_compliance_summary":out/"decisions/executive_compliance_summary.json","overall_report_status":out/"decisions/overall_report_status.json"}
            response=execute("final_saas_response",out/"decisions/final_compliance_response.json",lambda:response_engine.build(final_issues,aggregated,action_plan,executive,report_status,source_artifact_paths=source_paths),response_engine.save_json)
            summary_context_engine=self._component("final_summary_context",GenericFinalSummaryContextBuilder)
            summary_context=execute("final_summary_context",out/"summary/final_summary_context.json",lambda:summary_context_engine.build(effective_kb=effective,standard_validation=validation,product_profile=profile,applicability=group_app,na=group_na,evidence=matches,scope=scope,structure=structure_compatibility,technical=tech,parameters=consistency,final=final,canonical_requirement_state=canonical_state,canonical_metrics=canonical_metrics,coverage=coverage,issues=final_issues,aggregated=aggregated,actions=action_plan,executive=executive,status=report_status,response=response,manifest=manifest,source_paths={**{k:str(v.relative_to(out)) for k,v in source_paths.items()},"canonical_requirement_state":"decisions/canonical_requirement_state_store.json","canonical_metrics":"report/canonical_compliance_metrics.json","final_summary_context":"summary/final_summary_context.json"}),summary_context_engine.save_json)
            manifest["final_summary_context_result"]={"artifact_path":"summary/final_summary_context.json","schema_version":"FINAL_SUMMARY_CONTEXT_V1","generation_status":"PASS","source_artifact_references":sorted(summary_context.traceability.get("source_artifact_paths",{}))}
            brief_engine=self._component("final_summary_brief_context",GenericFinalSummaryBriefBuilder);brief=execute("final_summary_brief_context",out/"summary/final_summary_brief_context.json",lambda:brief_engine.build_from_canonical_client(client_projection,brief_engine.build(GenericFinalSummaryContextBuilder.to_dict(summary_context),source_path=out/"summary/final_summary_context.json")),brief_engine.save_json)
            state_integrity=state_engine.validate(canonical_state,effective,brief.get("requirement_summary"),self._get(aggregated,"professional_judgment",{}));state_engine.save_json(state_integrity,out/"decisions/canonical_requirement_state_integrity.json")
            manifest["final_summary_brief_context_result"]={"artifact_path":"summary/final_summary_brief_context.json","schema_version":FINAL_SUMMARY_BRIEF_SCHEMA_VERSION,"generation_status":"PASS","source_final_summary_context_sha256":brief["traceability"]["source_sha256"],"source_run_id":brief["traceability"]["source_run_id"]}
            final_path=str(out/"decisions/final_compliance_response.json");manifest["final_result"]={"overall_status":overall_status,"product_compliance_conclusion":product_conclusion,"output_artifact":final_path};manifest["pipeline_status"]=pipeline_status.value;manifest["completed_at"]=self.clock();manifest["step_execution_records"]=[asdict(x) for x in records];self._write_json(manifest_path,manifest);print(f"Final SaaS status ...... {overall_status}\nFinal artifact ......... {final_path}");return PipelineRunResult(rid,pipeline_status,str(out),str(manifest_path),final_path,validation)
        except PipelineBlockedError as exc:return self._failure(manifest,manifest_path,out,rid,records,PipelineStatus.BLOCKED,exc)
        except Exception as exc:return self._failure(manifest,manifest_path,out,rid,records,PipelineStatus.FAILED,exc)
    def validate_standard_set(self,base,delta,report_evidence,strict=False):
        base_num=self._standard_number(base);delta_num=self._standard_number(delta) if delta is not None else None;refs=[str(x) for x in self._get(report_evidence,"standard_numbers",[]) or []];supplied=[x for x in (base_num,delta_num) if x];diagnostics=[]
        if not base_num:return StandardValidationResult(StandardValidationStatus.STANDARD_SET_INCOMPLETE,supplied,refs,["Primary standard metadata is missing."])
        if delta is not None and not delta_num:return StandardValidationResult(StandardValidationStatus.STANDARD_SET_INCOMPLETE,supplied,refs,["Companion standard metadata is missing."])
        parent=self._get(self._get(delta,"document",{}),"parent_standard") if delta is not None else None;
        if parent and self._core(parent)!=self._core(base_num):return StandardValidationResult(StandardValidationStatus.STANDARD_MISMATCH,supplied,refs,["Part 2 parent standard does not match supplied Base standard."])
        cores={self._core(x) for x in supplied};report_cores={self._core(x) for x in refs if self._core(x)}
        # A report may list both an umbrella family identifier and the exact
        # governing members.  The ancestor is descriptive, not an additional
        # required document, when a more-specific report identity is present.
        report_cores={core for core in report_cores if not any(
            other!=core and other.startswith(core+"-") for other in report_cores
        )}
        missing=report_cores-cores
        if missing:return StandardValidationResult(StandardValidationStatus.STANDARD_MISMATCH,supplied,refs,["Report references standards not present in the supplied standard set: "+", ".join(sorted(missing))])
        supplied_years={self._core(n):self._get(self._get(kb,"document",{}),"year") for n,kb in ((base_num,base),(delta_num,delta)) if n and kb is not None}
        edition_mismatch=False
        for ref in refs:
            core=self._core(ref);year=self._year(ref)
            if core in supplied_years and year and supplied_years[core] and int(year)!=int(supplied_years[core]):
                edition_mismatch=True;diagnostics.append(f"Report-declared edition year {year} for {core} differs from supplied year {supplied_years[core]}.")
        amendment_gaps=[]
        for ref in refs:
            for amendment in re.findall(r"/(?:AMD|A)\s*\d+(?::\s*\d{4})?",ref,re.I):
                core=self._core(ref)
                supplied_ref=next((item for item in supplied if self._core(item)==core),"")
                if amendment.casefold() not in supplied_ref.casefold():
                    amendment_gaps.append(f"{core}{amendment.upper().replace(' ', '')}")
        if amendment_gaps:
            diagnostics.append("AMENDMENT_MISSING: Report declares amendment(s) absent from the supplied standard source: "+", ".join(sorted(set(amendment_gaps)))+". Amendment requirements were not inferred or fabricated.")
        if edition_mismatch and strict:return StandardValidationResult(StandardValidationStatus.STANDARD_MISMATCH,supplied,refs,diagnostics)
        if not refs:return StandardValidationResult(StandardValidationStatus.UNRESOLVED,supplied,refs,["Report did not expose resolvable standard metadata."])
        status=StandardValidationStatus.VALID if report_cores==cores and not edition_mismatch and not amendment_gaps else StandardValidationStatus.PARTIAL_MATCH
        if report_cores!=cores:diagnostics.append("Report metadata matches only part of the supplied standard set.")
        return StandardValidationResult(status,supplied,refs,diagnostics)
    @classmethod
    def _propagate_standard_source_gaps(cls,report,validation,effective,report_evidence):
        """Add review-only issues for report rows blocked by a known source-set gap."""
        if not any(str(x).startswith("AMENDMENT_MISSING:") for x in validation.diagnostics):return report
        def walk(items):
            for item in items or []:
                yield item;yield from walk(cls._get(item,"children",[]) or [])
        effective_ids={str(cls._get(x,"clause_id")) for x in walk(cls._get(effective,"clauses",[]) or [])}
        report_nodes=list(walk(cls._get(report_evidence,"clauses",[]) or []));created=[]
        for node in report_nodes:
            clause=str(cls._get(node,"clause_id") or "")
            if clause in effective_ids or not re.fullmatch(r"\d+(?:\.\d+)+",clause):continue
            parent=".".join(clause.split(".")[:-1])
            siblings={value for value in effective_ids if value.startswith(parent+".")
                      and value.count(".")==clause.count(".")}
            if parent not in effective_ids or not siblings:continue
            evidence_ids=sorted(str(cls._get(x,"evidence_id")) for x in cls._get(node,"evidence_items",[]) or [] if cls._get(x,"evidence_id"))
            token=hashlib.sha256((clause+"\x1f"+"\x1f".join(validation.diagnostics)).encode()).hexdigest()[:20].upper()
            created.append(FinalComplianceIssue(
                "FINAL-SOURCE-GAP-"+token,clause,None,FinalIssueType.STANDARD_SOURCE_GAP,
                ComplianceConclusion.NOT_EVALUATED,FinalSeverity.MEDIUM,
                Actionability.ACTIONABLE,True,
                "The report contains a row whose governing amendment or revision is missing from the supplied standard sources.",
                "No product compliance conclusion can be drawn for this row until authoritative source content is supplied.",
                FinalNextAction(FinalActionType.STANDARD_SOURCE_REQUEST,
                    "Provide the governing amendment or revision used by the report so the row can be evaluated."),
                evidence_refs=evidence_ids,
                provenance=FinalIssueProvenance(upstream_reason="AMENDMENT_MISSING",
                    upstream_metadata={"parent_clause_id":parent,"source_gap":"STANDARD_SOURCE_GAP"}),
                diagnostic={"finding_type":"STANDARD_SOURCE_GAP","report_clause_id":clause,
                            "fabricated_requirement":False},
            ))
        report.issues.extend(created)
        if created:
            report.issues=sorted({x.issue_id:x for x in report.issues}.values(),key=lambda x:x.issue_id)
            report.summary=dict(report.summary)
            report.summary["total_emitted_issues"]=len(report.issues)
            report.summary["actionable_issues"]=sum(x.actionability is Actionability.ACTIONABLE for x in report.issues)
            counts=dict(report.summary.get("counts_by_issue_type",{}));counts[FinalIssueType.STANDARD_SOURCE_GAP.value]=len(created);report.summary["counts_by_issue_type"]=counts
            actions=dict(report.summary.get("counts_by_action_type",{}));actions[FinalActionType.STANDARD_SOURCE_REQUEST.value]=len(created);report.summary["counts_by_action_type"]=actions
            report.diagnostics.append({"code":"STANDARD_SOURCE_GAP","count":len(created)})
        return report
    def _component(self,name,cls):return self.components.get(name) or cls()
    def _visual_inventory_sidecar(self,report_path,out,run_id,manifest,manifest_path):
        """Generate inventory metadata without granting it decision authority."""
        path=out/"report/report_visual_inventory.json"
        try:
            builder=self._component("visual_inventory",GenericReportVisualInventoryBuilder)
            inventory=builder.build(report_path,run_id=run_id)
            builder.save_json(inventory,path)
            manifest["visual_inventory_result"]={"status":"PASS","artifact_path":str(path.relative_to(out)),"schema_version":"REPORT_VISUAL_INVENTORY_V1","decision_authority":"NONE"}
            self._progress("visual_inventory","PASS")
        except Exception as exc:
            error=f"{type(exc).__name__}: {exc}"
            failure={"schema_version":"REPORT_VISUAL_INVENTORY_V1","run_id":run_id,"status":"REVIEW_REQUIRED","authority":"VISUAL_INVENTORY","decision_authority":"NONE","summary":{},"pages":[],"diagnostics":[{"code":"VISUAL_INVENTORY_FAILED","error_type":type(exc).__name__,"message":str(exc)}]}
            self._write_json(path,failure)
            manifest["visual_inventory_result"]={"status":"REVIEW_REQUIRED","artifact_path":str(path.relative_to(out)),"schema_version":"REPORT_VISUAL_INVENTORY_V1","decision_authority":"NONE","error":error}
            self._progress("visual_inventory","REVIEW_REQUIRED")
        self._write_json(manifest_path,manifest)
        return inventory if 'inventory' in locals() else failure
    def _visual_reconciliation_sidecar(self,visual_extraction,profile,out,run_id,manifest,manifest_path):
        """Reconcile visual candidates without enabling canonical promotion."""
        path=out/"report/report_visual_evidence_reconciliation.json"
        try:
            reconciler=self._component("visual_evidence_reconciler",GenericVisualEvidenceReconciler)
            native_profile=profile.to_dict() if hasattr(profile,"to_dict") else profile
            result=reconciler.reconcile(visual_extraction,native_profile,run_id=run_id)
            reconciler.save_json(result,path)
            manifest["visual_evidence_reconciliation_result"]={"status":"PASS","artifact_path":str(path.relative_to(out)),"schema_version":"REPORT_VISUAL_EVIDENCE_RECONCILIATION_V1","authority":"RECONCILED_EVIDENCE","decision_authority":"NONE","canonical_visual_promotion_enabled":False,"summary":result.summary}
            self._progress("visual_evidence_reconciliation","PASS")
        except Exception as exc:
            error=f"{type(exc).__name__}: {exc}"
            failure={"schema_version":"REPORT_VISUAL_EVIDENCE_RECONCILIATION_V1","run_id":run_id,"status":"REVIEW_REQUIRED","authority":"RECONCILED_EVIDENCE","decision_authority":"NONE","canonical_visual_promotion_enabled":False,"source_lineage":{},"summary":{},"reconciliations":[],"promotion_candidates":[],"diagnostics":[{"code":"VISUAL_RECONCILIATION_FAILED","error_type":type(exc).__name__,"message":str(exc)}]}
            self._write_json(path,failure)
            manifest["visual_evidence_reconciliation_result"]={"status":"REVIEW_REQUIRED","artifact_path":str(path.relative_to(out)),"schema_version":"REPORT_VISUAL_EVIDENCE_RECONCILIATION_V1","decision_authority":"NONE","error":error}
            self._progress("visual_evidence_reconciliation","REVIEW_REQUIRED")
        self._write_json(manifest_path,manifest)
    def _visual_extraction_sidecar(self,report_path,inventory,out,run_id,manifest,manifest_path):
        """Extract governed visual evidence without exposing it to decision consumers."""
        path=out/"report/report_visual_evidence_extraction.json"
        try:
            extractor=self._component("visual_evidence_extractor",GenericReportVisualEvidenceExtractor)
            extraction=extractor.extract(report_path,inventory,run_id=run_id)
            extractor.save_json(extraction,path)
            manifest["visual_evidence_extraction_result"]={"status":"PASS","artifact_path":str(path.relative_to(out)),"schema_version":"REPORT_VISUAL_EVIDENCE_EXTRACTION_V1","decision_authority":"NONE","summary":extraction.summary}
            self._progress("visual_evidence_extraction","PASS")
        except Exception as exc:
            error=f"{type(exc).__name__}: {exc}"
            failure={"schema_version":"REPORT_VISUAL_EVIDENCE_EXTRACTION_V1","run_id":run_id,"status":"REVIEW_REQUIRED","authority":"EXTRACTED_VISUAL_EVIDENCE","decision_authority":"NONE","source_inventory":{},"summary":{},"regions":[],"diagnostics":[{"code":"VISUAL_EXTRACTION_FAILED","error_type":type(exc).__name__,"message":str(exc)}]}
            self._write_json(path,failure)
            manifest["visual_evidence_extraction_result"]={"status":"REVIEW_REQUIRED","artifact_path":str(path.relative_to(out)),"schema_version":"REPORT_VISUAL_EVIDENCE_EXTRACTION_V1","decision_authority":"NONE","error":error}
            self._progress("visual_evidence_extraction","REVIEW_REQUIRED")
        self._write_json(manifest_path,manifest)
        return extraction if 'extraction' in locals() else failure
    def _visual_promotion_sidecars(self,out,run_id,manifest,manifest_path):
        """Materialize governed visual evidence; default flag is deliberately off."""
        promotion_path=out/"report/report_visual_evidence_promotion.json";impact_path=out/"report/report_visual_promotion_impact.json"
        try:
            promoter=self._component("visual_canonical_promoter",GenericVisualCanonicalPromoter)
            result=promoter.promote(out/"report/report_visual_evidence_reconciliation.json")
            promoter.save_json(result,promotion_path)
            impact=GenericVisualPromotionImpactBuilder().build(result);GenericVisualPromotionImpactBuilder.save_json(impact,impact_path)
            manifest["visual_promotion_result"]={"status":"PASS","artifact_path":str(promotion_path.relative_to(out)),"impact_artifact_path":str(impact_path.relative_to(out)),"schema_version":result.schema_version,"authority":"CANONICAL_VISUAL_EVIDENCE","canonical_visual_promotion_enabled":result.feature_enabled,"summary":result.summary}
            self._progress("visual_promotion","PASS")
        except Exception as exc:
            failure={"schema_version":"REPORT_VISUAL_EVIDENCE_PROMOTION_V1","authority":"CANONICAL_VISUAL_EVIDENCE","feature_enabled":False,"summary":{},"promotion_records":[],"canonical_evidence":[],"diagnostics":[{"code":"PROMOTION_ERROR","message":str(exc)}]};self._write_json(promotion_path,failure)
            impact={"schema_version":"REPORT_VISUAL_PROMOTION_IMPACT_V1","re_evaluation_status":"PROMOTION_ERROR","direct_promotion_effects":[],"derived_deterministic_effects":[],"summary":{}};self._write_json(impact_path,impact)
            manifest["visual_promotion_result"]={"status":"REVIEW_REQUIRED","artifact_path":str(promotion_path.relative_to(out)),"impact_artifact_path":str(impact_path.relative_to(out)),"error":str(exc)};self._progress("visual_promotion","REVIEW_REQUIRED")
        self._write_json(manifest_path,manifest)
    def _build_or_reuse_kb(self,builder,validator,source,out,kind,reuse):
        config=builder.__class__.__module__+"."+builder.__class__.__qualname__
        key=hashlib.sha256((self.sha256(source)+"\x1f"+config+"\x1f"+kind).encode()).hexdigest()
        cache=out.parent/".compliance_kb_cache"/(key+".json")
        if reuse and cache.is_file():return validator._kb_from_dict(json.loads(cache.read_text(encoding="utf-8")))
        if kind=="primary":
            primary_builder=getattr(builder,"build_primary_kb",None)
            value=primary_builder(source) if primary_builder else builder.build_base_kb(source)
        else:
            value=builder.build_base_kb(source) if kind=="base" else builder.build_delta_kb(source)
        cache.parent.mkdir(parents=True,exist_ok=True);builder.save_json(value,cache);return value
    @staticmethod
    def _require_pdf(value):
        p=Path(value).expanduser().resolve()
        if not p.is_file():raise FileNotFoundError(f"Input PDF does not exist: {p}")
        if p.suffix.casefold()!=".pdf" or p.read_bytes()[:5]!=b"%PDF-":raise ValueError(f"Input is not a readable PDF: {p}")
        return p
    @staticmethod
    def _validate_removal_target(path):
        target=Path(path).resolve();protected={Path.cwd().resolve(),Path.home().resolve(),Path(target.anchor).resolve()}
        if target in protected or target.is_symlink() or len(target.parts)<4:raise ValueError(f"Unsafe output removal target: {target}")
    @classmethod
    def deterministic_run_id(cls,inputs):return "RUN-"+hashlib.sha256("\x1f".join(f"{k}:{cls.sha256(v)}" for k,v in sorted(inputs.items())).encode()).hexdigest()[:20].upper()
    @staticmethod
    def sha256(path):
        h=hashlib.sha256()
        with Path(path).open("rb") as f:
            for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
        return h.hexdigest()
    @classmethod
    def _file_record(cls,p):return {"path":str(p),"filename":p.name,"sha256":cls.sha256(p)}
    @classmethod
    def _standard_number(cls,kb):return cls._s(cls._get(cls._get(kb,"document",{}),"standard_number"))
    @staticmethod
    def _core(v):
        value=str(v or "")
        year=GenericCompliancePipelineRunner._year(value)
        if year is not None:
            value=re.sub(rf"\s*[:-]\s*{year}(?!\d)","",value,count=1)
        m=re.search(r"\d+(?:-\d+)*",value);return m.group(0) if m else ""
    @staticmethod
    def _year(v):
        m=re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)",str(v or ""));return int(m.group(1)) if m else None
    @classmethod
    def _generic_save(cls,v,p):cls._write_json(p,cls._plain(v))
    @staticmethod
    def _write_json(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    @classmethod
    def _plain(cls,v):
        if isinstance(v,Enum):return v.value
        if is_dataclass(v):return cls._plain(asdict(v))
        if isinstance(v,dict):return {k:cls._plain(x) for k,x in v.items()}
        if isinstance(v,(list,tuple)):return [cls._plain(x) for x in v]
        return v
    @staticmethod
    def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
    @staticmethod
    def _s(v):return None if v is None else str(v.value if isinstance(v,Enum) else v)
    _enum=_s
    @staticmethod
    def _stop(requested,current):return bool(requested and requested==current)
    def _save_runtime_authority(
        self,m,path,out,rid,status,*,standard_authority=None,
        kb_maturity_authority=None,requirement_state=None,roots=None,metrics=None,
        final_disposition=None,blocking_gate=None,failed_stage=None,reason_code=None,
    ):
        engine=self._component("canonical_runtime_authority",GenericCanonicalRuntimeAuthority)
        runtime=engine.build(
            source_run_id=rid,status=status.value if isinstance(status,PipelineStatus) else status,
            standard_authority=standard_authority,kb_maturity_authority=kb_maturity_authority,
            requirement_state=requirement_state,roots=roots,metrics=metrics,
            final_disposition=final_disposition,blocking_gate=blocking_gate,
            failed_stage=failed_stage,reason_code=reason_code,
        )
        integrity=engine.validate(runtime)
        if not integrity.get("valid"):
            raise ValueError("Canonical runtime authority integrity validation failed")
        engine.save_json(runtime,out/"manifest/canonical_runtime_status.json")
        engine.save_json(integrity,out/"manifest/canonical_runtime_status_integrity.json")
        m["pipeline_status"]=runtime["status"]
        m["canonical_runtime_status_result"]={
            "artifact_path":"manifest/canonical_runtime_status.json",
            "schema_version":runtime.get("schema_version"),
            "policy_version":runtime.get("policy_version"),
            "status":runtime.get("status"),
            "terminal":runtime.get("terminal"),
            "runtime_state_sha256":runtime.get("runtime_state_sha256"),
        }
        self._write_json(path,m)
        return runtime
    @staticmethod
    def _read_json_if_present(path):
        target=Path(path)
        return json.loads(target.read_text(encoding="utf-8")) if target.is_file() else {}
    def _rewrite_runtime_projections(self,out,runtime):
        detailed_path=out/"summary/canonical_client_detailed.json"
        if detailed_path.is_file():
            detailed=self._read_json_if_present(detailed_path)
            detailed["canonical_runtime_status"]=self._plain(runtime)
            detailed.setdefault("run_context",{})["pipeline_status"]=runtime.get("status")
            detailed.setdefault("traceability",{})["canonical_runtime_status_sha256"]=runtime.get("runtime_state_sha256")
            detailed.pop("projection_sha256",None)
            detailed["projection_sha256"]=GenericCanonicalClientProjection._hash(detailed)
            self._write_json(detailed_path,detailed)
            brief_path=out/"summary/final_summary_brief_context.json"
            if brief_path.is_file():
                brief=self._read_json_if_present(brief_path)
                brief["canonical_runtime_status"]=self._plain(runtime)
                brief.setdefault("run_context",{})["pipeline_status"]=runtime.get("status")
                brief.setdefault("run",{})["pipeline_status"]=runtime.get("status")
                brief.setdefault("traceability",{})["canonical_runtime_status_sha256"]=runtime.get("runtime_state_sha256")
                brief["traceability"]["source_sha256"]=detailed.get("projection_sha256")
                self._write_json(brief_path,brief)
            compact_path=out/"summary/client_compliance_summary.json"
            if compact_path.is_file():
                compact=self._read_json_if_present(compact_path)
                compact["canonical_runtime_status"]=self._plain(runtime)
                self._write_json(compact_path,compact)
    def _stopped(self,m,path,out,rid,records,validation=None,final=None):
        self._save_runtime_authority(
            m,path,out,rid,PipelineStatus.SUCCESS_WITH_REVIEW,
            reason_code="REQUESTED_PARTIAL_PIPELINE_STOP",
        )
        m["completed_at"]=self.clock();m["step_execution_records"]=[asdict(x) for x in records];self._write_json(path,m)
        return PipelineRunResult(rid,PipelineStatus.SUCCESS_WITH_REVIEW,str(out),str(path),final,validation)
    def _failure(self,m,path,out,rid,records,status,exc):
        stage=records[-1].step_name if records else "input_validation";message=str(exc);code=type(exc).__name__.upper()
        standard=self._read_json_if_present(out/"standards/canonical_standard_authority.json")
        maturity=self._read_json_if_present(out/"standards/canonical_kb_maturity_authority.json")
        state=self._read_json_if_present(out/"decisions/canonical_requirement_state_store.json")
        roots=self._read_json_if_present(out/"report/canonical_root_cause_authority.json")
        metrics=self._read_json_if_present(out/"report/canonical_compliance_metrics.json")
        disposition=self._read_json_if_present(out/"decisions/overall_report_status.json")
        if status is PipelineStatus.FAILED:
            failed_stage=stage;blocking_gate=None;reason_code="PIPELINE_EXECUTION_FAILED"
        else:
            failed_stage=None
            if standard.get("standard_authority_status") in BLOCKING_STATES:
                blocking_gate="STANDARD_AUTHORITY"
            elif maturity.get("authorization_status") in BLOCKING_MATURITY_STATES:
                blocking_gate="KB_MATURITY_AUTHORITY"
            elif stage=="standard_validation":
                blocking_gate="STANDARD_VALIDATION"
            else:
                blocking_gate="PIPELINE_PRECONDITION"
            reason_code=f"{blocking_gate}_BLOCKED"
        runtime_path=out/"manifest/canonical_runtime_status.json"
        runtime=self._read_json_if_present(runtime_path)
        if status is PipelineStatus.FAILED or runtime.get("status")!=status.value:
            runtime=self._save_runtime_authority(
                m,path,out,rid,status,standard_authority=standard,
                kb_maturity_authority=maturity,requirement_state=state,
                roots=roots,metrics=metrics,final_disposition=disposition,
                blocking_gate=blocking_gate,failed_stage=failed_stage,
                reason_code=reason_code,
            )
        self._rewrite_runtime_projections(out,runtime)
        m["pipeline_status"]=runtime.get("status",status.value);m["completed_at"]=self.clock();m["step_execution_records"]=[asdict(x) for x in records]
        termination={"reason":f"{type(exc).__name__}: {exc}","failure_code":code,"message":message,"provenance":{"source":"step_execution_records","stage_status":records[-1].status if records else status.value,"exception_type":type(exc).__name__}}
        if status is PipelineStatus.FAILED:
            termination["failed_stage"]=failed_stage;m["failed_stage"]=failed_stage;m["failure"]=termination;m.pop("block",None)
            m["termination_kind"]="EXECUTION_FAILURE"
        else:
            termination["blocking_gate"]=blocking_gate;m["block"]=termination;m.pop("failure",None);m.pop("failed_stage",None)
            m["termination_kind"]="AUTHORITY_BLOCK" if blocking_gate in {"STANDARD_AUTHORITY","KB_MATURITY_AUTHORITY"} else "TERMINAL_REVIEW"
        self._write_json(path,m);print(f"{status.value} at: {stage}\nReason: {exc}\nArtifact: {path}");return PipelineRunResult(rid,status,str(out),str(path))
    @staticmethod
    def _progress(name,status):print(f"{name.replace('_',' ').title().replace('Saas','SaaS'):<28} {status}")

__all__=["GenericCompliancePipelineRunner","PipelineBlockedError","PipelineRunResult","PipelineStatus","StandardSetMode","StandardValidationResult","StandardValidationStatus","StepExecutionRecord"]
