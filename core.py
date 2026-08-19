"""Core pipeline: load Excel data, filter KRIs, enrich with KPIs, build context JSON.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

# ── Quarter resolution ──────────────────────────────────────────────────────

_Q_MONTHS = {1: (1, 2, 3), 2: (4, 5, 6), 3: (7, 8, 9), 4: (10, 11, 12)}


@dataclass(frozen=True)
class QInfo:
    ingestion: str          # "Q1_2026"
    test: str               # ingestion − 2
    base: str               # ingestion − 3
    ing_months: tuple[str, str, str]
    test_months: tuple[str, str, str]


def resolve_quarter(q: str) -> QInfo:
    parts = q.strip().split("_")
    qn, yr = int(parts[0][1:]), int(parts[1])

    def _shift(qn, yr, off):
        t = yr * 4 + (qn - 1) + off
        return (t % 4) + 1, t // 4

    def _months(qn, yr):
        return tuple(f"{yr}-{m:02d}" for m in _Q_MONTHS[qn])

    def _fmt(qn, yr):
        return f"Q{qn}_{yr}"

    tq, ty = _shift(qn, yr, -2)
    bq, by = _shift(qn, yr, -3)
    return QInfo(
        ingestion=_fmt(qn, yr), test=_fmt(tq, ty), base=_fmt(bq, by),
        ing_months=_months(qn, yr), test_months=_months(tq, ty),
    )


# ── Period & Quarter arithmetic helpers ──────────────────────────────────────

_DATE_RE = re.compile(r"^(\d{4})[-_/](\d{2})")
_QCOL_RE = re.compile(r"^Q\d_\d{4}$")
_RENAMES = {
    "active_ingestion_quarter": "ingestion_quarter",
    "active_test_quarter": "test_quarter",
    "active_base_quarter": "base_quarter",
}


def _period_to_qnum(val: Any) -> int | None:
    """Convert quarter or date representations to a sequential integer for chronological comparison.

    Examples:
      'Q1_2025' -> 2025 * 4 + 1 = 8101
      '2025-01-01' -> 2025 * 4 + 1 = 8101
      '2025-07' -> 2025 * 4 + 3 = 8103
    """
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (pd.Timestamp, pd.DatetimeIndex)):
        return val.year * 4 + ((val.month - 1) // 3 + 1)
    s = str(val).strip()
    if not s:
        return None

    # Pattern 1: Q1_2025, Q1-2025, Q1 2025, Q1.2025, Q1/2025
    m = re.match(r"^Q([1-4])[\s_\-/\.]+(\d{4})$", s, re.IGNORECASE)
    if m:
        return int(m.group(2)) * 4 + int(m.group(1))

    # Pattern 2: 2025_Q1, 2025-Q1, 2025Q1
    m = re.match(r"^(\d{4})[\s_\-/\.]*Q([1-4])$", s, re.IGNORECASE)
    if m:
        return int(m.group(1)) * 4 + int(m.group(2))

    # Pattern 3: 2025-01-01, 2025-01, 2025_01, 2025/01
    m = re.match(r"^(\d{4})[-_/](\d{1,2})", s)
    if m:
        yr = int(m.group(1))
        mo = int(m.group(2))
        q = max(1, min(4, (mo - 1) // 3 + 1))
        return yr * 4 + q

    return None


def extract_combo_from_filename(filename: str) -> tuple[str, str] | None:
    """Extract (country, business_line) from filename strictly by prefix.

    Naming convention: <COUNTRY>_<BUSINESS_LINE>_<REST...>
    Examples:
      PL_RB_kri.xlsx   -> ('PL', 'RB')
      ro_wb_kpi.xlsx   -> ('RO', 'WB')
      FR_RB_2026.xlsx  -> ('FR', 'RB')
      CH-WB-data.xlsx  -> ('CH', 'WB')
    """
    if filename.startswith("~$"):
        return None

    stem = Path(filename).stem.strip()

    # 1. Primary: underscore separated "<COUNTRY>_<BUSINESS_LINE>_..."
    parts = stem.split("_")
    if len(parts) >= 2:
        c = parts[0].strip().upper()
        b = parts[1].strip().upper()
        if 2 <= len(c) <= 4 and c.isalpha() and 1 <= len(b) <= 10 and b.isalpha():
            return c, b

    # 2. Fallback: hyphen separated "<COUNTRY>-<BUSINESS_LINE>-..."
    parts_h = stem.split("-")
    if len(parts_h) >= 2:
        c = parts_h[0].strip().upper()
        b = parts_h[1].strip().upper()
        if 2 <= len(c) <= 4 and c.isalpha() and 1 <= len(b) <= 10 and b.isalpha():
            return c, b

    return None


def find_matching_files(input_dir: str | Path, country: str, bl: str) -> list[Path]:
    """Find all excel files matching country & business line in input_dir."""
    root = Path(str(input_dir).strip(' "\''))
    if not root.is_dir():
        raise FileNotFoundError(f"Input directory not found: {root}")

    c_target = country.strip().upper()
    b_target = bl.strip().upper()

    matched: list[Path] = []
    for entry in os.scandir(root):
        if not entry.is_file() or entry.name.startswith("~$"):
            continue
        name_lower = entry.name.lower()
        if not (name_lower.endswith(".xlsx") or name_lower.endswith(".xls") or name_lower.endswith(".xlsm")):
            continue

        combo = extract_combo_from_filename(entry.name)
        if combo and combo[0] == c_target and combo[1] == b_target:
            matched.append(Path(entry.path))
            continue

        # Fallback: check starts with prefix directly
        name_upper = entry.name.upper()
        if (name_upper.startswith(f"{c_target}_{b_target}_") or
            name_upper.startswith(f"{c_target}_{b_target}.") or
            name_upper.startswith(f"{c_target}-{b_target}-")):
            matched.append(Path(entry.path))

    return sorted(matched)


def _norm_col(c):
    if isinstance(c, (pd.Timestamp, pd.DatetimeIndex)):
        return f"m_{c.strftime('%Y_%m')}"
    s = str(c).strip()
    m = _DATE_RE.match(s)
    if m:
        return f"m_{m.group(1)}_{m.group(2)}"
    if _QCOL_RE.match(s):
        return f"q_{s}"
    return _RENAMES.get(s, s)


def _clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize and deduplicate column names, then reset index."""
    if df is None or df.empty:
        return pd.DataFrame()
    df.columns = [_norm_col(c) for c in df.columns]
    # Remove duplicate columns (keeping first occurrence) to prevent DataFrame-valued column slicing
    df = df.loc[:, ~df.columns.duplicated(keep="first")]
    # Ensure fresh 0..N-1 RangeIndex to prevent axis reindexing errors
    return df.reset_index(drop=True)


