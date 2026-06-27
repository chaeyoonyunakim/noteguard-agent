# NoteGuard — the trust layer for clinical AI

**{Tech: Europe} London AI Hackathon · plan v2 (sponsor- and rubric-aligned)**
Build window 10:00–19:00 · team ≤ 5 · ≥ 3 partner technologies · newly built on the day (boilerplate allowed)

---

## What changed from v1, and why

Your original NoteGuard was the *privacy on-ramp for federated learning* — the de-identification gate that made NHS notes safe to train on before they went into **FLock**'s federated/blockchain stack (Encode's "Trusted Data & AI Infrastructure" brief). My airlock draft then over-rotated into air-gapped SDE governance — which actively fights this event's sponsors (they're cloud) and buries the demo.

This hackathon has **no FL/blockchain sponsor**, and the rubric rewards **technical depth (50) + wow (30) + a real problem (20)** — not governance prose. So v2 keeps the one thing that makes NoteGuard *NoteGuard* — **measured, NHS-aware de-identification of clinical free-text** — and rebuilds everything around it into a demoable, sponsor-native product: a privacy-and-safety layer that lets messy NHS notes safely drive an LLM agent. Federation becomes a one-line "where this goes next," not the build.

---

## The product in one line

> Messy NHS clinical notes go in → a safe, AI-drafted **discharge summary** comes out → and the model **provably never sees a single identifier**, with a live re-identification-risk number to prove it.

The dataset you're starting from (`NHSEDataScience/synthetic_clinical_notes`) was literally *built to evaluate AI-generated discharge summaries* — so the application and the data are a perfect match, and the privacy layer is the differentiator no other team will have.

---

## Why this scores (rubric map)

| Criterion | Weight | How v2 wins it |
|---|---|---|
| **Technical execution** | 50 | Real multi-stage system: NHS-aware NER + **measured residual-leakage eval** (ground-truth join) + semantic retrieval + grounded generation + cost-routing + voice. Deeper than the obvious "GPT writes a discharge letter" because we *measure* privacy and faithfulness, not vibe them. |
| **Creativity / wow** | 30 | The "what the AI sees" toggle — watch every identifier vanish in real time — plus a live **re-identification-risk meter** and voice dictation. "A model that *structurally cannot* see PHI" is a fresh take, not a chatbot wrapper. |
| **Real problem** | 20 | Discharge-summary admin is a named NHS priority (now rolling out on the FDP), and information governance is *the* blocker to clinical AI. You can speak to both from inside NHS England. |

---

## Architecture — privacy core, sponsor-powered pipeline

```
  messy notes ─►  NoteGuard de-id  ─►  de-identified text + audit + RESIDUAL-LEAKAGE %
  (synthetic)     (Presidio + NHS                  │
                   rules, mojibake fix)            ▼
                                          Superlinked  ── PHI-safe semantic retrieval
                                          (patient journey + cohort)
                                                   │
                            Tavily ──► grounding ──►│
                            (NICE / NHS guidance)   ▼
                                          Gemini  ── drafts discharge summary / answers
                                          (reasoning)│   (sees ONLY de-identified text)
                                                   ▼
                          NoteGuard re-id (surrogates → real names) for the CLINICIAN only
                                                   ▼
                          Trust panel: leakage %, identifiers removed, faithfulness, sources
                                                   ▲
       Mubit/Minima routes cheap model for NER, frontier for reasoning   │
       SLNG: clinician dictates a note / hears the summary read back ─────┘
       n8n orchestrates the whole flow   ·   Aikido scans the repo in CI
```

Key technical detail (the "deeper than obvious" bit judges look for): the LLM **only ever receives de-identified text with consistent surrogates**; real names/NHS numbers are re-attached at the very end for the clinician's eyes only. The model literally cannot leak what it never saw — and you prove it with the residual-leakage number.

---

## Partner technologies (≥ 3, plus 3 side prizes)

| Stage | Partner tech | What it does here | Prize surface |
|---|---|---|---|
| Reasoning / generation | **Google Gemini (DeepMind)** | Drafts the discharge summary and answers clinician questions from de-identified context | Infra partner |
| Retrieval | **Superlinked** | Vector index over de-identified notes → semantic search across the patient journey and cohort, no PHI | **Superlinked side prize ($500)** |
| Orchestration | **n8n (self-host or cloud)** | Visual agentic workflow wiring every stage; the "headless pipeline" story | **n8n side prize (Cloud Pro + $500)** |
| Voice | **SLNG** | Clinician dictates a ward note by voice; summary read back aloud | **SLNG side prize (LEGO)** |
| Grounding | **Tavily** | Pulls NICE / NHS guidance so the summary cites real clinical guidance | 1,000 credits |
| Model routing | **Mubit / Minima** | Recommends the cheapest model that clears the bar — cheap for NER, frontier for reasoning ("NHS budgets" line) | $2k credits |
| Security | **Aikido** | Scans the repo, screenshot the report — on-brand for a privacy tool | **Aikido "Most Secure Build" (€1,000)** |

That's **Gemini + Superlinked + n8n** as your core three, with SLNG, Tavily, Mubit and Aikido stacked on for extra prize surface. Pick the three you'll demo hardest; wire the rest if time allows.

---

## NoteGuard core — the differentiator (reuse your v1 engine)

This is the part that makes it more than a wrapper, and it's already built:

