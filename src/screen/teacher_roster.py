"""Teacher roster import (Phase 2 split of ``teacher_screen``).

Moved verbatim from ``src/screen/teacher_screen.py`` (Phase 2.1):
USN parsing, roster-result normalisation, and the CSV import UI.
The preview table is rendered inside an ``@st.fragment`` (see
``src/ui/fragments.py``) so interacting with it reruns only the
fragment. ``teacher_screen`` re-exports everything here.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from src.database.rest_db import enroll_student_by_usn, enroll_student_to_subject
from src.ui.fragments import records_table_fragment

try:
    from src.database.rest_db import get_enrolled_students  # noqa: F401  (re-exported for callers)
except ImportError:  # pragma: no cover
    get_enrolled_students = None  # type: ignore[assignment]

try:
    from src.database.roster import parse_roster_csv
except ImportError:  # pragma: no cover - roster module has not landed yet
    parse_roster_csv = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _row_usn(row: Dict[str, Any]) -> Optional[str]:
    """USN from a parsed roster row, tolerating header casing variants."""
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for key in ("usn", "student_usn", "university_seat_number", "student_id_or_usn"):
        value = lowered.get(key)
        if value:
            return str(value).strip()
    return None


def _parse_roster_result(result: Any) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Normalise parse_roster_csv output: (rows, errors) tuple or a dict
    with ``rows`` / ``errors`` keys, or a bare list of rows."""
    if isinstance(result, tuple) and len(result) == 2:
        rows, errors = result
        return list(rows or []), [str(e) for e in (errors or [])]
    if isinstance(result, dict):
        return list(result.get("rows") or []), [str(e) for e in (result.get("errors") or [])]
    if isinstance(result, list):
        return list(result), []
    return [], ["Unexpected roster parse result."]


def _roster_import_ui(teacher_id: Any, subjects: List[Dict[str, Any]]) -> None:
    """Roster CSV import. Parsing only shows rows/errors; nothing is
    enrolled until the teacher explicitly approves (checkbox, off by
    default) and clicks Import."""
    with st.container(border=True):
        st.subheader("Import Roster (CSV)")
        st.caption(
            "Upload a class roster CSV to enroll students in bulk. "
            "Rows are only shown for review until you approve the import below."
        )
        sub_opts = {f"{s['name']} ({s['subject_code']})": s["subject_id"] for s in subjects}
        sub_codes = {
            f"{s['name']} ({s['subject_code']})": str(s.get("subject_code", "")).strip().upper()
            for s in subjects
        }
        roster_label = st.selectbox(
            "Subject for roster import", options=list(sub_opts.keys()), key="select_roster_sub"
        )
        roster_file = st.file_uploader(
            "Roster CSV",
            type=["csv"],
            key="roster_csv_upload",
            help="CSV with a USN column (and optionally a name column).",
        )
        if roster_file is None:
            return
        if parse_roster_csv is None:
            logger.error("parse_roster_csv is unavailable")
            st.error("Roster import is not available yet. Please try again later.")
            return
        try:
            # parse_roster_csv takes bytes/str, not an UploadedFile:
            # pass raw bytes first (live UploadedFile has .getvalue()).
            parsed = parse_roster_csv(roster_file.getvalue())
        except Exception:
            logger.exception("Roster CSV parsing failed")
            st.error("Could not parse the roster CSV. Please check the file and try again.")
            return
        rows, errors = _parse_roster_result(parsed)
        st.info(f"Parsed {len(rows)} roster row(s).")
        for err in errors:
            st.warning(err)
        if rows:
            records_table_fragment(pd.DataFrame(rows).head(10))
            if len(rows) > 10:
                st.caption(f"Showing the first 10 of {len(rows)} rows.")
        approve = st.checkbox(
            "I have reviewed the roster above and approve importing these students",
            value=False,
            key="roster_approve_import",
        )
        if st.button(
            "Import Roster",
            type="primary",
            width="stretch",
            key="btn_import_roster",
            disabled=not approve or not rows,
        ):
            subject_id = sub_opts[roster_label]
            expected_code = sub_codes.get(roster_label, "")
            imported, failed = 0, 0
            for row in rows:
                try:
                    # Roster rows are usn, name, subject_code: a row naming
                    # a different subject must not be enrolled here.
                    row_code = (
                        str(row.get("subject_code") or row.get("Subject_Code") or "")
                        .strip()
                        .upper()
                    )
                    if row_code and expected_code and row_code != expected_code:
                        failed += 1
                        continue
                    student_id = (
                        row.get("student_id")
                        if isinstance(row.get("student_id"), str)
                        and len(str(row.get("student_id"))) >= 32
                        else None
                    )
                    usn = _row_usn(row)
                    if student_id is None:
                        if not usn:
                            failed += 1
                            continue
                        enrollment = enroll_student_by_usn(subject_id, usn)
                        if not enrollment:
                            failed += 1
                            continue
                    else:
                        enroll_student_to_subject(student_id, subject_id)
                    imported += 1
                except Exception:
                    logger.exception("Roster import failed for a row")
                    failed += 1
            st.success(f"Imported {imported} student(s) into the subject.")
            if failed:
                st.warning(
                    f"{failed} row(s) could not be imported (unknown USN or an error). Check the ro"
                        f"ster and try again."
                )
            st.rerun()
