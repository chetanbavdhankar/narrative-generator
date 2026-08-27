# Transaction Monitoring (TM) Narrative Generator

A lightweight, unified ETL and prompt framework for Transaction Monitoring (TM) Model Governance. It processes quarterly Excel workbooks, enriches alert definitions with quantitative KPIs and qualitative scenario detection logic from `scenarios.json`, decodes alert taxonomy (`ABCD.123.SS.RR.XY`), and generates **one single enriched Markdown dossier output file** ready for 2-step LLM governance narrative generation.

---

## 1. End-to-End Workflow Architecture

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ 1. INGESTION & UNIFIED DOSSIER GENERATOR (core.py / main.py / app.py)      │
│   • Quantitative Inputs: Country Excel Files (e.g. input/PL_RB_*.xlsx)     │
│   • Qualitative Input: Global Scenarios Catalog (e.g. scenarios.json)      │
│   • Automated Processing:                                                  │
│     - Resolves evaluation quarters (Ingestion / Test / Base)               │
│     - Evaluates KRI 1, 2, 3, 6 triggers                                    │
│     - Enriches KPI metrics (KPI 1, 2b, 3, 6, 11, 12, 15a/b, 16, 17, 18)   │
│     - Decodes AD Taxonomy (Segment SS, Risk RR, Monitoring Window XY)      │
│     - Injects Qualitative Scenario Logic (<scenario_detection_logic>)      │
│   • Output: ONE Single Enriched Dossier (output/<COUNTRY>_<BL>_dossiers.md)│
└─────────────────────────────────────┬──────────────────────────────────────┘
                                      │
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ 2. DIRECT LLM EXECUTIVE NARRATIVE SYNTHESIS (prompts/narrative_prompt.md)  │
│   • Single-Step Direct Generation: Paste Model Dossier -> Final Narrative  │
│   • Strict 3-Section Format: Observation -> Analysis -> Conclusion         │
│   • Mandatory Evidence Citations: [REF: <domain>.<metric>=<value>]         │
│   • Deterministic Governance Actions: NO ACTION / RECALIBRATE / RE-BAND/   │
│     DECOMMISSION                                                           │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Quickstart Execution Guide

### Prerequisites
```bash
pip install -r requirements.txt
```

---

### Option A: Interactive Web UI (Recommended)
Double-click [`start.bat`](start.bat) on Windows or execute:
```bash
python app.py --port 5000
```
- Open `http://localhost:5000` in your web browser.
- **Select Folders**: Browse and choose your input folder and output directory.
- **Select Scenario File**: Select your country-agnostic `scenarios.json` file (pre-filled by default).
- Click **Scan Folder** to detect and select countries/business lines.
- Click **Run Pipeline** $\rightarrow$ Generates **one single enriched Markdown dossier** per selected country portfolio in `output/`.

---

### Option B: Command Line Interface (CLI)
```bash
python main.py \
  --country PL \
  --business-line RB \
  --ingestion-quarter Q1_2026 \
  --scenarios-file scenarios.json \
  --input-dir input/ \
  --output-dir output/
```
*(Generates `output/PL_RB_Q1_2026_dossiers.md` as the single consolidated output file).*

---

### Option C: Generating the Executive Governance Narrative

1. Open [`prompts/narrative_prompt.md`](prompts/narrative_prompt.md).
2. Copy and paste the target model dossier block (`<model id="..."> ... </model>`) from your generated `_dossiers.md` file under the `# INPUT MODEL DOSSIER` section.
3. Pass to your LLM to generate the complete, audit-ready executive narrative ($\le 380$ words) structured into:
   - **Observation**: Factual summary with exact `[REF: ...]` citations.
   - **Analysis**: Causal diagnosis of customer population behavior, conversion rates, and threshold proximity.
   - **Conclusion**: Quantitative control integrity risk assessment and final `[ACTION: <TYPE>]` tag.

---

## 3. Project Structure & Components

