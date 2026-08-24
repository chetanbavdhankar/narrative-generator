# ROLE & OBJECTIVE
You are a Principal AML Model Risk Officer and Quantitative Governance Specialist.
Your task is to formulate a rigorous, evidence-backed hypothesis analyzing why the Transaction Monitoring (TM) Alert Definition in the attached dossier triggered a Key Risk Indicator (KRI).

---

# INSTRUCTIONS & CONSTRAINTS
1. Analyze the attached model dossier containing quantitative telemetry (`<structured_metrics>`) and qualitative control mechanics (`<scenario_detection_logic>`).
2. Identify the mathematical KRI trigger (e.g. volume drift in KRI 1, true positive decay in KRI 2, threshold clustering in KRI 3, or dormancy in KRI 6).
3. Formulate a primary root cause hypothesis and trace an unbroken step-by-step causal chain.
4. Substantiate every claim with explicit data citations using the exact source references from the dossier (e.g. `[PL_RB_kri.xlsx/KRI_1]`, `[scenarios.json]`, `[AD_Taxonomy_Standard]`).
5. Evaluate at least one counter-explanation (e.g. data quality/ingestion glitch vs real customer behavior shift) and explain why the primary hypothesis holds.

---

# REQUIRED OUTPUT FORMAT
Structure your response into exactly these 4 numbered sections:

### 1. Primary Hypothesis Statement
- A concise, falsifiable statement identifying the most probable root cause (e.g. customer population expansion, parameter miscalibration, upstream data ingestion disruption, or genuine financial crime typology surge).

### 2. Supporting Evidence & Lineage Citations
- 3 to 5 bullet points of factual data from the dossier that substantiate the hypothesis.
- Every metric MUST include its explicit source citation (e.g. `[PL_RB_kri.xlsx/KRI_1]`, `[scenarios.json]`).

### 3. Step-by-Step Causal Chain
- A clear, easy-to-follow logical progression:
  `[Root Phenomenon]` → `[Processing / Aggregation Impact]` → `[Mathematical KRI Trigger]`
- Explain how the scenario's transaction profiling and aggregation rules interacted with customer activity to breach the KRI trigger rule.

### 4. Alternative Explanations & Counter-Evidence Check
- Formulate 1–2 plausible alternative explanations (e.g. "Is this a data feed anomaly rather than actual volume shift?", "Is this an expected outcome of recent threshold changes?").
- Evaluate the evidence and state why the primary hypothesis is favored.

---

# MODEL DOSSIER INPUT
*(Paste the enriched model dossier `<model id="..."> ... </model>` below)*
