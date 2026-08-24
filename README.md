# Transaction Monitoring (TM) Narrative Generator

A complete, end-to-end ETL and prompt engineering framework for Transaction Monitoring (TM) Model Governance. It converts raw quarterly Excel workbooks and scenario catalogs into audit-grade, evidence-backed root cause hypotheses and executive narratives ($\le 400$ words) with strict data lineage citations.

---

## 1. End-to-End Pipeline Workflow

The governance pipeline operates in three consecutive, modular stages:

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ STAGE 1: Quantitative Ingestion & Dossier Serialization                    │
│   • Core Engine: core.py / main.py / app.py                                │
│   • Inputs: Excel Workbooks (e.g. input/PL_RB_kri.xlsx)                    │
│   • Logic: Evaluates KRI 1, 2, 3, 6 triggers, enriches KPIs (1, 2b, 3, etc)│
│   • Decodes: AD Taxonomy (ABCD.123.SS.RR.XY -> Segment, Risk, Period)      │
│   • Output: Quantitative Markdown Dossiers (output/<run>_dossiers.md)      │
└─────────────────────────────────────┬──────────────────────────────────────┘
                                      │
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ STAGE 2: Qualitative Scenario & Control Logic Enrichment                   │
│   • Enricher: scenario_enrichment/enricher.py                              │
│   • Inputs: Quantitative Dossiers + scenarios.json                         │
│   • Logic: Maps scenario key (AAAA.NNN), injects typology, detection logic,│
│     and alert trigger criteria inside <scenario_detection_logic>           │
│   • Output: Enriched Dossiers (output/<run>_dossiers_enriched.md)          │
└─────────────────────────────────────┬──────────────────────────────────────┘
                                      │
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ STAGE 3: 2-Step LLM Governance & Narrative Generation                      │
│   • Pipeline: prompt_pipeline/pipeline.py & prompt_pipeline/prompts.py     │
│   • Step 1: Hypothesis & Causal Chain Formulation                          │
│     - Falsifiable Hypothesis + 3-5 Cited Evidence Points                   │
│     - Unbroken Causal Chain + Alternative Explanations Evaluation          │
│   • Step 2: Executive Root Cause Narrative (<= 400 words)                  │
│     - Observation -> Analysis -> Deterministic Action Recommendation       │
│     - Deterministic Actions: NO ACTION / RECALIBRATE / RE-BAND / DECOM     │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Quickstart: Step-by-Step Execution (From Scratch to Narrative)

### Prerequisites
```bash
pip install -r requirements.txt
```

---

### Step 1: Generate Quantitative Model Dossiers

Choose one of the following execution methods:

#### Option A: Interactive Web UI (Recommended)
Double-click [`start.bat`](start.bat) on Windows or execute:
```bash
python app.py --port 5000
```
- Open `http://localhost:5000` in your web browser.
- **Browse** to select input/output directories.
- Click **Scan** to group portfolios by Country / Business Line, select files, and click **Run Pipeline**.

#### Option B: Command Line Interface (CLI)
```bash
python main.py --country PL --business-line RB --ingestion-quarter Q1_2026
```
*(Outputs saved to `output/PL_RB_Q1_2026_dossiers.md` and `output/per_model/`)*

---

### Step 2: Inject Qualitative Scenario & Control Logic

Run the standalone scenario enricher to map qualitative detection rules from `scenarios.json`:

```bash
# Enrich a single consolidated dossier file:
python scenario_enrichment/enricher.py \
  --scenarios-file scenarios.json \
  --dossier-input output/PL_RB_Q1_2026_dossiers.md \
  --output-target output/PL_RB_Q1_2026_dossiers_enriched.md

# Or enrich an entire directory of per-model dossiers:
python scenario_enrichment/enricher.py \
  --scenarios-file scenarios.json \
  --dossier-input output/per_model \
  --output-target output/per_model_enriched
```

---

### Step 3: Generate 2-Step LLM Prompt Bundles

Generate structured prompt bundles containing Step 1 (Hypothesis) and Step 2 (Narrative) prompt templates:

