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

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import create_react_agent

try:
    from langchain_tavily import TavilySearch
except ImportError:  # older package name
    from langchain_community.tools.tavily_search import TavilySearchResults as TavilySearch

from noteguard.deid import NoteGuard
from noteguard.retrieve import NoteIndex

SYSTEM = (
    "You are a clinical documentation assistant for NHS clinicians. "
    "You only ever see DE-IDENTIFIED notes: identifiers appear as surrogate "
    "tokens such as [PERSON_1] or [NHS_1]. Never invent or guess real "
    "identifiers, and keep any surrogate tokens intact in your reply. Use the "
    "search tool only to ground guidance in PUBLIC sources (e.g. NICE)."
)


class State(MessagesState):
    forward: dict
    reverse: dict
    clinician_answer: str
    retrieved_context: list   # de-identified snippets fed to agent
    # --- trust panel fields ---
    deid_text: str            # de-identified note text (what the AI saw)
    identifiers_removed: int  # identifiers replaced in this turn
    residual_count: int       # known identifiers that survived de-id
    faithfulness_score: float # LLM-as-judge: 0–1
    sources: list             # Tavily URLs cited in the answer


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
        return {"messages": out["messages"][len(state["messages"]):]}

    def reidentify_out(state: State):
        ng = NoteGuard(reverse=state.get("reverse"))
        last = state["messages"][-1]
        text = last.content if isinstance(last, AIMessage) else ""
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
        last_ai = next(
            (m for m in reversed(state["messages"]) if isinstance(m, AIMessage)), None
        )
        context_chunks = state.get("retrieved_context") or []
        if last_ai and context_chunks:
            context = "\n---\n".join(context_chunks)
            prompt = (
                f"CONTEXT (de-identified source notes):\n{context}\n\n"
                f"ANSWER:\n{last_ai.content}\n\n"
                "Is every clinical claim in ANSWER supported by CONTEXT? "
                "Reply with a single number between 0 and 1."
            )
            try:
                raw = model.invoke(prompt).content.strip()
                score = max(0.0, min(1.0, float(raw.split()[0])))
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
# so the retrieval node has context on `langgraph dev` / Streamlit startup.
_DEMO_KNOWN = {"PERSON": ["Margaret Okafor"], "NHS": ["485 777 3456"]}
_DEMO_RAWS = [
    "Pt Margaret Okafor (NHS 485 777 3456, DOB 14/03/1934) admitted post-fall. Hx AF, on warfarin.",
    "Follow-up Margaret Okafor: INR 2.4, warfarin dose adjusted to 4 mg. BP 128/74. Stable.",
    "Margaret Okafor discharged home with community physio referral and warfarin monitoring plan.",
    "A&E note: Margaret Okafor, fall on stairs, no LOC, no head injury, right wrist sprain confirmed.",
]

try:
    _demo_ng = NoteGuard(known=_DEMO_KNOWN)
    _demo_index = NoteIndex()
    for i, raw in enumerate(_DEMO_RAWS):
        res = _demo_ng.deidentify(raw)
        _demo_ng.assert_clean(res.clean_text)
        _demo_index.add_notes([{"note_id": f"demo_{i + 1}", "text": res.clean_text}], _demo_ng)
    graph = build_graph(known=_DEMO_KNOWN, note_index=_demo_index)
except Exception as _e:
    import warnings
    warnings.warn(f"NoteGuard: Superlinked index unavailable, running without retrieval: {_e}")
    graph = build_graph(known=_DEMO_KNOWN)
