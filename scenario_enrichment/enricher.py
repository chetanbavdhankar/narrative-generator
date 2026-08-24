"""Scenario Qualitative Context Enricher — Compact, robust dossier injector."""
from __future__ import annotations

import argparse, json, re, sys
from pathlib import Path
from typing import Any

_CODE_RE = re.compile(r"([A-Za-z]{3,5}[\.\-_ ]\d{3})", re.IGNORECASE)


def extract_code(ad: str) -> str | None:
    """Extract standard 8-char control code (e.g. 'CHQD.058') from an alert definition."""
    if not ad: return None
    s = str(ad).strip()
    if len(s) >= 8 and s[:4].isalpha() and s[4] in (".", "_", "-") and s[5:8].isdigit():
        return f"{s[:4].upper()}.{s[5:8]}"
    m = _CODE_RE.search(s)
    return m.group(1).upper().replace("_", ".").replace("-", ".") if m else None


def load_scenarios(filepath: str | Path) -> dict[str, Any]:
    """Load and normalize scenario catalog from root or nested 'models'/'scenarios' key."""
    raw = json.loads(Path(filepath).read_text(encoding="utf-8"))
    catalog = raw.get("models") or raw.get("scenarios") or raw.get("controls") or (raw if isinstance(raw, dict) else {})
    norm = {}
    for k, v in catalog.items():
        if isinstance(v, dict):
            k_std = extract_code(str(k)) or str(k).strip().upper()
            norm[k_std] = v
            norm[str(k).strip().upper()] = v
    return norm


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
    if not ad: return None
    m = _AD_TAXONOMY_RE.search(str(ad).strip())
    if not m: return None
    scenario, seg_code, risk_code, period_code = m.group(1).upper(), m.group(2), m.group(3), m.group(4).upper()
    seg_info = SEGMENT_MAPPING.get(seg_code, {})
    risk_info = RISK_MAPPING.get(risk_code, f"Risk Code {risk_code}")
    period_info = PERIOD_MAPPING.get(period_code, {"alias": period_code, "description": period_code})
    return {
        "scenario_code": scenario, "segment_code": seg_code, "segment_name": seg_info.get("name", f"Segment {seg_code}"),
        "customer_type_code": seg_info.get("ctc", "—"), "line_of_business": seg_info.get("lob", "—"),
        "risk_code": risk_code, "risk_name": risk_info,
        "period_code": period_code, "period_alias": period_info.get("alias", period_code), "period_description": period_info.get("description", period_code),
    }


def format_functional_block(code: str, info: dict[str, Any], source: str, ad_id: str | None = None) -> str:
    """Format scenario/control qualitative detection logic and alert generation rules."""
    esc = lambda v: str(v or "—").strip().replace("|", "\\|").replace("\n", " ")
    lines = [
        "<scenario_detection_logic>",
        f"## Parent Scenario & Control Specification: {code}",
        "",
        "> **Context for LLM:** This section defines the parent scenario detection mechanics governing how individual transaction monitoring alerts are triggered. While individual Alert Definitions apply specific segment/risk thresholds, the rules below define the core financial crime typology, focal entity scope, transaction aggregation, and alert generation criteria.",
        "",
        "| Scenario Dimension | Specification | Source |",
        "|---|---|---|",
        f"| Typology Description | {esc(info.get('Typology'))} | {source} |",
        f"| Financial Crime Risk Type | {esc(info.get('Risk Type'))} | {source} |",
        f"| Focal Entity Level | {esc(info.get('Focal Entity'))} | {source} |",
        f"| Alert Generation Policy | {esc(info.get('Alert Generation Criteria'))} | {source} |",
    ]

    decoded = decode_alert_definition(ad_id) if ad_id else None
    if decoded:
        lines.append(f"| Configured Segment Scope | {esc(decoded['segment_name'])} (CTC: {decoded['customer_type_code']}) [{decoded['line_of_business']}] [Code: {decoded['segment_code']}] | AD_Taxonomy_Standard |")
        lines.append(f"| Configured Customer Risk | {esc(decoded['risk_name'])} [Code: {decoded['risk_code']}] | AD_Taxonomy_Standard |")
        lines.append(f"| Configured Monitoring Window | {esc(decoded['period_alias'])} - {esc(decoded['period_description'])} [Code: {decoded['period_code']}] | AD_Taxonomy_Standard |")
    lines.append("")

    if info.get("Conditions"):
        lines.extend([
            "### 1. Target Population & Applicability Conditions",
            "Defines customer segments, entity types, and classification filters required for this control to evaluate activity:",
            info["Conditions"].strip(),
            ""
        ])

    if info.get("How to detect"):
        lines.extend([
            "### 2. Transaction Profiling & Aggregation Logic",
            "Defines how the monitoring engine profiles customer activity and aggregates transactional volume/value:",
            info["How to detect"].strip(),
            ""
        ])

    if info.get("FCRM will generate an alert if"):
        lines.extend([
            "### 3. Single Alert Trigger Criteria",
            "Defines the exact conditional rule that evaluates aggregated metrics to fire a single transaction monitoring alert:",
            info["FCRM will generate an alert if"].strip(),
            ""
        ])

    if info.get("FCRM Scenario Logic"):
        lines.extend([
            "### 4. Technical Scenario Logic",
            info["FCRM Scenario Logic"].strip(),
            ""
        ])

    profiles = info.get("Solution Definition Profiles", [])
    if profiles:
        lines.append("### 5. In-Scope Transaction Profiles")
        for p in profiles:
            p_name = p.get("profile", "—")
            tc = ", ".join(p.get("transaction_code", [])) or "—"
            dc = ", ".join(p.get("debit_credit", [])) or "—"
            lines.append(f"- **Profile `{p_name}`**: Transaction Codes: `[{tc}]` | Flow Direction: `[{dc}]`")
        lines.append("")

    lines.append("</scenario_detection_logic>")
    return "\n".join(lines)


