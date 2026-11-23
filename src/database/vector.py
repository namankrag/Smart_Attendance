"""pgvector access for Smart Attendance (Phase 1).

All face/voice matching against the database goes through the
``match_faces`` RPC defined in ``migrations/004_phase1_pgvector.sql`` —
never by loading embeddings into Python and comparing them there.

Why an RPC, and why two search modes (SPEC Phase 1 item 2):
- pgvector docs: https://supabase.com/docs/guides/database/extensions/pgvector
- HNSW indexes: https://supabase.com/docs/guides/ai/vector-indexes/hnsw-indexes
- HNSW paper (Malkov & Yashunin, 2016): https://arxiv.org/abs/1603.09320
- Roster <= 500: the RPC does an EXACT cosine search over the filtered
  roster (full recall — no approximation, no missed matches).
- Global duplicate-face check, or roster > 500: the RPC uses the HNSW
  index with ``SET LOCAL hnsw.iterative_scan = relaxed_order`` so the
  enrolment filter does not under-retrieve (without it, HNSW can return
  fewer than k rows when the filter discards most approximate
  candidates).

Dimensionality contract:
- Face vectors here are 512-d (ArcFace/AdaFace, Phase 2). The legacy
  128-d dlib vectors in ``students.face_embedding`` are NOT pgvector
  vectors and must never be passed to this module — :func:`match_faces`
  rejects anything that is not a finite 512-d list, and the SQL type
  ``vector(512)`` would reject it too. The legacy dlib pipeline keeps
  its own in-Python matching until Phase 2 replaces it.
- Voice vectors are 192-d (ECAPA-TDNN, Phase 2); there is no voice RPC
  yet — voice matching stays in the pipeline until Phase 2.

The Supabase client used here is the module-level anon client from
``src.database.config`` by default. Callers that have a Google-first
JWT (see ``src.database.auth_session``) should pass their authenticated
client explicitly so RLS ``auth.uid()`` resolves to the signed-in user;
the anon client can only see what the anon RLS policies allow (which,
after migration 003, is nothing on the RLS tables — by design).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

from src.database.config import supabase

try:
    # Phase 3: every template read/match is logged to audit_log
    # (DPDP Act Sec. 8(5) safeguards / GDPR Art. 9 accountability;
    # see src/database/privacy.py). Imported defensively so a missing
    # privacy module can never break matching — logging is best-effort
    # and never raises (see _log_template_access below).
    from src.database.privacy import log_template_access as _privacy_log
except ImportError:  # pragma: no cover - privacy module not present
    _privacy_log = None  # type: ignore[assignment]

FACE_VECTOR_DIM = 512
VOICE_VECTOR_DIM = 192
DEFAULT_TOP_K = 5
MAX_TOP_K = 50

__all__ = [
    "FACE_VECTOR_DIM",
    "VOICE_VECTOR_DIM",
    "validate_vector",
    "match_faces",
    "find_duplicate_face_owner",
]


def validate_vector(vector: Any, dim: int) -> List[float]:
    """Validate an embedding: a finite list of ``dim`` numbers.

    Raises ``ValueError`` otherwise. A zero vector is rejected too: it
    has no direction, so its cosine similarity to anything is undefined
    (pgvector would store it, but matching against it is meaningless).
    """
    if not isinstance(vector, (list, tuple)):
        raise ValueError(f"embedding must be a list of {dim} numbers")
    values = [float(x) for x in vector] if vector else []
    if len(values) != dim:
        raise ValueError(
            f"embedding must have exactly {dim} dimensions, got {len(values)}"
        )
    if not all(math.isfinite(x) for x in values):
        raise ValueError("embedding must contain only finite numbers")
    if not any(values):
        raise ValueError("embedding must not be the zero vector")
    return values


def _log_template_access(subject_id: Optional[str], matches: List[Dict[str, Any]],
                         client: Any = None) -> None:
    """Best-effort audit of one template read (Phase 3).

    Logs the match RPC call to audit_log via privacy.log_template_access
    (identifiers + outcome only — never an embedding). Never raises:
    a logging failure must not break matching, and a missing privacy
    module means "no audit sink", not "no match".
    """
    if _privacy_log is None:
        return
    try:
        for match in matches:
            sid = match.get("student_id")
            if sid is None:
                continue
            _privacy_log(
                str(sid),
                template_kind="face",
                action="match",
                subject_id=subject_id,
                matched=True,
                client=client,
            )
        if not matches:
            _privacy_log(
                "unknown",
                template_kind="face",
                action="match",
                subject_id=subject_id,
                matched=False,
                client=client,
            )
    except Exception:
        # Audit logging is best-effort; matching must not fail because
        # the audit insert did.
        pass


def match_faces(
    subject_id: Optional[str],
    query_embedding: Sequence[float],
    k: int = DEFAULT_TOP_K,
    client: Any = None,
) -> List[Dict[str, Any]]:
    """Top-k face matches for a 512-d query embedding, via the RPC.

    ``subject_id`` scopes the search to that subject's enrolled roster
    (exact search when the roster is <= 500, HNSW above that).
    ``subject_id=None`` runs the GLOBAL duplicate-face check over all
    stored templates (HNSW). Returns a list of
    ``{"student_id": ..., "cosine_similarity": ...}`` sorted by
    similarity, highest first — the RPC never returns raw embeddings.

    Phase 3: every call is audited (template read) in audit_log via
    :func:`src.database.privacy.log_template_access` — identifiers and
    match outcome only, never the query embedding. Audit failure never
    breaks the match.
    """
    query = validate_vector(query_embedding, FACE_VECTOR_DIM)
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError("k must be a positive integer")
    k = min(k, MAX_TOP_K)
    db = supabase if client is None else client
    response = db.rpc(
        "match_faces",
        {"p_subject_id": subject_id, "p_query": query, "p_k": k},
    ).execute()
    results = list(response.data or [])
    _log_template_access(subject_id, results, client=db)
    return results


def find_duplicate_face_owner(
    query_embedding: Sequence[float],
    *,
    exclude_student_id: Optional[str] = None,
    k: int = DEFAULT_TOP_K,
    client: Any = None,
) -> Optional[str]:
    """Student ID of an existing student whose face matches ``query``.

    Global duplicate-face check at registration (Phase 0 audit 7):
    a face that already belongs to another enrolled student must be
    rejected. Returns the matching ``student_id``, or ``None`` when no
    stored template is within the duplicate threshold. ``None`` here
    means "no duplicate found", not "check skipped" — callers must not
    treat it as permission to skip the check.

    The similarity threshold is the caller's decision (the RPC returns
    similarities; this helper only reports the best match). The
    duplicate threshold itself must be calibrated in Phase 2 per
    ISO/IEC 19795-1; until then the caller applies the provisional
    0.85 cosine gate from ``db.FACE_SIMILARITY_THRESHOLD``.
    """
    matches = match_faces(None, query_embedding, k=k, client=client)
    for match in matches:
        sid = match.get("student_id")
        if sid is None:
            continue
        if exclude_student_id is not None and str(sid) == str(exclude_student_id):
            continue
        return str(sid)
    return None
