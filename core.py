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
    try:
        ts = pd.to_datetime(s, errors="coerce")
        if pd.notna(ts):
            q = (ts.month - 1) // 3 + 1
            return f"Q{q}_{ts.year}"
    except Exception:
        pass

    return s


def resolve_quarter(q: str) -> QInfo:
    std = format_quarter(q) or q.strip()
    parts = std.split("_")
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
_QCOL_RE = re.compile(r"^Q\d_\d{4}$", re.IGNORECASE)
_RENAMES = {
    "active_ingestion_quarter": "ingestion_quarter",
    "active_test_quarter": "test_quarter",
    "active_base_quarter": "base_quarter",
    "active_benchmark_quarter": "benchmark_quarter",
    "active_benchmark_period": "benchmark_quarter",
    "benchmark_period": "benchmark_quarter",
    "benchmark_date": "benchmark_quarter",
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
    """Extract (country, business_line) from anywhere within the filename.

    Naming convention: ...<COUNTRY>_<BUSINESS_LINE>...xlsx
    Supported business line forms (case-insensitive):
      RB: RB, Retail, Retail_Bank, Retail_Banking, RetailBank, RetailBanking
      WB: WB, Wholesale, Wholesale_Bank, Wholesale_Banking, WholesaleBank, WholesaleBanking

    Examples:
      PL_RB_kri.xlsx                         -> ('PL', 'RB')
      2026_Q1_PL_retail_banking_kpi.xlsx     -> ('PL', 'RB')
      alert_data_RO_wholesale_bank.xlsx      -> ('RO', 'WB')
      FR_retail_2026.xlsx                    -> ('FR', 'RB')
      data_CH_WB.xlsx                        -> ('CH', 'WB')
    """
    if filename.startswith("~$"):
        return None

    stem = Path(filename).stem.strip()
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
    if _QCOL_RE.match(s):
        return f"q_{format_quarter(s)}"
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
        val = val.iloc[0] if len(val) > 0 else None
        if val is None:
            return None
    if pd.isna(val):
        return None
    return val.item() if hasattr(val, "item") else val


def _is_one(val: Any) -> bool:
    """Robust check for boolean / binary trigger flags (1, 1.0, True, '1')."""
    if val is None or pd.isna(val):
        return False
    if isinstance(val, (pd.Series, pd.DataFrame)):
        val = val.iloc[0] if len(val) > 0 else None
        if val is None or pd.isna(val):
            return False
    if hasattr(val, "item"):
        val = val.item()
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
    for sheet, extractor in _KRIS.items():
        if sheet not in tables:
            continue
        df = tables[sheet]
        if sheet not in df.columns:
            continue
        df = df.reset_index(drop=True)

        # Filter 1: Ingestion quarter match (Filter out anything not same as ingestion quarter)
        if "ingestion_quarter" in df.columns:
            df = df[df["ingestion_quarter"] == qi.ingestion].reset_index(drop=True)

        # Triggered flag match (KRI_1 == 1, KRI_2 == 1, etc.)
        triggered_mask = df[sheet].apply(_is_one)
        triggered = df[triggered_mask].reset_index(drop=True)
        print(f"  [KRI] {sheet}: {len(triggered)} triggered ({len(df)} in quarter)")

        for _, row in triggered.iterrows():
            # Filter 2 (for KRI_1, KRI_2, KRI_3): base_quarter must be strictly higher than benchmark_quarter
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

            ad = str(row.get("alert_definition", "?"))
            s_ref = str(row.get("_source_ref") or f"{sheet}")
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
        if c in df.columns:
            return c
        for col in df.columns:
            if str(col).lower() == c.lower():
                return col
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
            s_ref = str(row.get("_source_ref") or f"{sheet}")
            if val is not None:
                data.setdefault(ad, {})[out_key] = val
                data.setdefault(ad, {}).setdefault("_sources", {})[out_key] = s_ref
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
            s_ref = str(row.get("_source_ref") or f"{sheet}")
            ev = {short: _s(row.get(src)) for src, short in cfg["cols"].items()
                  if _s(row.get(src)) is not None}
            if ev:
                data.setdefault(ad, {})[cfg["key"]] = ev
                data.setdefault(ad, {}).setdefault("_sources", {})[cfg["key"]] = s_ref
                avail.setdefault(ad, []).append(sheet)
                n += 1
        print(f"  [KPI] {sheet}: {n} enriched")

    return data, avail


# ── Alert Definition Taxonomy Standards (ABCD.123.SS.RR.XY) ─────────────────

SEGMENT_MAPPING: dict[str, dict[str, str]] = {
    "01": {"ctc": "FI", "name": "Financial Institution", "lob": "Wholesale (WB)"},
    "02": {"ctc": "LARGE", "name": "Large Corporation", "lob": "Wholesale (WB)"},
    "03": {"ctc": "SMALL / OTHER", "name": "Small Corporation / Other Wholesale Banking Entity", "lob": "Wholesale (WB)"},
    "04": {"ctc": "MIDCORP", "name": "Medium Corporation", "lob": "Retail (RB)"},
    "05": {"ctc": "SME", "name": "Small-Medium Entity", "lob": "Retail (RB)"},
    "06": {"ctc": "PRIVATE", "name": "Private Individual", "lob": "Retail (RB)"},
    "07": {"ctc": "PRIBA", "name": "Private Banking", "lob": "Retail (RB)"},
    "08": {"ctc": "FI, LARGE, WBCORP, SMALL, OTHER, MEDIUM", "name": "Wholesale Banking Customer (Combined 01, 02, 03, 60)", "lob": "Wholesale (WB)"},
    "09": {"ctc": "MIDCORP, SME, CI (XL-XS), NCI (XL-XS)", "name": "Retail - Entity (Combined 04, 05, 13-22)", "lob": "Retail (RB)"},
    "10": {"ctc": "PRIVATE, PRIBA, IND (LT-VHT)", "name": "Retail - Individual (Combined 06, 07, 24-27)", "lob": "Retail (RB)"},
    "11": {"ctc": "All Retail Entities & Individuals", "name": "Retail Banking Customer (Combined 04-07, 13-22, 24-27)", "lob": "Retail (RB)"},
    "12": {"ctc": "All WB & RB Entities & Individuals", "name": "Universal Banking Customer (Combined 01-07, 13-22, 24-27, 60)", "lob": "Universal (UB = WB + RB)"},
    "13": {"ctc": "CI-XL", "name": "Cash Intensive Entity - Extra Large", "lob": "Retail (RB)"},
    "14": {"ctc": "CI-L", "name": "Cash Intensive Entity - Large", "lob": "Retail (RB)"},
    "15": {"ctc": "CI-M", "name": "Cash Intensive Entity - Medium", "lob": "Retail (RB)"},
    "16": {"ctc": "CI-S", "name": "Cash Intensive Entity - Small", "lob": "Retail (RB)"},
    "17": {"ctc": "CI-XS", "name": "Cash Intensive Entity - Extra Small", "lob": "Retail (RB)"},
    "18": {"ctc": "NCI-XL", "name": "Non-Cash Intensive Entity - Extra Large", "lob": "Retail (RB)"},
    "19": {"ctc": "NCI-L", "name": "Non-Cash Intensive Entity - Large", "lob": "Retail (RB)"},
    "20": {"ctc": "NCI-M", "name": "Non-Cash Intensive Entity - Medium", "lob": "Retail (RB)"},
    "21": {"ctc": "NCI-S", "name": "Non-Cash Intensive Entity - Small", "lob": "Retail (RB)"},
    "22": {"ctc": "NCI-XS", "name": "Non-Cash Intensive Entity - Extra Small", "lob": "Retail (RB)"},
    "23": {"ctc": "CI (XL-XS), NCI (XL-XS)", "name": "Cash and Non-Cash Intensive Entities (Combined 13-22)", "lob": "Retail (RB)"},
    "24": {"ctc": "INDLT", "name": "Individual - Low Turnover", "lob": "Retail (RB)"},
    "25": {"ctc": "INDMT", "name": "Individual - Medium Turnover", "lob": "Retail (RB)"},
    "26": {"ctc": "INDHT", "name": "Individual - High Turnover", "lob": "Retail (RB)"},
    "27": {"ctc": "INDVHT", "name": "Individual - Very High Turnover", "lob": "Retail (RB)"},
    "60": {"ctc": "MEDIUM", "name": "Medium Corporation", "lob": "Wholesale (WB)"},
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

    return {
        "scenario_code": scenario,
        "segment_code": seg_code,
        "segment_name": seg_info.get("name", f"Segment {seg_code}"),
        "customer_type_code": seg_info.get("ctc", "—"),
        "line_of_business": seg_info.get("lob", "—"),
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
        "description": "Measures unusual shifts in total alert volume vs base quarter. Dual-component: (1) 1-3 stddev delta + >=50 alerts (Retail) / >=30 (Wholesale) over >=2 consecutive quarters; (2) >=3 stddev delta + >=50 (Retail) / >=30 (Wholesale) in single quarter.",
        "diagnostic_focus": "Customer behaviour shifts, population drift, data quality/ingestion glitches, threshold changes, or emerging typology waves.",
    },
    "KRI_2": {
        "title": "Deviation in True Positive Volume",
        "description": "Measures downward reduction in productive alerts (True Positives) vs base quarter. Dual-component: (1) Downward 1-3 stddev + >=15 decrease (Retail) / >=10 (Wholesale) over >=2 consecutive quarters; (2) Downward >=3 stddev + >=15 (Retail) / >=10 (Wholesale) in single quarter.",
        "diagnostic_focus": "Reduced detection capability, control degradation, or decaying threshold calibration.",
    },
    "KRI_3": {
        "title": "Accumulation of Escalations in Proximity",
        "description": "Measures concentration of productive True Positive alerts near threshold boundaries. Dual-component: (1) 10-50 percentage points proximity deviation + 5-10 TPs over >=2 consecutive quarters; (2) >=50 percentage points deviation + >=10 TPs in single quarter.",
        "diagnostic_focus": "Threshold boundary sensitivity; indicates whether minor threshold adjustments will capture or shed major productive volume.",
    },
    "KRI_6": {
        "title": "Dormant Alert Definition Identification",
        "description": "Binary check identifying definitions active for >=3 consecutive quarters that subsequently generate zero alerts across 3 consecutive evaluation quarters.",
        "diagnostic_focus": "Control obsolescence, overly restrictive thresholds, data pipeline failures, or rare typology safety nets.",
    },
}


# ── Markdown Dossier Serialization ─────────────────────────────────────────

def _escape_md(val: Any) -> str:
    if val is None:
        return "—"
    s = str(val).strip()
    return s.replace("|", "\\|").replace("\n", " ")


def _format_metric_row(metric: str, val: Any, source: str) -> str:
    return f"    | {_escape_md(metric)} | {_escape_md(val)} | {_escape_md(source)} |"


def serialize_dossier_markdown(ad_block: dict[str, Any]) -> str:
    """Serialize a single alert definition data block into an LLM-optimized XML-tagged Markdown dossier."""
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
        parts.append(_format_metric_row("Target Segment", f"{decoded['segment_name']} (CTC: {decoded['customer_type_code']}) [Code: {decoded['segment_code']}]", "AD_Taxonomy_Standard"))
        parts.append(_format_metric_row("Line of Business", decoded["line_of_business"], "AD_Taxonomy_Standard"))
        parts.append(_format_metric_row("Customer Risk Tier", f"{decoded['risk_name']} [Code: {decoded['risk_code']}]", "AD_Taxonomy_Standard"))
        parts.append(_format_metric_row("Monitoring Evaluation Window", f"{decoded['period_alias']} ({decoded['period_description']}) [Code: {decoded['period_code']}]", "AD_Taxonomy_Standard"))

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

    # 2. Quarterly Context Domain
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

    # 3. Thresholds Domain
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

    # 4. Flags Domain
    if flags:
        parts.append('  <domain name="flags">')
        parts.append("    | Metric | Value | Source |")
        parts.append("    |--------|-------|--------|")
        for k, v in flags.items():
            label = k.replace("_", " ").title()
            parts.append(_format_metric_row(label, v, default_src))
        parts.append("  </domain>\n")

    # 5. Triggered KRIs Domain (Annotated with Governance Definitions)
    if triggered_kris:
        parts.append('  <domain name="triggered_kris">')
        parts.append("    | Metric | Value | Source |")
        parts.append("    |--------|-------|--------|")
        for ev in triggered_kris:
            kri_key = ev.get("kri", "KRI")
            spec = KRI_SPECIFICATIONS.get(kri_key, {})
            kri_title = spec.get("title", kri_key)
            ev_src = ev.get("source", default_src)

            prefix = f"{kri_key}: {kri_title}"
            if "direction" in ev:
                prefix += f" [{ev['direction'].upper()}]"
            elif "sub_trigger" in ev:
                prefix += f" [{ev['sub_trigger'].upper()}]"

            # Indicator Definition & Evaluation Logic Rows
            if spec.get("description"):
                parts.append(_format_metric_row(f"{kri_key} Evaluation Rule", spec["description"], "TM_Governance_Policy"))
            if spec.get("diagnostic_focus"):
                parts.append(_format_metric_row(f"{kri_key} Diagnostic Focus", spec["diagnostic_focus"], "TM_Governance_Policy"))

            for field, label in [
                ("test_quarter_count", f"{prefix} Test Quarter Count"),
                ("base_quarter_count", f"{prefix} Base Quarter Count"),
                ("difference", f"{prefix} Difference (Test - Base)"),
                ("full_period_avg_count", f"{prefix} Full Period Avg Count"),
                ("full_period_stddev_count", f"{prefix} Full Period Stddev"),
                ("three_sigma_exceeded", f"{prefix} 3-Sigma Exceeded (Component 2)"),
                ("consecutive_trigger", f"{prefix} Consecutive Trigger (Component 1)"),
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
        parts.append("  </domain>\n")

    # 6. KPI Metrics Domain
    if kpi_context:
        parts.append('  <domain name="kpi_metrics">')
        parts.append("    | Metric | Value | Source |")
        parts.append("    |--------|-------|--------|")
        kpi_labels = [
            ("kpi1_alert_count", "Alert Count (KPI_1)", "KPI_1"),
            ("kpi2b_productive_alert_rate", "Productive Alert Rate % (KPI_2b)", "KPI_2b"),
            ("kpi3_customer_count", "Customer Count (KPI_3)", "KPI_3"),
            ("kpi6_value", "KPI 6 Metric Value", "KPI_6"),
            ("kpi11_value", "KPI 11 Metric Value", "KPI_11"),
            ("kpi12_value", "KPI 12 Metric Value", "KPI_12"),
            ("kpi15a_value", "KPI 15a Metric Value", "KPI_15a"),
            ("kpi15b_value", "KPI 15b Metric Value", "KPI_15b"),
            ("kpi16_unique_customers", "Unique Customers (KPI_16)", "KPI_16"),
            ("kpi17_value", "KPI 17 Metric Value", "KPI_17"),
        ]
        for key, label, default_sheet in kpi_labels:
            if key in kpi_context:
                src = kpi_sources.get(key, default_sheet)
                parts.append(_format_metric_row(label, kpi_context[key], src))

        # Structured KPI 17
        if "kpi17_quarterly_metrics" in kpi_context:
            src = kpi_sources.get("kpi17_quarterly_metrics", "KPI_17_quarter")
            for sub_k, sub_v in kpi_context["kpi17_quarterly_metrics"].items():
                label = f"KPI_17 Quarterly {sub_k.replace('_', ' ').title()}"
                parts.append(_format_metric_row(label, sub_v, src))

        # Structured KPI 18
        if "kpi18_quarterly_thresholds" in kpi_context:
            src = kpi_sources.get("kpi18_quarterly_thresholds", "KPI_18_quarter")
            for sub_k, sub_v in kpi_context["kpi18_quarterly_thresholds"].items():
                label = f"KPI_18 Quarterly {sub_k.replace('_', ' ').title()}"
                parts.append(_format_metric_row(label, sub_v, src))
        parts.append("  </domain>\n")

    # 7. Governance & Recommendations Domain
    if rec:
        parts.append('  <domain name="governance_recommendations">')
        parts.append("    | Metric | Value | Source |")
        parts.append("    |--------|-------|--------|")
        parts.append(_format_metric_row("Recommendation", rec, default_src))
        parts.append("  </domain>\n")

    parts.append("</structured_metrics>\n")
    parts.append("</model>\n")
    return "\n".join(parts)


def serialize_relevance_matrix_markdown(matrix: list[dict[str, Any]], country: str, bl: str, quarter: str) -> str:
    """Serialize the alert definition trigger relevance matrix to a Markdown table."""
    lines = [
        f"# Transaction Monitoring Relevance Matrix — {country.upper()}/{bl.upper()} ({quarter})\n",
        "| Alert Definition | Triggered KRIs | Trigger Details | Available KPIs |",
        "|---|---|---|---|",
    ]
    for row in matrix:
        ad = _escape_md(row.get("alert_definition", ""))
        kris = _escape_md(", ".join(row.get("triggered_kris", [])))
        subs = []
        for k, vals in row.get("kri_sub_triggers", {}).items():
            subs.append(f"{k}: {', '.join(vals)}")
        subs_str = _escape_md("; ".join(subs) if subs else "Standard")
        kpis = _escape_md(", ".join(row.get("available_kpis", [])) or "None")
        lines.append(f"| {ad} | {kris} | {subs_str} | {kpis} |")
    return "\n".join(lines) + "\n"


# ── Context assembly ────────────────────────────────────────────────────────

def build_output(kri_results, kpi_data, kpi_avail, qi, output_dir, country, bl):
    out = Path(str(output_dir).strip(' "\''))
    out.mkdir(parents=True, exist_ok=True)
    per_model_dir = out / "per_model"
    per_model_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{country.upper()}_{bl.upper()}_{qi.ingestion}"

    context, matrix = [], []
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

        # Generate individual XML-tagged Markdown Dossier
        md_content = serialize_dossier_markdown(block)
        dossier_markdowns.append(md_content)

        safe_name = ad.lower().replace(" ", "_").replace("/", "_").replace("\\", "_")
        single_dossier_path = per_model_dir / f"{safe_name}_dossier.md"
        single_dossier_path.write_text(md_content, encoding="utf-8")

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

    # Write Combined Dossiers Markdown
    combined_dossier_path = out / f"{prefix}_dossiers.md"
    combined_dossier_path.write_text("\n\n".join(dossier_markdowns), encoding="utf-8")
    print(f"  -> [Dossiers Markdown] {combined_dossier_path}")
    print(f"  -> [Per-Model Dossiers] {len(context)} files in {per_model_dir}")

    # Write Markdown Relevance Matrix Table
    matrix_md_path = out / f"{prefix}_relevance_matrix.md"
    matrix_md_path.write_text(serialize_relevance_matrix_markdown(matrix, country, bl, qi.ingestion), encoding="utf-8")
    print(f"  -> [Relevance Matrix MD] {matrix_md_path}")

    # Backward compatibility: Write JSON payloads
    for name, data in [("quantitative_context", context), ("relevance_matrix", matrix)]:
        p = out / f"{prefix}_{name}.json"
        p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        print(f"  -> [JSON Payload] {p}")

    print(f"[Output] Generated dossiers for {len(context)} alert definition(s)")

