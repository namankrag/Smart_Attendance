"""Phase 0 items 2, 10, 12: retry only reads, schema guard, honest claims.
Old code: db_retry retried writes on string-matched errors; README/UI
claimed printed photos/replays were blocked.
"""
import pathlib
import pytest


def test_write_decorator_does_not_retry(monkeypatch):
    from src.database import config
    calls = {"n": 0}

    @config.db_retry_write
    def flaky():
        calls["n"] += 1
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        flaky()
    assert calls["n"] == 1  # old db_retry would have retried 3 times


def test_read_decorator_retries_transient_only(monkeypatch):
    import httpx
    from src.database import config
    calls = {"n": 0}

    @config.db_retry_read(max_retries=3, initial_delay=0.001)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("transient")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_schema_guard_fails_loudly_on_pinless_students(monkeypatch, fake_db):
    from src.database.config import check_pin_schema_guard
    # fake_db students[0] has pin_hash None -> guard must raise.
    with pytest.raises(RuntimeError):
        check_pin_schema_guard(supabase_client=fake_db)


def test_readme_has_no_unsupported_pad_claim():
    readme = pathlib.Path(__file__).parent.parent / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "printed photos are strictly rejected" not in text.lower()
    assert "strictly rejected" not in text.lower()
    assert "Honest Threat Model" in text or "honest threat" in text.lower()


@pytest.mark.parametrize("requirements_file", ["requirements.txt", "requirements-ui.txt"])
def test_pyarrow_stays_compatible_with_numpy_1(requirements_file):
    requirements = pathlib.Path(__file__).parent.parent / requirements_file
    text = requirements.read_text(encoding="utf-8")

    assert "numpy>=1.26,<2" in text
    assert "pyarrow>=16,<26" in text