def enrich(dossier_content: str, catalog: dict[str, Any], source_name: str) -> tuple[str, int]:
    """Inject scenario detection logic into all matching <model> blocks."""
    count = 0
    def _inject(m: re.Match) -> str:
        nonlocal count
        block, ad_id = m.group(0), m.group(1)
        if "<scenario_detection_logic>" in block or "<functional_requirements>" in block:
            return block
        code = extract_code(ad_id)
        info = catalog.get(code) or catalog.get(ad_id.strip().upper())
        if not info: return block
        count += 1
        fn_md = format_functional_block(code or ad_id, info, source_name, ad_id=ad_id)
        idx = block.rfind("</model>")
        return block[:idx] + f"{fn_md}\n\n" + block[idx:] if idx != -1 else f"{block}\n\n{fn_md}"

    return re.sub(r'<model\s+id="([^"]+)".*?</model>', _inject, dossier_content, flags=re.DOTALL | re.IGNORECASE), count


def run(dossier_in: str | Path, scenarios_in: str | Path, target_out: str | Path | None = None) -> int:
    """CLI engine: process single file or directory."""
    s_path = Path(scenarios_in)
    catalog = load_scenarios(s_path)
    src_name = s_path.name
    in_p = Path(dossier_in)
    if not in_p.exists(): raise FileNotFoundError(f"Input not found: {in_p}")

    total = 0
    if in_p.is_file():
        text, n = enrich(in_p.read_text(encoding="utf-8"), catalog, src_name)
        out_p = Path(target_out) if target_out else in_p
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(text, encoding="utf-8")
        print(f"  [Enriched File] {in_p} -> {out_p} ({n} model(s) matched)")
        total = n
    elif in_p.is_dir():
        out_dir = Path(target_out) if target_out else in_p
        out_dir.mkdir(parents=True, exist_ok=True)
        for f in in_p.glob("*.md"):
            text, n = enrich(f.read_text(encoding="utf-8"), catalog, src_name)
            (out_dir / f.name).write_text(text, encoding="utf-8")
            total += n
        print(f"  [Enriched Directory] {out_dir} ({total} total matches)")
    return total


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Enrich dossiers with qualitative scenario logic.")
    ap.add_argument("--scenarios-file", required=True, help="Path to scenarios JSON dictionary")
    ap.add_argument("--dossier-input", required=True, help="Path to dossier .md file or per_model/ directory")
    ap.add_argument("--output-target", default=None, help="Optional output target path")
    args = ap.parse_args()
    n = run(args.dossier_input, args.scenarios_file, args.output_target)
    print(f"[Done] Enriched {n} model(s).")
