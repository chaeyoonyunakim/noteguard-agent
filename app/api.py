"""NoteGuard FastAPI backend — PHI-safe REST endpoint for the LangGraph agent.

Exposes:
  GET  /              -> index.html (clinician web UI)
  GET  /health        -> {"status": "ok"}
  GET  /samples       -> paginated list of synthetic notes (requires data/ dir)
  GET  /sample/random -> one random synthetic note
  GET  /sample/{id}   -> full note by clinical_note_id
  POST /summarise     -> {clinician_answer, identifiers_removed, residual_risk,
                          deidentified_excerpt, ok}
  POST /process       -> {clinician_note, ai_note, identifiers, discharge_summary, metrics}

The assert_clean() guarantee is preserved: the graph raises ValueError if any
identifier survives de-identification, which surfaces here as HTTP 422.

Run:  uvicorn app.api:app --reload --port 8000
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from src.deid import NoteGuard, load_known_from_csv

STATIC_DIR = Path(__file__).parent / "static"
_DATA_DIR = Path(__file__).parent.parent / "data"

app = FastAPI(title="NoteGuard API", version="1.1.0")

# ---------------------------------------------------------------------------
# Dataset — loaded once at startup; degrades gracefully when data/ is absent
# ---------------------------------------------------------------------------

_NOTES: list[dict] = []
_DEFAULT_KNOWN: dict | None = None
_PATIENT_NAMES: dict[str, str] = {}  # person_id -> full_name for {{PATIENT}} resolution

try:
    _patients_csv = str(_DATA_DIR / "patients.csv")
    _admissions_csv = str(_DATA_DIR / "admissions.csv")
    _DEFAULT_KNOWN = load_known_from_csv(_patients_csv, _admissions_csv)

    # Build person_id → name lookup for {{PATIENT}} resolution
    with open(_patients_csv, newline="", encoding="utf-8-sig") as _pf:
        for _row in csv.DictReader(_pf):
            _pid = (_row.get("person_id") or "").strip()
            _name = (
                _row.get("full_name")
                or _row.get("patient_name")
                or f"{_row.get('first_name', '').strip()} {_row.get('surname', '').strip()}".strip()
            )
            if _pid and _name:
                _PATIENT_NAMES[_pid] = _name

    with open(_DATA_DIR / "synthetic_clinical_notes.csv", newline="", encoding="utf-8-sig") as _f:
        for _row in csv.DictReader(_f):
            _text = NoteGuard._fix_mojibake(_row["clean_note_text"])
            _NOTES.append(
                {
                    "clinical_note_id": _row["clinical_note_id"],
                    "person_id": _row["person_id"],
                    "note_type": _row.get("note_type", ""),
                    "note_subject": _row.get("note_subject", ""),
                    "excerpt": _text[:120].strip(),
                    "note_text": _text,
                }
            )
except Exception:
    pass  # data/ not present — /samples returns empty, /process still works

# ---------------------------------------------------------------------------
# Per-vault graph cache — key is a hashable snapshot of the known-identifier dict.
# ---------------------------------------------------------------------------

_graph_cache: dict = {}


def _vault_key(known: dict | None) -> tuple | None:
    if not known:
        return None
    return tuple(sorted((k, tuple(sorted(v))) for k, v in known.items()))


def _get_graph(known: dict | None):
    """Return a compiled NoteGuard graph, building it once per distinct vault."""
    key = _vault_key(known)
    if key not in _graph_cache:
        from agent.graph import build_graph

        _graph_cache[key] = build_graph(known=known)
    return _graph_cache[key]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SummariseRequest(BaseModel):
    note: str
    question: str = "Draft an NHS eDischarge summary."
    known: dict | None = None


class SummariseResponse(BaseModel):
    clinician_answer: str
    identifiers_removed: int
    residual_risk: float
    deidentified_excerpt: str
    ok: bool


class ProcessRequest(BaseModel):
    note: str
    question: str = "Draft an NHS eDischarge summary."
    known: dict | None = None
    person_id: str | None = None  # when set, {{PATIENT}} resolves to the real name


class ProcessResponse(BaseModel):
    clinician_note: str
    ai_note: str
    identifiers: list[str]
    discharge_summary: str
    metrics: dict


class SampleItem(BaseModel):
    clinical_note_id: str
    person_id: str
    note_type: str
    excerpt: str


class SamplesResponse(BaseModel):
    total: int
    items: list[SampleItem]


class SampleDetail(BaseModel):
    clinical_note_id: str
    person_id: str
    note_type: str
    note_subject: str
    note_text: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    """Liveness probe — no API keys required."""
    return {"status": "ok", "notes_loaded": len(_NOTES)}


@app.get("/samples", response_model=SamplesResponse)
def samples(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str = Query(""),
    note_type: str = Query(""),
):
    """Paginated list of synthetic notes with optional text/type filter."""
    hits = _NOTES
    if note_type:
        hits = [n for n in hits if n["note_type"] == note_type]
    if q:
        ql = q.lower()
        hits = [n for n in hits if ql in n["note_text"].lower() or ql in n["note_subject"].lower()]
    page = hits[offset : offset + limit]
    return SamplesResponse(
        total=len(hits),
        items=[
            SampleItem(
                clinical_note_id=n["clinical_note_id"],
                person_id=n["person_id"],
                note_type=n["note_type"],
                excerpt=n["excerpt"],
            )
            for n in page
        ],
    )


@app.get("/sample/random", response_model=SampleDetail)
def sample_random():
    """Return one random synthetic note."""
    if not _NOTES:
        raise HTTPException(status_code=404, detail="No notes loaded — run src/fetch_dataset.py first.")
    note = random.choice(_NOTES)
    return SampleDetail(**{k: note[k] for k in SampleDetail.model_fields})


@app.get("/sample/{clinical_note_id}", response_model=SampleDetail)
def sample_by_id(clinical_note_id: str):
    """Return a single synthetic note by its clinical_note_id."""
    for note in _NOTES:
        if note["clinical_note_id"] == clinical_note_id:
            return SampleDetail(**{k: note[k] for k in SampleDetail.model_fields})
    raise HTTPException(status_code=404, detail=f"Note {clinical_note_id!r} not found.")


@app.post("/summarise", response_model=SummariseResponse)
def summarise(req: SummariseRequest):
    """Run the NoteGuard agent and return a PHI-safe discharge summary.

    Raises:
        HTTPException 422: assert_clean() detected surviving PHI.
        HTTPException 500: unexpected agent error.
    """
    known = req.known if req.known is not None else _DEFAULT_KNOWN
    try:
        g = _get_graph(known)
        state = g.invoke({"messages": [HumanMessage(content=req.note + "\n\n" + req.question)]})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # De-id is correct iff nothing leaked to the model AND every surrogate reverses.
    residual_pii = state.get("residual_pii") or []
    leaked = state.get("leaked_tokens") or []
    ok = not residual_pii and not leaked
    return SummariseResponse(
        clinician_answer=state.get("clinician_answer", ""),
        identifiers_removed=len(state.get("forward", {})),
        residual_risk=0.0 if ok else 1.0,
        deidentified_excerpt=(state.get("deid_text") or "")[:400],
        ok=ok,
    )


@app.post("/process", response_model=ProcessResponse)
def process(req: ProcessRequest):
    """Run NoteGuard and return rich output for the clinician UI.

    When req.known is omitted, uses the pre-built vault from data/patients.csv
    so residual-leakage is measured against ground truth identifiers.
    """
    known = req.known if req.known is not None else _DEFAULT_KNOWN
    person_name = _PATIENT_NAMES.get(req.person_id, "Patient") if req.person_id else "Patient"
    try:
        g = _get_graph(known)
        state = g.invoke(
            {
                "messages": [HumanMessage(content=req.note + "\n\n" + req.question)],
                "person_name": person_name,
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    forward = state.get("forward") or {}
    leaked = state.get("leaked_tokens") or []
    residual_pii = state.get("residual_pii") or []
    reversible = not leaked
    deid_ok = not residual_pii and reversible

    return ProcessResponse(
        clinician_note=req.note,
        ai_note=state.get("deid_text", ""),
        identifiers=list(forward.keys()),
        discharge_summary=state.get("clinician_answer", ""),
        metrics={
            # Every metric reports whether reversible pseudonymisation was done correctly.
            "deid_ok": deid_ok,  # overall verdict: nothing leaked AND fully reversible
            "identifiers_removed": len(forward),  # PII spans pseudonymised this turn
            "residual_pii": residual_pii,  # [{type, text}] PII the model still saw
            "residual_pii_count": len(residual_pii),
            "reversible": reversible,  # every surrogate restores to a real value
            "leaked_tokens": leaked,  # orphaned/unresolved surrogate tokens
        },
    )


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
