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


def format_functional_block(code: str, info: dict[str, Any], source: str) -> str:
    """Format qualitative functional logic consistent with dossier 3-column tables & prose standards."""
    esc = lambda v: str(v or "—").strip().replace("|", "\\|").replace("\n", " ")
    lines = [
        "<functional_requirements>",
        f"## Scenario / Control Definition: {code}\n",
        "| Attribute | Details | Source |",
        "|---|---|---|",
        f"| Typology | {esc(info.get('Typology'))} | {source} |",
        f"| Risk Type | {esc(info.get('Risk Type'))} | {source} |",
        f"| Focal Entity | {esc(info.get('Focal Entity'))} | {source} |",
        f"| Generation Criteria | {esc(info.get('Alert Generation Criteria'))} | {source} |\n",
    ]
    for key, heading in [("Conditions", "Applicable Conditions"), ("How to detect", "Detection Logic"),
                         ("FCRM will generate an alert if", "Alert Trigger Criteria"), ("FCRM Scenario Logic", "Scenario Logic")]:
        if info.get(key):
            lines.extend([f"### {heading}", str(info[key]).strip(), ""])
    profiles = info.get("Solution Definition Profiles", [])
    if profiles:
        lines.append("### Solution Definition Profiles")
        for p in profiles:
            p_name = p.get("profile", "—")
            tc = ", ".join(p.get("transaction_code", [])) or "—"
            dc = ", ".join(p.get("debit_credit", [])) or "—"
            lines.append(f"- **Profile `{p_name}`**: Transaction Codes: `[{tc}]` | Debit/Credit: `[{dc}]`")
        lines.append("")
    lines.append("</functional_requirements>")
    return "\n".join(lines)


def enrich(dossier_content: str, catalog: dict[str, Any], source_name: str) -> tuple[str, int]:
    """Inject functional requirements into all matching <model> blocks."""
    count = 0
    def _inject(m: re.Match) -> str:
        nonlocal count
        block, ad_id = m.group(0), m.group(1)
        if "<functional_requirements>" in block: return block
        code = extract_code(ad_id)
        info = catalog.get(code) or catalog.get(ad_id.strip().upper())
        if not info: return block
        count += 1
        fn_md = format_functional_block(code or ad_id, info, source_name)
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