```text
narrative_generator/
├── core.py                   # Core ETL, taxonomy decoding & unified dossier serialization engine
├── app.py                    # Web UI with native folder/file pickers and batch country runner
├── main.py                   # CLI entry point for batch processing
├── start.bat                 # Windows one-click launcher for app.py
├── prompts/
│   └── narrative_prompt.md   # Standalone Executive Root Cause Narrative Prompt (Observation -> Analysis -> Conclusion)
├── requirements.txt          # Dependencies (pandas, openpyxl, flask)
└── README.md                 # Complete documentation and user guide
```

---

## 4. Alert Definition Taxonomy Standards (`ABCD.123.SS.RR.XY`)

Alert definitions are automatically decoded at the model header level:

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

## 5. KRI Evaluation Rules & Governance Actions

| Indicator | Title | Trigger Evaluation Rule (Boolean OR) | Diagnostic Focus |
|---|---|---|---|
| **KRI 1** | Deviation in Alert Volume | `[1-3 std dev + change >=50 (RB) / >=30 (WB) for >=2 consecutive quarters]`<br>**OR**<br>`[>=3 std dev + change >=50 (RB) / >=30 (WB) in 1 quarter]` | Customer behaviour shifts, population drift, data ingestion glitches, threshold modifications, emerging typology waves. |
| **KRI 2** | Deviation in True Positive Volume | `[Downward 1-3 std dev + drop >=15 (RB) / >=10 (WB) for >=2 consecutive quarters]`<br>**OR**<br>`[Downward >=3 std dev + drop >=15 (RB) / >=10 (WB) in 1 quarter]` | Reduced detection capability, control degradation, decaying threshold calibration. |
| **KRI 3** | Accumulation in Threshold Proximity | `[10-50% proximity shift + 5-10 TPs for >=2 consecutive quarters]`<br>**OR**<br>`[>=50% proximity shift + >=10 TPs in 1 quarter]` | Threshold boundary sensitivity; indicates if small threshold adjustments will capture or shed major productive volume. |
| **KRI 6** | Dormant Alert Definition Identification | `[Active for >=3 consecutive quarters and subsequently produces 0 alerts for 3 consecutive quarters]` | Control obsolescence, overly restrictive thresholds, data pipeline failures, or rare typology safety nets. |

### Deterministic Action Decisions
The LLM selects exactly one of the 4 standard governance actions:
1. `[ACTION: NO ACTION REQUIRED]` (Deactivated model, expected burn-in, post-change re-baseline, or justifiable business surge with healthy conversion).
2. `[ACTION: RECALIBRATE / TIGHTEN THRESHOLD]` (Volume surge with low/decaying true positive conversion).
3. `[ACTION: RE-BAND / ADJUST PROXIMITY BOUNDARY]` (Productive alerts clustering near threshold limits).
4. `[ACTION: DECOMMISSION / CONSOLIDATE]` (Prolonged dormancy across $\ge 3$ quarters unless serving as critical TF/Sanctions safety net).

For detailed mapping between KRIs, KPIs, and underlying ingestion table schemas, see [`kri_kpi_mapping.md`](kri_kpi_mapping.md).

---

## 6. Recent Changes & Paired Evaluation Architecture
- **Why:** Presenting KRIs and KPIs in disconnected sections fragmented causal analysis; pairing each KRI directly with its relevant KPIs creates a complete, self-contained diagnostic story.
- **How:** Restructured `serialize_dossier_markdown()` in `core.py` into `<domain name="triggered_kri_evaluations">`, where each Evaluation Unit contains:
  1. **KRI Trigger Telemetry**: Test/Base volume counts, statistical deviation, 3-sigma flag, monthly progression, policy definition.
  2. **Directly Paired KPI Metrics**: Primary & supporting KPIs with Test vs Baseline values, differences ($\Delta$), monthly trends, and relevance tags.
  3. **Integrated Causal Diagnostic Story**: Plain-English narrative synthesizing the KRI trigger mechanics with the KPI evidence into one cohesive root cause.
- **Impact:** LLM governance prompts receive clean, unified diagnostic context per trigger, preventing hallucinated or disconnected reasoning across multiple concurrent KRIs.


