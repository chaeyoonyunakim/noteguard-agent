# NoteGuard — Tool Card

**Version:** 0.2.0
**Track:** Public Sector & Citizen Services — NHS Secure Data Environment on-ramp
**Status:** Hackathon prototype; not validated for production use without further evaluation.

---

## Specification

| Field | Value |
|---|---|
| Description | De-identification gate + LangGraph agent that detects/removes PII from NHS clinical notes before any LLM sees them, then grounds a discharge summary in public NICE/NHS guidance |
| Type | Hybrid pipeline — pure-Python rule recognisers + optional Microsoft Presidio (spaCy NER); Gemini 2.5 Flash as the agent model; Tavily for public-guidance retrieval |
| Developer | Chaeyoon Kim — {Tech: Europe} London AI Hackathon |
| Status / version | Prototype · v1.0.0 |
| Repository | github.com/chaeyoonyunakim/noteguard-agent |

> Documented as a **tool card**, not a model card. NoteGuard does not train a model.
> A gov.uk Algorithmic Transparency Recording Standard (ATRS) record is in [`report.md`](report.md).

---

## What it does

NoteGuard is a **trust layer** for clinical AI. It:

1. **De-identifies** free-text NHS clinical notes inside the Trust using rule-based recognisers (NHS number, GMC/NMC, DOB, postcode, email, phone) and an optional NLP detector (Presidio + spaCy `en_core_web_lg`).
2. **Asserts clean** — raises `ValueError` if any known identifier survives, hard-blocking the model boundary.
3. Passes de-identified text to a **LangGraph ReAct agent** (Gemini 2.5 Flash) that drafts a compact eDischarge summary grounded in NICE/NHS guidance retrieved via Tavily.
4. **Re-identifies** the summary for the clinician — the model never sees or writes a real name.
5. **Audits the de-identification** — a vault-independent `scan_pii` pass flags any residual PII the model still saw (incl. free-text names the vault missed), plus orphaned surrogate tokens for reversibility. The trust panel reports only this; it carries no answer-quality metrics.

> "De-identify in → agent (Gemini + Tavily) → re-identify out → compute trust."

---

## Who uses it

| Role | When | Why |
|---|---|---|
| NHS Clinician | At discharge | Needs a draft summary without manually de-identifying notes |
| Data Wrangler / IG Analyst | Before releasing notes to AI teams | Cannot share raw free-text; needs measured leakage |
| SDE Operator | At Trust egress boundary | Gate between raw Trust data and a Secure Data Environment |

---

## Use cases out of scope

- **Not** a substitute for Information Governance sign-off, a DPIA, or DARS approval — it is a technical control, not a legal basis for processing.
- **Not** validated on real Trust data, non-English notes, or scanned/handwritten documents.
- **Not** a guarantee of zero re-identification: pseudonymised output is still personal data under UK GDPR, and residual leakage is *measured*, not assumed zero on unseen data.
- **Not** for clinical decision-making, autonomous prescribing, or any use of note content beyond de-identification and grounded summarisation.
- **Not** a replacement for a clinician review — the output is a draft that the clinician signs off.

---

## Detection coverage

| Entity type | Method | Notes |
|---|---|---|
| Patient / clinician name (`PERSON`) | Vault match (patients.csv + admissions.csv) + optional Presidio spaCy NER | Vault is ground-truth; Presidio adds unlisted names |
| NHS number (`NHS`) | Regex + 9-digit context anchor | Catches standard and synthetic-dataset forms |
| Date of birth (`DOB`) | DOB regex + consistent date-shift | Shift preserves clinical plausibility |
| UK postcode (`POSTCODE`) | Regex | Redacted outward-code only |
| GMC number (`GMC`) | Context-anchored regex with connector words | "GMC No. 7654321", "GMC number 7654321" |
| NMC / PIN (`NMC`) | Context-anchored regex with connector words | "NMC number: 18D6896L", "PIN 18D6896L" |
| Email / phone | Regex | Standard patterns |

---

## Anonymisation policy

| Mode | Behaviour |
|---|---|
| **Pseudonymise** (default) | Consistent surrogate tokens `[LABEL_n]`; DOB date-shifted; reidentify() restores originals for the clinician |
| `{{PATIENT}}` placeholder | Title line of discharge summary uses this literal; resolved from `patients.csv` — the model never writes the real name |

---

## Bias and fairness

The optional Presidio NER (spaCy `en_core_web_lg`) is trained largely on Western/English text, so **name recall can be lower for names of non-English origin**. This is an equity risk: under-detection means those patients carry a *higher residual re-identification risk*. Honest position and mitigations:

- The rule-based recognisers (NHS number, DOB, postcode, GMC/NMC) are **name-agnostic** and detect structured identifiers uniformly regardless of patient demographics.
- The **vault** (from `patients.csv` + `admissions.csv`) provides deterministic, demographic-agnostic coverage for all names in the structured dataset.
- **Required before deployment:** evaluate name recall *stratified by name origin* on representative Trust data and report the disparity. Not yet done — evaluation is on the `NHSEDataScience/synthetic_clinical_notes` synthetic dataset only.

---

## NHS Five Safes mapping

| Safe | Status | How |
|---|---|---|
| **Safe data** | ✅ | De-identified before model; assert_clean() hard gate; leakage measured |
| **Safe settings** | ✅ | Processing inside Trust; vault gitignored; Tavily receives only public queries |
| **Safe outputs** | ✅ | Only de-identified text + content-free trust metrics leave model boundary |
| **Safe people** | ⚠️ | Clinician reviews and signs off the draft; vault stays Trust-local |
| **Safe projects** | ⚠️ | Technical layer only; DPIA + project approval (DARS) remain Trust processes |

---

## Limitations and caveats

- **Pseudonymised data is still personal data** under UK GDPR — the surrogate vault is the re-identification key and must stay Trust-local.
- **Not clinically validated:** evaluated on the `NHSEDataScience/synthetic_clinical_notes` dataset. Real deployment requires validation on representative Trust data.
- **Tavily search** is for public NICE/NHS guidance only — patient text or surrogate tokens are never sent to it (enforced in the SYSTEM prompt and monitored via the trust metric).
- **Governance prerequisites for deployment:** a Data Protection Impact Assessment (DPIA), IG/Caldicott sign-off, and DARS project approval are required before any real use. NoteGuard is the technical control, not the approval.

---

## Components

| Component | Role in NoteGuard |
|---|---|
| **Google Gemini 2.5 Flash** | Agent model — drafts the eDischarge summary from de-identified text |
| **Tavily** | Public-guidance search — NICE/NHS sources only; never receives patient text |
| LangGraph | Agent orchestration |
| LangSmith | Tracing and evaluation |

---

*NoteGuard · {Tech: Europe} London AI Hackathon · prototype · not for clinical use without further validation*
