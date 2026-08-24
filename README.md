# Narrative Generator — KRI/KPI Quantitative Context & Dossier Builder

A lightweight, high-performance Python ETL pipeline for Transaction Monitoring (TM). It scans quarterly Excel workbooks, filters alert definitions with triggered Key Risk Indicators (KRIs), enriches them with Key Performance Indicator (KPI) metrics, tracks exact file and sheet source citations, and generates LLM-optimized XML-tagged Markdown dossiers alongside JSON context payloads.

---

## 1. Setup Instructions

Prerequisites: Python 3.10+

```bash
pip install -r requirements.txt
```

---

## 2. How to Run the Code

### Option A: Interactive Web Interface (Recommended)
Double-click [`start.bat`](start.bat) on Windows or execute:
```bash
python app.py --port 5000
```
- Automatically opens `http://localhost:5000` in your web browser.
- **Browse** and choose input/output folders with native Windows dialogs.
- **Scan** automatically groups and displays Excel files by Country and Business Line.
- Check/uncheck individual files or entire country portfolios, then click **Run**.

### Option B: Command Line Interface (CLI)
```bash
python main.py --country PL --business-line RB --ingestion-quarter Q1_2026
```
*(Optional flags: `--input-dir input/` and `--output-dir output/`)*

### Option C: Jupyter Notebook
Open [`run.ipynb`](run.ipynb) in VS Code or Jupyter, configure the `RUNS` list, and execute the cell:
```python
RUNS = [
    ("PL", "RB"),
    ("RO", "WB"),
]
```

---

## 3. How to Read the Codebase

### System Flow & Architecture

```text
Input Excel Files (e.g. input/PL_RB_*.xlsx)
                 │
                 ▼
      [core.py: load_tables] ── Fast openpyxl reader & source provenance tagger (file + sheet)
                 │
                 ▼
     [core.py: resolve_quarter] ── Ingestion / Test / Base quarter derivation
                 │
                 ▼
      [core.py: filter_kris] ── Filter triggered alert definitions (KRI == 1) with provenance
                 │
                 ▼
      [core.py: enrich_kpis] ── Vectorized KPI pull with sheet references
                 │
                 ▼
      [core.py: build_output]
                 ├── <COUNTRY>_<BL>_<QUARTER>_dossiers.md (Combined Dossiers)
                 ├── per_model/<ad>_dossier.md (Isolated Model Dossiers)
                 ├── <COUNTRY>_<BL>_<QUARTER>_relevance_matrix.md
                 ├── <COUNTRY>_<BL>_<QUARTER>_quantitative_context.json
                 └── <COUNTRY>_<BL>_<QUARTER>_relevance_matrix.json
```

### Core Components

| File | Role |
|---|---|
| [`core.py`](core.py) | **ETL & Dossier Engine**: Quarter arithmetic, Excel loader with provenance, KRI filter, KPI enricher, and XML-tagged Markdown Dossier serializer |
| [`scenario_enrichment/`](scenario_enrichment/) | **Qualitative Enricher (Standalone)**: CLI & engine to inject scenario definitions (`scenarios.json`) into quantitative dossiers |
| [`app.py`](app.py) | **Web Server & UI**: Flask endpoints (`/api/scan`, `/api/run`, `/api/browse`) with embedded dark-mode UI |
| [`main.py`](main.py) | **CLI Entry Point**: Parses command-line arguments and runs the pipeline |
| [`run.ipynb`](run.ipynb) | **Interactive Notebook**: Batch processing and interactive testing |
| [`start.bat`](start.bat) | **Windows Launcher**: Auto-checks dependencies and starts the web app |
| [`requirements.txt`](requirements.txt) | Explicit dependency versions (`pandas`, `openpyxl`, `flask`) |
| [`.gitignore`](.gitignore) | Excludes bytecode, temp Excel locks (`~$*.xlsx`), and output artifacts |

