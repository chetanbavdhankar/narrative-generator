# Narrative Generator — KRI/KPI Quantitative Context Builder

A lightweight, high-performance Python ETL pipeline for Transaction Monitoring (TM). It scans quarterly Excel workbooks, filters alert definitions with triggered Key Risk Indicators (KRIs), enriches them with Key Performance Indicator (KPI) metrics, and generates compact JSON context payloads for local ~2B-parameter LLMs.

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
      [core.py: load_tables] ── Fast openpyxl reader & column normalizer
                 │
                 ▼
     [core.py: resolve_quarter] ── Ingestion / Test / Base quarter derivation
                 │
                 ▼
      [core.py: filter_kris] ── Filter triggered alert definitions (KRI == 1)
                 │
                 ▼
      [core.py: enrich_kpis] ── Vectorized KPI pull for triggered alert definitions
                 │
                 ▼
      [core.py: build_output]
                 ├── <COUNTRY>_<BL>_<QUARTER>_quantitative_context.json
                 └── <COUNTRY>_<BL>_<QUARTER>_relevance_matrix.json
```

### Core Components

| File | Role |
|---|---|
| [`core.py`](core.py) | **ETL Engine**: Quarter arithmetic, Excel loader, KRI filter, vectorized KPI enricher, and JSON context builder |
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
- **KRI Trigger Evaluation**: Inspects sheets `KRI_1`, `KRI_2`, `KRI_3`, and `KRI_6`. Filters alert definitions where the trigger flag `== 1`.
- **KPI Enrichment**: Pre-filters KPI sheets (`KPI_1`, `KPI_2b`, `KPI_3`, `KPI_6`, `KPI_11`, `KPI_12`, `KPI_15a/b`, `KPI_16`, `KPI_17`, `KPI_18`) exclusively for the triggered alert definitions.

---

## 4. Input Filename Convention

Files placed in the input folder must follow the format `<Country>_<BusinessLine>_<description>.xlsx`:
- Examples: `PL_RB_kri.xlsx`, `PL_RB_kpi.xlsx`, `RO_WB_data.xlsx`, `FR_RB_2026.xlsx`

---

## 5. Output Deliverables & Examples

The pipeline writes two complementary JSON artifacts per run to the `output/` directory:

### Deliverable 1: `quantitative_context.json`
Abbreviation-dense context payload formatted for direct local LLM ingestion (~800–1000 tokens per alert definition).

```json
[
  {
    "alert_definition": "AD_PL_RB_001",
    "identity": {
      "country": "PL",
      "business_line": "RB",
      "segment_desc": "Retail Banking",
      "customer_type_code": "INDV",
      "customer_risk": "HIGH"
    },
    "thresholds": {
      "min_amt_th": 15000,
      "min_freq_th": 5
    },
    "flags": {
      "many_alert": 1,
      "low_amt_th": 0,
      "th_changed": 0
    },
    "quarters": {
      "ingestion": "Q1_2026",
      "test": "Q3_2025",
      "base": "Q2_2025"
    },
    "triggered_kris": [
      {
        "kri": "KRI_1",
        "dir": "increase",
        "test_q_cnt": 142,
        "base_q_cnt": 85,
        "diff": 57,
        "full_avg": 90.2,
        "full_std": 12.4,
        "3sigma": 1,
        "consec": 1,
        "trend": { "m1": 40, "m2": 48, "m3": 54 }
      }
    ],
    "recommendation": "Review threshold adjustment",
    "kpi_context": {
      "kpi1_alerts": 142,
      "kpi2b_prod": 18.5,
      "kpi3_cust": 110,
      "kpi17q": {
        "alert_cnt": 142,
        "tp_cnt": 26,
        "fpr": 0.817,
        "overlap": 0.12
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
      "min_amt_th": 25000,
      "min_freq_th": 8
    },
    "flags": {
      "many_alert": 0,
      "th_changed": 0
    },
    "quarters": {
      "ingestion": "Q1_2026",
      "test": "Q3_2025",
      "base": "Q2_2025"
    },
    "triggered_kris": [
      {
        "kri": "KRI_2",
        "test_q_cnt": 8,
        "base_q_cnt": 34,
        "diff": -26,
        "alert_cnt": 220,
        "full_avg": 31.5,
        "full_std": 6.8,
        "3sigma": 1,
        "consec": 1,
        "trend": { "m1": 4, "m2": 2, "m3": 2 }
      }
    ],
    "recommendation": "Investigate drop in true productive alerts",
    "kpi_context": {
      "kpi1_alerts": 220,
      "kpi2b_prod": 3.6,
      "kpi3_cust": 185
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
      "min_amt_th": 50000,
      "min_freq_th": 10
    },
    "flags": {
      "many_alert": 0,
      "th_changed": 1
    },
    "quarters": {
      "ingestion": "Q1_2026",
      "test": "Q3_2025",
      "base": "Q2_2025"
    },
    "triggered_kris": [
      {
        "kri": "KRI_3",
        "sub": "amount",
        "test_accum_amt": 1250000.0,
        "base_accum_amt": 820000.0,
        "dev_amt": 0.524,
        "alert_cnt": 38,
        "fpr": 0.658,
        "tpr": 0.342
      },
      {
        "kri": "KRI_6",
        "test_q_alerts": 38,
        "test_q_m1_alerts": 35,
        "test_q_m2_alerts": 30,
        "total": 103,
        "oldest_bench": "2024-01"
      }
    ],
    "recommendation": "Maintain active monitoring",
    "kpi_context": {
      "kpi1_alerts": 38,
      "kpi6_val": 3.4,
      "kpi16_uniq_cust": 29
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
    "available_kpis": [
      "KPI_1",
      "KPI_6",
      "KPI_16"
    ]
  }
]
```

---
