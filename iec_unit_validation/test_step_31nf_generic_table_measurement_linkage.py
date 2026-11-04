"""Focused generic ownership and measurement-linkage corrections."""
import unittest
from iec_par.generic_report_evidence_extractor import GenericReportEvidenceExtractor
from iec_par.generic_requirement_evidence_matcher import GenericRequirementEvidenceMatcher

class _Table:
 def __init__(self,rows):self._rows=rows
 def extract(self):return self._rows
class _Found:
 def __init__(self,tables):self.tables=[_Table(x) for x in tables]
class _Page:
 def __init__(self,tables):self.tables=tables
 def find_tables(self):return _Found(self.tables)

class Step31NFTests(unittest.TestCase):
 def test_01_explicit_owner(self):
  text,owner=GenericReportEvidenceExtractor._layout_table_rows(_Page([[['7.1','TABLE: values'],['Voltage (V)',''],['5','']]]),None)
  self.assertEqual(owner,'7.1');self.assertIn('\n7.1\n',text)
 def test_02_bounded_continuation(self):
  text,owner=GenericReportEvidenceExtractor._layout_table_rows(_Page([[['Voltage (V)'],['5']]]),'7.1')
  self.assertEqual(owner,'7.1');self.assertIn('5 V',text)
 def test_03_unrelated_caption_breaks_owner(self):
  text,owner=GenericReportEvidenceExtractor._layout_table_rows(_Page([[['TABLE: unrelated'],['Voltage (V)'],['5']]]),'7.1')
  self.assertEqual((text,owner),('',None))
 def test_04_lowercase_list_marker_not_ampere(self):
  text,_=GenericReportEvidenceExtractor._layout_table_rows(_Page([[['7.1','TABLE: list'],['Clause'],['14.7 a']]]),None)
  self.assertNotIn('Measured',text)
 def test_05_measurement_requires_constraint(self):
  req={'technical_constraints':[]};m=[{'measurement_id':'M','parameter':'voltage','unit':'V'}]
  self.assertEqual(GenericRequirementEvidenceMatcher._compatible_measurement_ids(req,m),[])
 def test_06_parameter_must_match(self):
  req={'technical_constraints':[{'operator':'less_than','parameter':'force','unit':'N'}]};m=[{'measurement_id':'M','parameter':'voltage','unit':'V'}]
  self.assertEqual(GenericRequirementEvidenceMatcher._compatible_measurement_ids(req,m),[])
 def test_07_unit_dimension_must_match(self):
  req={'technical_constraints':[{'operator':'less_than','parameter':'voltage','unit':'V'}]};m=[{'measurement_id':'M','parameter':'voltage','unit':'N'}]
  self.assertEqual(GenericRequirementEvidenceMatcher._compatible_measurement_ids(req,m),[])
 def test_08_compatible_measurement_retained(self):
  req={'technical_constraints':[{'operator':'less_than','parameter':'voltage','unit':'V'}]};m=[{'measurement_id':'M','parameter':'voltage','unit':'mV'}]
  self.assertEqual(GenericRequirementEvidenceMatcher._compatible_measurement_ids(req,m),['M'])
 def test_09_opaque_legacy_reference_retained(self):
  self.assertEqual(GenericRequirementEvidenceMatcher._compatible_measurement_ids({},[{'measurement_id':'M'}]),['M'])
 def test_10_no_numeric_similarity_fallback(self):self.test_06_parameter_must_match()
 def test_11_no_cross_clause_rule(self):self.test_05_measurement_requires_constraint()
 def test_12_no_family_specific_logic(self):
  import inspect
  source=(inspect.getsource(GenericReportEvidenceExtractor)+inspect.getsource(GenericRequirementEvidenceMatcher)).casefold()
  for token in ('iec 60065','speaker.pdf','clause_id =='):self.assertNotIn(token,source)

if __name__=='__main__':unittest.main(verbosity=2)