- **NHS-aware recognisers** — checksum/context NHS numbers, GMC/NMC/ODS, postcodes, dates, record UUIDs (Presidio + pure-Python rules behind one `Detector` interface).
- **Measured residual leakage** — because the dataset keeps identifiers in structured tables, join them back to each note for *free ground truth* and report a real re-identification number. Your v1 already shows 74.8% (rules only) → **8.5% (Presidio + rules)**. That measured number is the demo's spine.
- **Patient-consistent pseudonymisation** — same patient → same surrogate across the whole admission; DOB date-shifted, visit dates preserved (clinically useful).
- **Mojibake fix** — the dataset has known mis-decoded characters; your `_fix_mojibake` cleans them so they don't pollute output.

v2 adds, on the day: the **retrieval + generation + re-id round-trip**, the **faithfulness/groundedness check** (LLM-as-judge over the generated summary vs the de-identified source), and the **trust panel** UI.

---

## Dataset plan — `NHSEDataScience/synthetic_clinical_notes`

- Hugging Face, **MIT**, fully synthetic (GPT-4o pipeline, built on Palantir Foundry — the FDP platform family). Purpose: evaluating AI discharge summaries.
- **Silver tier:** 70 patients (50 adult, 20 paediatric), ~20–50 notes each.
- Tables: `patients.csv` (name, dob, NHS number, person_id…), `admissions.csv`, `synthetic_clinical_notes.csv` (`clean_note_text`, note_type, admission_id, person_id…).
- **Ground-truth join** = your unfair advantage: structured identifiers → measure leakage exactly.
- Say "fully synthetic" out loud in the demo — zero IG risk, runs anywhere, scores trust points.

---

## Nine-hour build plan

| Time | Milestone |
|---|---|
| 10:00–10:30 | Clone v1, pull dataset, agree the three demo sponsors, cut scope to one patient journey end-to-end. |
| 10:30–12:00 | Wire NoteGuard de-id → `clean(note) → {text, surrogates, leakage}`. Stand up n8n + Gemini call. |
| 12:00–13:30 | Superlinked index over de-identified notes; retrieval across the patient's journey. |
| 13:30–15:00 | Gemini drafts the discharge summary from retrieved de-identified context; re-id round-trip for the clinician view. |
| 15:00–16:30 | Trust panel: leakage %, identifiers removed, faithfulness (LLM-as-judge), Tavily-grounded sources. Mubit routing. |
| 16:30–17:30 | SLNG voice in/out. Aikido scan + screenshot. Polish the toggle demo. |
| 17:30–18:15 | Record 2-min Loom; README (boilerplate-vs-new table); push public repo. |
| 18:15–19:00 | Buffer + submit by 19:00. Rehearse. |

---

## Two-minute demo script

1. **Hook (15s):** "NHS notes are full of identifiers, so they can't safely touch an LLM. We fixed that — and we can prove it with a number."
2. **Raw note (20s):** show a messy ward note with NHS number + name visible (highlighted).
3. **The toggle (30s):** flip to **"what the AI sees"** — every identifier is replaced by a consistent surrogate. Residual re-identification risk reads **0.0%** (down from a measured baseline).
4. **Generate (35s):** Gemini drafts the discharge summary from de-identified context, grounded in NICE guidance (Tavily). Re-id round-trip fills the clinician's real names back in *only at the end*.
5. **Trust panel (10s):** identifiers removed, faithfulness score, sources, model routing (Mubit).
6. **Voice (10s):** dictate a one-line addendum via SLNG; it flows through the same safe pipeline.
7. **Close:** "Fully synthetic data, measured privacy, built on Gemini + Superlinked + n8n. Federation is where it goes next."

---

## Built-on-the-day vs reused (state this in the README)

| Reused (NoteGuard v1 boilerplate) | New at the hackathon |
|---|---|
| Presidio + NHS-aware detectors, one `Detector` interface | Superlinked retrieval over de-identified notes |
| Residual-leakage eval via ground-truth join | Gemini discharge-summary generation + re-id round-trip |
| Patient-consistent pseudonymisation, mojibake fix | Faithfulness/groundedness check (LLM-as-judge) |
| Streamlit shell | Trust-panel UI, n8n workflow, SLNG voice, Mubit routing, Aikido scan |

---

## Stretch / extra wow (only if ahead)

- **Cohort search** ("show me diabetic paediatric admissions") over the PHI-safe Superlinked index — semantic search on clinical notes with zero exposure.
- **Re-identification attack demo** — try to recover a name from the de-identified output and show it fails; contrast with the raw note.
- **One-line federation nod** — "each Trust runs NoteGuard locally; only de-identified text or model updates ever leave" — ties back to your original FL vision without building it.

---

## Risks & ethics (keep it short, it still scores)

- Pseudonymised ≠ anonymous — still personal data under UK GDPR; don't over-claim.
- Synthetic ≠ real — Silver data is GPT-4o-generated; frame as methodology, not a finished product.
- Faithfulness checks reduce but don't eliminate hallucination — clinician stays in the loop and signs off.

---

## Suggested repo structure

```
noteguard/
  src/
    detect/         # (reused) Presidio + NHS rules
    transform/      # (reused) pseudonymisation + date-shift + mojibake fix
    eval/           # (reused) residual-leakage metric  +  (new) faithfulness judge
    retrieve.py     # (new) Superlinked index + search
    generate.py     # (new) Gemini draft + re-id round-trip
    route.py        # (new) Mubit/Minima model routing
  workflows/airlock.n8n.json   # (new) n8n agentic pipeline
  app/trust_panel.py           # (new) clinician UI + trust panel (extends Streamlit)
  voice/slng.py                # (new) dictate-in / read-back
  README.md                    # boilerplate-vs-new table up top
```
