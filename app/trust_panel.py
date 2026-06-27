"""NoteGuard Trust Panel — Streamlit demo UI.

Run:  streamlit run app/trust_panel.py

Shows the full de-id → retrieve → generate → re-id pipeline and the
trust panel (identifiers removed, residual leakage, faithfulness, sources).
"""
import os
import sys

# Ensure project root is on the path when run from any directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

import streamlit as st
from langchain_core.messages import HumanMessage

st.set_page_config(
    page_title="NoteGuard — Trust Layer for Clinical AI",
    page_icon="🔒",
    layout="wide",
)

DEFAULT_NOTE = (
    "Ward RJ1, 02 Jan. Pt Margaret Okafor (NHS 485 777 3456, DOB 14/03/1934) "
    "admitted post-fall. Hx AF, on warfarin. Contact a.okafor@example.com, "
    "020 7946 0991. GMC 7654321. Please draft a discharge summary."
)


@st.cache_resource(show_spinner="Loading NoteGuard (first run takes ~20 s)…")
def _load_graph():
    from agent.graph import graph  # imports & seeds Superlinked index
    return graph


def _invoke(note: str) -> dict:
    g = _load_graph()
    state = g.invoke({"messages": [HumanMessage(content=note)]})
    return state


# ── Layout ────────────────────────────────────────────────────────────────────

st.title("🔒 NoteGuard — Trust Layer for Clinical AI")
st.caption(
    "NHS clinical notes go in → a safe AI-drafted summary comes out → "
    "the model **provably never sees a single identifier**."
)

with st.sidebar:
    st.header("Clinical Note")
    note = st.text_area("Paste a ward note:", value=DEFAULT_NOTE, height=260)
    run = st.button("Analyse with NoteGuard", type="primary", use_container_width=True)
    st.divider()
    st.caption(
        "**Pipeline:** de-identify → Superlinked retrieval → Gemini → re-identify  \n"
        "**Guarantee:** `assert_clean()` fires before Gemini sees anything."
    )

if run and note.strip():
    with st.spinner("De-identifying → Retrieving → Generating…"):
        try:
            result = _invoke(note)
            st.session_state["result"] = result
            st.session_state["note"] = note
        except Exception as exc:
            st.error(f"Error: {exc}")

# ── Results ───────────────────────────────────────────────────────────────────

if "result" in st.session_state:
    result = st.session_state["result"]
    raw_note = st.session_state["note"]

    # Toggle: raw note vs what the AI sees vs clinician answer
    view = st.radio(
        "Toggle view",
        ["Raw note (with PHI)", "What the AI sees (de-identified)", "Clinician answer (re-identified)"],
        horizontal=True,
    )
    st.divider()

    if view.startswith("Raw"):
        st.markdown("#### Raw note")
        st.warning(raw_note)

    elif view.startswith("What"):
        st.markdown("#### De-identified — what Gemini received")
        st.info(result.get("deid_text", "*(not captured)*"))
        if result.get("retrieved_context"):
            with st.expander(f"Superlinked retrieved {len(result['retrieved_context'])} context chunk(s)"):
                for i, chunk in enumerate(result["retrieved_context"], 1):
                    st.markdown(f"**Chunk {i}:** {chunk}")

    else:
        st.markdown("#### Clinician answer (identifiers restored)")
        st.success(result.get("clinician_answer", "*(empty)*"))

    # ── Trust Panel ───────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Trust Panel")

    ids_removed = result.get("identifiers_removed", 0)
    residual = result.get("residual_count", 0)
    leakage_pct = 0.0 if ids_removed == 0 else residual / max(ids_removed, 1) * 100
    faith = result.get("faithfulness_score", 0.0)
    sources = result.get("sources", [])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Identifiers removed", ids_removed)
    c2.metric(
        "Residual leakage",
        f"{leakage_pct:.1f}%",
        delta=f"{residual} known remaining" if residual else "0 remaining",
        delta_color="inverse",
    )
    c3.metric(
        "Faithfulness",
        f"{faith:.2f}" if faith else "n/a",
        help="LLM-as-judge: is every clinical claim supported by the de-identified source?",
    )
    c4.metric("Sources cited", len(sources))

    if sources:
        with st.expander("Sources (Tavily / NICE / NHS)"):
            for url in sources:
                st.markdown(f"- {url}")

    # Forward map: what was replaced
    forward = result.get("forward") or {}
    if forward:
        with st.expander(f"Identifier vault ({len(forward)} mappings)"):
            rows = [{"Original → Surrogate": f"{orig}  →  {tok}"} for orig, tok in forward.items()]
            st.table(rows)
