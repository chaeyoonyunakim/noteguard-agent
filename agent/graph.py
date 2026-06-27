"""LangGraph agent (Gemini + Tavily) wrapped by NoteGuard de-identification.

Guarantee enforced in-graph: the LLM and the Tavily tool only ever receive
DE-IDENTIFIED text. Real identifiers are restored only in the final,
clinician-facing answer (reidentify_out).

Run locally:  langgraph dev      (serves the `noteguard` graph for Agent Chat UI)
Trace:        set LANGSMITH_TRACING=true + LANGSMITH_API_KEY (runs auto-trace)

Graph flow:
  deidentify_in -> retrieve_context -> agent -> reidentify_out -> compute_trust

Version note: import names track LangGraph v1 / LangChain v0.3+. If your installed
versions differ, adjust the two prebuilt imports and the create_react_agent call.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from noteguard.retrieve import NoteIndex

from dotenv import load_dotenv

load_dotenv()  # pick up .env before any os.getenv / API-key validation

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import create_react_agent

try:
    from langchain_tavily import TavilySearch
except ImportError:  # older package name
    from langchain_community.tools.tavily_search import TavilySearchResults as TavilySearch

from noteguard.deid import NoteGuard

SYSTEM = """\
You are a clinical documentation assistant for NHS clinicians.
Draft eDischarge summaries that comply with the PRSB / Academy of Medical Royal Colleges eDischarge standard.

## De-identification rules — NEVER violate
You only ever see DE-IDENTIFIED text. Patient identifiers — names, NHS numbers, dates of birth,
addresses, GP names, consultant names, GMC codes — have been replaced with surrogate tokens such as
[PERSON_1], [NHS_1], [DOB_1], [ADDRESS_1], [DATE_1].
Preserve every surrogate token exactly as given. A re-identification step restores real values for
the clinician after you respond. Never invent, guess, or expand a surrogate into a real value.

## Output structure
Produce the summary under the headings below IN ORDER.
Mandatory sections must always appear (write "Not documented" if the notes contain no data for them).
Omit optional sections entirely when not relevant.

### 1. Patient details [MANDATORY]
Name · DOB · NHS number · address · sex/gender — use surrogate tokens from the input.

### 2. GP practice details [MANDATORY]
GP name · practice name and address — use surrogate tokens.

### 3. Admission and discharge details
Admission date · discharge date · ward · responsible consultant · discharge destination.

### 4. Diagnoses [MANDATORY]
Primary diagnosis first, then secondary. Be specific (e.g. "Acute exacerbation of COPD",
"Type 2 diabetes mellitus").

### 5. Clinical summary [MANDATORY]
Reason for admission · relevant history and examination · hospital course and management ·
complications (if any).

### 6. Procedures
List with dates if any were performed.

### 7. Investigations and results
Key results; flag anything still pending.

### 8. Allergies and adverse reactions [MANDATORY]
List allergies or write "No known drug allergies".

### 9. Medications
**Medication changes:** each entry as STARTED / STOPPED / CHANGED — include reason.
**Medications to take home (TTO):** drug · form · route · dose · frequency · duration · indication.

### 10. Plan and requested actions
(a) Actions for the GP.
(b) Hospital follow-up and referrals.

### 11. Information for the patient
One plain-English paragraph addressed to the patient.

### 12. Safety alerts / safeguarding [optional]

### 13. Social context / individual requirements [optional]

### 14. Person completing record [MANDATORY]
Name · role · grade · specialty · date — use surrogate tokens where applicable.