### Business & Pipeline Logic
- **Quarter Math**:
  - `ingestion_quarter` (e.g. `Q1_2026`) = current run period.
  - `test_quarter` = ingestion − 2 quarters (`Q3_2025`, evaluation period).
  - `base_quarter` = ingestion − 3 quarters (`Q2_2025`, baseline period).
- **Provenance & Citations**: Every single data point captures its origin (`<Filename>.xlsx/<SheetName>`), enabling LLMs to generate verifiable narrative citations.
- **KRI Trigger Evaluation**: Inspects sheets `KRI_1`, `KRI_2`, `KRI_3`, and `KRI_6`. Filters alert definitions where the trigger flag `== 1`.
- **KPI Enrichment**: Pre-filters KPI sheets (`KPI_1`, `KPI_2b`, `KPI_3`, `KPI_6`, `KPI_11`, `KPI_12`, `KPI_15a/b`, `KPI_16`, `KPI_17`, `KPI_18`) exclusively for triggered alert definitions.

---

## 4. Input Filename Convention

Input files must include `<Country>_<BusinessLine>` separated by underscores (`_`) anywhere in the filename.

- **Country**: 2 to 4 letter country code (e.g. `PL`, `RO`, `FR`, `DE`, `CH`, `NL`).
- **Business Line**: Short or long format (case-insensitive):
  - **RB** synonyms: `RB`, `Retail`, `Retail_Bank`, `Retail_Banking`, `RetailBank`, `RetailBanking`
  - **WB** synonyms: `WB`, `Wholesale`, `Wholesale_Bank`, `Wholesale_Banking`, `WholesaleBank`, `WholesaleBanking`

---

## 5. Output Deliverables & Formats

The pipeline generates both XML-tagged Markdown Dossiers (for prompt injection / narrative drafting) and JSON payloads (for programmatic parsing):

### Deliverable 1: XML-Tagged Markdown Dossiers (`_dossiers.md` and `per_model/<ad>_dossier.md`)
High-signal, structured markdown tables enclosed in semantic XML tags with explicit source citations per row:

