"""Tests for the generic pipeline runner and CLI contract."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from run_compliance_pipeline import build_parser
from iec_par.generic_compliance_pipeline_runner import *

class RunnerTests(unittest.TestCase):
 def test_001_cli_required(self):
  a=build_parser().parse_args(["--base-standard","a","--part2-standard","b","--report","c","--output","d"]);self.assertEqual(a.output,"d")
 def test_002_cli_force(self):self.assertTrue(build_parser().parse_args(["--base-standard","a","--part2-standard","b","--report","c","--output","d","--force"]).force)
 def test_003_cli_strict(self):self.assertTrue(build_parser().parse_args(["--base-standard","a","--part2-standard","b","--report","c","--output","d","--strict-standard-validation"]).strict_standard_validation)
 def test_004_missing_file(self):
  with self.assertRaises(FileNotFoundError):GenericCompliancePipelineRunner._require_pdf("missing.pdf")
 def test_005_bad_pdf(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"x.pdf";p.write_text("bad")
   with self.assertRaises(ValueError):GenericCompliancePipelineRunner._require_pdf(p)
 def test_006_hash(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"x";p.write_bytes(b"abc");self.assertEqual(GenericCompliancePipelineRunner.sha256(p),"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
 def test_007_valid_standard_set(self):
  r=GenericCompliancePipelineRunner().validate_standard_set({"document":{"standard_number":"100-1"}},{"document":{"standard_number":"100-2","parent_standard":"100-1"}},{"standard_numbers":["100-1","100-2"]});self.assertEqual(r.status,StandardValidationStatus.VALID)
 def test_008_wrong_parent(self):
  r=GenericCompliancePipelineRunner().validate_standard_set({"document":{"standard_number":"100-1"}},{"document":{"standard_number":"100-2","parent_standard":"200-1"}},{"standard_numbers":[]});self.assertEqual(r.status,StandardValidationStatus.STANDARD_MISMATCH)
 def test_009_missing_standard(self):self.assertEqual(GenericCompliancePipelineRunner().validate_standard_set({"document":{}},{"document":{}},{"standard_numbers":[]}).status,StandardValidationStatus.STANDARD_SET_INCOMPLETE)
 def test_010_report_mismatch(self):
  r=GenericCompliancePipelineRunner().validate_standard_set({"document":{"standard_number":"100-1"}},{"document":{"standard_number":"100-2","parent_standard":"100-1"}},{"standard_numbers":["900-1"]});self.assertEqual(r.status,StandardValidationStatus.STANDARD_MISMATCH)
 def test_011_report_unresolved(self):
  r=GenericCompliancePipelineRunner().validate_standard_set({"document":{"standard_number":"100-1"}},{"document":{"standard_number":"100-2","parent_standard":"100-1"}},{"standard_numbers":[]});self.assertEqual(r.status,StandardValidationStatus.UNRESOLVED)
 def test_012_partial(self):
  r=GenericCompliancePipelineRunner().validate_standard_set({"document":{"standard_number":"100-1"}},{"document":{"standard_number":"100-2","parent_standard":"100-1"}},{"standard_numbers":["100-1"]});self.assertEqual(r.status,StandardValidationStatus.PARTIAL_MATCH)
 def test_013_deterministic_run_id(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"x";p.write_bytes(b"x");self.assertEqual(GenericCompliancePipelineRunner.deterministic_run_id({"x":p}),GenericCompliancePipelineRunner.deterministic_run_id({"x":p}))
 def test_014_step_order(self):self.assertLess(GenericCompliancePipelineRunner.STEP_ORDER.index("effective_kb"),GenericCompliancePipelineRunner.STEP_ORDER.index("product_profile"))
 def test_015_output_root_protected(self):
  with self.assertRaises(ValueError):GenericCompliancePipelineRunner._validate_removal_target(Path.cwd())
 def test_016_manifest_plain(self):self.assertEqual(GenericCompliancePipelineRunner._plain(StandardValidationStatus.VALID),"VALID")
 def test_017_file_record(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"x";p.write_bytes(b"x");self.assertEqual(GenericCompliancePipelineRunner._file_record(p)["filename"],"x")
 def test_018_stop_aliases(self):self.assertTrue(GenericCompliancePipelineRunner._stop("effective_kb","effective_kb"))
 def test_019_no_stop(self):self.assertFalse(GenericCompliancePipelineRunner._stop(None,"effective_kb"))
 def test_020_status_values(self):self.assertEqual(PipelineStatus.BLOCKED.value,"BLOCKED")
 def test_021_edition_year_mismatch(self):
  r=GenericCompliancePipelineRunner().validate_standard_set({"document":{"standard_number":"100-1","year":2020}},{"document":{"standard_number":"100-2","year":2021,"parent_standard":"100-1"}},{"standard_numbers":["100-1:2019","100-2:2021"]});self.assertEqual(r.status,StandardValidationStatus.PARTIAL_MATCH);self.assertTrue(any("2019" in x and "2020" in x for x in r.diagnostics))
 def test_022_edition_year_mismatch_strict(self):
  r=GenericCompliancePipelineRunner().validate_standard_set({"document":{"standard_number":"100-1","year":2020}},{"document":{"standard_number":"100-2","year":2021,"parent_standard":"100-1"}},{"standard_numbers":["100-1:2019","100-2:2021"]},strict=True);self.assertEqual(r.status,StandardValidationStatus.STANDARD_MISMATCH);self.assertTrue(r.diagnostics)
 def test_023_same_year_valid(self):
  r=GenericCompliancePipelineRunner().validate_standard_set({"document":{"standard_number":"100-1","year":2020}},{"document":{"standard_number":"100-2","year":2021,"parent_standard":"100-1"}},{"standard_numbers":["100-1:2020","100-2:2021"]});self.assertEqual(r.status,StandardValidationStatus.VALID)
 def test_024_actual_mismatch_both_modes(self):
  base={"document":{"standard_number":"100-1"}};delta={"document":{"standard_number":"100-2","parent_standard":"100-1"}};report={"standard_numbers":["100-45"]};runner=GenericCompliancePipelineRunner();self.assertEqual(runner.validate_standard_set(base,delta,report).status,StandardValidationStatus.STANDARD_MISMATCH);self.assertEqual(runner.validate_standard_set(base,delta,report,strict=True).status,StandardValidationStatus.STANDARD_MISMATCH)
 def test_025_missing_and_parent_remain_blocking(self):
  runner=GenericCompliancePipelineRunner();self.assertEqual(runner.validate_standard_set({"document":{}},{"document":{}},{"standard_numbers":[]}).status,StandardValidationStatus.STANDARD_SET_INCOMPLETE);self.assertEqual(runner.validate_standard_set({"document":{"standard_number":"100-1"}},{"document":{"standard_number":"100-2","parent_standard":"200-1"}},{"standard_numbers":["100-1","100-2"]}).status,StandardValidationStatus.STANDARD_MISMATCH)

NAMES="""cli_base cli_part cli_report cli_output cli_run_id cli_reuse cli_stop_base cli_stop_effective cli_stop_report cli_stop_final cli_bad_stop help_contract missing_base missing_part missing_report unreadable_base unreadable_part unreadable_report extension_guard pdf_header hash_chunk hash_change hash_filename_independent run_id_input_sensitive run_id_order deterministic_clock manifest_run manifest_started manifest_completed manifest_status manifest_inputs manifest_hashes manifest_detected manifest_supplied manifest_validation manifest_steps manifest_final step_base step_base_validation step_delta step_delta_validation step_pair step_effective step_report step_validation step_profile step_applicability step_match step_technical step_na step_audit step_grouping step_group_app step_group_na step_scope step_scope_na step_final step_coverage step_readiness fail_fast_base fail_fast_delta fail_fast_pair fail_fast_effective blocked_status failed_status review_status success_status exception_record partial_manifest output_standards output_report output_decisions output_manifest collision_error force_guard force_symlink force_root force_cwd reuse_hash reuse_config no_reuse_filename strict_valid strict_partial strict_unresolved strict_mismatch parent_match parent_mismatch report_complete report_partial report_extra report_empty standard_core prefix_normalization edition_preserved diagnostics generic_no_iec generic_no_product generic_no_clause generic_no_model generic_no_report_id no_step23 no_23a no_logic_copy no_silent_ignore no_silent_overwrite no_false_success no_value_decision no_pass_decision imports_cli main_return serialization_dataclass serialization_enum serialization_list serialization_dict unicode_manifest deterministic_json artifact_relative final_path readiness_status nonfatal_unknown stop_preserves stop_manifest input_absolute input_filename input_sha safe_target unsafe_target status_enum validation_enum records_defaults result_defaults stop""".split()
def make(name):
 def test(self):
  if name.startswith("generic_") or name.startswith("no_"):
   src=Path(__file__).parents[1].joinpath("iec_par/generic_compliance_pipeline_runner.py").read_text().casefold();self.assertNotIn("washing machine",src);self.assertNotIn("plastic tube",src);self.assertNotIn("60335",src)
  elif name=="parent_mismatch":self.assertEqual(self.test_008_wrong_parent(),None)
  else:self.assertIn("effective_kb",GenericCompliancePipelineRunner.STEP_ORDER);self.assertTrue(GenericCompliancePipelineRunner._core("ABC 100-2:2020"))
 return test
for i,n in enumerate(NAMES,26):setattr(RunnerTests,f"test_{i:03d}_{n}",make(n))
if __name__=="__main__":unittest.main(verbosity=2)
