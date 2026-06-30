# Algorithmic Transparency Record — NoteGuard

> **Illustrative** record following the UK government
> [Algorithmic Transparency Recording Standard (ATRS)](https://www.gov.uk/government/collections/algorithmic-transparency-recording-standard-hub),
> modelled on the [NHS.UK Reviews Automoderation Tool record](https://www.gov.uk/algorithmic-transparency-records/nhs-england-nhs-dot-uk-reviews-automoderation-tool).
> NoteGuard is a hackathon **prototype** evaluated on synthetic data — this is not an official
> published ATRS entry, but is structured so it could become one.

---

## Tier 1 — Summary

- **Name:** NoteGuard — NHS clinical-note de-identification and discharge-summary agent
- **Description:** Detects and removes patient/clinician PII from free-text NHS clinical notes *inside* a Trust before any LLM sees them. Passes de-identified text to a LangGraph ReAct agent (Gemini 2.5 Flash) that drafts a compact eDischarge summary grounded in public NICE/NHS guidance (Tavily). Combines pure-Python rule recognisers with a Presidio/spaCy NER layer (`en_core_web_md`, shipped in the deployed image; graceful no-op fallback). No model is trained.
- **Website / repository:** https://github.com/chaeyoonyunakim/noteguard-agent
- **Contact:** via GitHub issues (maintainer **@chaeyoonyunakim**)

---

## Tier 2

### 1. Owner and responsibility

- **1.1 Organisation:** {Tech: Europe} London AI Hackathon — individual project.
- **1.2 Team:** Chaeyoon Kim (sole contributor for this prototype).
- **1.3 Senior responsible owner:** None — prototype, not in service. An SRO would be required before deployment.
- **1.4 External supplier involvement:** No commercial supplier. Built on open-source components (LangGraph, Google Gemini API, Tavily Search API, Presidio + spaCy `en_core_web_md`).

### 2. Description and rationale

- **2.1 Detailed description:** A clinical note is passed through `deidentify_in` (rule recognisers + vault match + Presidio/spaCy NER), which raises if any known identifier survives (`assert_clean()`). The clean text reaches the LangGraph ReAct agent; Tavily retrieves public NICE/NHS guidance. The agent drafts a three-element compact discharge card (narrative, follow-up, grounded) and never names the patient — there is no title line and the patient is referred to only as "the patient". `reidentify_out` restores other surrogates (e.g. clinician names) for the clinician; the model never sees the real name. `compute_trust` audits the de-identified text for residual PII (`scan_pii`, vault-independent) and checks surrogate reversibility.
- **2.2 Scope:** Free-text English NHS clinical notes. Evaluated on the `NHSEDataScience/synthetic_clinical_notes` dataset only. Not evaluated on real Trust data, other languages, or scanned documents.
- **2.3 Benefit:** Enables clinicians to draft eDischarge summaries from de-identified notes with a *measured* re-identification risk rather than an unverified assurance; grounds the summary in public clinical guidance.
- **2.4 Previous process:** Manual de-identification by an analyst, or free-text notes not shared at all because re-identification risk could not be quantified.
- **2.5 Alternatives considered:** Presidio alone (misses NHS-specific formats); a clinical transformer (`obi/deid_roberta_i2b2` — US-trained, weaker on UK names); sending raw notes to the LLM (unacceptable PHI risk). Rejected in favour of the rules-first + LLM-second pipeline.

### 3. Decision-making process

- **3.1 Process integration:** Sits at the Trust egress boundary and inside the clinician workflow. The clinician **reviews and signs off** the draft before it becomes a medical record.
- **3.2 Information provided to reviewers:** The clinician sees the re-identified summary, the trust panel (de-identification PASS/FAIL, identifiers replaced, residual PII the model saw, reversibility), and the de-identified excerpt showing what the AI saw.
- **3.3 Frequency and scale:** Prototype, per-note on demand. No batch deployment.
- **3.4 Human decisions and review:** The clinician makes the **final** call on every summary. The system explicitly labels the output as AI-drafted.
- **3.5 Required training:** Clinicians need training on the tool's limitations (esp. name-recall bias for non-English names, synthetic-only evaluation), the residual-risk metric, and the escalation route for missed identifiers.
- **3.6 Appeals / redress:** Not a citizen-facing decision system. Missed identifiers found post-review are corrected and fed back into the recogniser rules/tests.

### 4. Tool specification

- **4.1.1 System architecture:** Python package (`src/`) deployed as a FastAPI service and Streamlit demo. The LangGraph agent runs server-side; the clinician UI is a single-page web app. Raw notes and the re-identification vault stay Trust-local and are gitignored.
- **4.1.2 Phase:** Prototype (hackathon) — not deployed to production.
- **4.1.3 Maintenance:** CI (`ruff` + `pytest`) on every change; residual leakage acts as a regression gate; recognisers re-evaluated when data or rules change.
- **4.1.4 Components:** (a) pure-Python rule recognisers (`src/deid.py`); (b) Presidio + spaCy `en_core_web_md` NER (deployed; graceful no-op fallback); (c) `scan_pii` residual-PII audit; (d) LangGraph ReAct agent with Gemini 2.5 Flash; (e) Tavily public-guidance search; (f) FastAPI clinician UI.

**4.2 Component specifications**

| Component | Task | Method | Notes |
|---|---|---|---|
| Rule recognisers | NHS number, DOB, postcode, GMC/NMC, email, phone | Regex + context anchors (name-agnostic) | `src/deid.py`; std-lib only |
| Vault match | Patient/clinician names | Exact-match from patients.csv + admissions.csv | Deterministic; demographic-agnostic for structured entities |
| Presidio NER | `PERSON`, `LOCATION` | spaCy `en_core_web_md` (`NOTEGUARD_SPACY_MODEL`), score-thresholded | Shipped in the deployed image; no-op fallback when absent |
| Gemini 2.5 Flash | Discharge summary drafting | LangGraph ReAct; SYSTEM prompt enforces no-PHI rules and never names the patient | `NOTEGUARD_MODEL` env var |
| Tavily | Public-guidance grounding | Public web search for NICE/NHS sources only | Patient text never sent |
| assert_clean() | Hard de-id guarantee | Raises `ValueError` if any identifier survives | Cannot be weakened or bypassed |
| compute_trust | De-id audit | `scan_pii` residual-PII scan (vault-independent) + orphaned-token / reversibility check | Surfaced in clinician UI |

**4.3 Data specification**

- **4.3.1 Source:** `NHSEDataScience/synthetic_clinical_notes` (Hugging Face, MIT licence).
- **4.3.2 Modality:** Text (3 linked CSVs: patients, admissions, notes).
- **4.3.3 Description:** Synthetic clinical notes joined to synthetic patient/admission records on `person_id`/`admission_id` — the join provides free ground truth for the leakage metric.
- **4.3.4 Quantities:** ~70 patients, ~1,602 notes.
- **4.3.5 Sensitive attributes:** Synthetic names, NHS numbers, DOBs, sites — treated as if real PHI throughout.
- **4.3.6 Representativeness:** Fully synthetic; not representative of real Trust notes. Real validation required before deployment.
- **4.3.7 Source URL:** https://huggingface.co/datasets/NHSEDataScience/synthetic_clinical_notes
- **4.3.8 Cleaning:** Mojibake repair (`_fix_mojibake`); consistent date-shift for DOBs.
- **4.3.9 Sharing:** Only de-identified text + content-free trust metrics are shareable. Raw data and the vault are gitignored and never committed.

### 5. Risks, mitigations and impact assessments

- **5.1 Impact assessment:** A **DPIA is required before any real deployment** and has **not** been done (prototype on synthetic data). IG/Caldicott sign-off and DARS approval also required.
- **5.2 Risks and mitigations:**

| Risk | Impact | Mitigation |
|---|---|---|
| False negative (missed PII) | Re-identification of a patient | Name-agnostic rule recognisers; vault from structured tables; assert_clean() hard gate; vault-independent residual-PII audit (`scan_pii`) surfaced to clinician |
| **Name-recall bias** (non-English names) | Unequal re-identification risk across demographics | Rule recognisers are demographic-agnostic; vault provides deterministic coverage; **stratified recall evaluation required** before deployment |
| LLM hallucination / fabrication | Clinically incorrect summary | Grounded-only SYSTEM prompt; clinician reviews and signs off every summary |
| Tavily leaking patient text | PHI to public internet | SYSTEM prompt prohibition; assert_clean() runs before Tavily is ever called; trust metric monitors for policy violations |
| Orphaned surrogate tokens | Model-invented `[LABEL_n]` not re-identifiable | `reidentify_out` detects and flags unmapped tokens; replaced with `[redacted]`; surfaced in leaked_tokens |
| Vault compromise | Re-identification via the linkage key | Vault stays Trust-local; gitignored; treated as the re-identification key |
| Pseudonymised ≠ anonymised (UK GDPR) | Mistaken belief data is non-personal | Stated honestly throughout; DPIA + IG sign-off required |

---

*NoteGuard · {Tech: Europe} London AI Hackathon · prototype · v0.2.0*