## Content rules
- State only facts present in the source notes. Write "Not documented" if a field is absent — never fabricate.
- Use the search tool only for public clinical guidance (NICE/NHS). Never send patient text or \
surrogate tokens to it.
"""


class State(MessagesState):
    forward: dict
    reverse: dict
    clinician_answer: str
    retrieved_context: list  # de-identified snippets fed to agent
    # --- trust panel fields ---
    deid_text: str  # de-identified note text (what the AI saw)
    identifiers_removed: int  # identifiers replaced in this turn
    residual_count: int  # known identifiers that survived de-id
    faithfulness_score: float  # LLM-as-judge: 0–1
    sources: list  # Tavily URLs cited in the answer


def build_graph(known: dict | None = None, note_index: NoteIndex | None = None):
    model = init_chat_model(os.getenv("NOTEGUARD_MODEL", "google_genai:gemini-2.5-flash"))
    tools = [TavilySearch(max_results=3)]
    react = create_react_agent(model, tools, prompt=SYSTEM)

    def deidentify_in(state: State):
        prior_n = len(state.get("forward") or {})
        ng = NoteGuard(known=known, forward=state.get("forward"), reverse=state.get("reverse"))
        last = state["messages"][-1]
        if not isinstance(last, HumanMessage):
            return {"forward": ng.forward, "reverse": ng.reverse}
        res = ng.deidentify(last.content)
        ng.assert_clean(res.clean_text)  # hard guarantee before model/tool see anything
        cleaned = HumanMessage(content=res.clean_text, id=last.id)
        return {
            "messages": [cleaned],
            "forward": ng.forward,
            "reverse": ng.reverse,
            "deid_text": res.clean_text,
            "identifiers_removed": len(ng.forward) - prior_n,
            "residual_count": len(res.residual),
        }

    def retrieve_context(state: State):
        """Query Superlinked for de-identified notes similar to the current message."""
        if note_index is None:
            return {"retrieved_context": []}
        last = state["messages"][-1]
        if not isinstance(last, HumanMessage):
            return {"retrieved_context": []}
        ng = NoteGuard(known=known, forward=state.get("forward"), reverse=state.get("reverse"))
        chunks = note_index.retrieve(last.content, ng, top_k=3)
        if not chunks:
            return {"retrieved_context": []}
        context_block = "\n---\n".join(chunks)
        augmented = HumanMessage(
            content=(
                f"RELEVANT CONTEXT FROM PATIENT RECORD (de-identified):\n{context_block}"
                f"\n\n---\nQUESTION:\n{last.content}"
            ),
            id=last.id,
        )
        return {"messages": [augmented], "retrieved_context": chunks}

    def run_agent(state: State):
        out = react.invoke({"messages": state["messages"]})
        return {"messages": out["messages"][len(state["messages"]) :]}

    def reidentify_out(state: State):
        ng = NoteGuard(reverse=state.get("reverse"))
        last = state["messages"][-1]
        if not isinstance(last, AIMessage):
            return {"clinician_answer": ""}
        content = last.content
        # Gemini can return content as a list of blocks [{type, text}, ...]
        if isinstance(content, list):
            text = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block) for block in content
            ).strip()
        else:
            text = content or ""
        return {"clinician_answer": ng.reidentify(text)}

    def compute_trust(state: State):
        """Extract Tavily sources and compute faithfulness (LLM-as-judge).

        The faithfulness judge compares the de-identified AI answer against
        the de-identified retrieved context — it never sees PHI.
        """
        # --- Tavily sources from ToolMessages ---
        sources: list[str] = []
        for msg in state["messages"]:
            content = getattr(msg, "content", None)
            if not content:
                continue
            try:
                items = json.loads(content) if isinstance(content, str) else content
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict) and item.get("url"):
                            sources.append(item["url"])
            except (json.JSONDecodeError, TypeError):
                pass

        # --- faithfulness: judge de-identified answer vs retrieved context ---
        score = 0.0
        last_ai = next((m for m in reversed(state["messages"]) if isinstance(m, AIMessage)), None)
        context_chunks = state.get("retrieved_context") or []
        if last_ai and context_chunks:
            ai_content = last_ai.content
            if isinstance(ai_content, list):
                ai_content = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b) for b in ai_content
                ).strip()
            context = "\n---\n".join(context_chunks)
            prompt = (
                f"CONTEXT (de-identified source notes):\n{context}\n\n"
                f"ANSWER:\n{ai_content}\n\n"
                "Is every clinical claim in ANSWER supported by CONTEXT? "
                "Reply with a single number between 0 and 1."
            )
            try:
                raw = model.invoke(prompt).content
                if isinstance(raw, list):
                    raw = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in raw)
                score = max(0.0, min(1.0, float(raw.strip().split()[0])))
            except Exception:
                score = 0.0

        return {
            "sources": list(dict.fromkeys(filter(None, sources))),
            "faithfulness_score": score,
        }

    g = StateGraph(State)
    g.add_node("deidentify_in", deidentify_in)
    g.add_node("retrieve_context", retrieve_context)
    g.add_node("agent", run_agent)
    g.add_node("reidentify_out", reidentify_out)
    g.add_node("compute_trust", compute_trust)
    g.add_edge(START, "deidentify_in")
    g.add_edge("deidentify_in", "retrieve_context")
    g.add_edge("retrieve_context", "agent")
    g.add_edge("agent", "reidentify_out")
    g.add_edge("reidentify_out", "compute_trust")
    g.add_edge("compute_trust", END)
    return g.compile()


# Demo seed — pre-populate Superlinked index with de-identified clinical notes
# so the retrieval node has context on `langgraph dev` / web UI startup.
_DEMO_KNOWN = {"PERSON": ["Margaret Okafor"], "NHS": ["485 777 3456"]}
_DEMO_RAWS = [
    "Pt Margaret Okafor (NHS 485 777 3456, DOB 14/03/1934) admitted post-fall. Hx AF, on warfarin.",
    "Follow-up Margaret Okafor: INR 2.4, warfarin dose adjusted to 4 mg. BP 128/74. Stable.",
    "Margaret Okafor discharged home with community physio referral and warfarin monitoring plan.",
    "A&E note: Margaret Okafor, fall on stairs, no LOC, no head injury, right wrist sprain confirmed.",
]

try:
    from noteguard.retrieve import NoteIndex as _NoteIndex

    _demo_ng = NoteGuard(known=_DEMO_KNOWN)
    _demo_index = _NoteIndex()
    for i, raw in enumerate(_DEMO_RAWS):
        res = _demo_ng.deidentify(raw)
        _demo_ng.assert_clean(res.clean_text)
        _demo_index.add_notes([{"note_id": f"demo_{i + 1}", "text": res.clean_text}], _demo_ng)
    graph = build_graph(known=_DEMO_KNOWN, note_index=_demo_index)
except Exception as _e:
    import warnings

    warnings.warn(
        f"NoteGuard: Superlinked index unavailable, running without retrieval: {_e}",
        stacklevel=2,
    )
    graph = build_graph(known=_DEMO_KNOWN)