```markdown
<model id="AD_PL_RB_001" code="AD_PL_RB_001">

<structured_metrics>
  <domain name="identity">
    | Metric | Value | Source |
    |--------|-------|--------|
    | Country | PL | PL_RB_kri.xlsx/KRI_1 |
    | Business Line | RB | PL_RB_kri.xlsx/KRI_1 |
    | Segment Description | Retail Banking | PL_RB_kri.xlsx/KRI_1 |
    | Customer Type Code | INDV | PL_RB_kri.xlsx/KRI_1 |
    | Customer Risk | HIGH | PL_RB_kri.xlsx/KRI_1 |
  </domain>

  <domain name="quarterly_context">
    | Metric | Value | Source |
    |--------|-------|--------|
    | Ingestion Quarter | Q1_2026 | Derived/Quarter_Resolution |
    | Test Quarter (Evaluation) | Q3_2025 | Derived/Quarter_Resolution |
    | Base Quarter (Baseline) | Q2_2025 | Derived/Quarter_Resolution |
  </domain>

  <domain name="thresholds">
    | Metric | Value | Source |
    |--------|-------|--------|
    | Min Amount Threshold | 15000 | PL_RB_kri.xlsx/KRI_1 |
    | Min Frequency Threshold | 5 | PL_RB_kri.xlsx/KRI_1 |
  </domain>

  <domain name="flags">
    | Metric | Value | Source |
    |--------|-------|--------|
    | Many Alerts Flag | 1 | PL_RB_kri.xlsx/KRI_1 |
    | Lowest Amount Threshold Flag | 0 | PL_RB_kri.xlsx/KRI_1 |
    | Thresholds Changed Flag | 0 | PL_RB_kri.xlsx/KRI_1 |
  </domain>

  <domain name="triggered_kris">
    | Metric | Value | Source |
    |--------|-------|--------|
    | KRI_1 (increase) Test Quarter Count | 142 | PL_RB_kri.xlsx/KRI_1 |
    | KRI_1 (increase) Base Quarter Count | 85 | PL_RB_kri.xlsx/KRI_1 |
    | KRI_1 (increase) Difference (Test - Base) | 57 | PL_RB_kri.xlsx/KRI_1 |
    | KRI_1 (increase) Full Period Avg Count | 90.2 | PL_RB_kri.xlsx/KRI_1 |
    | KRI_1 (increase) Full Period Stddev | 12.4 | PL_RB_kri.xlsx/KRI_1 |
    | KRI_1 (increase) 3-Sigma Exceeded | 1 | PL_RB_kri.xlsx/KRI_1 |
    | KRI_1 (increase) Consecutive Trigger | 1 | PL_RB_kri.xlsx/KRI_1 |
    | KRI_1 (increase) Monthly Trend | month_1: 40 | month_2: 48 | month_3: 54 | PL_RB_kri.xlsx/KRI_1 |
  </domain>

  <domain name="kpi_metrics">
    | Metric | Value | Source |
    |--------|-------|--------|
    | Alert Count (KPI_1) | 142 | PL_RB_kpi.xlsx/KPI_1 |
    | Productive Alert Rate % (KPI_2b) | 18.5 | PL_RB_kpi.xlsx/KPI_2b |
    | Customer Count (KPI_3) | 110 | PL_RB_kpi.xlsx/KPI_3 |
    | KPI_17 Quarterly Alert Count | 142 | PL_RB_kpi.xlsx/KPI_17_quarter |
    | KPI_17 Quarterly True Positive Count | 26 | PL_RB_kpi.xlsx/KPI_17_quarter |
    | KPI_17 Quarterly False Positive Rate | 0.817 | PL_RB_kpi.xlsx/KPI_17_quarter |
    | KPI_17 Quarterly General Overlap Ratio | 0.12 | PL_RB_kpi.xlsx/KPI_17_quarter |
  </domain>

  <domain name="governance_recommendations">
    | Metric | Value | Source |
    |--------|-------|--------|
    | Recommendation | Review threshold adjustment | PL_RB_kri.xlsx/KRI_1 |
  </domain>
</structured_metrics>

</model>
```
      "base": "Q2_2025"
    },
    "triggered_kris": [
      {
        "kri": "KRI_1",
        "direction": "increase",
        "test_quarter": "Q3_2025",
        "base_quarter": "Q2_2025",
        "test_quarter_count": 142,
        "base_quarter_count": 85,
        "difference": 57,
        "full_period_avg_count": 90.2,
        "full_period_stddev_count": 12.4,
        "three_sigma_exceeded": 1,
        "consecutive_trigger": 1,
        "monthly_trend": { "month_1": 40, "month_2": 48, "month_3": 54 }
      }
    ],
    "recommendation": "Review threshold adjustment",
    "kpi_context": {
      "kpi1_alert_count": 142,
      "kpi2b_productive_alert_rate": 18.5,
      "kpi3_customer_count": 110,
      "kpi17_quarterly_metrics": {
        "alert_count": 142,
        "true_positive_count": 26,
        "false_positive_rate": 0.817,
        "general_overlap_ratio": 0.12
      }
    }
  },
  {
    "alert_definition": "AD_PL_RB_002",
    "identity": {
      "country": "PL",
      "business_line": "RB",
      "segment_desc": "Retail Small Business",
      "customer_type_code": "SME",
      "customer_risk": "MEDIUM"
    },
    "thresholds": {
      "min_amount_threshold": 25000,
      "min_frequency_threshold": 8
    },
    "flags": {
      "many_alerts_flag": 0,
      "thresholds_changed_flag": 0
    },
    "quarters": {
      "ingestion": "Q1_2026",
      "test": "Q3_2025",
      "base_quarters": ["Q1_2025", "Q2_2025"]
    },
    "triggered_kris": [
      {
        "kri": "KRI_2",
        "test_quarter": "Q3_2025",
        "base_quarter": "Q2_2025",
        "test_quarter_count": 8,
        "base_quarter_count": 34,
        "difference": -26,
        "alert_count": 220,
        "full_period_avg_productive_alerts": 31.5,
        "full_period_stddev_productive_alerts": 6.8,
        "three_sigma_exceeded": 1,
        "consecutive_trigger": 1,
        "monthly_trend": { "month_1": 4, "month_2": 2, "month_3": 2 }
      },
      {
        "kri": "KRI_2",
        "test_quarter": "Q3_2025",
        "base_quarter": "Q1_2025",
        "test_quarter_count": 8,
        "base_quarter_count": 40,
        "difference": -32,
        "alert_count": 220,
        "full_period_avg_productive_alerts": 31.5,
        "full_period_stddev_productive_alerts": 6.8,
        "three_sigma_exceeded": 1,
        "consecutive_trigger": 1,
        "monthly_trend": { "month_1": 4, "month_2": 2, "month_3": 2 }
      }
    ],
    "recommendation": "Investigate drop in true productive alerts",
    "kpi_context": {
      "kpi1_alert_count": 220,
      "kpi2b_productive_alert_rate": 3.6,
      "kpi3_customer_count": 185
    }
  },
  {
    "alert_definition": "AD_PL_RB_003",
    "identity": {
      "country": "PL",
      "business_line": "RB",
      "segment_desc": "Private Banking",
      "customer_type_code": "CORP",
      "customer_risk": "MEDIUM"
    },
    "thresholds": {
      "min_amount_threshold": 50000,
      "min_frequency_threshold": 10
    },
    "flags": {
      "many_alerts_flag": 0,
      "thresholds_changed_flag": 1
    },
    "quarters": {
      "ingestion": "Q1_2026",
      "test": "Q3_2025"
    },
    "triggered_kris": [
      {
        "kri": "KRI_3",
        "sub_trigger": "amount",
        "test_quarter": "Q3_2025",
        "base_quarter": "Q2_2025",
        "test_quarter_accum_ratio_amount": 1250000.0,
        "base_quarter_accum_ratio_amount": 820000.0,
        "amount_deviation": 0.524,
        "alert_count": 38,
        "false_positive_rate": 0.658,
        "true_positive_rate": 0.342
      },
      {
        "kri": "KRI_6",
        "test_quarter": "Q3_2025",
        "test_quarter_alerts": 0,
        "test_quarter_minus_1_alerts": 0,
        "test_quarter_minus_2_alerts": 0,
        "total_monitoring_alerts": 103,
        "oldest_benchmark_period": "2024-01"
      }
    ],
    "recommendation": "Maintain active monitoring",
    "kpi_context": {
      "kpi1_alert_count": 38,
      "kpi6_value": 3.4,
      "kpi16_unique_customers": 29
    }
  }
]
```

### Deliverable 2: `relevance_matrix.json`
Lightweight lookup mapping allowing prompt builders to look up and inject only relevant qualitative descriptions.

```json
[
  {
    "alert_definition": "AD_PL_RB_001",
    "triggered_kris": [
      "KRI_1"
    ],
    "kri_sub_triggers": {
      "KRI_1": [
        "increase"
      ]
    },
    "evaluated_base_quarters": [
      "Q2_2025"
    ],
    "available_kpis": [
      "KPI_1",
      "KPI_2b",
      "KPI_3",
      "KPI_17_quarter"
    ]
  },
  {
    "alert_definition": "AD_PL_RB_002",
    "triggered_kris": [
      "KRI_2"
    ],
    "evaluated_base_quarters": [
      "Q1_2025",
      "Q2_2025"
    ],
    "available_kpis": [
      "KPI_1",
      "KPI_2b",
      "KPI_3"
    ]
  },
  {
    "alert_definition": "AD_PL_RB_003",
    "triggered_kris": [
      "KRI_3",
      "KRI_6"
    ],
    "kri_sub_triggers": {
      "KRI_3": [
        "amount"
      ]
    },
    "evaluated_base_quarters": [
      "Q2_2025"
    ],
    "available_kpis": [
      "KPI_1",
      "KPI_6",
      "KPI_16"
    ]
  }
]
```

---
