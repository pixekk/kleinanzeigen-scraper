from pathlib import Path

import pytest

from app.config import load_config

MINIMAL_YAML = """
smtp:
  host: mail.example.com
  user: scanner@example.com
  password: secret
recipients:
  - a@b.de
searches:
  - name: test
    query: ps5
"""


@pytest.fixture
def config_env(monkeypatch, tmp_path):
    config_path = tmp_path / "searches.yaml"
    config_path.write_text(MINIMAL_YAML, encoding="utf-8")
    monkeypatch.setenv("CONFIG_YAML", "")
    monkeypatch.delenv("SMTP_SECURITY", raising=False)
    return config_path


def test_smtp_security_env_fallback_ssl(monkeypatch, config_env):
    monkeypatch.setenv("SMTP_SECURITY", "ssl")
    config = load_config(config_env)
    assert config.smtp.security == "ssl"


def test_smtp_security_defaults_to_starttls_when_unset(monkeypatch, config_env):
    monkeypatch.delenv("SMTP_SECURITY", raising=False)
    config = load_config(config_env)
    assert config.smtp.security == "starttls"