def load_tables(
    input_dir: str,
    country: str,
    bl: str,
    selected_files: list[str] | None = None
) -> dict[str, pd.DataFrame]:
    """Load all sheets from matching or explicitly selected Excel files."""
    root = Path(str(input_dir).strip(' "\''))
    if selected_files:
        files = [root / f if not Path(f).is_absolute() else Path(f) for f in selected_files]
        files = [f for f in files if f.is_file()]
    else:
        files = find_matching_files(root, country, bl)

    if not files:
        raise FileNotFoundError(f"No valid files found for {country.upper()}/{bl.upper()} in {input_dir}")

    print(f"\n[Load] {len(files)} file(s) for {country}/{bl}:")
    tables: dict[str, pd.DataFrame] = {}
    for f in files:
        xls = pd.ExcelFile(f, engine="openpyxl")
        print(f"  → {f.name}  ({', '.join(xls.sheet_names)})")
        for s in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=s)
            cleaned_df = _clean_dataframe(raw_df)
            if s in tables:
                # Merge across files without index clashes
                merged = pd.concat([tables[s], cleaned_df], ignore_index=True)
                tables[s] = _clean_dataframe(merged)
            else:
                tables[s] = cleaned_df
    print(f"[Load] {len(tables)} table(s) total.\n")
    return tables


