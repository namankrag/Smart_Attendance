"""Regression tests for the 004/005 live-migration preflight (2026-11-22).

Preflight method: the 2026-11-22 Supabase backup
(smartclass-backup-2026-11-22.dump, pre-001) was restored into a local
Postgres 16.15 + pgvector 0.8.0 copy, then 001 -> 002 (dummy PINs,
local copy only) -> 003 -> 004 -> 005 were applied in order. Three
defects in 004 were found only by running it on that copy:

  A. subjects.teacher_id_legacy was never dropped (Step 9 missed it),
     so 004's own verification query (columns LIKE '%_legacy')
     returned 1 row instead of 0.
  B. match_faces() was declared STABLE but runs
     `SET LOCAL hnsw.iterative_scan` on the global (p_subject_id NULL)
     and large-roster (>500) paths. Postgres rejects SET inside a
     non-volatile function, so both paths failed with:
       ERROR: SET is not allowed in a non-volatile function
     The small-roster path worked, which is why the defect hid.
  C. The pgvector version guard compared versions as text
     (`v_version < '0.8.0'`), which wrongly rejects a future 0.10.0
     ('1' < '8' lexicographically). It now compares int arrays.

These tests assert the fixes in the migration files, the same way
test_migration_sql.py guards 001 against the live 42830 / 42P16 /
42P17 failures. They do not run the migrations (no live DB here).
"""
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
MIG004 = MIGRATIONS / "004_phase1_pgvector.sql"
MIG005 = MIGRATIONS / "005_phase3_privacy.sql"


def _sql(path):
    return path.read_text()


def _code_lines(path):
    return [
        line for line in path.read_text().splitlines()
        if not line.lstrip().startswith("--")
    ]


# --- Fix A: every *_legacy column created by 001 must be dropped by 004 ---

# Columns 001 Step 6 renames to *_legacy (verified against the restored
# copy's schema after 001): students.student_id, teachers.teacher_id,
# subjects.subject_id, subjects.teacher_id, subject_students.student_id,
# subject_students.subject_id, attendance_logs.student_id,
# attendance_logs.subject_id.
LEGACY_COLUMNS = (
    ("students", "student_id_legacy"),
    ("teachers", "teacher_id_legacy"),
    ("subjects", "subject_id_legacy"),
    ("subjects", "teacher_id_legacy"),
    ("subject_students", "student_id_legacy"),
    ("subject_students", "subject_id_legacy"),
    ("attendance_logs", "student_id_legacy"),
    ("attendance_logs", "subject_id_legacy"),
)


def test_004_drops_every_legacy_column_001_created():
    sql = _sql(MIG004)
    for table, column in LEGACY_COLUMNS:
        assert (
            f"alter table {table} drop column if exists {column}" in sql
        ), f"004 never drops {table}.{column} (preflight: 1 _legacy column survived)"


def test_004_drops_subjects_teacher_id_legacy():
    """The missed one: 001 renames subjects.teacher_id -> teacher_id_legacy.

    Without this drop, 004's own verification query
    (columns LIKE '%_legacy') returns 1 row instead of 0.
    """
    sql = _sql(MIG004)
    assert "alter table subjects drop column if exists teacher_id_legacy" in sql


# --- Fix B: match_faces must be VOLATILE so SET LOCAL can run ---

def test_004_match_faces_is_volatile_not_stable():
    """SET LOCAL is rejected in a non-volatile function.

    Preflight: the STABLE version failed the global path
    (p_subject_id NULL) with
      ERROR: SET is not allowed in a non-volatile function
    and the >500-roster path uses the same SET LOCAL, so it would
    fail identically. The function only reads, but VOLATILE is
    required for the SET LOCAL to run.
    """
    sql = _sql(MIG004)
    start = sql.index("create or replace function public.match_faces")
    body = sql[start:start + 800]
    assert "volatile security definer" in body
    assert "stable security definer" not in body
    # The relaxed iterative scan must still be there for HNSW paths.
    assert "hnsw.iterative_scan = 'relaxed_order'" in sql


def test_005_has_no_set_local_in_non_volatile_function():
    """005 must not repeat the 004 defect: no SET LOCAL anywhere, and
    delete_subject_tx must not be declared STABLE."""
    sql = _sql(MIG005)
    assert "set local" not in sql.lower()
    start = sql.index("create or replace function public.delete_subject_tx")
    body = sql[start:start + 400]
    assert "stable" not in body


# --- Fix C: pgvector version guard must compare numerically ---

def test_004_pgvector_version_guard_is_numeric_not_lexicographic():
    """Text compare `v_version < '0.8.0'` wrongly rejects pgvector
    0.10.0 ('1' < '8'). The guard must compare dotted-numeric
    components as integers."""
    sql = _sql(MIG004)
    assert "v_version < '0.8.0'" not in sql
    assert "string_to_array(v_version, '.')::int[]" in sql
    assert "array[0, 8, 0]" in sql
    # The floor itself and the abort are unchanged.
    assert "0.8.0" in sql
    assert "raise exception" in sql


# --- 004/005 RLS: policies call SECURITY DEFINER helpers only (42P17 lesson) ---

def test_004_and_005_policies_use_helpers_not_recursive_exists():
    for path in (MIG004, MIG005):
        code = "\n".join(_code_lines(path))
        assert "for all using (exists (select 1 from" not in code
        assert "for select using (exists (select 1 from" not in code
        assert "security definer" in code


def test_005_tables_rls_and_delete_subject_tx_present():
    sql = _sql(MIG005)
    assert "create table if not exists consent_records" in sql
    assert "create table if not exists parental_consents" in sql
    assert "alter table students add column if not exists date_of_birth date" in sql
    assert "alter table consent_records enable row level security" in sql
    assert "alter table parental_consents enable row level security" in sql
    assert "create or replace function public.delete_subject_tx" in sql
    assert "student_is_self" in sql
    assert "teacher_teaches_student" in sql
    # 005 depends on the 004 helper; the file must say so.
    assert "004" in sql
