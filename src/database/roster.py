"""Roster CSV parsing for Smart Attendance (Phase 0).

Pure validation/parsing -- no database or network access, no Streamlit.
Used by the (future) bulk-enrolment flow to turn a teacher-uploaded CSV
into validated ``{usn, name, subject_code}`` rows before any row touches
the database. Every rejection raises ``ValueError`` naming the CSV row
number (1-based, header is row 1) so the teacher can fix the file.

Canonicalisation decisions (tests / callers must know):
- ``usn`` is stripped and upper-cased (USNs are case-insensitive
  institutional IDs); dedupe is by this canonical form, first row wins.
- ``subject_code`` is stripped and upper-cased (matches
  ``create_subject``, which stores codes upper-cased).
- ``name`` is stripped but its case is preserved.
- Extra columns are ignored; the three required columns may appear in
  any order and with any casing / surrounding whitespace in the header.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Union

REQUIRED_COLUMNS = ("usn", "name", "subject_code")

# A USN is a non-empty identifier of letters/digits (and the separators
# some institutions use). This is intentionally permissive: the roster is
# validated for presence/shape here; existence in the students table is
# the enrolment step's job, not the parser's.
_USN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_/]*$")


def validate_usn(usn: str) -> str:
    """Validate a USN and return its canonical (stripped, upper-cased) form.

    Raises ``ValueError`` for empty / non-string / malformed USNs.
    """
    if not isinstance(usn, str):
        raise ValueError("USN must be a non-empty string")
    candidate = usn.strip().upper()
    if not candidate or not _USN_RE.match(candidate):
        raise ValueError(f"Invalid USN: {usn!r}")
    return candidate


def _normalise_header(fieldnames: list[str] | None) -> dict[str, str]:
    """Map lower-cased stripped header names to the original header names."""
    if not fieldnames:
        raise ValueError("Roster CSV is empty or has no header row")
    mapping: dict[str, str] = {}
    for raw in fieldnames:
        if raw is None:
            continue
        mapping[raw.strip().lower()] = raw
    missing = [col for col in REQUIRED_COLUMNS if col not in mapping]
    if missing:
        raise ValueError(
            "Roster CSV is missing required column(s): " + ", ".join(missing)
        )
    return mapping


def parse_roster_csv(data: Union[bytes, str]) -> list[dict[str, str]]:
    """Parse roster CSV bytes/text into validated rows.

    Returns a list of ``{"usn": ..., "name": ..., "subject_code": ...}``
    dicts, in file order, deduplicated by canonical USN (first occurrence
    wins; later duplicates are dropped silently -- the row is identical
    by USN, so there is nothing to reconcile).

    Raises ``ValueError`` with the offending row number for: empty input,
    missing required columns, or any row with an empty/invalid ``usn``,
    empty ``name``, or empty ``subject_code``. Completely blank lines
    are skipped (they carry no row number in the error sense and are a
    common artefact of spreadsheet exports).
    """
    if isinstance(data, bytes):
        # utf-8-sig tolerates the BOM that Excel writes.
        text = data.decode("utf-8-sig")
    elif isinstance(data, str):
        text = data.lstrip("\ufeff")
    else:
        raise ValueError("Roster CSV must be bytes or str")
    if not text.strip():
        raise ValueError("Roster CSV is empty")

    reader = csv.DictReader(io.StringIO(text))
    header = _normalise_header(reader.fieldnames)
    usn_key, name_key, code_key = (
        header["usn"],
        header["name"],
        header["subject_code"],
    )

    rows: list[dict[str, str]] = []
    seen_usns: set[str] = set()
    for raw_row in reader:
        # csv row number: reader.line_num is the 1-based line of the last
        # line read, header being line 1 -- exactly the number a teacher
        # sees in a spreadsheet.
        row_number = reader.line_num
        if raw_row is None:
            continue
        values = [v for v in raw_row.values() if v is not None and str(v).strip()]
        if not values:
            continue  # blank line

        raw_usn = (raw_row.get(usn_key) or "").strip()
        name = (raw_row.get(name_key) or "").strip()
        subject_code = (raw_row.get(code_key) or "").strip()

        if not raw_usn:
            raise ValueError(f"Row {row_number}: usn is empty")
        try:
            usn = validate_usn(raw_usn)
        except ValueError as exc:
            raise ValueError(f"Row {row_number}: {exc}") from exc
        if not name:
            raise ValueError(f"Row {row_number}: name is empty")
        if not subject_code:
            raise ValueError(f"Row {row_number}: subject_code is empty")

        if usn in seen_usns:
            continue  # dedupe by USN, first occurrence wins
        seen_usns.add(usn)
        rows.append(
            {"usn": usn, "name": name, "subject_code": subject_code.upper()}
        )

    if not rows:
        raise ValueError("Roster CSV contains no data rows")
    return rows
