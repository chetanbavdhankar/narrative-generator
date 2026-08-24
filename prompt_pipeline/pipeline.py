"""Prompt Pipeline Orchestrator — Automates 2-Step Hypothesis and Narrative Prompt Generation."""
from __future__ import annotations

import argparse, json, re
from pathlib import Path
from typing import Any

from .prompts import (
    HYPOTHESIS_SYSTEM_PROMPT,
    HYPOTHESIS_USER_TEMPLATE,
    NARRATIVE_SYSTEM_PROMPT,
    NARRATIVE_USER_TEMPLATE,
)


def extract_models_from_dossier(content: str) -> list[tuple[str, str]]:
    """Extract individual (model_id, model_block_text) tuples from a dossier file."""
    pattern = re.compile(r'<model\s+id="([^"]+)".*?</model>', re.DOTALL | re.IGNORECASE)
    matches = [(m.group(1), m.group(0).strip()) for m in pattern.finditer(content)]
    if not matches and content.strip():
        # Fallback if whole file is a single model
        return [("single_model", content.strip())]
    return matches


def build_hypothesis_prompt(dossier_text: str) -> dict[str, str]:
    """Generate Step 1 (Hypothesis) prompt pair."""
    return {
        "system": HYPOTHESIS_SYSTEM_PROMPT.strip(),
        "user": HYPOTHESIS_USER_TEMPLATE.format(dossier_content=dossier_text.strip()).strip(),
    }


def build_narrative_prompt(dossier_text: str, hypothesis_text: str) -> dict[str, str]:
    """Generate Step 2 (Narrative) prompt pair given dossier and generated hypothesis."""
    return {
        "system": NARRATIVE_SYSTEM_PROMPT.strip(),
        "user": NARRATIVE_USER_TEMPLATE.format(
            dossier_content=dossier_text.strip(),
            hypothesis_content=hypothesis_text.strip(),
        ).strip(),
    }


def prepare_prompt_bundles(
    dossier_path: str | Path,
    output_dir: str | Path | None = None
) -> dict[str, Any]:
    """Prepare prompt bundles for all models found in a dossier file or directory."""
    d_path = Path(dossier_path)
    if not d_path.exists():
        raise FileNotFoundError(f"Dossier path not found: {d_path}")

    files = [d_path] if d_path.is_file() else sorted(d_path.glob("*.md"))
    bundles = {}

    for f in files:
        text = f.read_text(encoding="utf-8")
        models = extract_models_from_dossier(text)
        for model_id, model_body in models:
            hypo_prompt = build_hypothesis_prompt(model_body)
            # Pre-build narrative prompt skeleton (waiting for hypothesis fill)
            narr_prompt_template = build_narrative_prompt(model_body, "{HYPOTHESIS_OUTPUT_PLACEHOLDER}")
            
            bundle = {
                "model_id": model_id,
                "source_file": f.name,
                "step_1_hypothesis_prompt": hypo_prompt,
                "step_2_narrative_prompt_template": narr_prompt_template,
            }
            bundles[model_id] = bundle

            if output_dir:
                out_p = Path(output_dir) / f"{model_id}_prompts.json"
                out_p.parent.mkdir(parents=True, exist_ok=True)
                out_p.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")

    return bundles


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Prepare 2-step Hypothesis & Narrative prompts from dossiers.")
    ap.add_argument("--dossier-input", required=True, help="Path to dossier .md file or directory")
    ap.add_argument("--output-dir", default=None, help="Directory to save generated prompt bundle JSONs")
    args = ap.parse_args()

    results = prepare_prompt_bundles(args.dossier_input, args.output_dir)
    print(f"[Success] Generated 2-step prompt bundles for {len(results)} model(s).")