```bash
python -m prompt_pipeline.pipeline \
  --dossier-input output/PL_RB_Q1_2026_dossiers_enriched.md \
  --output-dir output/prompts/
```

#### Step 3 (Python API): Direct LLM Orchestration
```python
from prompt_pipeline import build_hypothesis_prompt, build_narrative_prompt

# 1. Load the enriched dossier for a model
dossier_text = open("output/per_model_enriched/CHQD.058.09.01.TM_dossier.md", encoding="utf-8").read()

# 2. Step 1: Generate Hypothesis Prompt
hypo_prompt = build_hypothesis_prompt(dossier_text)
# hypo_response = llm_client.generate(hypo_prompt["system"], hypo_prompt["user"])

# 3. Step 2: Generate Narrative Prompt (using the generated hypothesis)
narr_prompt = build_narrative_prompt(dossier_text, hypo_response)
# final_narrative = llm_client.generate(narr_prompt["system"], narr_prompt["user"])
```

---

## 3. Project Structure & Components

| Module / Path | Role | Description |
|---|---|---|
| [`core.py`](core.py) | **ETL & Dossier Engine** | Excel ingestion, quarter arithmetic, KRI filtering, KPI vectorization, taxonomy decoding, and XML-tagged Markdown serialization. |
| [`scenario_enrichment/`](scenario_enrichment/) | **Qualitative Enricher** | Standalone module to load `scenarios.json` and inject `<scenario_detection_logic>` into dossiers. |
| [`prompt_pipeline/`](prompt_pipeline/) | **2-Step Prompt Framework** | Generates Step 1 (Hypothesis / Causal Chain) and Step 2 (Executive Narrative $\le 400$ words) prompt bundles. |
| [`app.py`](app.py) | **Web Server & UI** | Flask app with embedded dashboard for scanning and running pipeline runs. |
| [`main.py`](main.py) | **CLI Entry Point** | Command-line runner for batch country/business line processing. |
| [`start.bat`](start.bat) | **Windows Launcher** | Zero-config batch script to launch the web dashboard. |
| [`run.ipynb`](run.ipynb) | **Jupyter Notebook** | Interactive notebook for batch execution and experimentation. |

---

## 4. Alert Definition Taxonomy Standards (`ABCD.123.SS.RR.XY`)

Alert definition codes are automatically parsed into their constituent governance parameters:

### Segment Mapping (`SS`)
| Code | CTC | Segment Name | Line of Business |
|---|---|---|---|
| **01** | FI | Financial Institution | Wholesale (WB) |
| **02** | LARGE | Large Corporation | Wholesale (WB) |
| **03** | SMALL / OTHER | Small Corporation / Other WB Entity | Wholesale (WB) |
| **04** | MIDCORP | Medium Corporation | Retail (RB) |
| **05** | SME | Small-Medium Entity | Retail (RB) |
| **06** | PRIVATE | Private Individual | Retail (RB) |
| **07** | PRIBA | Private Banking | Retail (RB) |
| **08** | Combined | Wholesale Banking Customer (01, 02, 03, 60) | Wholesale (WB) |
| **09** | Combined | Retail - Entity (04, 05, 13–22: Midcorp, SME, CI, NCI) | Retail (RB) |
| **10** | Combined | Retail - Individual (06, 07, 24–27: Private, PRIBA, Turnover bands) | Retail (RB) |
| **11** | Combined | Retail Banking Customer (04–07, 13–22, 24–27) | Retail (RB) |
| **12** | Combined | Universal Banking Customer (All WB & RB Segments) | Universal (UB) |
| **13–17** | CI-XL to CI-XS | Cash Intensive Entities (Extra Large to Extra Small) | Retail (RB) |
| **18–22** | NCI-XL to NCI-XS | Non-Cash Intensive Entities (Extra Large to Extra Small) | Retail (RB) |
| **23** | Combined | Cash & Non-Cash Intensive Entities (13–22) | Retail (RB) |
| **24–27** | INDLT to INDVHT | Individuals (Low, Medium, High, Very High Turnover) | Retail (RB) |
| **60** | MEDIUM | Medium Corporation | Wholesale (WB) |

