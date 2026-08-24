"""Prompt Pipeline package."""
from .prompts import (
    HYPOTHESIS_SYSTEM_PROMPT,
    HYPOTHESIS_USER_TEMPLATE,
    NARRATIVE_SYSTEM_PROMPT,
    NARRATIVE_USER_TEMPLATE,
)
from .pipeline import (
    build_hypothesis_prompt,
    build_narrative_prompt,
    prepare_prompt_bundles,
    extract_models_from_dossier,
)

__all__ = [
    "HYPOTHESIS_SYSTEM_PROMPT",
    "HYPOTHESIS_USER_TEMPLATE",
    "NARRATIVE_SYSTEM_PROMPT",
    "NARRATIVE_USER_TEMPLATE",
    "build_hypothesis_prompt",
    "build_narrative_prompt",
    "prepare_prompt_bundles",
    "extract_models_from_dossier",
]
