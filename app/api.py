"""NoteGuard FastAPI backend — PHI-safe REST endpoint for the LangGraph agent.

Exposes:
  GET  /health      -> {"status": "ok"}
  POST /summarise   -> {clinician_answer, identifiers_removed, residual_risk,
                        deidentified_excerpt, ok}

The assert_clean() guarantee is preserved: the graph raises ValueError if any
identifier survives de-identification, which surfaces here as HTTP 422.

Run:  uvicorn app.api:app --reload --port 8000
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

app = FastAPI(title="NoteGuard API", version="0.1.0")

# Per-vault graph cache — key is a hashable snapshot of the known-identifier dict.
_graph_cache: dict = {}


def _vault_key(known: dict | None) -> tuple | None:
    """Convert a known-identifier dict to a hashable cache key."""
    if not known:
        return None
    return tuple(sorted((k, tuple(sorted(v))) for k, v in known.items()))


def _get_graph(known: dict | None):
    """Return a compiled NoteGuard graph, building it once per distinct vault."""
    key = _vault_key(known)
    if key not in _graph_cache:
        # Lazy import — agent.graph needs API keys; /health must not trigger this.
        from agent.graph import build_graph

        _graph_cache[key] = build_graph(known=known)
    return _graph_cache[key]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SummariseRequest(BaseModel):
    note: str
    question: str = "Draft a discharge summary."
    known: dict | None = None


class SummariseResponse(BaseModel):
    clinician_answer: str
    identifiers_removed: int
    residual_risk: float
    deidentified_excerpt: str
    ok: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health():
    """Liveness probe — no API keys required."""
    return {"status": "ok"}


@app.post("/summarise", response_model=SummariseResponse)
def summarise(req: SummariseRequest):
    """Run the NoteGuard agent and return a PHI-safe discharge summary.

    Raises:
        HTTPException 422: assert_clean() detected surviving PHI.
        HTTPException 500: unexpected agent error.
    """
    try:
        g = _get_graph(req.known)
        state = g.invoke(
            {"messages": [HumanMessage(content=req.note + "\n\n" + req.question)]}
        )
    except ValueError as exc:
        # assert_clean() raised — a PHI identifier survived de-identification.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    residual = state.get("residual_count", 0)
    return SummariseResponse(
        clinician_answer=state.get("clinician_answer", ""),
        identifiers_removed=len(state.get("forward", {})),
        residual_risk=0.0 if residual == 0 else 1.0,
        deidentified_excerpt=(state.get("deid_text") or "")[:400],
        ok=residual == 0,
    )