# ── Helpers ─────────────────────────────────────────────────────────────────

def _s(val):
    """Safe scalar: Series/array unwrapping, numpy → Python native, NaN → None."""
    if val is None:
        return None
    if isinstance(val, (pd.Series, pd.DataFrame)):
        val = val.iloc[0] if len(val) > 0 else None
        if val is None:
            return None
    if pd.isna(val):
        return None
    return val.item() if hasattr(val, "item") else val


def _trend(row, months):
    return {f"month_{i}": _s(row[f"m_{m.replace('-','_')}"])
            for i, m in enumerate(months, 1)
            if f"m_{m.replace('-','_')}" in row.index and _s(row.get(f"m_{m.replace('-','_')}")) is not None}


def _identity(row):
    keys = ["alert_definition", "country", "business_line",
            "segment_desc", "customer_type_code", "customer_risk"]
    return {k: str(row[k]) for k in keys if k in row.index and pd.notna(row.get(k))}


_FLAG_MAP = {
    "many_alert_flag": "many_alerts_flag",
    "lowest_am_th_flag": "lowest_amount_threshold_flag",
    "lowest_freq_th_flag": "lowest_frequency_threshold_flag",
    "lowest_both_th_flag": "lowest_both_thresholds_flag",
    "ths_changed_ad_flag": "thresholds_changed_flag",
    "ths_not_changed_ad_flag": "thresholds_unchanged_flag",
    "deactivated_ad_flag": "deactivated_flag",
    "newly_active_ingestion_quarter_ad_flag": "newly_active_flag",
}


def _flags(row):
    return {v: int(_s(row[k])) for k, v in _FLAG_MAP.items()
            if k in row.index and _s(row.get(k)) is not None}


def _thresholds(row):
    out = {}
    for c in ("current_min_amount_threshold", "current_min_freq_threshold"):
        v = _s(row.get(c))
        if v is not None:
            out[c.replace("current_", "")] = v
    return out


def _strip(d): return {k: v for k, v in d.items() if v is not None}


# ── KRI extraction ──────────────────────────────────────────────────────────

def _kri1(row, qi):
    results = []
    t_q = _s(row.get("test_quarter")) or qi.test
    b_q = _s(row.get("base_quarter")) or qi.base
    for sfx, label in [("incrs", "increase"), ("dcrs", "decrease")]:
        if _s(row.get(f"KRI_1_{sfx}")) != 1: continue
        results.append(_strip({
            "kri": "KRI_1",
            "direction": label,
            "test_quarter": t_q,
            "base_quarter": b_q,
            "test_quarter_count": _s(row.get("test_quarter_count")),
            "base_quarter_count": _s(row.get("base_quarter_count")),
            "difference": _s(row.get("test_base_quarter_diff")),
            "full_period_avg_count": _s(row.get("full_period_avg(count)")),
            "full_period_stddev_count": _s(row.get("full_period_stddev_pop(count)")),
            "three_sigma_exceeded": _s(row.get(f"KRI_1_{sfx}_three_sigma_exceeded")),
            "consecutive_trigger": _s(row.get(f"KRI_1_{sfx}_with_consecutive")),
            "monthly_trend": _trend(row, qi.test_months),
        }))
    if not results and _s(row.get("KRI_1")) == 1:
        results.append(_strip({
            "kri": "KRI_1",
            "test_quarter": t_q,
            "base_quarter": b_q,
            "test_quarter_count": _s(row.get("test_quarter_count")),
            "base_quarter_count": _s(row.get("base_quarter_count")),
            "difference": _s(row.get("test_base_quarter_diff")),
            "monthly_trend": _trend(row, qi.test_months)
        }))
    return results


