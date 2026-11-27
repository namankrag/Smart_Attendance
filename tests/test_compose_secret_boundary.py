from pathlib import Path
import re


def test_compose_keeps_worker_secrets_out_of_ui_service():
    compose = Path(__file__).resolve().parents[1] / "docker-compose.yml"
    text = compose.read_text(encoding="utf-8")
    services = re.split(r"(?m)^  (ui|worker):\s*$", text)
    service_blocks = dict(zip(services[1::2], services[2::2], strict=True))
    ui = service_blocks["ui"]
    worker = service_blocks["worker"]

    assert "env_file:" not in ui
    assert "SUPABASE_SERVICE_ROLE_KEY" not in ui
    assert "HF_TOKEN" not in ui
    assert "./.streamlit/secrets.toml:/app/.streamlit/secrets.toml:ro" in ui
    assert re.search(r"(?m)^    env_file:\n      - \.env$", worker)
