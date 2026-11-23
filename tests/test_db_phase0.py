"""Phase 0 items 7-10: roster, join codes, ownership, pagination,
idempotent writes. Old code: subject_code was the join key, no
ownership checks, unbounded reads, plain-insert attendance duplicates.
"""

import pytest
from src.database import db as dbmod
from src.database.roster import parse_roster_csv, validate_usn

TEACHER = "33333333-3333-3333-3333-333333333333"
OTHER_TEACHER = "99999999-9999-9999-9999-999999999999"
SUBJECT = "44444444-4444-4444-4444-444444444444"
STUDENT = "11111111-1111-1111-1111-111111111111"


def test_roster_parses_and_dedupes_by_usn():
    rows = parse_roster_csv(
        b"usn,name,subject_code\n1ms21cs001,Asha,MPW\n1MS21CS001,Asha,MPW\n1MS21CS002,Ben,MPW\n"
    )
    assert [r["usn"] for r in rows] == ["1MS21CS001", "1MS21CS002"]
    assert rows[0]["subject_code"] == "MPW"


def test_roster_rejects_bad_rows_with_row_number():
    with pytest.raises(ValueError) as exc:
        parse_roster_csv("usn,name,subject_code\n,NoName,MPW\n")
    assert "Row 2" in str(exc.value)
    with pytest.raises(ValueError):
        parse_roster_csv("usn,name\n1MS21CS001,Asha\n")


def test_validate_usn_canonicalises():
    assert validate_usn(" 1ms21cs001 ") == "1MS21CS001"
    with pytest.raises(ValueError):
        validate_usn("")


def test_join_code_separate_from_subject_code(monkeypatch, fake_db):
    monkeypatch.setattr(dbmod, "supabase", fake_db)
    # Two sections share subject_code MPW but have different join codes.
    a = dbmod.get_subject_by_join_code("abc-123_XYZ")
    b = dbmod.get_subject_by_join_code("def-456_UVW")
    assert a["subject_id"] != b["subject_id"]
    assert a["subject_code"] == b["subject_code"] == "MPW"
    assert dbmod.get_subject_join_code(SUBJECT) == "abc-123_XYZ"
    assert dbmod.get_subject_by_join_code("MPW") is None


def test_create_subject_generates_join_code(monkeypatch, fake_db):
    monkeypatch.setattr(dbmod, "supabase", fake_db)
    rows = dbmod.create_subject("CS101", "Intro", "A", TEACHER)
    assert rows[0]["join_code"]
    assert rows[0]["join_code"] != "CS101"


def test_enrolled_students_and_is_enrolled(monkeypatch, fake_db):
    monkeypatch.setattr(dbmod, "supabase", fake_db)
    assert dbmod.is_student_enrolled(STUDENT, SUBJECT) is True
    assert dbmod.is_student_enrolled(STUDENT, "55555555-5555-5555-5555-555555555555") is False
    rows = dbmod.get_enrolled_students(SUBJECT)
    assert len(rows) == 1


def test_ownership_checks_block_other_teacher(monkeypatch, fake_db):
    monkeypatch.setattr(dbmod, "supabase", fake_db)
    with pytest.raises(PermissionError):
        dbmod.get_session_details(SUBJECT, "2026-09-20T09:41:07+00:00", teacher_id=OTHER_TEACHER)
    # A log that exists, in this teacher's subject, must be blocked for
    # the other teacher (PermissionError, not ValueError) and allowed
    # for the owner.
    fake_db.tables["attendance_logs"].append(
        {
            "id": "log-1",
            "session_id": "sess-1",
            "student_id": STUDENT,
            "subject_id": SUBJECT,
            "timestamp": "2026-09-20T09:41:07+00:00",
            "is_present": False,
        }
    )
    with pytest.raises(PermissionError):
        dbmod.update_attendance_status("log-1", True, teacher_id=OTHER_TEACHER)
    assert dbmod.update_attendance_status("log-1", True, teacher_id=TEACHER)
    assert fake_db.tables["attendance_logs"][0]["is_present"] is True
    # A nonexistent log is a ValueError, not an ownership bypass.
    with pytest.raises(ValueError):
        dbmod.update_attendance_status("nope", True, teacher_id=TEACHER)
    with pytest.raises(PermissionError):
        dbmod.delete_subject(SUBJECT, teacher_id=OTHER_TEACHER)
    assert fake_db.tables["subjects"]  # nothing deleted


def test_pagination_validates_and_caps(monkeypatch, fake_db):
    monkeypatch.setattr(dbmod, "supabase", fake_db)
    with pytest.raises(ValueError):
        dbmod.get_all_students(limit=1001)
    with pytest.raises(ValueError):
        dbmod.get_all_students(limit=10, offset=-1)
    assert len(dbmod.get_all_students(limit=1, offset=0)) == 1
    assert dbmod.get_all_students(limit=10, offset=10) == []


def test_idempotent_attendance_upsert(monkeypatch, fake_db):
    monkeypatch.setattr(dbmod, "supabase", fake_db)
    session = dbmod.create_session(SUBJECT, TEACHER, "face")
    sid = session["session_id"]
    logs = [
        {
            "student_id": STUDENT,
            "subject_id": SUBJECT,
            "timestamp": "2026-11-22T09:00:00+00:00",
            "is_present": True,
        }
    ]
    dbmod.create_attendance_upsert(logs, sid)
    logs[0]["is_present"] = False
    dbmod.create_attendance_upsert(logs, sid)
    rows = fake_db.tables["attendance_logs"]
    assert len(rows) == 1  # old plain insert would have created 2 rows
    assert rows[0]["is_present"] is False
    assert rows[0]["session_id"] == sid


def test_create_session_requires_subject_owner(monkeypatch, fake_db):
    monkeypatch.setattr(dbmod, "supabase", fake_db)
    with pytest.raises(PermissionError):
        dbmod.create_session(SUBJECT, OTHER_TEACHER, "face")
    with pytest.raises(ValueError):
        dbmod.create_session(SUBJECT, TEACHER, "telepathy")