### Customer Risk Mapping (`RR`)
| Code | Risk Category | Description |
|---|---|---|
| **00** | All Risks | Combined 01 (High), 02 (Medium), 03 (Low) |
| **01** | High Risk | High risk tier |
| **02** | Medium Risk | Medium risk tier |
| **03** | Low Risk | Low risk tier |
| **04** | Medium/Low Risk | Combined 02 (Medium) and 03 (Low) |

### Monitoring Period Mapping (`XY`)
| Code | Alias | Evaluation Window |
|---|---|---|
| **TD** | Today | 1 day transaction activity |
| **TDY** | Today + Yesterday | 2 days transaction activity |
| **TW** | This Week | 1 calendar week (Mon–Sun, 1–7 days) |
| **TWLW** | This Week + Last Week | 2 calendar weeks (8–14 days) |
| **TM** | This Month | 1 calendar month |
| **TMLM** | This Month + Last Month | 2 calendar months (current + preceding month) |
| **TQ** | This Quarter | 1 calendar quarter (90–92 days) |
| **TQLQ** | This Quarter + Last Quarter | 2 calendar quarters (current + preceding quarter) |
| **RP** | Rolling Period | Rolling window (This Month + N Last Months) |

---

## 5. KRI Governance Evaluation Rules

| Indicator | Title | Trigger Evaluation Rule (Boolean OR) | Diagnostic Focus |
|---|---|---|---|
| **KRI 1** | Deviation in Alert Volume | `[1-3 std dev + change >=50 (RB) / >=30 (WB) for >=2 consecutive quarters]`<br>**OR**<br>`[>=3 std dev + change >=50 (RB) / >=30 (WB) in 1 quarter]` | Customer behaviour shifts, population drift, data ingestion glitches, threshold modifications, emerging typology waves. |
| **KRI 2** | Deviation in True Positive Volume | `[Downward 1-3 std dev + drop >=15 (RB) / >=10 (WB) for >=2 consecutive quarters]`<br>**OR**<br>`[Downward >=3 std dev + drop >=15 (RB) / >=10 (WB) in 1 quarter]` | Reduced detection capability, control degradation, decaying threshold calibration. |
| **KRI 3** | Accumulation in Threshold Proximity | `[10-50% proximity shift + 5-10 TPs for >=2 consecutive quarters]`<br>**OR**<br>`[>=50% proximity shift + >=10 TPs in 1 quarter]` | Threshold boundary sensitivity; indicates if small threshold adjustments will capture or shed major productive volume. |
| **KRI 6** | Dormant Alert Definition Identification | `[Active for >=3 consecutive quarters and subsequently produces 0 alerts for 3 consecutive quarters]` | Control obsolescence, overly restrictive thresholds, data pipeline failures, or rare typology safety nets. |

---

## 6. Deterministic Action Taxonomy for Narratives

The LLM is strictly constrained in Step 2 to select exactly one of the 4 governance actions:

1. `[ACTION: NO ACTION REQUIRED]`
   - Justification: Deactivated model, expected burn-in period for newly active rule, post-change re-baseline, or temporary volume fluctuation with healthy conversion rates (KPI 2b).
2. `[ACTION: RECALIBRATE / TIGHTEN THRESHOLD]`
   - Justification: Alert volume explosion (KRI 1) accompanied by collapsing True Positive rates (KRI 2 / KPI 2b), indicating excessive noise.
3. `[ACTION: RE-BAND / ADJUST PROXIMITY BOUNDARY]`
   - Justification: Escalation clustering near boundary limits (KRI 3), indicating parameter sensitivity or customer structuring.
4. `[ACTION: DECOMMISSION / CONSOLIDATE]`
   - Justification: Prolonged zero-volume dormancy across $\ge 3$ evaluation quarters (KRI 6) where typology coverage is superseded by another control (retained only if serving as a critical Terrorist Financing / Sanctions safety net).
