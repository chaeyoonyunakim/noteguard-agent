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

import os

from dotenv import load_dotenv

load_dotenv(override=True)  # pick up .env before any os.getenv / API-key validation

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
Do NOT name the patient anywhere in your output — no title, no real name, no patient surrogate
token. Refer to the patient only as "the patient". (Surrogate tokens for OTHER people, e.g. a GP
or consultant, may appear and will be restored.)

## Output format — three elements, blank line between each

Admitted <admission date> after <reason>. Background: <key conditions/meds>. <what was done>. <key finding>.

Follow-up: <GP action> · <action 2> · <action 3>

Grounded: <source name 1>, <source name 2> · via Tavily

## Rules for each element

**Narrative paragraph:** plain clinical prose, max 4 sentences. Include only facts stated in \
the source note — never invent investigations, doses, dates, or diagnoses. \
Refer to the patient as "the patient" — never write the patient's name or their surrogate token. \
Surrogate tokens for other people ([DATE_1], [PERSON_1], etc.) may appear here and will be restored. \
Include the admission date ONLY if a date surrogate token (e.g. [DATE_1]) appears in the \
source note — reproduce that exact token. If the source states no admission date, omit it \
entirely (write "Admitted after <reason>"). NEVER output a literal placeholder such as \
<admission date> or [DATE_X]. \
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
    # --- trust panel fields (all about de-identification correctness) ---
    deid_text: str  # de-identified note text (what the AI saw)
    identifiers_removed: int  # identifiers replaced in this turn
    residual_count: int  # known identifiers that survived de-id (pre-model)
    leaked_tokens: list  # orphaned surrogate tokens in the output (reversibility)
    residual_pii: list  # suspected un-redacted PII the model saw (de-id audit)


def build_graph(known: dict | None = None):
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

        # Restore known surrogates for the clinician (the patient is never named).
        restored = ng.reidentify(raw_text)

        # Anything surrogate-shaped still present is either an unrestored surrogate or
        # a stray template placeholder the model echoed (e.g. [DATE_X]); redact + flag
        # so it never reaches the clinician verbatim.
        restored, leaked_tokens = ng.redact_unresolved(restored)
        leaked = [f"unresolved_token:{tok}" for tok in leaked_tokens]

        return {"clinician_answer": restored, "leaked_tokens": leaked}

    def compute_trust(state: State):
        """Audit de-identification quality for the trust panel.

        Two independent de-id failures, neither needing PHI to compute:
        - residual_pii: PII the vault/NER passes missed but that still reached the
          model — scanned out of deid_text (what the model actually saw). This is
          the failure the old residual_count was blind to (vault-only).
        - leaked_tokens: orphaned surrogate tokens in the output that cannot be
          reversed — the reversibility side of the pseudonymisation guarantee.
        """
        ng = NoteGuard(known=known, reverse=state.get("reverse"))
        deid_text = state.get("deid_text") or ""
        residual_pii = ng.scan_pii(deid_text) if deid_text else []
        leaked = list(state.get("leaked_tokens") or [])

        return {
            "residual_pii": residual_pii,
            "leaked_tokens": leaked,
            "residual_count": state.get("residual_count", 0) + len(leaked),
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
