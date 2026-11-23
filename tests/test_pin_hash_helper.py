"""End-to-end tests for scripts/pin_hash_helper.py.

Drives the script as a subprocess with the PIN on stdin (getpass falls
back to stdin without a tty). Asserts the printed hash verifies, the
PIN itself never appears in the output, and bad/mismatched PINs fail
without printing a hash.
"""
import re
import subprocess
import sys
from pathlib import Path

from src.database.auth import verify_credential

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "pin_hash_helper.py"
HASH_RE = re.compile(r"\$argon2id\$[^\s'\";]+")


def _run(usn: str, stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # fixed argv: own interpreter + repo script; no shell
        [sys.executable, str(SCRIPT), "--usn", usn],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
        shell=False,
    )


def test_helper_prints_verifying_hash_and_sql_without_pin():
    result = _run("1MS21CS002", "1234\n1234\n")
    assert result.returncode == 0, result.stderr
    assert "1234" not in result.stdout, "PIN must never be printed"
    assert "1234" not in result.stderr
    match = HASH_RE.search(result.stdout)
    assert match, result.stdout
    assert verify_credential("1234", match.group(0))[0] is True
    assert verify_credential("9999", match.group(0))[0] is False
    assert "UPDATE students SET pin_hash =" in result.stdout
    assert "WHERE usn = '1MS21CS002'" in result.stdout


def test_helper_rejects_mismatched_pin():
    result = _run("1MS21CS002", "1234\n9999\n")
    assert result.returncode != 0
    assert "$argon2id$" not in result.stdout


def test_helper_rejects_short_pin():
    result = _run("1MS21CS002", "123\n123\n")
    assert result.returncode != 0
    assert "$argon2id$" not in result.stdout