def _kri2(row, qi):
    t_q = _s(row.get("test_quarter")) or qi.test
    b_q = _s(row.get("base_quarter")) or qi.base
    return [_strip({
        "kri": "KRI_2",
        "test_quarter": t_q,
        "base_quarter": b_q,
        "test_quarter_count": _s(row.get("test_quarter_count")),
        "base_quarter_count": _s(row.get("base_quarter_count")),
        "difference": _s(row.get("test_base_quarter_diff")),
        "alert_count": _s(row.get("alert_count")),
        "full_period_avg_productive_alerts": _s(row.get("full_period_avg(productive_alerts_count)")),
        "full_period_stddev_productive_alerts": _s(row.get("full_period_stddev_pop(productive_alerts_count)")),
        "three_sigma_exceeded": _s(row.get("KRI_2_dcrs_three_sigma_exceeded")),
        "consecutive_trigger": _s(row.get("KRI_2_dcrs_with_consecutive")),
        "monthly_trend": _trend(row, qi.test_months),
    })]


def _kri3(row, qi):
    results = []
    t_q = _s(row.get("test_quarter")) or qi.test
    b_q = _s(row.get("base_quarter")) or qi.base
    for label, col in [("amount", "KRI_3_amount"), ("freq", "KRI_3_freq"),
                        ("perc_avg", "KRI_3_perc_avg_without_consecutive")]:
        if _s(row.get(col)) != 1: continue
        results.append(_strip({
            "kri": "KRI_3",
            "sub_trigger": label,
            "test_quarter": t_q,
            "base_quarter": b_q,
            "test_quarter_accum_ratio_amount": _s(row.get("test_quarter_accum_ratio_amount")),
            "base_quarter_accum_ratio_amount": _s(row.get("base_quarter_accum_ratio_amount")),
            "amount_deviation": _s(row.get("kri3_amount_deviation")),
            "frequency_deviation": _s(row.get("kri3_freq_deviation")),
            "alert_count": _s(row.get("alert_count")),
            "false_positive_rate": _s(row.get("false_positive_rate")),
            "true_positive_rate": _s(row.get("true_positive_rate")),
        }))
    if not results and _s(row.get("KRI_3")) == 1:
        results.append(_strip({
            "kri": "KRI_3",
            "test_quarter": t_q,
            "base_quarter": b_q,
            "alert_count": _s(row.get("alert_count")),
            "false_positive_rate": _s(row.get("false_positive_rate")),
            "true_positive_rate": _s(row.get("true_positive_rate"))
        }))
    return results


def _kri6(row, qi):
    t_q = _s(row.get("test_quarter")) or qi.test
    return [_strip({
        "kri": "KRI_6",
        "test_quarter": t_q,
        "test_quarter_alerts": _s(row.get("test_quarter_alert_count")),
        "test_quarter_minus_1_alerts": _s(row.get("test_quarter_minus_1_alert_count")),
        "test_quarter_minus_2_alerts": _s(row.get("test_quarter_minus_2_alert_count")),
        "total_monitoring_alerts": _s(row.get("total_count")),
        "oldest_benchmark_period": _s(row.get("oldest_benchmark_period")),
    })]


_KRIS = {"KRI_1": _kri1, "KRI_2": _kri2, "KRI_3": _kri3, "KRI_6": _kri6}


