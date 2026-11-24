"""Phase 2 load-test deliverable tests.

The locustfile must exist, parse, define the 50-user workload
(logins, attendance lookups, group-photo jobs), and use a real
decodable JPEG payload. No benchmark report is fabricated here: the
test asserts the file documents how to run it, and that no benchmark
numbers are claimed anywhere in the repo.
"""
import ast
import base64
import io
import sys
from pathlib import Path

from PIL import Image

REPO = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, REPO)

LOCUSTFILE = Path(REPO) / "tests/load/locustfile.py"


def test_locustfile_exists_and_parses():
    assert LOCUSTFILE.is_file()
    tree = ast.parse(LOCUSTFILE.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            names.add(node.name)
        if isinstance(node, ast.FunctionDef):
            names.add(node.name)
    assert "AttendanceUser" in names
    assert "group_photo_job" in names
    assert "home_page" in names
    assert "attendance_records" in names


def test_locustfile_documents_50_users_and_no_live_benchmark():
    text = LOCUSTFILE.read_text(encoding="utf-8")
    assert "50" in text
    assert "p50" in text and "p95" in text and "p99" in text
    assert "No live benchmark was run" in text


def test_locustfile_tiny_jpeg_is_a_real_jpeg():
    # Extract the embedded base64 payload and decode it: the load test
    # must submit a real (if tiny) JPEG, not a corrupt blob.
    ns: dict = {}
    src = LOCUSTFILE.read_text(encoding="utf-8")
    # Only the constant definition + helper, without importing locust.
    start = src.index("_TINY_JPEG_B64")
    end = src.index("def _tiny_jpeg_b64")
    exec(src[start:end], ns)  # noqa: S102  # deliberate: runs only the file's own constant + helper
    raw = base64.b64decode(ns["_TINY_JPEG_B64"])
    img = Image.open(io.BytesIO(raw))
    img.load()
    assert img.format == "JPEG"


def test_no_fabricated_benchmark_report_in_repo():
    # A benchmark report must not exist (none was run in Phase 2).
    for name in ("load-report.html", "load-report_stats.csv",
                 "load-report_stats_history.csv", "benchmark-report.md"):
        assert not (Path(REPO) / name).exists()
        assert not (Path(REPO) / "tests/load" / name).exists()
