"""Regression tests for migration 004_phase1_pgvector.sql (Phase 1).

The migration is local-only (never run live by tests or code); these
tests assert its contents, the same way test_migration_sql.py guards
001 against the live 42830 / 42P16 / 42P17 failures.
"""
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "004_phase1_pgvector.sql"


def _sql():
    return MIGRATION.read_text()


def _code_lines():
    return [
        line for line in _sql().splitlines()
        if not line.lstrip().startswith("--")
    ]


def test_migration_file_exists_with_sql_editor_instructions():
    sql = _sql()
    assert "SQL Editor" in sql
    assert "BACK UP FIRST" in sql
    assert "tomhefyrrwjdyaddlidg" in sql


def test_pgvector_extension_with_version_guard():
    sql = _sql()
    assert "create extension if not exists vector" in sql
    assert "0.8.0" in sql
    assert "raise exception" in sql  # guard aborts on an older version


def test_embedding_tables_and_hnsw_cosine_indexes():
    sql = _sql()
    assert "create table if not exists face_embeddings" in sql
    assert "embedding vector(512)" in sql
    assert "norm_quality" in sql
    assert "model_version" in sql
    assert "create table if not exists voice_embeddings" in sql
    assert "embedding vector(192)" in sql
    assert "using hnsw (embedding vector_cosine_ops)" in sql
    assert sql.count("using hnsw (embedding vector_cosine_ops)") == 2


def test_match_faces_rpc_exact_and_hnsw_paths():
    sql = _sql()
    assert "create or replace function public.match_faces" in sql
    assert "p_subject_id uuid" in sql
    assert "p_query vector(512)" in sql
    # Roster <= 500: exact search (full recall).
    assert "v_roster <= 500" in sql
    # Global check / large roster: HNSW with relaxed iterative scan.
    assert "hnsw.iterative_scan = 'relaxed_order'" in sql
    # Returns similarities, never raw embeddings.
    assert "cosine_similarity double precision" in sql
    assert "1 - (fe.embedding <=> p_query)" in sql


def test_enrollments_view_over_subject_students_not_a_rename():
    sql = _sql()
    assert "create or replace view public.enrollments" in sql
    assert "from subject_students" in sql
    # The live table is NOT renamed.
    assert "rename table subject_students" not in sql.lower()
    assert "alter table subject_students" in sql  # enrolled_at only
    assert "enrolled_at timestamptz" in sql


def test_inference_jobs_and_audit_log():
    sql = _sql()
    assert "create table if not exists inference_jobs" in sql
    for col in ("type", "status", "progress", "result_json", "error",
                "created_at", "expires_at"):
        assert col in sql
    assert "create table if not exists audit_log" in sql
    assert "revoke update, delete on audit_log" in sql


def test_sql_views_count_from_enrolled_at():
    sql = _sql()
    assert "create or replace view public.v_session_counts" in sql
    assert "create or replace view public.v_attendance_percentages" in sql
    # Absences count only sessions on/after enrolment (audit 27).
    assert "s.started_at >= ss.enrolled_at" in sql
    assert "attendance_percentage" in sql


def test_rls_on_new_tables_with_security_definer_helpers():
    sql = _sql()
    for table in ("face_embeddings", "voice_embeddings", "inference_jobs"):
        assert f"alter table {table} enable row level security" in sql
    assert "teacher_teaches_student" in sql
    assert "security definer" in sql
    # Policies call helpers only — no direct cross-table EXISTS in a
    # USING clause (the 42P17 lesson from 001/003).
    code = "\n".join(_code_lines())
    assert "for all using (exists (select 1 from" not in code


def test_legacy_integer_columns_dropped_idempotently_and_guarded():
    sql = _sql()
    for stmt in (
        "alter table students drop column if exists student_id_legacy",
        "alter table teachers drop column if exists teacher_id_legacy",
        "alter table subjects drop column if exists subject_id_legacy",
        "alter table subject_students drop column if exists student_id_legacy",
        "alter table subject_students drop column if exists subject_id_legacy",
        "alter table attendance_logs drop column if exists student_id_legacy",
        "alter table attendance_logs drop column if exists subject_id_legacy",
    ):
        assert stmt in sql
    # Guard: abort if any UUID PK is still NULL before dropping.
    assert "student_id is null" in sql
    assert "aborting legacy drop" in sql


def test_all_timestamps_timestamptz():
    sql = _sql()
    assert "timestamptz" in sql
    # No naive `timestamp` (without tz) column definitions.
    for line in _code_lines():
        stripped = line.strip()
        if stripped.startswith("created_at") or stripped.startswith("expires_at"):
            assert "timestamptz" in line