def filter_kris(tables, qi):
    """Returns {alert_def: [evidence_dicts]} for all triggered KRIs."""
    results = {}
    for sheet, extractor in _KRIS.items():
        if sheet not in tables: continue
        df = tables[sheet]
        if sheet not in df.columns: continue
        df = df.reset_index(drop=True)
        if "ingestion_quarter" in df.columns:
            df = df[df["ingestion_quarter"] == qi.ingestion].reset_index(drop=True)
        triggered = df[df[sheet] == 1].reset_index(drop=True)
        print(f"  [KRI] {sheet}: {len(triggered)} triggered ({len(df)} in quarter)")

        for _, row in triggered.iterrows():
            # Benchmark period filtering:
            # Benchmark quarter must always be before test_quarter and before base_quarter.
            bench_val = None
            for bcol in ("benchmark_quarter", "benchmark_period", "oldest_benchmark_period", "benchmark"):
                if bcol in row.index and _s(row.get(bcol)) is not None:
                    bench_val = _s(row.get(bcol))
                    break

            base_val = _s(row.get("base_quarter"))
            test_val = _s(row.get("test_quarter"))

            if bench_val and base_val:
                b_bench = _period_to_qnum(bench_val)
                b_base = _period_to_qnum(base_val)
                if b_bench is not None and b_base is not None and b_bench > b_base:
                    continue  # Filter out: base_quarter is older than benchmark boundary

            if bench_val and test_val:
                b_bench = _period_to_qnum(bench_val)
                b_test = _period_to_qnum(test_val)
                if b_bench is not None and b_test is not None and b_bench > b_test:
                    continue  # Filter out: test_quarter is older than benchmark boundary

            ad = str(row.get("alert_definition", "?"))
            meta = _strip({
                "identity": _identity(row),
                "thresholds": _thresholds(row),
                "flags": _flags(row),
                "recommendation": _s(row.get("recommendation")),
                "final_recommendation": _s(row.get("final_recommendation")),
            })
            for ev in extractor(row, qi):
                ev["_meta"] = meta
                results.setdefault(ad, []).append(ev)
    return results


# ── KPI enrichment ──────────────────────────────────────────────────────────

_SIMPLE_KPIS = {
    "KPI_1": "kpi1_alert_count",
    "KPI_2b": "kpi2b_productive_alert_rate",
    "KPI_3": "kpi3_customer_count",
    "KPI_6": "kpi6_value",
    "KPI_11": "kpi11_value",
    "KPI_12": "kpi12_value",
    "KPI_15a": "kpi15a_value",
    "KPI_15b": "kpi15b_value",
    "KPI_16": "kpi16_unique_customers",
    "KPI_17": "kpi17_value",
}

_STRUCT_KPIS = {
    "KPI_17_quarter": {
        "filter": "test_quarter", "key": "kpi17_quarterly_metrics",
        "cols": {
            "alert_count": "alert_count",
            "tp_count": "true_positive_count",
            "false_positive_rate": "false_positive_rate",
            "general_overlap_ratio": "general_overlap_ratio",
            "prod_general_overlap_ratio": "productive_overlap_ratio",
        },
    },
    "KPI_18_quarter": {
        "filter": "test_quarter", "key": "kpi18_quarterly_thresholds",
        "cols": {
            "alert_count": "alert_count",
            "tp_count": "true_positive_count",
            "min_amount_threshold": "min_amount_threshold",
            "max_amount_threshold": "max_amount_threshold",
            "min_frequency_threshold": "min_frequency_threshold",
        },
    },
}


def _q_col(df, qi):
    for q in (qi.ingestion, qi.test):
        c = f"q_{q}"
        if c in df.columns: return c
    return None


