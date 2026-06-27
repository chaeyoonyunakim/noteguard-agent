"""NoteGuard FastAPI backend — PHI-safe REST endpoint for the LangGraph agent.

Exposes:
  GET  /         -> index.html (clinician web UI)
  GET  /health   -> {"status": "ok"}
  POST /summarise -> {clinician_answer, identifiers_removed, residual_risk,
                      deidentified_excerpt, ok}
  POST /process  -> {clinician_note, ai_note, identifiers, discharge_summary, metrics}

The assert_clean() guarantee is preserved: the graph raises ValueError if any
identifier survives de-identification, which surfaces here as HTTP 422.

Run:  uvicorn app.api:app --reload --port 8000
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

STATIC_DIR = Path(__file__).parent / "static"

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


class ProcessRequest(BaseModel):
    note: str
    question: str = "Draft a discharge summary."
    known: dict | None = None


class ProcessResponse(BaseModel):
    clinician_note: str
    ai_note: str
    identifiers: list[str]
    discharge_summary: str
    metrics: dict


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


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
        state = g.invoke({"messages": [HumanMessage(content=req.note + "\n\n" + req.question)]})
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


@app.post("/process", response_model=ProcessResponse)
def process(req: ProcessRequest):
    """Run NoteGuard and return rich output for the clinician UI.

    Returns the original note, the de-identified note the model saw,
    the list of redacted identifier strings (for highlighting), the
    Gemini-drafted discharge summary (re-identified), and trust metrics.
    """
    try:
        g = _get_graph(req.known)
        state = g.invoke({"messages": [HumanMessage(content=req.note + "\n\n" + req.question)]})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    forward = state.get("forward") or {}
    residual = state.get("residual_count", 0)
    retrieved = state.get("retrieved_context") or []
    faith = state.get("faithfulness_score", 0.0)

    return ProcessResponse(
        clinician_note=req.note,
        ai_note=state.get("deid_text", ""),
        identifiers=list(forward.keys()),
        discharge_summary=state.get("clinician_answer", ""),
        metrics={
            "identifiers_removed": len(forward),
            "residual_risk": 0.0 if residual == 0 else 1.0,
            "grounded_sources": len(state.get("sources") or []),
            "faithfulness": faith if retrieved else None,
        },
    )


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
