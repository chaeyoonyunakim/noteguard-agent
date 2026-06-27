"""NoteGuard — interactive de-identification demo (Streamlit).

Run: streamlit run streamlit_app.py
No API keys required — uses the pure-Python rule layer only.
"""

from __future__ import annotations

import streamlit as st
from src.deid import NoteGuard

st.set_page_config(page_title="NoteGuard demo", page_icon=":lock:", layout="wide")

st.title("NoteGuard — NHS clinical-note de-identification")
st.caption(
    "Trust layer for clinical AI · "
    "Pseudonymises free-text before any LLM sees it · "
    "Pure-Python rule layer (no API key needed for this demo)"
)

BUILT_IN = (
    "02 Jan 2025, Ward RJ1.\n"
    "Pt Margaret Okafor (NHS 485 777 3456, DOB 14/03/1934, F).\n"
    "GP: Dr James Obi, Riverside Surgery SE1 7PB.\n"
    "Admitted post-fall. Hx: AF on warfarin, T2DM on metformin.\n"
    "Nurse Chukwuebuka Okafor reviewed at triage, NMC number: 18D6896L.\n"
    "Consultant: Dr Sarah Chen, GMC No. 7654321.\n"
    "Contact: a.okafor@nhs.net · 020 7946 0991."
)

col_in, col_out = st.columns(2)

with col_in:
    st.subheader("Clinical note (input)")
    note = st.text_area(
        "Paste or edit a clinical note:", value=BUILT_IN, height=300, label_visibility="collapsed"
    )
    known_names = st.text_input(
        "Known patient/clinician names (comma-separated, optional):",
        placeholder="e.g. Margaret Okafor, Chukwuebuka Okafor",
    )

run = st.button("De-identify", type="primary")

if run and note.strip():
    known: dict = {"PERSON": [], "NHS": []}
    if known_names.strip():
        known["PERSON"] = [n.strip() for n in known_names.split(",") if n.strip()]

    ng = NoteGuard(known=known)
    result = ng.deidentify(note)

    with col_out:
        st.subheader("De-identified text (what the AI sees)")
        st.code(result.clean_text, language=None)

    st.divider()
    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("Identifiers removed", len(result.forward))
    col_m2.metric("Residual (known vault)", len(result.residual))
    col_m3.metric("Re-ID risk", "0.0%" if not result.residual else f"{len(result.residual)} found")

    if result.forward:
        with st.expander("Surrogate mapping (clinician eyes only — never sent to model)"):
            st.table(
                [
                    {"original": k, "surrogate": v}
                    for k, v in sorted(result.forward.items(), key=lambda kv: kv[1])
                ]
            )

    if result.residual:
        st.error(f"Residual identifiers detected: {result.residual}")
    else:
        st.success("assert_clean passed — no known identifier reached the model boundary.")
elif run:
    st.warning("Please enter a note to de-identify.")
