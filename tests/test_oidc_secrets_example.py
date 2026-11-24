"""Regression test: Streamlit OIDC secrets template (Phase 1).

With a named OIDC provider (``st.login("google")``), Streamlit
requires the shared settings ``redirect_uri`` and ``cookie_secret``
in ``[auth]``, while ``[auth.google]`` holds ONLY ``client_id``,
``client_secret`` and ``server_metadata_url``. An earlier version of
``.streamlit/secrets.toml.example`` had no ``[auth]`` section at all
and the ``auth_session.py`` docstring told Naman to register Google
via ``[auth.google]`` only — putting the shared settings there is
ignored by Streamlit and login breaks. These tests pin the correct
layout and that the example file contains placeholders only, never
real secrets.
"""
import pathlib
import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib

EXAMPLE_PATH = (
    pathlib.Path(__file__).parent.parent
    / ".streamlit"
    / "secrets.toml.example"
)


def _load_example():
    if not EXAMPLE_PATH.is_file():
        pytest.skip("No public secrets template in this workspace; local secrets are not inspected")
    text = EXAMPLE_PATH.read_text(encoding="utf-8")
    with EXAMPLE_PATH.open("rb") as fh:
        data = tomllib.load(fh)
    return text, data


def test_auth_section_has_redirect_uri_and_cookie_secret():
    _, data = _load_example()
    assert "auth" in data, "[auth] section is missing from secrets.toml.example"
    auth = data["auth"]
    assert "redirect_uri" in auth, "[auth] must define redirect_uri"
    assert "oauth2callback" in auth["redirect_uri"], (
        "[auth] redirect_uri must end in /oauth2callback, got: "
        f"{auth['redirect_uri']!r}"
    )
    assert "cookie_secret" in auth, "[auth] must define cookie_secret"
    cookie_secret = auth["cookie_secret"]
    assert isinstance(cookie_secret, str) and cookie_secret.strip()
    # Placeholder only — never a real-looking secret.
    assert cookie_secret == "<strong-random-secret>", (
        "cookie_secret must stay the placeholder "
        "'<strong-random-secret>', got a real-looking value"
    )


def test_auth_google_section_has_only_provider_credentials():
    _, data = _load_example()
    assert "auth" in data and "google" in data["auth"], (
        "[auth.google] section is missing from secrets.toml.example"
    )
    google = data["auth"]["google"]
    assert google["client_id"] == "YOUR-GOOGLE-OAUTH-CLIENT-ID"
    assert google["client_secret"] == "YOUR-GOOGLE-OAUTH-CLIENT-SECRET"
    assert "accounts.google.com" in google["server_metadata_url"], (
        "server_metadata_url must point at Google's OIDC discovery "
        f"document, got: {google['server_metadata_url']!r}"
    )
    # Shared settings belong in [auth], NOT under [auth.google].
    assert "redirect_uri" not in google, (
        "redirect_uri must live in [auth], not [auth.google]"
    )
    assert "cookie_secret" not in google, (
        "cookie_secret must live in [auth], not [auth.google]"
    )


def test_example_contains_no_real_secrets():
    text, data = _load_example()
    # The real Supabase project slug must never appear in the example.
    assert "tomhefyrrwjdyaddlidg" not in text
    # Every supabase.co URL must be the placeholder, not a real project.
    for line in text.splitlines():
        if "supabase.co" in line:
            assert "YOUR-PROJECT" in line, (
                "non-placeholder supabase.co URL in example file: "
                f"{line.strip()!r}"
            )
    # No real Google client secret (real ones start with GOCSPX-).
    assert "GOCSPX-" not in text
    # Parsed values must all be placeholders, not real credentials.
    assert data["SUPABASE_KEY"] == "YOUR-SUPABASE-ANON-KEY"
    assert data["auth"]["google"]["client_secret"] == (
        "YOUR-GOOGLE-OAUTH-CLIENT-SECRET"
    )


def test_example_keeps_supabase_and_app_url_placeholders():
    _, data = _load_example()
    assert data["SUPABASE_URL"] == "https://YOUR-PROJECT.supabase.co"
    assert "APP_URL" in data


def test_example_notes_deployed_redirect_uri():
    text, _ = _load_example()
    assert "streamlit.app/oauth2callback" in text, (
        "example must note the deployed redirect_uri replaces the "
        "localhost one"
    )
