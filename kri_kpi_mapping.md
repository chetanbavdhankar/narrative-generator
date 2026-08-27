# TM Governance: KRI-to-KPI Diagnostic Mapping & Technical Schema Matrix

Comprehensive reference mapping connecting **Key Risk Indicator (KRI)** trigger mechanics to **Key Performance Indicator (KPI)** diagnostics and their underlying data schemas in `core.py`.

---

## 1. Governance Baseline & Temporal Evaluation Architecture

All KRI triggers evaluate Alert Definition (AD) health by comparing performance against certified baselines:
- **Benchmark Quarter ($Q_{\text{bench}}$)**: Certified deployment baseline when thresholds and models are verified.
- **Base Quarter ($Q_{\text{base}}$)**: Historical comparison period ($Q_{\text{base}} > Q_{\text{bench}}$).
- **Test Quarter ($Q_{\text{test}}$)**: Current evaluation period ($Q_{\text{test}} > Q_{\text{base}} \ge Q_{\text{bench}} + 1$).

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    TM KRI MONITORING FRAMEWORK                                   │
├─────────────────────────┬─────────────────────────┬────────────────────┬─────────────────────────┤
│          KRI 1          │          KRI 2          │       KRI 3        │          KRI 6          │
│   Gross Volume Shift    │   True Positive Decay   │ Proximity Clustered│     Control Dormancy    │
│  (1-3σ / ≥3σ + Volume)  │ (Downward 1-3σ / ≥3σ)   │  (10-50% / ≥50% TP)│  (3Q Active -> 3Q Zero) │
└─────────────────────────┴─────────────────────────┴────────────────────┴─────────────────────────┘
```

---

## 2. Ingestion Table Schemas & Codebase Columns (`core.py`)

In `core.py`, data tables are loaded from quarterly workbooks and filtered by `ingestion_quarter`, `test_quarter`, and `alert_definition`:

| Sheet / Table Name | Table Type | Available / Extracted Columns | Target Output Key in Dossier |
| :--- | :--- | :--- | :--- |
| `KPI_1` | Simple (Quarterly) | `alert_definition`, `q_<ingestion_quarter>`, `q_<test_quarter>` | `kpi1_alert_count` |
| `KPI_2b` | Simple (Quarterly) | `alert_definition`, `q_<ingestion_quarter>`, `q_<test_quarter>` | `kpi2b_productive_alert_rate` (Alerted Customers) |
| `KPI_3` | Simple (Quarterly) | `alert_definition`, `q_<ingestion_quarter>`, `q_<test_quarter>` | `kpi3_customer_count` (Productive Customers / L3) |
| `KPI_6` | Simple (Quarterly) | `alert_definition`, `q_<ingestion_quarter>`, `q_<test_quarter>` | `kpi6_value` (First Productive Alert Percentile Rank) |
| `KPI_11` | Simple (Quarterly) | `alert_definition`, `q_<ingestion_quarter>`, `q_<test_quarter>` | `kpi11_value` (False Positive Rate %) |
| `KPI_12` | Simple (Quarterly) | `alert_definition`, `q_<ingestion_quarter>`, `q_<test_quarter>` | `kpi12_value` (True Positive Rate %) |
| `KPI_15a` | Simple (Quarterly) | `alert_definition`, `q_<ingestion_quarter>`, `q_<test_quarter>` | `kpi15a_value` (Amount Proximity TP %) |
| `KPI_15b` | Simple (Quarterly) | `alert_definition`, `q_<ingestion_quarter>`, `q_<test_quarter>` | `kpi15b_value` (Frequency Proximity TP %) |
| `KPI_16` | Simple (Quarterly) | `alert_definition`, `q_<ingestion_quarter>`, `q_<test_quarter>` | `kpi16_unique_customers` (Total Productive Alerts / TPs) |
| `KPI_17` | Simple (Quarterly) | `alert_definition`, `q_<ingestion_quarter>`, `q_<test_quarter>` | `kpi17_value` (Unique Productivity Ratio) |
| `KPI_17_quarter` | Structured Table | `alert_definition`, `test_quarter`, `alert_count`, `tp_count`, `false_positive_rate`, `general_overlap_ratio`, `prod_general_overlap_ratio` | `kpi17_quarterly_metrics` |
| `KPI_18_quarter` | Structured Table | `alert_definition`, `test_quarter`, `alert_count`, `tp_count`, `min_amount_threshold`, `max_amount_threshold`, `min_frequency_threshold` | `kpi18_quarterly_thresholds` |
| `KRI_1` / `2` / `3` / `6` | Trigger Tables | `test_quarter_count`, `base_quarter_count`, `test_base_quarter_diff`, `full_period_avg(*)`, `full_period_stddev_pop(*)`, `*_three_sigma_exceeded`, `*_with_consecutive`, `m_<month>` | `triggered_kris` |

---

## 3. KRI-to-KPI Deep-Dive & Diagnostic Mappings

### KRI 1: Deviation in Alert Volume (Gross Alert Volatility)

#### Technical Logic & Trigger Conditions
Evaluates statistical deviation of test quarter monthly alert volume against historical distribution:
$$\Delta_{\text{vol}} = \text{Count}(Q_{\text{test}}) - \text{Count}(Q_{\text{base}}), \quad \text{Z-Score} = \frac{|\Delta_{\text{vol}}|}{\sigma_{\text{pop}}}$$
- **Persistent Shift:** $1.0 \le \text{Z-Score} < 3.0$ **AND** $|\Delta_{\text{vol}}| \ge 50$ (Retail) / $\ge 30$ (Wholesale) for **$\ge 2$ consecutive test quarters**.
- **Extreme Anomaly:** $\text{Z-Score} \ge 3.0$ **AND** $|\Delta_{\text{vol}}| \ge 50$ (Retail) / $\ge 30$ (Wholesale) in **1 single quarter**.

#### Business Value & Governance Implications
Prevents operational investigator backlog, identifies customer demographic surges, flags upstream ETL duplicates, and highlights macro transactional drift.

#### Relevant KPIs & Schema Mapping
| Relevant KPI | Codebase Source Table | Extracted / Target Columns | Diagnostic Purpose for KRI 1 |
| :--- | :--- | :--- | :--- |
| **KPI 1** (Alert Count) | `KPI_1` / `KRI_1` | `q_<test_quarter>`, `test_quarter_count`, `base_quarter_count`, `difference` | Establishes the exact quarterly alert count and absolute delta against baseline. |
| **KPI 2b** (Alerted Customers) | `KPI_2b` | `q_<test_quarter>`, `q_<base_quarter>` | Ratio $\frac{\text{KPI 1}}{\text{KPI 2b}}$ reveals if volume surge is spread across new customers (macro growth) or repeat alerts on few entities (smurfing/burst). |
| **KPI 4b** (Tx Volume) | Feeds / System Metadata | `transaction_volume`, `transaction_count` | Correlates whether alert surge is linearly explained by upstream transaction growth. |
| **KPI 11** (FP Ratio) | `KPI_11` / `KPI_17_quarter` | `q_<test_quarter>`, `false_positive_rate` | Identifies whether the volume spike degraded operational efficiency with low-quality alerts. |
| **KPI 12** (TP Ratio) | `KPI_12` | `q_<test_quarter>` | Evaluates whether the volume surge yielded a proportional increase in detected risk. |
| **KPI 16** (Productive Alerts) | `KPI_16` / `KPI_17_quarter` | `q_<test_quarter>`, `tp_count` | Confirms if absolute productive output scaled with gross alert volume. |

---

### KRI 2: Deviation in True Positive Volume (Detection Capability Decay)

#### Technical Logic & Trigger Conditions
Evaluates downward statistical shifts in productive alerts (escalated to L3 / SAR/STR):
$$\Delta_{\text{TP}} = \text{TP}(Q_{\text{test}}) - \text{TP}(Q_{\text{base}})$$
- **Persistent Decay:** Downward $1.0 \le \text{Z-Score} < 3.0$ **AND** drop $\ge 15$ TPs (Retail) / $\ge 10$ TPs (Wholesale) across **$\ge 2$ consecutive quarters**.
- **Severe Collapse:** Downward $\text{Z-Score} \ge 3.0$ **AND** drop $\ge 15$ TPs (Retail) / $\ge 10$ TPs (Wholesale) in **1 single quarter**.

#### Business Value & Governance Implications
Uncovers silent control degradation, obsolete threshold calibration, evasion by illicit actors, or cannibalization by overlapping controls.

#### Relevant KPIs & Schema Mapping
| Relevant KPI | Codebase Source Table | Extracted / Target Columns | Diagnostic Purpose for KRI 2 |
| :--- | :--- | :--- | :--- |
| **KPI 16** (Productive Alerts) | `KPI_16` / `KRI_2` | `q_<test_quarter>`, `full_period_avg(productive_alerts_count)`, `difference` | Direct quantification of the drop in L3 escalated alerts. |
| **KPI 3** (Productive Customers) | `KPI_3` | `q_<test_quarter>`, `q_<base_quarter>` | Distinguishes whether we lost a single large productive client vs. broad systematic loss of true positive customers across the portfolio. |
| **KPI 12** (TP Ratio) | `KPI_12` | `q_<test_quarter>` | Assesses conversion efficiency collapse ($\text{TP} / \text{Total Alerts}$). |
| **KPI 6** (1st Productive Position) | `KPI_6` | `q_<test_quarter>` | Reveals if productive transactions shifted further away from the threshold, signaling typology migration. |
| **KPI 17** (Unique Productivity) | `KPI_17` / `KPI_17_quarter` | `q_<test_quarter>`, `prod_general_overlap_ratio`, `general_overlap_ratio` | Identifies if the drop is an illusion caused by a sister AD in the same typology capturing the alerts first. |
| **KPI 13** (Effectiveness Classification) | Derived Metric | `kpi12_value`, `kpi16_unique_customers` | Categorizes if the AD has transitioned into an "ineffective" state. |

---

### KRI 3: Accumulation in Threshold Proximity (Boundary Sensitivity)

#### Technical Logic & Trigger Conditions
Measures whether productive cases (TPs) cluster right at the edge of the trigger threshold ($[\text{Threshold}, \text{Threshold} + \delta]$):
$$\Delta_{\text{accum\_ratio}} = \text{Ratio}_{\text{prox}}(Q_{\text{test}}) - \text{Ratio}_{\text{prox}}(Q_{\text{base}})$$
- **Moderate Accumulation:** $10\% \le \Delta_{\text{accum\_ratio}} < 50\%$ **AND** $5 \le \text{TPs in proximity} \le 10$ for **$\ge 2$ consecutive quarters**.
- **High Accumulation:** $\Delta_{\text{accum\_ratio}} \ge 50\%$ **AND** $\text{TPs} \ge 10$ in **1 single quarter**.

#### Business Value & Governance Implications
Identifies smurfing/structuring patterns just above thresholds and highlights high boundary elasticity where minor threshold tuning significantly impacts risk capture.

#### Relevant KPIs & Schema Mapping
| Relevant KPI | Codebase Source Table | Extracted / Target Columns | Diagnostic Purpose for KRI 3 |
| :--- | :--- | :--- | :--- |
| **KPI 15a** (Amount Proximity TP) | `KPI_15a` / `KRI_3` | `q_<test_quarter>`, `test_quarter_accum_ratio_amount`, `kri3_amount_deviation` | Quantifies the % of productive alerts clustered near the minimum/maximum amount thresholds. |
| **KPI 15b** (Freq Proximity TP) | `KPI_15b` / `KRI_3` | `q_<test_quarter>`, `kri3_freq_deviation` | Quantifies the % of productive alerts clustered near transaction count/frequency thresholds. |
| **KPI 6** (1st Productive Position) | `KPI_6` | `q_<test_quarter>` | Pinpoints the lowest percentile rank of TPs; values close to $0.00\text{--}0.10$ confirm boundary stacking. |
| **KPI 18** (Secondary Parameters) | `KPI_18_quarter` | `min_amount_threshold`, `max_amount_threshold`, `min_frequency_threshold` | Evaluates proximity against secondary limits (ratios, profile multipliers, z-score cutoffs). |
| **KPI 16** (Productive Alerts) | `KPI_16` / `KRI_3` | `q_<test_quarter>`, `alert_count`, `tp_count` | Validates that sample size meets statistical significance ($\ge 5\text{--}10$ TPs). |
| **KPI 11 / 12** (FP / TP Rates) | `KPI_11`, `KPI_12` | `q_<test_quarter>` | Forecasts the noise-to-signal trade-off if thresholds are lowered. |

---

### KRI 6: Dormant Alert Definition Identification (Zero-Generation Control)

#### Technical Logic & Trigger Conditions
Non-statistical, temporal absence evaluation:
$$\text{Alerts}(Q_{t}) = 0 \quad \text{for } t \in \{T, T-1, T-2\} \quad \text{after being active for } \ge 3 \text{ historical quarters}$$

#### Business Value & Governance Implications
Identifies dead controls, overly restrictive multi-condition thresholds, or broken upstream data pipelines, enabling safe decommissioning or corrective re-engineering.

#### Relevant KPIs & Schema Mapping
| Relevant KPI | Codebase Source Table | Extracted / Target Columns | Diagnostic Purpose for KRI 6 |
| :--- | :--- | :--- | :--- |
| **KPI 1** (Alert Count) | `KPI_1` / `KRI_6` | `test_quarter_alert_count`, `test_quarter_minus_1_alert_count`, `test_quarter_minus_2_alert_count` | Confirms zero alert generation across all 3 trailing quarters ($Q_T = Q_{T-1} = Q_{T-2} = 0$). |
| **KPI 2b** (Alerted Customers) | `KPI_2b` | `q_<test_quarter>` | Confirms zero customer coverage. |
| **KPI 4b** (Tx Volume) | Feeds / Logs | `transaction_count`, `eligible_population_count` | **Critical Discriminator:** If Tx volume $> 0$ but alerts $= 0 \rightarrow$ threshold too high; if Tx volume $= 0 \rightarrow$ data pipeline broken or segment empty. |
| **KPI 18** (Threshold Configuration) | `KPI_18_quarter` / `thresholds` | `min_amount_threshold`, `min_frequency_threshold`, `flags` | Checks whether extreme threshold values prevent alerts from ever firing. |
| **KPI 17** (Typology Overlap) | `KPI_17_quarter` | `general_overlap_ratio` | Evaluates if a newer, broader AD has completely superseded this rule, making it redundant. |

---

## 4. Master Cross-KRI Relevance Matrix

| KPI Indicator | KPI Name | KRI 1 (Volume Shift) | KRI 2 (TP Decay) | KRI 3 (Proximity Accum) | KRI 6 (Dormancy) | Primary Codebase Source |
| :---: | :--- | :---: | :---: | :---: | :---: | :--- |
| **KPI 1** | Alert Count | **Primary** | Secondary | Context | **Primary** | `KPI_1`, `KRI_1`, `KRI_6` |
| **KPI 2b** | Alerted Customers | **Primary** | Secondary | Context | Secondary | `KPI_2b` |
| **KPI 3** | Productive Customers (L3) | Secondary | **Primary** | Context | — | `KPI_3` |
| **KPI 4b** | Transaction Volume | **Primary** | Context | Context | **Primary** | Ingestion feeds / Metadata |
| **KPI 6** | 1st Productive Position | — | Secondary | **Primary** | — | `KPI_6` |
| **KPI 11** | False Positive Ratio | **Primary** | Secondary | Secondary | — | `KPI_11`, `KPI_17_quarter` |
| **KPI 12** | True Positive Ratio | **Primary** | **Primary** | Secondary | — | `KPI_12` |
| **KPI 13** | Effectiveness State | Secondary | **Primary** | Secondary | Secondary | Derived from `KPI_11` / `12` |
| **KPI 14** | Lifecycle Timeliness | Context | Context | — | — | Pipeline metadata |
| **KPI 15a** | Amount Proximity TP % | — | — | **Primary** | — | `KPI_15a`, `KRI_3` |
| **KPI 15b** | Freq Proximity TP % | — | — | **Primary** | — | `KPI_15b`, `KRI_3` |
| **KPI 16** | Productive Alerts Count | Secondary | **Primary** | **Primary** | — | `KPI_16`, `KPI_17_quarter` |
| **KPI 17** | Unique Typology Productivity | Context | **Primary** | — | Secondary | `KPI_17`, `KPI_17_quarter` |
| **KPI 18** | Secondary Parameters / Limits | Context | Context | **Primary** | **Primary** | `KPI_18_quarter` |

---

## 5. End-User Narrative Decision Logic

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                             DIAGNOSTIC ROOT-CAUSE DECISION TREE                                 │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│ KRI 1 Spike:                                                                                     │
│   ├── KPI 2b proportional increase + KPI 4b growth ──> Macro segment growth ──> [NO ACTION]     │
│   ├── KPI 2b flat + KPI 1 spike                   ──> Customer repeat bursts ──> [RE-BAND]      │
│   └── KPI 11 surges (>98%) + KPI 12 collapses     ──> Low-quality noise      ──> [RECALIBRATE]  │
│                                                                                                  │
│ KRI 2 Drop:                                                                                      │
│   ├── KPI 17 high overlap (>80%)                  ──> Captured by sister AD  ──> [NO ACTION]     │
│   └── KPI 3 drop + KPI 6 shift                    ──> Detection decay        ──> [RECALIBRATE]  │
│                                                                                                  │
│ KRI 3 Proximity:                                                                                 │
│   ├── KPI 15a/b high + KPI 6 ≤ 0.10               ──> Boundary clustering    ──> [RECALIBRATE]  │
│   └── Multi-segment concentration                 ──> Variance across tiers  ──> [RE-BAND]      │
│                                                                                                  │
│ KRI 6 Dormancy:                                                                                  │
│   ├── KPI 4b Tx Volume = 0                        ──> Data pipeline issue    ──> [PIPELINE FIX] │
│   └── KPI 4b Tx Volume > 0 + KPI 18 restrictive   ──> Overly strict / dead   ──> [DECOM / TUNE] │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```