def enrich_kpis(tables, triggered_ads, qi):
    data, avail = {}, {}
    if not triggered_ads:
        return data, avail

    for sheet, out_key in _SIMPLE_KPIS.items():
        if sheet not in tables: continue
        df = tables[sheet].reset_index(drop=True)
        if "ingestion_quarter" in df.columns:
            df = df[df["ingestion_quarter"] == qi.ingestion].reset_index(drop=True)
        if "alert_definition" in df.columns:
            df = df[df["alert_definition"].isin(triggered_ads)].reset_index(drop=True)
        qc = _q_col(df, qi)
        if not qc or df.empty: continue

        n = 0
        for _, row in df.iterrows():
            ad = str(row.get("alert_definition", ""))
            val = _s(row.get(qc))
            if val is not None:
                data.setdefault(ad, {})[out_key] = val
                avail.setdefault(ad, []).append(sheet)
                n += 1
        print(f"  [KPI] {sheet}: {n} enriched")

    for sheet, cfg in _STRUCT_KPIS.items():
        if sheet not in tables: continue
        df = tables[sheet].reset_index(drop=True)
        filt_col = cfg["filter"]
        filt_val = qi.test if filt_col == "test_quarter" else qi.ingestion
        if filt_col in df.columns:
            df = df[df[filt_col] == filt_val].reset_index(drop=True)
        if "alert_definition" in df.columns:
            df = df[df["alert_definition"].isin(triggered_ads)].reset_index(drop=True)
        if df.empty: continue

        n = 0
        for _, row in df.iterrows():
            ad = str(row.get("alert_definition", ""))
            ev = {short: _s(row.get(src)) for src, short in cfg["cols"].items()
                  if _s(row.get(src)) is not None}
            if ev:
                data.setdefault(ad, {})[cfg["key"]] = ev
                avail.setdefault(ad, []).append(sheet)
                n += 1
        print(f"  [KPI] {sheet}: {n} enriched")

    return data, avail


# ── Context assembly ────────────────────────────────────────────────────────

def build_output(kri_results, kpi_data, kpi_avail, qi, output_dir, country, bl):
    out = Path(str(output_dir).strip(' "\''))
    out.mkdir(parents=True, exist_ok=True)
    prefix = f"{country.upper()}_{bl.upper()}_{qi.ingestion}"

    context, matrix = [], []
    for ad, evidences in sorted(kri_results.items()):
        meta = {}
        for ev in evidences:
            for k, v in ev.pop("_meta", {}).items():
                if k not in meta and v: meta[k] = v

        block = {"alert_definition": ad}
        for k in ("identity", "thresholds", "flags"):
            if meta.get(k): block[k] = meta[k]

        # Extract unique evaluated base and test quarters across evidences
        evaluated_base_quarters = sorted({ev["base_quarter"] for ev in evidences if "base_quarter" in ev})
        evaluated_test_quarters = sorted({ev["test_quarter"] for ev in evidences if "test_quarter" in ev})

        quarters_summary = {
            "ingestion": qi.ingestion,
            "test": evaluated_test_quarters[0] if len(evaluated_test_quarters) == 1 else (evaluated_test_quarters or qi.test),
        }
        if len(evaluated_base_quarters) == 1:
            quarters_summary["base"] = evaluated_base_quarters[0]
        elif evaluated_base_quarters:
            quarters_summary["base_quarters"] = evaluated_base_quarters

        block["quarters"] = quarters_summary
        block["triggered_kris"] = evidences
        rec = meta.get("final_recommendation") or meta.get("recommendation")
        if rec: block["recommendation"] = rec
        if ad in kpi_data: block["kpi_context"] = kpi_data[ad]
        context.append(block)

        kris = sorted({ev.get("kri", "") for ev in evidences})
        subs = {}
        for ev in evidences:
            k = ev.get("kri", "")
            s = ev.get("sub_trigger") or ev.get("direction")
            if s: subs.setdefault(k, []).append(s)
        entry = {"alert_definition": ad, "triggered_kris": kris}
        if any(subs.values()): entry["kri_sub_triggers"] = subs
        if evaluated_base_quarters:
            entry["evaluated_base_quarters"] = evaluated_base_quarters
        entry["available_kpis"] = kpi_avail.get(ad, [])
        matrix.append(entry)

    for name, data in [("quantitative_context", context), ("relevance_matrix", matrix)]:
        p = out / f"{prefix}_{name}.json"
        p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        print(f"  → {p}")
    print(f"[Output] {len(context)} alert definition(s)")
