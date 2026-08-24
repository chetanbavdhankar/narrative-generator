# 2-Step LLM Governance Narrative Generation Pipeline

A structured reasoning framework designed to convert enriched Transaction Monitoring (TM) Model Dossiers into audit-grade root cause narratives and deterministic action decisions.

---

## 1. Architecture Overview

To eliminate superficial narrative generation and hallucinations, the governance reasoning workflow is split into two distinct stages:

```text
┌─────────────────────────────────────────────────────────┐
│              Enriched Model Dossier                     │
│  • <structured_metrics> (Quantitative Telemetry)        │
│  • <scenario_detection_logic> (Qualitative Mechanics)   │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│ STEP 1: Hypothesis & Causal Chain Generation            │
│  1. Primary Hypothesis Statement                        │
│  2. Evidence Points & Data Lineage Citations            │
│  3. Step-by-Step Causal Chain Formulation               │
│  4. Alternative Explanations & Counter-Evidence Check   │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│ STEP 2: Executive Root Cause Narrative (<= 400 words)   │
│  1. Observation (Factual telemetry & threshold context) │
│  2. Analysis (Root cause diagnosis & causal mechanics)  │
│  3. Conclusion & Governance Action:                     │
│     [ACTION: NO ACTION / RECALIBRATE / RE-BAND / DECOM] │
└─────────────────────────────────────────────────────────┘
```

---

## 2. Directory Structure

```text
prompt_pipeline/
├── __init__.py       # Package exports
├── prompts.py        # System and user prompt templates for Step 1 & Step 2
├── pipeline.py       # Prompt generation and batch preparation engine
└── README.md         # Architecture and usage guide
```

---

## 3. Prompt Specifications

### Step 1: Hypothesis Generation (`prompts.HYPOTHESIS_SYSTEM_PROMPT`)
- **Role**: Principal AML Model Risk Officer.
- **Output Sections**:
  1. **Primary Hypothesis Statement**: Concisely identifies the root cause (e.g. population drift, threshold miscalibration, ingestion delay).
  2. **Evidence Points & Citations**: 3–5 substantiating facts with brackets citations (`[Source: PL_RB_kri.xlsx/KRI_1]`).
  3. **Step-by-Step Causal Chain**: `[Root Cause] -> [Mechanism Impact] -> [Mathematical KRI Trigger]`.
  4. **Alternative Explanations**: Assesses competing possibilities (e.g. data glitch vs real crime wave) and states why primary hypothesis holds.

### Step 2: Executive Narrative (`prompts.NARRATIVE_SYSTEM_PROMPT`)
- **Role**: Senior AML Model Governance Architect.
- **Constraints**:
  - **Length**: Strict $\le 400$ words total.
  - **Citations**: Explicit bracket citations on every factual number/threshold (`[PL_RB_kri.xlsx/KRI_1]`).
  - **Action**: One deterministic action from standard taxonomy:
    - `[ACTION: NO ACTION REQUIRED]`
    - `[ACTION: RECALIBRATE / TIGHTEN THRESHOLD]`
    - `[ACTION: RE-BAND / ADJUST PROXIMITY BOUNDARY]`
    - `[ACTION: DECOMMISSION / CONSOLIDATE]`
- **Output Sections**:
  1. **Observation**
  2. **Analysis**
  3. **Conclusion & Action Recommendation**

---

## 4. Usage

### CLI: Pre-generate Prompt Bundles for All Models
```bash
python -m prompt_pipeline.pipeline \
  --dossier-input output/PL_RB_Q1_2026_dossiers_enriched.md \
  --output-dir output/prompts/
```

### Python API
```python
from prompt_pipeline import build_hypothesis_prompt, build_narrative_prompt

dossier_text = open("output/per_model/model_1_dossier.md", encoding="utf-8").read()

# Step 1: Build prompt for LLM to produce hypothesis
hypo_prompt = build_hypothesis_prompt(dossier_text)
# hypo_response = llm_client.generate(hypo_prompt["system"], hypo_prompt["user"])

# Step 2: Build prompt for LLM to produce final narrative
narr_prompt = build_narrative_prompt(dossier_text, hypo_response)
# final_narrative = llm_client.generate(narr_prompt["system"], narr_prompt["user"])
```
