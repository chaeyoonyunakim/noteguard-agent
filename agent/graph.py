"""LangGraph agent (Gemini + Tavily) wrapped by NoteGuard de-identification.

Guarantee enforced in-graph: the LLM and the Tavily tool only ever receive
DE-IDENTIFIED text. Real identifiers are restored only in the final,
clinician-facing answer (reidentify_out).

Run locally:  langgraph dev      (serves the `noteguard` graph for Agent Chat UI)
Trace:        set LANGSMITH_TRACING=true + LANGSMITH_API_KEY (runs auto-trace)

Graph flow:
  deidentify_in -> agent -> reidentify_out -> compute_trust

Version note: import names track LangGraph v1 / LangChain v0.3+. If your installed
versions differ, adjust the two prebuilt imports and the create_react_agent call.
"""

from __future__ import annotations

import json
import os
import re

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

from src.deid import NoteGuard

SYSTEM = """\
You are a clinical documentation assistant for NHS clinicians.
Your ONLY output is a compact discharge-summary card. Reproduce EXACTLY the format below — \
no headings, no bullets, no preamble, no sign-off.

## De-identification rules — NEVER violate
You only ever see DE-IDENTIFIED text. Patient identifiers — names, NHS numbers, dates of birth,
addresses, GP names, consultant names — have been replaced with surrogate tokens such as
[PERSON_1], [NHS_1], [DOB_1], [ADDRESS_1], [DATE_1].
Preserve every surrogate token exactly as given. A re-identification step restores real values
for the clinician after you respond. Never invent, guess, or expand a surrogate into a real value.
Never write the literal text of a surrogate token (e.g. [PERSON_1]) in the title line — \
use {{PATIENT}} there instead (see below).

## Output format — four elements, blank line between each

{{PATIENT}} — discharge summary

Admitted [DATE_X] after <reason>. Background: <key conditions/meds>. <what was done>. <key finding>.

Follow-up: <GP action> · <action 2> · <action 3>

Grounded: <source name 1>, <source name 2> · via Tavily

## Rules for each element

**Title line:** write exactly `{{PATIENT}} — discharge summary`. \
The placeholder {{PATIENT}} is resolved to the real patient name by the system — \
you must never write a real name, a surrogate token, or any other identifier there.

**Narrative paragraph:** plain clinical prose, max 4 sentences. Include only facts stated in \
the source note — never invent investigations, doses, dates, or diagnoses. \
Surrogate tokens ([DATE_1], [PERSON_1], etc.) may appear here and will be restored. \
Drop a sentence entirely when there is nothing to say (e.g. no imaging → omit that sentence).

**Follow-up line:** items separated by " · " (middle dot U+00B7). \
Always include the GP action as the first item.

**Grounded line:** list only the public guidance sources (short readable names, not URLs) \
actually returned by the Tavily search tool this run. \
If Tavily returned no results, omit the Grounded line entirely — never fabricate citations.

**Search tool:** use only for public NICE/NHS clinical guidance. \
Never send patient text or surrogate tokens to the search tool.
"""


class State(MessagesState):
    forward: dict
    reverse: dict
    clinician_answer: str
    person_name: str  # resolved from person_id — fills {{PATIENT}} in title
    # --- trust panel fields ---
    deid_text: str  # de-identified note text (what the AI saw)
    identifiers_removed: int  # identifiers replaced in this turn
    residual_count: int  # known identifiers that survived de-id (pre-model)
    leaked_tokens: list  # tokens/patterns that slipped through (post-model)
    faithfulness_score: float  # LLM-as-judge: 0–1
    sources: list  # Tavily URLs cited in the answer


def build_graph(known: dict | None = None):
    model = init_chat_model(os.getenv("NOTEGUARD_MODEL", "google_genai:gemini-2.0-flash"))
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

    def run_agent(state: State):
        out = react.invoke({"messages": state["messages"]})
        return {"messages": out["messages"][len(state["messages"]) :]}

    def reidentify_out(state: State):
        ng = NoteGuard(reverse=state.get("reverse"))
        last = state["messages"][-1]
        if not isinstance(last, AIMessage):
            return {"clinician_answer": "", "leaked_tokens": []}
        content = last.content
        # Gemini can return content as a list of blocks [{type, text}, ...]
        if isinstance(content, list):
            raw_text = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block) for block in content
            ).strip()
        else:
            raw_text = content or ""

        # Check model output for orphaned tokens BEFORE reidentify restores known ones
        reverse = state.get("reverse") or {}
        leaked: list[str] = []
        for m in re.finditer(r"\[[A-Z]+_\d+\]", raw_text):
            tok = m.group(0)
            if tok not in reverse:
                leaked.append(f"unmapped_token:{tok}")

        # Restore known surrogates
        restored = ng.reidentify(raw_text)

        # Replace {{PATIENT}} with the structured patient name (never from model)
        person_name = state.get("person_name") or "Patient"
        restored = restored.replace("{{PATIENT}}", person_name)

        # Replace any remaining [LABEL_n] that reidentify couldn't resolve — flag each
        def _replace_leftover(m: re.Match) -> str:
            tok = m.group(0)
            leaked.append(f"unresolved_token:{tok}")
            return "[redacted]"

        restored = re.sub(r"\[[A-Z]+_\d+\]", _replace_leftover, restored)

        return {"clinician_answer": restored, "leaked_tokens": leaked}

    def compute_trust(state: State):
        """Extract Tavily sources and compute faithfulness (LLM-as-judge).

        The faithfulness judge compares the de-identified AI answer against
        the de-identified source note (deid_text) — it never sees PHI.
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

        # --- faithfulness: judge de-identified answer vs de-identified source note ---
        score = 0.0
        last_ai = next((m for m in reversed(state["messages"]) if isinstance(m, AIMessage)), None)
        context = state.get("deid_text") or ""
        if last_ai and context:
            ai_content = last_ai.content
            if isinstance(ai_content, list):
                ai_content = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b) for b in ai_content
                ).strip()
            prompt = (
                f"CONTEXT (de-identified source note):\n{context}\n\n"
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

        # Merge leaked_tokens from reidentify_out with any new findings
        leaked = list(state.get("leaked_tokens") or [])
        residual_extra = state.get("residual_count", 0)

        return {
            "sources": list(dict.fromkeys(filter(None, sources))),
            "faithfulness_score": score,
            "leaked_tokens": leaked,
            # Bump residual_count so the API's risk calculation sees the truth
            "residual_count": residual_extra + len(leaked),
        }

    g = StateGraph(State)
    g.add_node("deidentify_in", deidentify_in)
    g.add_node("agent", run_agent)
    g.add_node("reidentify_out", reidentify_out)
    g.add_node("compute_trust", compute_trust)
    g.add_edge(START, "deidentify_in")
    g.add_edge("deidentify_in", "agent")
    g.add_edge("agent", "reidentify_out")
    g.add_edge("reidentify_out", "compute_trust")
    g.add_edge("compute_trust", END)
    return g.compile()


# Demo vault — seeds the known-identifier set so `langgraph dev` / the web UI
# resolve surrogates consistently on startup.
_DEMO_KNOWN = {"PERSON": ["Margaret Okafor"], "NHS": ["485 777 3456"]}
graph = build_graph(known=_DEMO_KNOWN)
