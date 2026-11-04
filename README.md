# PDF clause knowledge base

This project converts the IEC PDF in `RawData` into a clause-oriented JSON
knowledge base. It removes repeating page headers, footers, and the personalized
licence watermark while retaining clause text, notes, tests, tables, and figure
text.

## Generate the knowledge base

```powershell
python -m pip install -r requirements.txt
python -m iec_par ".\RawData\IEC_60335-1 .pdf" -o .\output.json
```

Each object in `sections` contains a unique `id`, optional `title`, hierarchical
`parent_id`, clause `kind`, source page range, individual `paragraphs`, and the
combined searchable `text`. Document metadata and extraction statistics are
stored at the root of the JSON file.

## Extract a test report

```powershell
python -m report_extractor .\Report\test_report_mixer.pdf .\reportoutput.json

# Generalized IEC compliance schema (no word/bounds data)
python -m report_extractor .\Report\TST_60204.pdf .\Report\report_60204.json --structured
```

The class-based `report_extractor` package retains page text, metadata, and
positioned words.

## Generate the compliance gap analysis

```powershell
python -m gap_analysis .\output.json .\reportoutput.json .\gapAnalysis.json
```

The class-based `gap_analysis` package maps clauses, checks report consistency,
classifies gaps, evaluates appendix pointers, and produces an auditable
readiness score.

