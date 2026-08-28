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

# ── Quarter resolution & standardization ────────────────────────────────────

_Q_MONTHS = {1: (1, 2, 3), 2: (4, 5, 6), 3: (7, 8, 9), 4: (10, 11, 12)}


@dataclass(frozen=True)
class QInfo:
    ingestion: str          # "Q1_2026"
    test: str               # ingestion − 2
    base: str               # ingestion − 3
    ing_months: tuple[str, str, str]
    test_months: tuple[str, str, str]


def format_quarter(val: Any) -> str | None:
    """Standardize any quarter or date representation into 'Q<N>_<YYYY>'.

    Examples:
      'Q1_2025', 'q1-2025', '2025Q1', '2025-01-01', pd.Timestamp('2025-02-15') -> 'Q1_2025'
      '2025-07-01', '2025-07' -> 'Q3_2025'
      '20251' -> 'Q1_2025'
    """
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (pd.Timestamp, pd.DatetimeIndex)):
        q = (val.month - 1) // 3 + 1
        return f"Q{q}_{val.year}"
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "null", "nat"):
        return None

    # Pattern 1: Q1_2025, Q1-2025, Q1 2025, Q1.2025, Q1/2025
    m = re.match(r"^Q([1-4])[\s_\-/\.]*(\d{4})$", s, re.IGNORECASE)
    if m:
        return f"Q{m.group(1)}_{m.group(2)}"

    # Pattern 2: 2025_Q1, 2025-Q1, 2025Q1, 2025/Q1
    m = re.match(r"^(\d{4})[\s_\-/\.]*Q([1-4])$", s, re.IGNORECASE)
    if m:
        return f"Q{m.group(2)}_{m.group(1)}"

    # Pattern 3: 5-digit integer string like 20251 (YYYYQ)
    if s.isdigit() and len(s) == 5:
        return f"Q{s[4]}_{s[:4]}"

    # Fallback: robust pd.to_datetime parsing for all standard ISO, EU, US date formats
    if re.match(r"^\d{4}[-_/]\d{1,2}(?:[-_/]\d{1,2})?$", s) or re.match(r"^\d{1,2}[-_/]\d{1,2}[-_/]\d{4}$", s):
        try:
            ts = pd.to_datetime(s, errors="coerce")
            if pd.notna(ts):
                q = (ts.month - 1) // 3 + 1
                return f"Q{q}_{ts.year}"
        except Exception:
            pass

    return None



def resolve_quarter(q: str) -> QInfo:
    std = format_quarter(q) or str(q).strip()
    parts = std.split("_")
    if len(parts) >= 2 and parts[0].upper().startswith("Q") and parts[0][1:].isdigit() and parts[1].isdigit():
        qn, yr = int(parts[0][1:]), int(parts[1])
    else:
        qn, yr = 1, 2026

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
_QCOL_RE = re.compile(r"^Q\d_\d{4}$", re.IGNORECASE)
_RENAMES = {
    "active_ingestion_quarter": "ingestion_quarter",
    "active_test_quarter": "test_quarter",
    "active_base_quarter": "base_quarter",
    "active_benchmark_quarter": "benchmark_quarter",
    "active_benchmark_period": "benchmark_quarter",
    "benchmark_period": "benchmark_quarter",
    "benchmark_date": "benchmark_quarter",
    "alert_definition_id": "alert_definition",
    "alert_definition_name": "alert_definition",
    "alert_def": "alert_definition",
    "alert_definition_code": "alert_definition",
    "ad_id": "alert_definition",
    "ad_name": "alert_definition",
    "ad": "alert_definition",
}



def _period_to_qnum(val: Any) -> int | None:
    """Convert standardized quarter 'Q<N>_<YYYY>' to chronological integer YYYY * 4 + N."""
    fmt = format_quarter(val)
    if not fmt:
        return None
    m = re.match(r"^Q([1-4])_(\d{4})$", fmt, re.IGNORECASE)
    if m:
        return int(m.group(2)) * 4 + int(m.group(1))
    return None


_BL_SYNONYMS = {
    "RB": "RB",
    "RETAIL": "RB",
    "RETAIL_BANK": "RB",
    "RETAIL_BANKING": "RB",
    "RETAILBANK": "RB",
    "RETAILBANKING": "RB",
    "WB": "WB",
    "WHOLESALE": "WB",
    "WHOLESALE_BANK": "WB",
    "WHOLESALE_BANKING": "WB",
    "WHOLESALEBANK": "WB",
    "WHOLESALEBANKING": "WB",
}

# Regex searching for <COUNTRY>_<BUSINESS_LINE> anywhere in filename (underscore separated)
_COMBO_RE = re.compile(
    r"(?:^|_)([A-Za-z]{2,4})_(RB|WB|RETAIL(?:_BANK(?:ING)?)?|RETAILBANK(?:ING)?|WHOLESALE(?:_BANK(?:ING)?)?|WHOLESALEBANK(?:ING)?)(?:_|\.|$)",
    re.IGNORECASE
)


def normalize_business_line(bl_str: str) -> str:
    """Map any business line variation (e.g. 'retail_banking', 'WB', 'wholesale') to canonical 'RB' or 'WB'."""
    s = str(bl_str).strip().upper()
    return _BL_SYNONYMS.get(s, s)


def extract_combo_from_filename(filename: str) -> tuple[str, str] | None:
    """Extract (country, business_line) from anywhere within short or long filenames.

    Spaces and hyphens in the filename are normalized to underscores prior to matching.

    Examples:
      export_2026_Q1_consolidated_RO_Retail_Bank_monitoring_kpi_v2.xlsx -> ('RO', 'RB')
      ro_retail.xlsx                                                    -> ('RO', 'RB')
      alert_data_RO_wholesale_bank_2026_Q1.xlsx                         -> ('RO', 'WB')
      PL Retail Banking Data Final.xlsx                                 -> ('PL', 'RB')
      2026_Q1_pl_rb.xlsx                                                -> ('PL', 'RB')
      FR-retail-2026.xlsx                                               -> ('FR', 'RB')
    """
    if filename.startswith("~$"):
        return None

    # Normalize spaces and hyphens to underscores for clean substring matching
    stem = re.sub(r"[\s\-]+", "_", Path(filename).stem.strip())
    m = _COMBO_RE.search(stem)
    if m:
        country = m.group(1).upper()
        raw_bl = m.group(2).upper()
        canon_bl = normalize_business_line(raw_bl)
        return country, canon_bl

    return None


def find_matching_files(input_dir: str | Path, country: str, bl: str) -> list[Path]:
    """Find all excel files matching country & business line anywhere in filename."""
    root = Path(str(input_dir).strip(' "\''))
    if not root.is_dir():
        raise FileNotFoundError(f"Input directory not found: {root}")

    c_target = country.strip().upper()
    b_target = normalize_business_line(bl)

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

    return sorted(matched)


def _norm_col(c):
    if isinstance(c, (pd.Timestamp, pd.DatetimeIndex)):
        return f"m_{c.strftime('%Y_%m')}"
    s = str(c).strip()
    m = _DATE_RE.match(s)
    if m:
        return f"m_{m.group(1)}_{m.group(2)}"
    fmt_q = format_quarter(s)
    if fmt_q:
        return f"q_{fmt_q}"
    cleaned = s.lower().replace(" ", "_").replace("-", "_")
    return _RENAMES.get(cleaned, _RENAMES.get(s.lower(), _RENAMES.get(s, s)))



