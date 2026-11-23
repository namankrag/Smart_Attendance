"""Offline PIN-hash helper for Smart Attendance (Phase 0).

Purpose: set an Argon2id PIN hash for one existing student, so the
``002_phase0_pin_enforcement.sql`` NOT NULL guard can pass, without
sending any PIN in chat, email, or a ticket.

Run locally, from the repo root, one student at a time::

    python scripts/pin_hash_helper.py --usn 1MS21CS002

The script prompts twice (hidden input, ``getpass``) for a 4-6 digit PIN,
hashes it with the *same* function the app uses
(``src.database.auth.hash_pin`` — Argon2id, OWASP parameters:
time_cost=2, memory 19 MiB, parallelism 1), verifies the hash
round-trips with ``verify_credential`` before printing anything, and
then prints ONLY the hash and the SQL to run in the Supabase SQL Editor::

    UPDATE students SET pin_hash = '<hash>' WHERE usn = '<usn>';

Safety rules, by design:
- The PIN is never printed, logged, or written to any file. Only the
  hash leaves this process. Do not paste a PIN into a shell command
  (it would land in shell history); always type it at the prompt.
- This script never connects to Supabase and never writes to the
  database. Applying the printed SQL is a separate, deliberate step
  in the Supabase SQL Editor, after the manual backup and after
  ``001_phase0_core.sql`` has been run.
- The USN is matched exactly. After 001, students with no USN get
  ``usn = 'LEGACY-<old integer id>'`` (see 001); use that value for
  legacy rows, e.g. ``--usn LEGACY-5``.
- Run ``002`` only after the check in that file returns 0:
  ``select count(*) from students where pin_hash is null or pin_hash = '';``

References: OWASP Password Storage Cheat Sheet
https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

# Allow running as ``python scripts/pin_hash_helper.py`` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database.auth import hash_pin, validate_pin, verify_credential  # noqa: E402


def _prompt_pin() -> str:
    """Prompt twice for a PIN; return it only if both entries match."""
    first = getpass.getpass("Enter new 4-6 digit PIN (hidden): ")
    second = getpass.getpass("Re-enter PIN to confirm (hidden): ")
    if first != second:
        raise ValueError("PINs did not match — nothing was generated. Run again.")
    return validate_pin(first)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate an Argon2id hash for one student's PIN (offline, local only)."
    )
    parser.add_argument(
        "--usn",
        required=True,
        help="Student USN to target in the printed UPDATE (e.g. 1MS21CS002, or LEGACY-5 after migra"
            "tion 001).",
    )
    args = parser.parse_args(argv)

    usn = args.usn.strip()
    if not usn:
        print("error: --usn must not be empty", file=sys.stderr)
        return 2
    if "'" in usn or "\\" in usn:
        print("error: USN contains a quote/backslash; refusing to build SQL", file=sys.stderr)
        return 2

    pin = ""
    try:
        pin = _prompt_pin()
        pin_hash = hash_pin(pin)
        # Fail closed: never hand out a hash that does not verify.
        ok, _needs_rehash = verify_credential(pin, pin_hash)
        if not ok:
            print("error: generated hash failed to verify — nothing printed", file=sys.stderr)
            return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:  # argon2-cffi missing
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        # Drop the plaintext from this process as soon as we are done.
        pin = ""

    print(f"-- PIN hash for USN {usn} (generated locally; PIN never printed or stored)")
    print("-- Run in Supabase SQL Editor, after backup + migration 001:")
    # The UPDATE is printed for the operator to paste into the SQL Editor;
    # this script never executes SQL itself.
    print(f"UPDATE students SET pin_hash = '{pin_hash}' WHERE usn = '{usn}';")  # noqa: S608
    print("-- Then confirm: select count(*) from students where pin_hash is null;")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
