# Gap Analysis Validator

Python package that compares clause evidence in `reportoutput.json` with the IEC
knowledge base in `output.json`. It distinguishes missing evidence, explicit
failures, Part 2-only clauses, and appendix compliance-engine requirements.

```shell
python -m gap_analysis output.json reportoutput.json gapAnalysis.json
```