def _clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize and deduplicate column names, standardize quarter columns, and reset index."""
    if df is None or df.empty:
        return pd.DataFrame()
    df.columns = [_norm_col(c) for c in df.columns]
    # Remove duplicate columns (keeping first occurrence) to prevent DataFrame-valued column slicing
    df = df.loc[:, ~df.columns.duplicated(keep="first")]

    # Standardize all quarter/period values to 'Q<N>_<YYYY>'
    for c in df.columns:
        c_lower = str(c).lower()
        if "quarter" in c_lower or "benchmark_period" in c_lower:
            df[c] = df[c].apply(format_quarter)

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
        print(f"  -> {f.name}  ({', '.join(xls.sheet_names)})")
        for s in xls.sheet_names:
            raw_df = pd.read_excel(xls, sheet_name=s)
            cleaned_df = _clean_dataframe(raw_df)
            if not cleaned_df.empty:
                cleaned_df["_source_file"] = f.name
                cleaned_df["_source_sheet"] = s
                cleaned_df["_source_ref"] = f"{f.name}/{s}"
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
    """Safe scalar: Series/array unwrapping, numpy -> Python native, NaN -> None."""
    if val is None:
        return None
    if isinstance(val, (pd.Series, pd.DataFrame)):
        if len(val) == 0:
            return None
        try:
            val = val.iloc[0]
        except Exception:
            return None
        if val is None:
            return None
    try:
        if pd.isna(val):
            return None
    except Exception:
        pass
    if hasattr(val, "item") and not isinstance(val, (str, bytes)):
        try:
            return val.item()
        except Exception:
            return val
    return val


def _is_one(val: Any) -> bool:
    """Robust check for boolean / binary trigger flags (1, 1.0, True, '1')."""
    if val is None:
        return False
    if isinstance(val, (pd.Series, pd.DataFrame)):
        if len(val) == 0:
            return False
        try:
            val = val.iloc[0]
        except Exception:
            return False
        if val is None:
            return False
    try:
        if pd.isna(val):
            return False
    except Exception:
        pass
    if hasattr(val, "item") and not isinstance(val, (str, bytes)):
        try:
            val = val.item()
        except Exception:
            pass
    return str(val).strip() in ("1", "1.0", "True", "true") or val == 1



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
    t_q = format_quarter(_s(row.get("test_quarter"))) or qi.test
    b_q = format_quarter(_s(row.get("base_quarter"))) or qi.base
    bench_q = format_quarter(_s(row.get("benchmark_quarter")))
    s_ref = str(row.get("_source_ref") or "KRI_1")
    for sfx, label in [("incrs", "increase"), ("dcrs", "decrease")]:
        col = f"KRI_1_{sfx}"
        if col in row.index and _is_one(row.get(col)):
            results.append(_strip({
                "kri": "KRI_1",
                "direction": label,
                "test_quarter": t_q,
                "base_quarter": b_q,
                "benchmark_quarter": bench_q,
                "test_quarter_count": _s(row.get("test_quarter_count")),
                "base_quarter_count": _s(row.get("base_quarter_count")),
                "difference": _s(row.get("test_base_quarter_diff")),
                "full_period_avg_count": _s(row.get("full_period_avg(count)")),
                "full_period_stddev_count": _s(row.get("full_period_stddev_pop(count)")),
                "three_sigma_exceeded": _s(row.get(f"KRI_1_{sfx}_three_sigma_exceeded")),
                "consecutive_trigger": _s(row.get(f"KRI_1_{sfx}_with_consecutive")),
                "monthly_trend": _trend(row, qi.test_months),
                "source": s_ref,
            }))
    if not results and _is_one(row.get("KRI_1")):
        results.append(_strip({
            "kri": "KRI_1",
            "test_quarter": t_q,
            "base_quarter": b_q,
            "benchmark_quarter": bench_q,
            "test_quarter_count": _s(row.get("test_quarter_count")),
            "base_quarter_count": _s(row.get("base_quarter_count")),
            "difference": _s(row.get("test_base_quarter_diff")),
            "monthly_trend": _trend(row, qi.test_months),
            "source": s_ref,
        }))
    return results


def _kri2(row, qi):
    t_q = format_quarter(_s(row.get("test_quarter"))) or qi.test
    b_q = format_quarter(_s(row.get("base_quarter"))) or qi.base
    bench_q = format_quarter(_s(row.get("benchmark_quarter")))
    s_ref = str(row.get("_source_ref") or "KRI_2")
    return [_strip({
        "kri": "KRI_2",
        "test_quarter": t_q,
        "base_quarter": b_q,
        "benchmark_quarter": bench_q,
        "test_quarter_count": _s(row.get("test_quarter_count")),
        "base_quarter_count": _s(row.get("base_quarter_count")),
        "difference": _s(row.get("test_base_quarter_diff")),
        "alert_count": _s(row.get("alert_count")),
        "full_period_avg_productive_alerts": _s(row.get("full_period_avg(productive_alerts_count)")),
        "full_period_stddev_productive_alerts": _s(row.get("full_period_stddev_pop(productive_alerts_count)")),
        "three_sigma_exceeded": _s(row.get("KRI_2_dcrs_three_sigma_exceeded")),
        "consecutive_trigger": _s(row.get("KRI_2_dcrs_with_consecutive")),
        "monthly_trend": _trend(row, qi.test_months),
        "source": s_ref,
    })]


def _kri3(row, qi):
    results = []
    t_q = format_quarter(_s(row.get("test_quarter"))) or qi.test
    b_q = format_quarter(_s(row.get("base_quarter"))) or qi.base
    bench_q = format_quarter(_s(row.get("benchmark_quarter")))
    s_ref = str(row.get("_source_ref") or "KRI_3")
    for label, col in [("amount", "KRI_3_amount"), ("freq", "KRI_3_freq"),
                        ("perc_avg", "KRI_3_perc_avg_without_consecutive")]:
        if col in row.index and _is_one(row.get(col)):
            results.append(_strip({
                "kri": "KRI_3",
                "sub_trigger": label,
                "test_quarter": t_q,
                "base_quarter": b_q,
                "benchmark_quarter": bench_q,
                "test_quarter_accum_ratio_amount": _s(row.get("test_quarter_accum_ratio_amount")),
                "base_quarter_accum_ratio_amount": _s(row.get("base_quarter_accum_ratio_amount")),
                "amount_deviation": _s(row.get("kri3_amount_deviation")),
                "frequency_deviation": _s(row.get("kri3_freq_deviation")),
                "alert_count": _s(row.get("alert_count")),
                "false_positive_rate": _s(row.get("false_positive_rate")),
                "true_positive_rate": _s(row.get("true_positive_rate")),
                "source": s_ref,
            }))
    if not results and _is_one(row.get("KRI_3")):
        results.append(_strip({
            "kri": "KRI_3",
            "test_quarter": t_q,
            "base_quarter": b_q,
            "benchmark_quarter": bench_q,
            "alert_count": _s(row.get("alert_count")),
            "false_positive_rate": _s(row.get("false_positive_rate")),
            "true_positive_rate": _s(row.get("true_positive_rate")),
            "source": s_ref,
        }))
    return results


def _kri6(row, qi):
    t_q = format_quarter(_s(row.get("test_quarter"))) or qi.test
    s_ref = str(row.get("_source_ref") or "KRI_6")
    return [_strip({
        "kri": "KRI_6",
        "test_quarter": t_q,
        "test_quarter_alerts": _s(row.get("test_quarter_alert_count")),
        "test_quarter_minus_1_alerts": _s(row.get("test_quarter_minus_1_alert_count")),
        "test_quarter_minus_2_alerts": _s(row.get("test_quarter_minus_2_alert_count")),
        "total_monitoring_alerts": _s(row.get("total_count")),
        "oldest_benchmark_period": format_quarter(_s(row.get("oldest_benchmark_period"))) or _s(row.get("oldest_benchmark_period")),
        "source": s_ref,
    })]


_KRIS = {"KRI_1": _kri1, "KRI_2": _kri2, "KRI_3": _kri3, "KRI_6": _kri6}


def filter_kris(tables, qi):
    """Returns {alert_def: [evidence_dicts]} for all triggered KRIs."""
    results = {}
    for sheet_key, extractor in _KRIS.items():
        matched_sheet = _find_sheet(tables, sheet_key)
        if not matched_sheet:
            continue
        df = tables[matched_sheet]

        # Locate trigger flag column
        trig_col = None
        for c in (sheet_key, sheet_key.lower(), sheet_key.upper(), f"q_{sheet_key}", f"kri_{sheet_key[-1]}"):
            if c in df.columns:
                trig_col = c
                break
        if not trig_col:
            continue

        df = df.reset_index(drop=True)

        # Filter 1: Ingestion quarter match (Strictly disregard all rows where ingestion_quarter != user input)
        ing_col = None
        for c in ("ingestion_quarter", "active_ingestion_quarter"):
            if c in df.columns:
                ing_col = c
                break
        if ing_col:
            target_ing = format_quarter(qi.ingestion) or str(qi.ingestion).strip()
            df = df[df[ing_col].apply(format_quarter) == target_ing].reset_index(drop=True)

        # Triggered flag match (KRI_1 == 1, KRI_2 == 1, etc.)
        triggered_mask = df[trig_col].apply(_is_one)
        triggered = df[triggered_mask].reset_index(drop=True)
        print(f"  [KRI] {matched_sheet}: {len(triggered)} triggered ({len(df)} in ingestion quarter {qi.ingestion})")

        # Locate alert definition column
        ad_col = None
        for c in ("alert_definition", "alert_definition_id", "alert_def", "alert_definition_code", "ad_id", "ad_name", "ad", "scenario_id"):
            if c in triggered.columns:
                ad_col = c
                break
        if not ad_col:
            if len(triggered.columns) > 0:
                ad_col = triggered.columns[0]
            else:
                continue


        for _, row in triggered.iterrows():
            # Filter 2 (for KRI_1, KRI_2, KRI_3 only): base_quarter must be strictly higher than benchmark_quarter
            if sheet_key in ("KRI_1", "KRI_2", "KRI_3"):
                bench_val = None
                for bcol in ("benchmark_quarter", "benchmark_period", "active_benchmark_quarter", "benchmark"):
                    if bcol in row.index and pd.notna(row.get(bcol)):
                        bench_val = row.get(bcol)
                        break

                base_val = row.get("base_quarter")
                if bench_val is not None and base_val is not None:
                    b_bench = _period_to_qnum(bench_val)
                    b_base = _period_to_qnum(base_val)
                    if b_bench is not None and b_base is not None:
                        # ONLY select if base_quarter is strictly higher than benchmark_quarter
                        if not (b_base > b_bench):
                            continue

            ad = str(row.get(ad_col, "?")).strip()
            s_ref = str(row.get("_source_ref") or f"{matched_sheet}")
            meta = _strip({
                "identity": _identity(row),
                "thresholds": _thresholds(row),
                "flags": _flags(row),
                "recommendation": _s(row.get("recommendation")),
                "final_recommendation": _s(row.get("final_recommendation")),
                "_source": s_ref,
            })
            for ev in extractor(row, qi):
                ev["_meta"] = meta
                results.setdefault(ad, []).append(ev)
    return results



# ── KPI enrichment ──────────────────────────────────────────────────────────

# Dynamic Time-Series KPIs (Contain dynamic Q{N}_{YYYY} and YYYY-MM-01 columns)
_SIMPLE_KPIS = {
    "KPI_1": "kpi1_alert_count",
    "KPI_2b": "kpi2b_alerted_customers",
    "KPI_3": "kpi3_customer_count",
    "KPI_6": "kpi6_value",
    "KPI_11": "kpi11_value",
    "KPI_12": "kpi12_value",
    "KPI_15a": "kpi15a_value",
    "KPI_15b": "kpi15b_value",
    "KPI_16": "kpi16_unique_customers",
}

# Static / Relational / Overlap & Threshold KPIs (Do NOT contain quarterly time series columns)
_STRUCT_KPIS = {
    "KPI_17": {
        "aliases": ["KPI_17", "KPI_17_quarter", "overlap"],
        "filter": "test_quarter", "key": "kpi17_quarterly_metrics",
        "cols": {
            "alert_count": "alert_count",
            "tp_count": "true_positive_count",
            "false_positive_rate": "false_positive_rate",
            "general_overlap_ratio": "general_overlap_ratio",
            "prod_general_overlap_ratio": "productive_overlap_ratio",
            "typology_top_overlapping_ad_general_alerts": "top_overlapping_ad",
            "typology_top_overlapping_ad_prod_alerts": "top_overlapping_ad_prod",
        },
    },
    "KPI_18": {
        "aliases": ["KPI_18", "KPI_18_quarter", "thresholds"],
        "filter": "test_quarter", "key": "kpi18_quarterly_thresholds",
        "cols": {
            "alert_count": "alert_count",
            "tp_count": "true_positive_count",
            "min_amount_threshold": "min_amount_threshold",
            "max_amount_threshold": "max_amount_threshold",
            "min_frequency_threshold": "min_frequency_threshold",
            "min_percentage_threshold": "min_percentage_threshold",
            "abs_distance_first_tp_and_min_amount_threshold": "distance_amount_first_tp",
            "abs_distance_first_tp_and_min_frequency_threshold": "distance_frequency_first_tp",
        },
    },
}



def _find_sheet(tables: dict[str, pd.DataFrame], target: str) -> str | None:
    """Find matching sheet name in tables handling casing and whitespace/underscore variations."""
    if target in tables:
        return target
    target_clean = re.sub(r"[\s_-]+", "", target).upper()
    for s in tables:
        if re.sub(r"[\s_-]+", "", str(s)).upper() == target_clean:
            return s
    return None


def _find_q_col(df: pd.DataFrame, q_str: str | None) -> str | None:
    """Resolve dynamic quarter column name matching standard 'Q{N}_{YYYY}' (e.g. 'Q3_2025', 'Q1_2026')."""
    if not q_str:
        return None
    q_std = format_quarter(q_str) or str(q_str).strip()
    candidates = [
        f"q_{q_std}",
        q_std,
        f"q_{q_std.lower()}",
        q_std.lower(),
        f"Q_{q_std}",
        q_std.replace("_", " "),
        q_std.replace("_", ""),
    ]
    for cand in candidates:
        if cand in df.columns:
            return cand
    for col in df.columns:
        c_str = str(col).strip()
        if c_str.upper() in (cand.upper() for cand in candidates):
            return col
        col_q = format_quarter(col)
        if col_q and col_q == q_std:
            return col
    return None


def _kpi_trend(row: pd.Series, months: tuple[str, ...]) -> dict[str, Any]:
    """Extract monthly trend values from row given list of months (e.g. ('2025-07', '2025-08', '2025-09'))."""
    trend = {}
    for i, m in enumerate(months, 1):
        val = None
        m_norm = m.replace("-", "_")
        for col in row.index:
            col_str = str(col).strip()
            if col_str.startswith(m) or col_str.startswith(f"m_{m_norm}") or col_str.startswith(f"m_{m}") or col_str == m:
                val = _s(row.get(col))
                break
        if val is not None:
            trend[f"m{i} ({m})"] = val
    return trend


def enrich_kpis(tables, triggered_ads, qi):
    data, avail = {}, {}
    if not triggered_ads:
        return data, avail

    triggered_map = {str(a).strip().upper(): a for a in triggered_ads}

    for sheet_key, out_key in _SIMPLE_KPIS.items():
        matched_sheet = _find_sheet(tables, sheet_key)
        if not matched_sheet:
            continue
        df = tables[matched_sheet].reset_index(drop=True)

        # Locate alert definition column
        ad_col = None
        for c in ("alert_definition", "alert_definition_id", "alert_def", "alert_definition_code", "ad_id", "ad_name", "ad", "scenario_id"):
            if c in df.columns:
                ad_col = c
                break
        if not ad_col:
            for c in df.columns:
                if df[c].astype(str).str.strip().str.upper().isin(triggered_map).any():
                    ad_col = c
                    break

        if not ad_col or df.empty:
            continue

        # Ingestion quarter filter (if sheet has ingestion_quarter column and matching rows exist)
        if "ingestion_quarter" in df.columns:
            target_ing = format_quarter(qi.ingestion) or str(qi.ingestion).strip()
            sub_df = df[df["ingestion_quarter"].apply(format_quarter) == target_ing].reset_index(drop=True)
            if not sub_df.empty:
                df = sub_df

        qc_test = _find_q_col(df, qi.test) or _find_q_col(df, qi.ingestion)
        qc_base = _find_q_col(df, qi.base)
        if not qc_test:
            continue

        n = 0
        for _, row in df.iterrows():
            raw_ad = str(row.get(ad_col, "")).strip()
            canonical_ad = triggered_map.get(raw_ad.upper())
            if not canonical_ad:
                continue

            val_test = _s(row.get(qc_test))
            val_base = _s(row.get(qc_base)) if qc_base else None
            s_ref = str(row.get("_source_ref") or f"{matched_sheet}")

            diff = None
            if isinstance(val_test, (int, float)) and isinstance(val_base, (int, float)):
                diff = round(val_test - val_base, 4)

            m_trend = _kpi_trend(row, qi.test_months)

            if val_test is not None:
                data.setdefault(canonical_ad, {})[out_key] = val_test
                data.setdefault(canonical_ad, {})[f"{out_key}_base"] = val_base
                data.setdefault(canonical_ad, {})[f"{out_key}_diff"] = diff
                data.setdefault(canonical_ad, {})[f"{out_key}_trend"] = m_trend
                if out_key == "kpi2b_alerted_customers":
                    data.setdefault(canonical_ad, {})["kpi2b_productive_alert_rate"] = val_test
                data.setdefault(canonical_ad, {}).setdefault("_sources", {})[out_key] = s_ref
                avail.setdefault(canonical_ad, []).append(matched_sheet)
                n += 1
        print(f"  [KPI] {matched_sheet}: {n} enriched (Test col: {qc_test}, Base col: {qc_base})")

    for sheet_key, cfg in _STRUCT_KPIS.items():
        matched_sheet = None
        for alias in cfg.get("aliases", [sheet_key]):
            matched_sheet = _find_sheet(tables, alias)
            if matched_sheet:
                break
        if not matched_sheet:
            continue
        df = tables[matched_sheet].reset_index(drop=True)

        ad_col = None
        for c in ("alert_definition", "alert_definition_id", "alert_def", "alert_definition_code", "ad_id", "ad_name", "ad", "scenario_id"):
            if c in df.columns:
                ad_col = c
                break
        if not ad_col:
            for c in df.columns:
                if df[c].astype(str).str.strip().str.upper().isin(triggered_map).any():
                    ad_col = c
                    break
        if not ad_col or df.empty:
            continue

        filt_col = cfg["filter"]
        filt_val = qi.test if filt_col == "test_quarter" else qi.ingestion
        if filt_col in df.columns:
            sub_df = df[df[filt_col].apply(format_quarter) == format_quarter(filt_val)].reset_index(drop=True)
            if not sub_df.empty:
                df = sub_df

        n = 0
        for _, row in df.iterrows():
            raw_ad = str(row.get(ad_col, "")).strip()
            canonical_ad = triggered_map.get(raw_ad.upper())
            if not canonical_ad:
                continue
            s_ref = str(row.get("_source_ref") or f"{matched_sheet}")
            ev = {short: _s(row.get(src)) for src, short in cfg["cols"].items()
                  if _s(row.get(src)) is not None}
            if ev:
                data.setdefault(canonical_ad, {})[cfg["key"]] = ev
                data.setdefault(canonical_ad, {}).setdefault("_sources", {})[cfg["key"]] = s_ref
                avail.setdefault(canonical_ad, []).append(matched_sheet)
                n += 1
        print(f"  [KPI] {matched_sheet}: {n} enriched")


    return data, avail




# ── Alert Definition Taxonomy Standards (ABCD.123.SS.RR.XY) ─────────────────

SEGMENT_MAPPING: dict[str, dict[str, Any]] = {
    "01": {"ctc": "FI (Financial Institution)", "name": "Financial Institution", "lob": "Wholesale (WB)"},
    "02": {"ctc": "LARGE (Large Corporation)", "name": "Large Corporation", "lob": "Wholesale (WB)"},
    "03": {"ctc": "SMALL / OTHER (Small Corporation / Other Wholesale Banking Entity)", "name": "Small Corporation / Other Wholesale Banking Entity", "lob": "Wholesale (WB)"},
    "04": {"ctc": "MIDCORP (Medium Corporation)", "name": "Medium Corporation", "lob": "Retail (RB)"},
    "05": {"ctc": "SME (Small-Medium Entity)", "name": "Small-Medium Entity", "lob": "Retail (RB)"},
    "06": {"ctc": "PRIVATE (Private Individual)", "name": "Private Individual", "lob": "Retail (RB)"},
    "07": {"ctc": "PRIBA (Private Banking)", "name": "Private Banking", "lob": "Retail (RB)"},
    "08": {
        "ctc": "Financial Institution (FI), Large Corporation (LARGE), Small Corporation / Other (SMALL/OTHER), Medium Corporation (MEDIUM)",
        "name": "Wholesale Banking Portfolio (Financial Institutions, Large Corporations, Small/Other WB Entities, and Medium Corporations)",
        "lob": "Wholesale (WB)",
        "members": ["01", "02", "03", "60"],
    },
    "09": {
        "ctc": "Medium Corporation (MIDCORP), Small-Medium Entity (SME), Cash Intensive Entities Extra Large to Extra Small (CI-XL, CI-L, CI-M, CI-S, CI-XS), Non-Cash Intensive Entities Extra Large to Extra Small (NCI-XL, NCI-L, NCI-M, NCI-S, NCI-XS)",
        "name": "Retail Entity Portfolio (Medium Corporations, Small-Medium Entities, Cash Intensive Entities [XL-XS], and Non-Cash Intensive Entities [XL-XS])",
        "lob": "Retail (RB)",
        "members": ["04", "05", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22"],
    },
    "10": {
        "ctc": "Private Individual (PRIVATE), Private Banking (PRIBA), Individual Low Turnover (INDLT), Individual Medium Turnover (INDMT), Individual High Turnover (INDHT), Individual Very High Turnover (INDVHT)",
        "name": "Retail Individual Portfolio (Private Individuals, Private Banking, and Individuals across Low, Medium, High, and Very High Turnover Bands)",
        "lob": "Retail (RB)",
        "members": ["06", "07", "24", "25", "26", "27"],
    },
    "11": {
        "ctc": "All Retail Entities (MIDCORP, SME, CI XL-XS, NCI XL-XS) and Retail Individuals (PRIVATE, PRIBA, IND LT-VHT)",
        "name": "Full Retail Banking Customer Portfolio (All Retail Corporate Entities and All Retail Private Individuals)",
        "lob": "Retail (RB)",
        "members": ["04", "05", "06", "07", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "24", "25", "26", "27"],
    },
    "12": {
        "ctc": "All Wholesale Entities (FI, LARGE, MEDIUM, SMALL/OTHER) and All Retail Entities & Individuals (MIDCORP, SME, CI, NCI, PRIVATE, PRIBA, IND)",
        "name": "Universal Banking Customer Portfolio (All Wholesale Corporate Entities, Retail Entities, and Retail Individuals)",
        "lob": "Universal (UB = WB + RB)",
        "members": ["01", "02", "03", "04", "05", "06", "07", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "24", "25", "26", "27", "60"],
    },
    "13": {"ctc": "CI-XL (Cash Intensive Entity - Extra Large)", "name": "Cash Intensive Entity - Extra Large", "lob": "Retail (RB)"},
    "14": {"ctc": "CI-L (Cash Intensive Entity - Large)", "name": "Cash Intensive Entity - Large", "lob": "Retail (RB)"},
    "15": {"ctc": "CI-M (Cash Intensive Entity - Medium)", "name": "Cash Intensive Entity - Medium", "lob": "Retail (RB)"},
    "16": {"ctc": "CI-S (Cash Intensive Entity - Small)", "name": "Cash Intensive Entity - Small", "lob": "Retail (RB)"},
    "17": {"ctc": "CI-XS (Cash Intensive Entity - Extra Small)", "name": "Cash Intensive Entity - Extra Small", "lob": "Retail (RB)"},
    "18": {"ctc": "NCI-XL (Non-Cash Intensive Entity - Extra Large)", "name": "Non-Cash Intensive Entity - Extra Large", "lob": "Retail (RB)"},
    "19": {"ctc": "NCI-L (Non-Cash Intensive Entity - Large)", "name": "Non-Cash Intensive Entity - Large", "lob": "Retail (RB)"},
    "20": {"ctc": "NCI-M (Non-Cash Intensive Entity - Medium)", "name": "Non-Cash Intensive Entity - Medium", "lob": "Retail (RB)"},
    "21": {"ctc": "NCI-S (Non-Cash Intensive Entity - Small)", "name": "Non-Cash Intensive Entity - Small", "lob": "Retail (RB)"},
    "22": {"ctc": "NCI-XS (Non-Cash Intensive Entity - Extra Small)", "name": "Non-Cash Intensive Entity - Extra Small", "lob": "Retail (RB)"},
    "23": {
        "ctc": "Cash Intensive Entities (CI-XL, CI-L, CI-M, CI-S, CI-XS), Non-Cash Intensive Entities (NCI-XL, NCI-L, NCI-M, NCI-S, NCI-XS)",
        "name": "Cash Intensive and Non-Cash Intensive Entities Portfolio (All Turnover Bands from Extra Large to Extra Small)",
        "lob": "Retail (RB)",
        "members": ["13", "14", "15", "16", "17", "18", "19", "20", "21", "22"],
    },
    "24": {"ctc": "INDLT (Individual - Low Turnover)", "name": "Individual - Low Turnover", "lob": "Retail (RB)"},
    "25": {"ctc": "INDMT (Individual - Medium Turnover)", "name": "Individual - Medium Turnover", "lob": "Retail (RB)"},
    "26": {"ctc": "INDHT (Individual - High Turnover)", "name": "Individual - High Turnover", "lob": "Retail (RB)"},
    "27": {"ctc": "INDVHT (Individual - Very High Turnover)", "name": "Individual - Very High Turnover", "lob": "Retail (RB)"},
    "60": {"ctc": "MEDIUM (Medium Corporation)", "name": "Medium Corporation", "lob": "Wholesale (WB)"},
}


RISK_MAPPING: dict[str, str] = {
    "00": "All Risks (Combined 01 High, 02 Medium, 03 Low)",
    "01": "High Risk",
    "02": "Medium Risk",
    "03": "Low Risk",
    "04": "Medium/Low Risk (Combined 02 Medium, 03 Low)",
}

PERIOD_MAPPING: dict[str, dict[str, str]] = {
    "TD": {"alias": "Today", "description": "1 day transaction activity"},
    "TDY": {"alias": "Today + Yesterday", "description": "2 days transaction activity"},
    "TW": {"alias": "This Week", "description": "1 calendar week (Mon-Sun, 1-7 days)"},
    "TWLW": {"alias": "This Week + Last Week", "description": "2 calendar weeks (8-14 days)"},
    "TM": {"alias": "This Month", "description": "1 calendar month"},
    "TMLM": {"alias": "This Month + Last Month", "description": "2 calendar months (current + preceding month)"},
    "TQ": {"alias": "This Quarter", "description": "1 calendar quarter (90-92 days)"},
    "TQLQ": {"alias": "This Quarter + Last Quarter", "description": "2 calendar quarters (current + preceding quarter)"},
    "RP": {"alias": "Rolling Period", "description": "Rolling window (This Month + N Last Months)"},
}

_AD_TAXONOMY_RE = re.compile(
    r"([A-Za-z]{3,5}\.\d{3})[\.\-_](\d{2})[\.\-_](\d{2})[\.\-_]([A-Za-z]{2,4})",
    re.IGNORECASE
)


def decode_alert_definition(ad: str) -> dict[str, Any] | None:
    """Decode standard alert definition structure ABCD.123.SS.RR.XY into taxonomy attributes."""
    if not ad:
        return None
    m = _AD_TAXONOMY_RE.search(str(ad).strip())
    if not m:
        return None

    scenario, seg_code, risk_code, period_code = m.group(1).upper(), m.group(2), m.group(3), m.group(4).upper()
    seg_info = SEGMENT_MAPPING.get(seg_code, {})
    risk_info = RISK_MAPPING.get(risk_code, f"Risk Code {risk_code}")
    period_info = PERIOD_MAPPING.get(period_code, {"alias": period_code, "description": period_code})

    members_detail = []
    if seg_info.get("members"):
        for m_code in seg_info["members"]:
            m_info = SEGMENT_MAPPING.get(m_code, {})
            members_detail.append({
                "code": m_code,
                "name": m_info.get("name", f"Segment {m_code}"),
                "ctc": m_info.get("ctc", "—"),
                "lob": m_info.get("lob", "—"),
            })

    return {
        "scenario_code": scenario,
        "segment_code": seg_code,
        "segment_name": seg_info.get("name", f"Segment {seg_code}"),
        "customer_type_code": seg_info.get("ctc", "—"),
        "line_of_business": seg_info.get("lob", "—"),
        "is_combined": bool(members_detail),
        "members_detail": members_detail,
        "risk_code": risk_code,
        "risk_name": risk_info,
        "period_code": period_code,
        "period_alias": period_info.get("alias", period_code),
        "period_description": period_info.get("description", period_code),
    }



# ── KRI Reference Definitions ───────────────────────────────────────────────

KRI_SPECIFICATIONS: dict[str, dict[str, str]] = {
    "KRI_1": {
        "title": "Deviation in Alert Volume",
        "trigger_condition": (
            "Triggers if: [1-3 std dev + absolute change >=50 (RB) / >=30 (WB) for >=2 consecutive quarters] "
            "OR [>=3 std dev + absolute change >=50 (RB) / >=30 (WB) in 1 quarter]."
        ),
        "policy_definition": (
            "KRI 1 measures whether an Alert Definition has experienced an unusual change in the volume of alerts generated "
            "compared to its base quarter. The baseline is established by the benchmark quarter, which represents the period "
            "when a change is implemented or when the alert definition is verified as functioning correctly. Subsequent quarters "
            "act as base quarters, and comparisons are performed against a test quarter, with the condition that the base quarter "
            "precedes the test quarter by at least one quarter, and both follow the benchmark quarter. The indicator operates "
            "through a dual-component trigger logic based on magnitude and persistence. The first component triggers when the "
            "test quarter average monthly alert volume deviates from the base quarter by between 1 and 3 standard deviations, "
            "combined with an absolute volume change of at least 50 alerts for Retail Banking countries or at least 30 alerts "
            "for Wholesale Banking countries, persisting for at least two consecutive test quarters. The second component triggers "
            "immediately when the volume deviates by at least 3 standard deviations, combined with an absolute change of at least "
            "50 alerts for Retail Banking countries or at least 30 alerts for Wholesale Banking countries, observed for at least "
            "one test quarter without requiring consecutiveness. The purpose is to identify Alert Definitions whose activity levels "
            "have materially shifted due to customer behaviour changes, data quality issues, implementation defects, threshold "
            "modifications, model misconfigurations, control degradation, or emerging financial crime risks. Statistically, it "
            "evaluates standard deviation distance from historical distributions. Logically, it separates ordinary fluctuations "
            "from material shifts, applying stricter criteria to single-quarter anomalies while capturing sustained moderate "
            "deviations. From a business perspective, it serves as an early warning mechanism. Technologically, it relies on "
            "historical alert aggregation, benchmark periods, and automated statistical calculations."
        ),
        "diagnostic_focus": "Customer behaviour shifts, population drift, data quality/ingestion glitches, threshold changes, or emerging typology waves.",
    },
    "KRI_2": {
        "title": "Deviation in True Positive Volume",
        "trigger_condition": (
            "Triggers if: [Downward 1-3 std dev + drop >=15 (RB) / >=10 (WB) for >=2 consecutive quarters] "
            "OR [Downward >=3 std dev + drop >=15 (RB) / >=10 (WB) in 1 quarter]."
        ),
        "policy_definition": (
            "KRI 2 measures whether an Alert Definition has experienced a significant reduction in the volume of productive alerts "
            "generated compared to its base quarter, where the base quarter is positioned after the benchmark quarter and precedes "
            "the test quarter by at least one quarter. The indicator is structured into two components. The first component triggers "
            "when the test quarter average monthly True Positive alert volume deviates downward by between 1 and 3 standard deviations "
            "from the base quarter, combined with an absolute decrease of at least 15 alerts for Retail Banking countries or at least "
            "10 alerts for Wholesale Banking countries, observed for at least two consecutive test quarters. The second component "
            "triggers immediately when the downward deviation reaches at least 3 standard deviations, combined with an absolute "
            "decrease of at least 15 alerts for Retail Banking countries or at least 10 alerts for Wholesale Banking countries, "
            "observed for at least one test quarter. The purpose is to detect situations where a control remains active but loses "
            "effectiveness in identifying genuinely relevant cases. Statistically, it compares current productive volumes against "
            "base quarter baselines. Logically, it focuses exclusively on decreases that signal reduced detection capability, "
            "deteriorating calibration, or weakened control performance. Business-wise, it assesses true effectiveness rather than "
            "gross activity volume. Technologically, it utilizes historical productive alert data, benchmark comparisons, and "
            "deviation analysis."
        ),
        "diagnostic_focus": "Reduced detection capability, control degradation, or decaying threshold calibration.",
    },
    "KRI_3": {
        "title": "Accumulation of Escalations in Proximity",
        "trigger_condition": (
            "Triggers if: [10-50% proximity shift + 5-10 TPs for >=2 consecutive quarters] "
            "OR [>=50% proximity shift + >=10 TPs in 1 quarter]."
        ),
        "policy_definition": (
            "KRI 3 measures whether productive alerts are increasingly concentrated near the configured threshold boundaries of an "
            "Alert Definition when compared between a test quarter and a base quarter that follows the benchmark quarter. The indicator "
            "is divided into two components. The first component triggers when the test quarter True Positive alert accumulation in "
            "threshold proximity deviates from the base quarter by between 10 and 50 percentage points, combined with between 5 and "
            "10 True Positive alerts, observed for at least two consecutive test quarters. The second component triggers immediately "
            "when the deviation in threshold proximity reaches at least 50 percentage points, combined with at least 10 True Positive "
            "alerts, observed for at least one test quarter. Conceptually, it examines the relationship between productive outcomes "
            "and threshold positioning. Statistically, it evaluates clustering patterns around threshold limits. Logically, "
            "accumulations near boundaries indicate that small threshold adjustments could significantly influence detection outcomes. "
            "From a business perspective, it supports threshold optimization and control tuning. Technologically, it relies on "
            "threshold values, alert measurements, and escalation outcomes to quantify proximity-based behaviour."
        ),
        "diagnostic_focus": "Threshold boundary sensitivity; indicates whether minor threshold adjustments will capture or shed major productive volume.",
    },
    "KRI_6": {
        "title": "Dormant Alert Definition Identification",
        "trigger_condition": (
            "Triggers if: [Active for >=3 consecutive quarters and subsequently produces 0 alerts for 3 consecutive quarters]."
        ),
        "policy_definition": (
            "KRI 6 measures whether an Alert Definition has become operationally inactive despite remaining in scope and available "
            "for monitoring. The indicator evaluates inactivity by tracking whether an alert definition has been active for three "
            "consecutive quarters and subsequently produces zero alerts across three consecutive quarters, rendering it eligible "
            "for flagging without comparison to a base or benchmark quarter. The purpose is to identify definitions that have stopped "
            "generating alerts over a sustained period, representing potential blind spots in the control framework. Logically, a "
            "dormant Alert Definition continues to exist and remain eligible for monitoring but produces zero alerts for multiple "
            "consecutive evaluation periods. Statistically, this is a binary absence check rather than a deviation-based calculation. "
            "From a business perspective, prolonged inactivity indicates control obsolescence, implementation issues, overly "
            "restrictive thresholds, underlying data problems, or ingestion failures. Technologically, it combines benchmark eligibility "
            "information, quarterly alert counts, and existence checks to flag definitions generating zero alerts across the evaluation "
            "window, ensuring temporary fluctuations are excluded."
        ),
    },
}

KPI_SPECIFICATIONS: dict[str, dict[str, str]] = {
    "KPI_1": {
        "title": "Number of Alerts",
        "formula": "Count of Alerts",
        "description": "Measures the volume of alerts generated by an Alert Definition during a specific period.",
        "story_template": "During {test_quarter}, this Alert Definition generated {val} alerts, establishing the gross operational monitoring volume.",
    },
    "KPI_2b": {
        "title": "Number of Alerted Customers",
        "formula": "Count Distinct(Customer ID)",
        "description": "Measures unique customers triggering alerts, providing insight into customer coverage versus single-entity alert concentration.",
        "story_template": "Alerts in {test_quarter} were distributed across {val} unique alerted customers, reflecting broad portfolio coverage.",
    },
    "KPI_3": {
        "title": "Number of Productive Customers",
        "formula": "Count Distinct(Customer ID where LOD = L3)",
        "description": "Measures unique customers associated with productive alerts escalated to Level 3 investigation.",
        "story_template": "{val} distinct customers generated alerts that were escalated to Level 3 review as productive cases in {test_quarter}.",
    },
    "KPI_6": {
        "title": "First Productive Alert Position from Threshold",
        "formula": "Lowest Percentile Rank among Productive Alerts relative to Threshold Floor",
        "description": "Evaluates proximity of earliest productive alert to configured threshold floor; values near 0% indicate high threshold sensitivity.",
        "story_template": "The earliest productive alert occurred at the {val} percentile position above the threshold floor in {test_quarter}.",
    },
    "KPI_11": {
        "title": "False Positive Ratio",
        "formula": "((Total Alerts - Productive Alerts) / Total Alerts) * 100",
        "description": "Measures the proportion of alerts closed without escalation, reflecting operational efficiency and noise.",
        "story_template": "{val}% of all alerts in {test_quarter} were closed as false positives without requiring escalation.",
    },
    "KPI_12": {
        "title": "True Positive Ratio",
        "formula": "(Productive Alerts / Total Alerts) * 100",
        "description": "Measures the proportion of alerts resulting in productive outcomes (L3 escalations / SAR filings).",
        "story_template": "The model achieved a True Positive conversion rate of {val}% in {test_quarter}.",
    },
    "KPI_15a": {
        "title": "Productive Alerts Within Amount Threshold Proximity",
        "formula": "(Amount Proximity Productive Alerts / Total Productive Alerts) * 100",
        "description": "Measures the percentage of productive alerts clustered near the configured amount threshold.",
        "story_template": "{val}% of productive alerts clustered near the Amount threshold boundary in {test_quarter}.",
    },
    "KPI_15b": {
        "title": "Productive Alerts Within Frequency Threshold Proximity",
        "formula": "(Frequency Proximity Productive Alerts / Total Productive Alerts) * 100",
        "description": "Measures the percentage of productive alerts clustered near the configured frequency/count threshold.",
        "story_template": "{val}% of productive alerts clustered near the Frequency threshold boundary in {test_quarter}.",
    },
    "KPI_16": {
        "title": "Number of Productive Alerts",
        "formula": "Count of Productive Alerts (LOD = L3)",
        "description": "Measures the absolute volume of productive alerts escalated to Level 3 investigation.",
        "story_template": "Generated {val} productive (L3 escalated) alerts in {test_quarter}.",
    },
    "KPI_17": {
        "title": "Unique Productivity & Overlap Within Typology",
        "formula": "Productive alerts uniquely attributable after removing multi-AD overlap",
        "description": "Measures sibling alert definition overlap ratios and productive yield uniquely attributable to this control.",
        "story_template": "Unique productivity and sibling overlap metrics evaluated within typology.",
    },
    "KPI_18": {
        "title": "Secondary Threshold Limits & Proximity Distances",
        "formula": "Configured threshold parameter boundaries and distance to earliest productive alerts",
        "description": "Measures active threshold boundaries (min/max amount, min frequency) and distance to earliest true positive alerts.",
        "story_template": "Configured with active thresholds and evaluated for boundary proximity.",
    },
}

KRI_RELEVANT_KPIS: dict[str, dict[str, Any]] = {
    "KRI_1": {
        "title": "Deviation in Alert Volume",
        "primary_kpis": ["KPI_1", "KPI_2b", "KPI_11", "KPI_12"],
        "secondary_kpis": ["KPI_16", "KPI_3", "KPI_18"],
        "diagnostic_focus": "Evaluates whether alert volume surge is driven by customer breadth (KPI 2b) vs repeat bursts, and verifies false positive (KPI 11) vs true positive (KPI 12) conversion stability.",
    },
    "KRI_2": {
        "title": "Deviation in True Positive Volume",
        "primary_kpis": ["KPI_16", "KPI_3", "KPI_12", "KPI_6"],
        "secondary_kpis": ["KPI_1", "KPI_17", "KPI_18"],
        "diagnostic_focus": "Identifies true positive decay across distinct customers (KPI 3), evaluates conversion rate (KPI 12) and threshold margin sensitivity (KPI 6), and checks sibling control overlap (KPI 17).",
    },
    "KRI_3": {
        "title": "Accumulation in Threshold Proximity",
        "primary_kpis": ["KPI_15a", "KPI_15b", "KPI_6", "KPI_18"],
        "secondary_kpis": ["KPI_16", "KPI_12", "KPI_11"],
        "diagnostic_focus": "Quantifies productive alert clustering near threshold boundaries (amount KPI 15a, frequency KPI 15b, threshold distances KPI 18) to evaluate recalibration vs re-banding.",
    },
    "KRI_6": {
        "title": "Dormant Alert Definition Identification",
        "primary_kpis": ["KPI_1", "KPI_17", "KPI_18"],
        "secondary_kpis": ["KPI_2b", "KPI_16"],
        "diagnostic_focus": "Confirms sustained zero-alert generation and isolates root cause between control obsolescence (superseded by sibling rule in KPI 17), hyper-restrictive parameters (KPI 18), or pipeline failure.",
    },
}



# ── Scenario Qualitative Detection Logic Standards ─────────────────────────

def extract_scenario_code(ad: str) -> str | None:
    """Extract standard 8-char control code (e.g. 'CHQD.058') from an alert definition."""
    if not ad: return None
    s = str(ad).strip()
    if len(s) >= 8 and s[:4].isalpha() and s[4] in (".", "_", "-") and s[5:8].isdigit():
        return f"{s[:4].upper()}.{s[5:8]}"
    m = re.search(r"([A-Za-z]{3,5}[\.\-_ ]\d{3})", s)
    return m.group(1).upper().replace("_", ".").replace("-", ".") if m else None


def load_scenarios_catalog(filepath: str | Path | None) -> tuple[dict[str, Any], str]:
    """Load and normalize scenario catalog from root or nested 'models'/'scenarios' key."""
    if not filepath:
        return {}, ""
    p = Path(str(filepath).strip(' "\''))
    if not p.exists() or not p.is_file():
        return {}, ""
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        catalog = raw.get("models") or raw.get("scenarios") or raw.get("controls") or (raw if isinstance(raw, dict) else {})
        norm = {}
        for k, v in catalog.items():
            if isinstance(v, dict):
                k_str = str(k).strip()
                k_std = extract_scenario_code(k_str) or k_str.upper()
                norm[k_std] = v
                norm[k_str.upper()] = v
        return norm, p.name
    except Exception as e:
        print(f"  [Warning] Failed to load scenarios catalog from {p}: {e}")
        return {}, p.name


def format_scenario_detection_logic(code: str, info: dict[str, Any], source: str, ad_id: str | None = None) -> str:
    """Format scenario/control qualitative detection logic and alert generation rules."""
    esc = lambda v: str(v or "—").strip().replace("|", "\\|").replace("\n", " ")
    lines = [
        "  <domain name=\"scenario_detection_logic\">",
        f"    ### Parent Scenario & Control Specification: {code}\n",
        "    > **Context for LLM:** This section defines the parent scenario detection mechanics governing how individual transaction monitoring alerts are triggered. While individual Alert Definitions apply specific segment/risk thresholds, the rules below define the core financial crime typology, focal entity scope, and alert generation criteria.\n",
        "    | Scenario Dimension | Specification | Source |",
        "    |---|---|---|",
        f"    | Typology Description | {esc(info.get('Typology'))} | {source} |",
        f"    | Financial Crime Risk Type | {esc(info.get('Risk Type'))} | {source} |",
        f"    | Focal Entity Level | {esc(info.get('Focal Entity'))} | {source} |",
        f"    | Alert Generation Policy | {esc(info.get('Alert Generation Criteria'))} | {source} |",
    ]

    decoded = decode_alert_definition(ad_id) if ad_id else None
    if decoded:
        lines.append(f"    | Configured Segment Scope | {esc(decoded['segment_name'])} (CTC: {decoded['customer_type_code']}) [{decoded['line_of_business']}] [Code: {decoded['segment_code']}] | AD_Taxonomy_Standard |")
        lines.append(f"    | Configured Customer Risk | {esc(decoded['risk_name'])} [Code: {decoded['risk_code']}] | AD_Taxonomy_Standard |")
        lines.append(f"    | Configured Monitoring Window | {esc(decoded['period_alias'])} - {esc(decoded['period_description'])} [Code: {decoded['period_code']}] | AD_Taxonomy_Standard |")
    lines.append("")

    if info.get("Conditions"):
        lines.extend([
            "    #### Target Population & Applicability Conditions",
            f"    {info['Conditions'].strip()}",
            ""
        ])

    if info.get("FCRM will generate an alert if"):
        lines.extend([
            "    #### Single Alert Trigger Criteria",
            f"    {info['FCRM will generate an alert if'].strip()}",
            ""
        ])

    if info.get("FCRM Scenario Logic"):
        lines.extend([
            "    #### Technical Scenario Logic",
            f"    {info['FCRM Scenario Logic'].strip()}",
            ""
        ])

    profiles = info.get("Solution Definition Profiles", [])
    if profiles:
        lines.append("    #### In-Scope Transaction Profiles")
        for p in profiles:
            p_name = p.get("profile", "—")
            tc = ", ".join(p.get("transaction_code", [])) or "—"
            dc = ", ".join(p.get("debit_credit", [])) or "—"
            lines.append(f"    - **Profile `{p_name}`**: Transaction Codes: `[{tc}]` | Flow Direction: `[{dc}]`")
        lines.append("")

    lines.append("  </domain>\n")
    return "\n".join(lines)


# ── Markdown Dossier Serialization ─────────────────────────────────────────

def _escape_md(val: Any) -> str:
    if val is None:
        return "—"
    s = str(val).strip()
    return s.replace("|", "\\|").replace("\n", " ")


def _format_metric_row(metric: str, val: Any, source: str) -> str:
    return f"    | {_escape_md(metric)} | {_escape_md(val)} | {_escape_md(source)} |"


def serialize_dossier_markdown(
    ad_block: dict[str, Any],
    scenarios_catalog: dict[str, Any] | None = None,
    scenario_source: str = "scenarios.json"
) -> str:
    """Serialize a single alert definition data block into an LLM-optimized XML-tagged Markdown dossier in exact domain order."""
    ad = ad_block.get("alert_definition", "UNKNOWN")
    identity = ad_block.get("identity", {})
    thresholds = ad_block.get("thresholds", {})
    flags = ad_block.get("flags", {})
    quarters = ad_block.get("quarters", {})
    triggered_kris = ad_block.get("triggered_kris", [])
    kpi_context = ad_block.get("kpi_context", {})
    kpi_sources = kpi_context.get("_sources", {})
    rec = ad_block.get("recommendation")
    default_src = ad_block.get("_source", "Excel")

    parts: list[str] = []
    parts.append(f'<model id="{ad}" code="{ad}">\n')
    parts.append("<structured_metrics>")

    # 1. Identity Domain
    parts.append('  <domain name="identity">')
    parts.append("    | Metric | Value | Source |")
    parts.append("    |--------|-------|--------|")

    # Decode standard taxonomy structure ABCD.123.SS.RR.XY
    decoded = decode_alert_definition(ad)
    if decoded:
        parts.append(_format_metric_row("Control Scenario Code", decoded["scenario_code"], "AD_Taxonomy_Standard"))
        parts.append(_format_metric_row("Target Segment", f"{decoded['segment_name']} [Code: {decoded['segment_code']}]", "AD_Taxonomy_Standard"))
        parts.append(_format_metric_row("Line of Business", decoded["line_of_business"], "AD_Taxonomy_Standard"))
        parts.append(_format_metric_row("Customer Risk Tier", f"{decoded['risk_name']} [Code: {decoded['risk_code']}]", "AD_Taxonomy_Standard"))
        parts.append(_format_metric_row("Monitoring Evaluation Window", f"{decoded['period_alias']} ({decoded['period_description']}) [Code: {decoded['period_code']}]", "AD_Taxonomy_Standard"))

        if decoded.get("customer_type_code") and decoded.get("customer_type_code") != "—":
            parts.append(_format_metric_row("Customer Type Code (CTC)", decoded["customer_type_code"], "AD_Taxonomy_Standard"))


    id_labels = [
        ("country", "Country"),
        ("business_line", "Business Line"),
        ("segment_desc", "Segment Description (Reported)"),
        ("customer_type_code", "Customer Type Code (Reported)"),
        ("customer_risk", "Customer Risk (Reported)"),
    ]
    for k, label in id_labels:
        if k in identity and identity[k]:
            parts.append(_format_metric_row(label, identity[k], default_src))
    parts.append("  </domain>\n")

    # 2. Scenario Detection Logic (Qualitative context immediately after identity)
    if scenarios_catalog:
        scen_code = extract_scenario_code(ad)
        info = scenarios_catalog.get(scen_code) or scenarios_catalog.get(ad.strip().upper())
        if info:
            logic_md = format_scenario_detection_logic(scen_code or ad, info, scenario_source, ad_id=ad)
            parts.append(logic_md)

    # 3. Quarterly Context Domain
    parts.append('  <domain name="quarterly_context">')
    parts.append("    | Metric | Value | Source |")
    parts.append("    |--------|-------|--------|")
    if "ingestion" in quarters:
        parts.append(_format_metric_row("Ingestion Quarter", quarters["ingestion"], "Derived/Quarter_Resolution"))
    if "test" in quarters:
        parts.append(_format_metric_row("Test Quarter (Evaluation)", quarters["test"], "Derived/Quarter_Resolution"))
    if "base" in quarters:
        parts.append(_format_metric_row("Base Quarter (Baseline)", quarters["base"], "Derived/Quarter_Resolution"))
    elif "base_quarters" in quarters:
        parts.append(_format_metric_row("Base Quarters (Baseline)", ", ".join(quarters["base_quarters"]), "Derived/Quarter_Resolution"))
    parts.append("  </domain>\n")

    # 4. Triggered KRI & Paired KPI Diagnostic Evaluation Units
    if triggered_kris:
        test_q_str = str(quarters.get("test") or "Evaluation Quarter")
        base_quarters_list = quarters.get("base_quarters")
        if quarters.get("base"):
            base_q_str = str(quarters["base"])
        elif isinstance(base_quarters_list, list) and len(base_quarters_list) > 0:
            base_q_str = str(base_quarters_list[0])
        else:
            base_q_str = "Baseline"
        parts.append('  <domain name="triggered_kri_evaluations">')


        for idx, ev in enumerate(triggered_kris, 1):
            kri_key = ev.get("kri", "KRI")
            spec = KRI_SPECIFICATIONS.get(kri_key, {})
            kri_title = spec.get("title", kri_key)
            ev_src = ev.get("source", default_src)
            k_map = KRI_RELEVANT_KPIS.get(kri_key, {})

            prefix = f"{kri_key}: {kri_title}"
            if "direction" in ev:
                prefix += f" [{ev['direction'].upper()}]"
            elif "sub_trigger" in ev:
                prefix += f" [{ev['sub_trigger'].upper()}]"

            parts.append(f"\n    ### Evaluation Unit {idx}: {prefix}\n")

            # 1. KRI Trigger Telemetry
            parts.append(f"    #### 1. KRI Trigger Condition & Telemetry ({kri_key})")
            parts.append("    | Metric | Value | Source |")
            parts.append("    |---|---|---|")
            if spec.get("trigger_condition"):
                parts.append(_format_metric_row(f"{kri_key} Trigger Rule", spec["trigger_condition"], "TM_Governance_Policy"))
            if spec.get("policy_definition"):
                parts.append(_format_metric_row(f"{kri_key} Policy Definition", spec["policy_definition"], "TM_Governance_Policy"))
            if spec.get("diagnostic_focus"):
                parts.append(_format_metric_row(f"{kri_key} Diagnostic Focus", spec["diagnostic_focus"], "TM_Governance_Policy"))

            for field, label in [
                ("test_quarter_count", f"{prefix} Test Quarter Count"),
                ("base_quarter_count", f"{prefix} Base Quarter Count"),
                ("difference", f"{prefix} Difference (Test - Base)"),
                ("full_period_avg_count", f"{prefix} Full Period Avg Count"),
                ("full_period_stddev_count", f"{prefix} Full Period Stddev"),
                ("three_sigma_exceeded", f"{prefix} >=3-Sigma Exceeded (Single Quarter)"),
                ("consecutive_trigger", f"{prefix} Consecutive Trigger (>=2 Quarters)"),
                ("alert_count", f"{prefix} Total Alerts Evaluated"),
                ("test_quarter_accum_ratio_amount", f"{prefix} Test Proximity Accum Ratio"),
                ("base_quarter_accum_ratio_amount", f"{prefix} Base Proximity Accum Ratio"),
                ("amount_deviation", f"{prefix} Proximity Amount Deviation"),
                ("frequency_deviation", f"{prefix} Proximity Frequency Deviation"),
                ("false_positive_rate", f"{prefix} False Positive Rate"),
                ("true_positive_rate", f"{prefix} True Positive Rate"),
                ("test_quarter_alerts", f"{prefix} Test Quarter Alerts"),
                ("test_quarter_minus_1_alerts", f"{prefix} Test Quarter -1 Alerts"),
                ("test_quarter_minus_2_alerts", f"{prefix} Test Quarter -2 Alerts"),
                ("total_monitoring_alerts", f"{prefix} Total Trailing Alerts"),
                ("oldest_benchmark_period", f"{prefix} Benchmark Quarter"),
            ]:
                if field in ev and ev[field] is not None:
                    parts.append(_format_metric_row(label, ev[field], ev_src))

            if "monthly_trend" in ev and ev["monthly_trend"]:
                trend_str = " | ".join(f"{k}: {v}" for k, v in ev["monthly_trend"].items())
                parts.append(_format_metric_row(f"{prefix} Monthly Progression", trend_str, ev_src))

            # 2. Directly Corresponding KPI Metrics for this KRI
            parts.append(f"\n    #### 2. Directly Corresponding KPI Metrics for {kri_key}")
            parts.append(f"    | KPI Metric | Evaluation ({test_q_str}) | Baseline ({base_q_str}) | Diff (Δ) | Monthly Trend | Relevance | Source |")
            parts.append("    |---|---|---|---|---|---|---|")

            primary_kpis = k_map.get("primary_kpis", [])
            secondary_kpis = k_map.get("secondary_kpis", [])
            all_unit_kpis = []
            seen_kpis = set()
            for pk in primary_kpis:
                clean_pk = "KPI_17" if pk == "KPI_17_quarter" else ("KPI_18" if pk == "KPI_18_quarter" else pk)
                if clean_pk not in seen_kpis:
                    all_unit_kpis.append((clean_pk, "Primary Evidence"))
                    seen_kpis.add(clean_pk)
            for sk in secondary_kpis:
                clean_sk = "KPI_17" if sk == "KPI_17_quarter" else ("KPI_18" if sk == "KPI_18_quarter" else sk)
                if clean_sk not in seen_kpis:
                    all_unit_kpis.append((clean_sk, "Supporting Evidence"))
                    seen_kpis.add(clean_sk)


            for kpi_code, rel_type in all_unit_kpis:
                if kpi_code in ("KPI_17", "KPI_17_quarter"):
                    qm = kpi_context.get("kpi17_quarterly_metrics", {})
                    gen_ov = qm.get("general_overlap_ratio")
                    prod_ov = qm.get("productive_overlap_ratio")
                    if gen_ov is not None or prod_ov is not None:
                        val_disp = f"General: {gen_ov or '—'} | Productive: {prod_ov or '—'}"
                    else:
                        val_disp = "Independent Typology (No Sibling Overlap)"
                    parts.append(f"    | Sibling Typology Overlap ({kpi_code}) | {val_disp} | — | — | — | {rel_type} | {kpi_sources.get('kpi17_quarterly_metrics', 'KPI_17')} |")
                elif kpi_code in ("KPI_18", "KPI_18_quarter"):
                    qt = kpi_context.get("kpi18_quarterly_thresholds", {})
                    min_amt = qt.get("min_amount_threshold")
                    min_freq = qt.get("min_frequency_threshold")
                    dist = qt.get("distance_amount_first_tp")
                    if min_amt is not None or min_freq is not None:
                        val_disp = f"Min Amt: {min_amt or '—'} | Min Freq: {min_freq or '—'} (Dist: {dist or '—'})"
                    else:
                        val_disp = "Standard Baseline Boundaries"
                    parts.append(f"    | Configured Limits & Distances ({kpi_code}) | {val_disp} | — | — | — | {rel_type} | {kpi_sources.get('kpi18_quarterly_thresholds', 'KPI_18')} |")
                else:
                    spec_kpi = KPI_SPECIFICATIONS.get(kpi_code, {})
                    title = spec_kpi.get("title", kpi_code)
                    val_test = None
                    val_base = None
                    val_diff = None
                    m_trend = None
                    src_kpi = kpi_sources.get(kpi_code, kpi_code)
                    for k_name, s_name in [
                        ("kpi1_alert_count", "KPI_1"),
                        ("kpi2b_alerted_customers", "KPI_2b"),
                        ("kpi2b_productive_alert_rate", "KPI_2b"),
                        ("kpi3_customer_count", "KPI_3"),
                        ("kpi6_value", "KPI_6"),
                        ("kpi11_value", "KPI_11"),
                        ("kpi12_value", "KPI_12"),
                        ("kpi15a_value", "KPI_15a"),
                        ("kpi15b_value", "KPI_15b"),
                        ("kpi16_unique_customers", "KPI_16"),
                    ]:
                        if s_name == kpi_code and k_name in kpi_context:
                            val_test = kpi_context[k_name]
                            val_base = kpi_context.get(f"{k_name}_base")
                            val_diff = kpi_context.get(f"{k_name}_diff")
                            m_trend = kpi_context.get(f"{k_name}_trend")
                            src_kpi = kpi_sources.get(k_name, kpi_code)
                            break
                    if val_test is not None:
                        diff_disp = f"{val_diff:+}" if isinstance(val_diff, (int, float)) else (str(val_diff) if val_diff is not None else "—")
                        trend_disp = " | ".join(f"{k}: {v}" for k, v in m_trend.items()) if m_trend else "—"
                        b_disp = str(val_base) if val_base is not None else "—"
                        parts.append(f"    | {title} ({kpi_code}) | {val_test} | {b_disp} | {diff_disp} | {trend_disp} | {rel_type} | {src_kpi} |")
                    else:
                        parts.append(f"    | {title} ({kpi_code}) | Not Populated / 0 Alerts | — | — | — | {rel_type} | {src_kpi} |")

            # 3. Integrated Causal Diagnostic Story for this KRI
            parts.append(f"\n    #### 3. Integrated Causal Diagnostic Story for {kri_key}")
            unit_stories = []
            for kpi_code, _ in all_unit_kpis:
                if kpi_code in ("KPI_17", "KPI_17_quarter"):
                    qm = kpi_context.get("kpi17_quarterly_metrics", {})
                    gen_ov = qm.get("general_overlap_ratio")
                    prod_ov = qm.get("productive_overlap_ratio")
                    if gen_ov is not None or prod_ov is not None:
                        unit_stories.append(f"    - **{kpi_code} (Overlap Analysis):** Demonstrated a general overlap ratio of **{gen_ov or '—'}** and productive overlap ratio of **{prod_ov or '—'}** with sibling alert definitions within the same typology.")
                    else:
                        unit_stories.append(f"    - **{kpi_code} (Overlap Analysis):** Operates as an independent detection control within its typology without significant sibling overlap.")
                elif kpi_code in ("KPI_18", "KPI_18_quarter"):
                    qt = kpi_context.get("kpi18_quarterly_thresholds", {})
                    min_amt = qt.get("min_amount_threshold")
                    min_freq = qt.get("min_frequency_threshold")
                    dist = qt.get("distance_amount_first_tp")
                    if min_amt is not None or min_freq is not None:
                        unit_stories.append(f"    - **{kpi_code} (Thresholds & Distances):** Evaluated against configured thresholds: Min Amount = **{min_amt or '—'}**, Max Amount = **{qt.get('max_amount_threshold', '—')}**, Min Frequency = **{min_freq or '—'}** (Distance to 1st TP: {dist or '—'}).")
                    else:
                        unit_stories.append(f"    - **{kpi_code} (Thresholds & Distances):** Evaluated against baseline parameter boundaries without secondary threshold proximity breaches.")
                elif kpi_code in KPI_SPECIFICATIONS:
                    spec_kpi = KPI_SPECIFICATIONS[kpi_code]
                    val = None
                    b_val = None
                    d_val = None
                    m_trend = None
                    for k_name, s_name in [
                        ("kpi1_alert_count", "KPI_1"),
                        ("kpi2b_alerted_customers", "KPI_2b"),
                        ("kpi2b_productive_alert_rate", "KPI_2b"),
                        ("kpi3_customer_count", "KPI_3"),
                        ("kpi6_value", "KPI_6"),
                        ("kpi11_value", "KPI_11"),
                        ("kpi12_value", "KPI_12"),
                        ("kpi15a_value", "KPI_15a"),
                        ("kpi15b_value", "KPI_15b"),
                        ("kpi16_unique_customers", "KPI_16"),
                    ]:
                        if s_name == kpi_code and k_name in kpi_context:
                            val = kpi_context[k_name]
                            b_val = kpi_context.get(f"{k_name}_base")
                            d_val = kpi_context.get(f"{k_name}_diff")
                            m_trend = kpi_context.get(f"{k_name}_trend")
                            break

                    if kpi_code == "KPI_1":
                        if val is not None:
                            cmp_str = f" (compared to {b_val} in {base_q_str}, Δ = {d_val:+})" if b_val is not None and isinstance(d_val, (int, float)) else ""
                            story_text = f"Generated **{val} alerts** in {test_q_str}{cmp_str}, establishing the gross operational monitoring volume."
                        else:
                            story_text = f"Gross alert volume was unpopulated or zero in {test_q_str}."
                    elif kpi_code == "KPI_2b":
                        if val is not None:
                            cmp_str = f" (compared to {b_val} in {base_q_str}, Δ = {d_val:+})" if b_val is not None and isinstance(d_val, (int, float)) else ""
                            ratio_str = f" (yielding {round(kpi_context.get('kpi1_alert_count', val) / val, 2)} alerts/customer)" if isinstance(kpi_context.get('kpi1_alert_count'), (int, float)) and val > 0 else ""
                            story_text = f"Alerts in {test_q_str} were distributed across **{val} unique alerted customers**{cmp_str}{ratio_str}, providing insight into customer coverage breadth rather than repeat alert volume."
                        else:
                            story_text = f"Unique customer alert coverage was unpopulated or zero in {test_q_str}."
                    elif kpi_code == "KPI_3":
                        if val is not None:
                            cmp_str = f" (compared to {b_val} in {base_q_str}, Δ = {d_val:+})" if b_val is not None and isinstance(d_val, (int, float)) else ""
                            story_text = f"A total of **{val} distinct customers** generated alerts confirmed as productive and escalated to Level 3 investigation in {test_q_str}{cmp_str}."
                        else:
                            story_text = f"No unique customers triggered Level 3 productive escalations in {test_q_str}."
                    elif kpi_code == "KPI_6":
                        if val is not None:
                            cmp_str = f" (compared to {b_val} in {base_q_str}, Δ = {d_val:+})" if b_val is not None and isinstance(d_val, (int, float)) else ""
                            story_text = f"The earliest productive alert occurred at the **{val} percentile position** above the configured threshold floor in {test_q_str}{cmp_str}, evaluating threshold sensitivity."
                        else:
                            story_text = f"First productive alert percentile position was unpopulated in {test_q_str}."
                    elif kpi_code == "KPI_11":
                        if val is not None:
                            cmp_str = f" (compared to {b_val} in {base_q_str}, Δ = {d_val:+})" if b_val is not None and isinstance(d_val, (int, float)) else ""
                            story_text = f"A false positive ratio of **{val}%** was recorded in {test_q_str}{cmp_str}, reflecting operational investigator filtering efficiency."
                        else:
                            story_text = f"False positive closure ratio was unpopulated in {test_q_str}."
                    elif kpi_code == "KPI_12":
                        if val is not None:
                            cmp_str = f" (compared to {b_val} in {base_q_str}, Δ = {d_val:+})" if b_val is not None and isinstance(d_val, (int, float)) else ""
                            story_text = f"Achieved a True Positive conversion efficiency rate of **{val}%** in {test_q_str}{cmp_str}."
                        else:
                            story_text = f"True positive conversion efficiency rate was unpopulated in {test_q_str}."
                    elif kpi_code == "KPI_15a":
                        if val is not None:
                            cmp_str = f" (compared to {b_val} in {base_q_str}, Δ = {d_val:+})" if b_val is not None and isinstance(d_val, (int, float)) else ""
                            story_text = f"**{val}% of productive alerts** clustered within the configured Amount threshold proximity window in {test_q_str}{cmp_str}."
                        else:
                            story_text = f"Amount threshold proximity accumulation ratio was unpopulated in {test_q_str}."
                    elif kpi_code == "KPI_15b":
                        if val is not None:
                            cmp_str = f" (compared to {b_val} in {base_q_str}, Δ = {d_val:+})" if b_val is not None and isinstance(d_val, (int, float)) else ""
                            story_text = f"**{val}% of productive alerts** clustered within the configured Frequency threshold proximity window in {test_q_str}{cmp_str}."
                        else:
                            story_text = f"Frequency threshold proximity accumulation ratio was unpopulated in {test_q_str}."
                    elif kpi_code == "KPI_16":
                        if val is not None:
                            cmp_str = f" (compared to {b_val} in {base_q_str}, Δ = {d_val:+})" if b_val is not None and isinstance(d_val, (int, float)) else ""
                            story_text = f"Generated **{val} productive (Level 3 escalated) alerts** in {test_q_str}{cmp_str}."
                        else:
                            story_text = f"Zero productive alerts were generated in {test_q_str}."
                    else:
                        story_text = f"{spec_kpi['description']}"

                    if m_trend:
                        story_text += f" Monthly trajectory: {', '.join(f'{mk}: {mv}' for mk, mv in m_trend.items())}."
                    unit_stories.append(f"    - **{kpi_code} ({spec_kpi['title']}):** {story_text}")

            if unit_stories:
                parts.append("\n".join(unit_stories))

        parts.append("  </domain>\n")


    # 5. Thresholds Domain
    if thresholds:
        parts.append('  <domain name="thresholds">')
        parts.append("    | Metric | Value | Source |")
        parts.append("    |--------|-------|--------|")
        th_labels = [
            ("min_amount_threshold", "Min Amount Threshold"),
            ("min_freq_threshold", "Min Frequency Threshold"),
            ("max_amount_threshold", "Max Amount Threshold"),
        ]
        for k, label in th_labels:
            if k in thresholds:
                parts.append(_format_metric_row(label, thresholds[k], default_src))
        parts.append("  </domain>\n")

    # 6. Flags Domain
    if flags:
        parts.append('  <domain name="flags">')
        parts.append("    | Metric | Value | Source |")
        parts.append("    |--------|-------|--------|")
        for k, v in flags.items():
            label = k.replace("_", " ").title()
            parts.append(_format_metric_row(label, v, default_src))
        parts.append("  </domain>\n")

    # 7. Portfolio KPI Baseline Domain (Complete Multi-Quarter Telemetry)
    if kpi_context:
        test_q_str = str(quarters.get("test") or "Evaluation Quarter")
        base_quarters_list = quarters.get("base_quarters")
        if quarters.get("base"):
            base_q_str = str(quarters["base"])
        elif isinstance(base_quarters_list, list) and len(base_quarters_list) > 0:
            base_q_str = str(base_quarters_list[0])
        else:
            base_q_str = "Baseline"
        parts.append('  <domain name="portfolio_kpi_baseline">')
        parts.append(f"    | Metric | Evaluation ({test_q_str}) | Baseline ({base_q_str}) | Diff (Δ) | Monthly Trend | Source |")

        parts.append("    |---|---|---|---|---|---|")
        kpi_labels = [
            ("kpi1_alert_count", "Alert Count (KPI_1)", "KPI_1"),
            ("kpi2b_alerted_customers", "Alerted Customers Count (KPI_2b)", "KPI_2b"),
            ("kpi2b_productive_alert_rate", "Alerted Customers Count (KPI_2b)", "KPI_2b"),
            ("kpi3_customer_count", "Productive Customers Count (KPI_3)", "KPI_3"),
            ("kpi6_value", "First Productive Alert Percentile Position (KPI_6)", "KPI_6"),
            ("kpi11_value", "False Positive Ratio % (KPI_11)", "KPI_11"),
            ("kpi12_value", "True Positive Ratio % (KPI_12)", "KPI_12"),
            ("kpi15a_value", "Amount Proximity Productive Alert Ratio % (KPI_15a)", "KPI_15a"),
            ("kpi15b_value", "Frequency Proximity Productive Alert Ratio % (KPI_15b)", "KPI_15b"),
            ("kpi16_unique_customers", "Productive Alerts Count (KPI_16)", "KPI_16"),
            ("kpi17_value", "Unique Productivity Metric (KPI_17)", "KPI_17"),
        ]
        rendered_keys = set()
        for key, label, default_sheet in kpi_labels:
            if key in kpi_context and key not in rendered_keys:
                src = kpi_sources.get(key, default_sheet)
                val_test = kpi_context.get(key)
                val_base = kpi_context.get(f"{key}_base") or "—"
                val_diff = kpi_context.get(f"{key}_diff")
                diff_disp = f"{val_diff:+}" if isinstance(val_diff, (int, float)) else (str(val_diff) if val_diff is not None else "—")
                m_trend = kpi_context.get(f"{key}_trend")
                trend_disp = " | ".join(f"{k}: {v}" for k, v in m_trend.items()) if m_trend else "—"
                parts.append(f"    | {label} | {val_test} | {val_base} | {diff_disp} | {trend_disp} | {src} |")
                rendered_keys.add(key)
                if key == "kpi2b_alerted_customers":
                    rendered_keys.add("kpi2b_productive_alert_rate")

        # Structured KPI 17
        if "kpi17_quarterly_metrics" in kpi_context:
            src = kpi_sources.get("kpi17_quarterly_metrics", "KPI_17_quarter")
            for sub_k, sub_v in kpi_context["kpi17_quarterly_metrics"].items():
                label = f"KPI_17 Quarterly {sub_k.replace('_', ' ').title()}"
                parts.append(f"    | {label} | {sub_v} | — | — | — | {src} |")

        # Structured KPI 18
        if "kpi18_quarterly_thresholds" in kpi_context:
            src = kpi_sources.get("kpi18_quarterly_thresholds", "KPI_18_quarter")
            for sub_k, sub_v in kpi_context["kpi18_quarterly_thresholds"].items():
                label = f"KPI_18 Quarterly {sub_k.replace('_', ' ').title()}"
                parts.append(f"    | {label} | {sub_v} | — | — | — | {src} |")

        parts.append("  </domain>\n")





    # 8. Governance & Recommendations Domain
    if rec:
        parts.append('  <domain name="governance_recommendations">')
        parts.append("    | Metric | Value | Source |")
        parts.append("    |--------|-------|--------|")
        parts.append(_format_metric_row("Recommendation", rec, default_src))
        parts.append("  </domain>\n")

    parts.append("</structured_metrics>\n")
    parts.append("</model>\n")
    return "\n".join(parts)


# ── Context assembly ────────────────────────────────────────────────────────

def build_output(
    kri_results: dict[str, list[dict[str, Any]]],
    kpi_data: dict[str, dict[str, Any]],
    kpi_avail: dict[str, list[str]],
    qi: Any,
    output_dir: str | Path,
    country: str,
    bl: str,
    scenarios_file: str | Path | None = None
) -> Path:
    """Assemble and write one single enriched Markdown dossier output file for all triggered models."""
    out = Path(str(output_dir).strip(' "\''))
    out.mkdir(parents=True, exist_ok=True)
    prefix = f"{country.upper()}_{bl.upper()}_{qi.ingestion}"

    scenarios_catalog, scenario_src_name = load_scenarios_catalog(scenarios_file)

    dossier_markdowns = []
    for ad, evidences in sorted(kri_results.items()):
        meta = {}
        for ev in evidences:
            for k, v in ev.pop("_meta", {}).items():
                if k not in meta and v: meta[k] = v

        block = {"alert_definition": ad}
        if meta.get("_source"):
            block["_source"] = meta["_source"]
        for k in ("identity", "thresholds", "flags"):
            if meta.get(k): block[k] = meta[k]

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

        # Generate XML-tagged Markdown Dossier with scenario enrichment
        md_content = serialize_dossier_markdown(block, scenarios_catalog, scenario_src_name or "scenarios.json")
        dossier_markdowns.append(md_content)

    # Write ONLY ONE SINGLE OUTPUT FILE for all models
    combined_dossier_path = out / f"{prefix}_dossiers.md"
    combined_dossier_path.write_text("\n\n".join(dossier_markdowns), encoding="utf-8")
    print(f"  -> [Single Dossier Output] {combined_dossier_path} ({len(dossier_markdowns)} model(s) included)")

    return combined_dossier_path

