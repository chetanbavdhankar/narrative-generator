# Scenario Qualitative Context Enricher

A standalone enrichment module that maps Transaction Monitoring (TM) Alert Definitions to parent scenario/control definitions in a scenario JSON catalog (e.g. `scenarios.json`), extracting and appending qualitative functional specifications directly into the model's Markdown dossiers.

---

## 1. Overview

While `narrative_generator` processes quantitative metrics (KRIs, KPIs, thresholds, flags) from Excel files, qualitative definitions (such as typology descriptions, focal entities, NAIC conditions, detection logic, alert criteria, and solution profiles) reside in scenario catalogs.

This module bridges both sources by:
1. Parsing the Alert Definition key (e.g. `CHQD.058_PL_RB_...` $\rightarrow$ `CHQD.058`).
2. Looking up the control specifications from `scenarios.json`.
3. Formatting the qualitative logic into LLM-ready `<functional_requirements>` blocks with full file citations.
4. Appending the block before the closing `</model>` tag in the target dossier(s).

---

## 2. File Architecture

```text
scenario_enrichment/
├── enricher.py       # Standalone CLI & Python enrichment engine
└── README.md         # Documentation and usage guide
```

---

## 3. How to Run

### CLI Usage

Enrich a single consolidated dossier file:
```bash
python scenario_enrichment/enricher.py \
  --scenarios-file scenarios.json \
  --dossier-input output/PL_RB_Q1_2026_dossiers.md \
  --output-target output/PL_RB_Q1_2026_dossiers_enriched.md
```

Enrich an entire directory of individual per-model dossiers:
```bash
python scenario_enrichment/enricher.py \
  --scenarios-file scenarios.json \
  --dossier-input output/per_model \
  --output-target output/per_model_enriched
```

*(Note: If `--output-target` is omitted, the input dossier file or directory will be updated in-place).*

---

## 4. Python API Usage

```python
from scenario_enrichment.enricher import load_scenarios_json, enrich_dossier_text

scenarios = load_scenarios_json("scenarios.json")
raw_dossier = open("output/model_dossier.md", encoding="utf-8").read()

enriched_dossier = enrich_dossier_text(raw_dossier, scenarios, source_filename="scenarios.json")
```

---

## 5. Output Format Example

```markdown
<functional_requirements>
## Scenario / Control Definition: CHQD.058

| Attribute | Details | Source |
|---|---|---|
| Typology | Anomalies in the use of physical cash and/or cash equivalents... | scenarios.json |
| Risk Type | TF | scenarios.json |
| Focal Entity | Customer Centric | scenarios.json |
| Generation Criteria | Only generate one alert per monitoring period | scenarios.json |

### Applicable Conditions
Customers who are Entity.
Only the retail entity customer segments are included in this AD (SME, Mid Corp).
Customer is NPO based on NAICs.

### Detection Logic
FCRM will create a customer profile and aggregate cheque debits over predefined period.

### Alert Trigger Criteria
The aggregated cheque debit amount is greater than or equal to the amount threshold.

### Solution Definition Profiles
- **Profile `IN-TC_D_CHEQ`**: Transaction Codes: `[CHEQ]` | Debit/Credit: `[DEBIT]`
</functional_requirements>
```
