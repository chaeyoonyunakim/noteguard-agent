"""Superlinked retrieval node — PHI-safe semantic search over de-identified notes.

GUARANTEE: every document entering the index and every chunk leaving it passes
through assert_clean(). PHI cannot enter or leave this module.

sentence-transformers >= 5.6 renamed _model_config to _get_model_config(); we add
a compat property before importing superlinked so no site-packages edits are needed.

Note: no `from __future__ import annotations` here — Superlinked's SchemaFactory
inspects class annotations at runtime and needs real type objects, not strings.
"""

# --- compat shim: sentence-transformers 5.6 + superlinked 37 --------------------
try:
    from sentence_transformers import SentenceTransformer as _ST

    if not hasattr(_ST, "_model_config"):
        _ST._model_config = property(  # type: ignore[attr-defined]
            lambda self: self._get_model_config()
        )
except ImportError:
    pass
# ---------------------------------------------------------------------------------

import superlinked.framework as sl

from noteguard.deid import NoteGuard

_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class _NoteSchema(sl.Schema):
    note_id: sl.IdField
    text: sl.String


_note = _NoteSchema()
_space = sl.TextSimilaritySpace(text=_note.text, model=_MODEL)
_index = sl.Index([_space])


class NoteIndex:
    """In-memory Superlinked index over de-identified clinical notes."""

    def __init__(self) -> None:
        self._source = sl.InMemorySource(_note)
        executor = sl.InMemoryExecutor(sources=[self._source], indices=[_index])
        self._app = executor.run()
        self._query = (
            sl.Query(_index)
            .find(_note)
            .select_all()
            .similar(_space.text, sl.Param("query_text"))
            .limit(sl.Param("limit"))
        )
        self._count = 0

    def add_notes(self, notes: list[dict], ng: NoteGuard) -> None:
        """Index de-identified notes. Raises if any PHI is detected."""
        rows = []
        for note in notes:
            text = note.get("text", "")
            ng.assert_clean(text)
            self._count += 1
            rows.append({"note_id": note.get("note_id", str(self._count)), "text": text})
        if rows:
            self._source.put(rows)

    def retrieve(self, query_text: str, ng: NoteGuard, top_k: int = 3) -> list[str]:
        """Return de-identified context chunks. Raises if PHI is found anywhere."""
        ng.assert_clean(query_text)
        if self._count == 0:
            return []
        result = self._app.query(self._query, query_text=query_text, limit=top_k)
        chunks = []
        for entry in result.entries:
            text = str(entry.fields.get("text", ""))
            if text:
                ng.assert_clean(text)
                chunks.append(text)
        return chunks
