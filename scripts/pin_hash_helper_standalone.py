"""Standalone PIN-hash helper for Smart Attendance (Phase 0).

Use this version if you do NOT have the Phase 0 repo on your own
computer. It is a single file, with no import from src/database/auth.py.

It uses the exact same Argon2id parameters as the app
(OWASP: time_cost=2, memory 19 MiB, parallelism 1, hash_len 32,
salt_len 16), so a hash made here verifies in the app.

Run on your own computer, in a terminal / Command Prompt, in any
folder where you saved this file:

    pip install argon2-cffi
    python pin_hash_helper_standalone.py --usn LEGACY-5

It prompts twice (hidden input) for a 4-6 digit PIN, verifies the
hash round-trips, then prints ONLY the hash and the SQL to run in
the Supabase SQL Editor:

    UPDATE students SET pin_hash = '<hash>' WHERE usn = '<usn>';

Safety: the PIN is never printed, logged, or written to a file.
Never pass it on the command line. This script never connects to
Supabase and never writes to the database.
"""

from __future__ import annotations

import argparse
import getpass
import re
import sys

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerificationError
except Exception as exc:  # pragma: no cover
    PasswordHasher = None  # type: ignore[assignment]
    VerificationError = Exception  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

_PIN_RE = re.compile(r"^[0-9]{4,6}$")


def _hasher() -> "PasswordHasher":
    if PasswordHasher is None:
        raise RuntimeError(
            "argon2-cffi is not installed. Run: pip install argon2-cffi "
            f"({_IMPORT_ERROR})"
        )
    return PasswordHasher(
        time_cost=2, memory_cost=19 * 1024, parallelism=1,
        hash_len=32, salt_len=16,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate an Argon2id hash for one student's PIN (offline, standalone)."
    )
    parser.add_argument("--usn", required=True, help="e.g. LEGACY-5")
    args = parser.parse_args(argv)
    usn = args.usn.strip()
    if not usn or "'" in usn or "\\" in usn:
        print("error: --usn must be a plain USN with no quotes", file=sys.stderr)
        return 2
    first = getpass.getpass("Enter new 4-6 digit PIN (hidden): ")
    second = getpass.getpass("Re-enter PIN to confirm (hidden): ")
    if first != second:
        print("error: PINs did not match — nothing was generated. Run again.", file=sys.stderr)
        return 2
    pin = first.strip()
    if not _PIN_RE.match(pin):
        print("error: PIN must be 4-6 digits only", file=sys.stderr)
        return 2
    try:
        hasher = _hasher()
        pin_hash = hasher.hash(pin)
        try:
            hasher.verify(pin_hash, pin)
        except VerificationError:
            print("error: generated hash failed to verify — nothing printed", file=sys.stderr)
            return 2
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        pin = ""
    print(f"-- PIN hash for USN {usn} (generated locally; PIN never printed or stored)")
    # The UPDATE is printed for the operator to paste into the SQL Editor;
    # this script never executes SQL itself.
    print(f"UPDATE students SET pin_hash = '{pin_hash}' WHERE usn = '{usn}';")  # noqa: S608
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
