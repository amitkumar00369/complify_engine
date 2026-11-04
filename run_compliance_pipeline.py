#!/usr/bin/env python3
"""CLI entry point for the generic compliance pipeline."""
import argparse
from iec_parser.generic_compliance_pipeline_runner import GenericCompliancePipelineRunner,PipelineStatus
def build_parser():
 p=argparse.ArgumentParser(description="Run the generic compliance pipeline through overall readiness.")
 p.add_argument("--base-standard",required=True);p.add_argument("--part2-standard");p.add_argument("--report",required=True);p.add_argument("--output",required=True);p.add_argument("--run-id");p.add_argument("--force",action="store_true");p.add_argument("--stop-after",choices=("base_kb","effective_kb","report_evidence","final_decision"));p.add_argument("--reuse-kb",action="store_true");p.add_argument("--strict-standard-validation",action="store_true");return p
def main(argv=None):
 a=build_parser().parse_args(argv);r=GenericCompliancePipelineRunner().run(a.base_standard,a.part2_standard,a.report,a.output,run_id=a.run_id,force=a.force,stop_after=a.stop_after,reuse_kb=a.reuse_kb,strict_standard_validation=a.strict_standard_validation);return 0 if r.pipeline_status in {PipelineStatus.SUCCESS,PipelineStatus.SUCCESS_WITH_REVIEW} else 2
if __name__=="__main__":raise SystemExit(main())
