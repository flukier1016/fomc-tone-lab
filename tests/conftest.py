"""Every test runs without credentials, so the suite never reaches Claude or spends a key, even on a machine
where a teammate has saved one in .env; label files go to a temporary folder."""

import pytest


@pytest.fixture(autouse=True)
def no_api_key(tmp_path, monkeypatch):
    from fomc import labels
    from fomc.llm import provider

    monkeypatch.setattr(provider, "ENV_FILE", tmp_path / "no.env")
    monkeypatch.setattr(labels, "LABELS_DIR", tmp_path / "labels")  # label files stay out of the repository
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
