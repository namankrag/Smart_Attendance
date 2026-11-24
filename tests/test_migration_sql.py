"""Regression test for migration 001 error 42830.

Live run 2026-11-22 failed with:
  ERROR: 42830: there is no unique constraint matching given keys
  for referenced table "subjects"

Cause: attendance_sessions was created with inline
`references subjects(id)` / `references teachers(id)` before those
UUID columns became primary keys in Step 6. Postgres requires the
referenced columns to be unique at CREATE TABLE time.
Fix: no inline REFERENCES in Step 2; FKs are added in Step 6 after
the PKs exist, as fk_session_subject / fk_session_teacher.
"""
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "001_phase0_core.sql"


def _sql():
    return MIGRATION.read_text(encoding="utf-8")


def _code_lines():
    # Ignore -- comments, which may quote the old failing SQL for context.
    return [
        line for line in _sql().splitlines()
        if not line.lstrip().startswith("--")
    ]


def test_no_inline_reference_to_unkeyed_uuid_columns():
    code = "\n".join(_code_lines())
    assert "references subjects(id)" not in code
    assert "references teachers(id)" not in code


def test_session_fks_added_after_subject_and_teacher_pks():
    sql = _sql()
    assert "add constraint fk_session_subject" in sql
    assert "add constraint fk_session_teacher" in sql
    pk_subject = sql.index("alter table subjects add primary key (subject_id)")
    pk_teacher = sql.index("alter table teachers add primary key (teacher_id)")
    fk_subject = sql.index("add constraint fk_session_subject")
    fk_teacher = sql.index("add constraint fk_session_teacher")
    assert pk_subject < fk_subject
    assert pk_teacher < fk_teacher


def test_old_pks_and_fks_dropped_before_new_pks_42p16():
    """Live run 2026-11-22, second failure: 42P16 multiple primary keys.

    The live tables already have students_pkey / teachers_pkey /
    subjects_pkey / subject_students_pkey, and FKs referencing them.
    Renaming the PK column carries the PK with it, so adding a second
    PK fails, and renaming a UUID column to student_id fails while
    the legacy integer column still has that name.
    """
    sql = _sql()
    for name in (
        "students_pkey",
        "teachers_pkey",
        "subjects_pkey",
        "subject_students_pkey",
        "attendance_logs_student_id_fkey",
        "subject_students_student_id_fkey",
        "subjects_teacher_id_fkey",
    ):
        assert f"drop constraint if exists {name}" in sql
    drop_pk = sql.index("drop constraint if exists students_pkey")
    add_pk = sql.index("alter table students add primary key (student_id)")
    assert drop_pk < add_pk
    # Legacy FK columns must be renamed before the UUID columns take
    # their canonical names, in every FK table.
    legacy_enroll = sql.index(
        "alter table subject_students rename column student_id to student_id_legacy"
    )
    uuid_enroll = sql.index(
        "alter table subject_students rename column student_uuid to student_id"
    )
    assert legacy_enroll < uuid_enroll
    legacy_log = sql.index(
        "alter table attendance_logs rename column student_id to student_id_legacy"
    )
    uuid_log = sql.index(
        "alter table attendance_logs rename column student_uuid to student_id"
    )
    assert legacy_log < uuid_log
    legacy_subject = sql.index(
        "alter table subjects rename column teacher_id to teacher_id_legacy"
    )
    uuid_subject = sql.index(
        "alter table subjects rename column teacher_uuid to teacher_id"
    )
    assert legacy_subject < uuid_subject


def test_rls_policies_use_security_definer_helpers_not_recursive_exists_42p17():
    """Live run 2026-11-22, third failure: 42P17 infinite recursion.

    Policies in 001 Step 7 directly referenced other RLS tables
    (subjects -> subject_students -> subjects), so every read on
    subjects / attendance_logs failed with 42P17. Policies must only
    call SECURITY DEFINER helpers; the helpers do the cross-table
    check while bypassing RLS.
    """
    from pathlib import Path

    mig1 = Path(__file__).resolve().parents[1] / "migrations" / "001_phase0_core.sql"
    mig3 = Path(__file__).resolve().parents[1] / "migrations" / "003_fix_rls_recursion.sql"
    assert mig3.exists()
    for path in (mig1, mig3):
        sql = path.read_text(encoding="utf-8")
        assert "security definer" in sql
        assert "teacher_owns_subject" in sql
        assert "student_enrolled_in_subject" in sql
        assert "student_is_self" in sql
        # No policy USING clause may directly EXISTS-select from another
        # RLS table. Check the code lines, ignoring -- comments.
        code = "\n".join(
            line for line in sql.splitlines() if not line.lstrip().startswith("--")
        )
        assert "for all using (exists (select 1 from subjects" not in code
        assert "for select using (exists (select 1 from subject_students" not in code
        assert "for all using (exists (select 1 from subjects sub" not in code
