"""The one place that knows how to reach Claude.

Credentials, in order of precedence:
  1. ANTHROPIC_API_KEY already in the environment;
  2. ANTHROPIC_API_KEY in the project's .env file (git-ignored, mode 600),
     which the Settings page of the dashboard can write;
  3. any other credential source the Anthropic SDK resolves on its own
     (ANTHROPIC_AUTH_TOKEN, an `ant auth login` profile).
Model and effort overrides live in config/local.yaml (git-ignored), so each
teammate can use their own key and model without touching shared settings.

Keys are never printed, logged or returned by the API; only a masked hint is.
"""

from __future__ import annotations

import os
import stat

import anthropic
import yaml
from dotenv import load_dotenv

from ..config import ROOT, reload_settings, settings

ENV_FILE = ROOT / ".env"
LOCAL_CONFIG = ROOT / "config" / "local.yaml"
KEY_VAR = "ANTHROPIC_API_KEY"


def load_env() -> None:
    load_dotenv(ENV_FILE, override=False)


def api_key() -> str | None:
    load_env()
    return os.environ.get(KEY_VAR) or None


def key_hint(key: str | None) -> str | None:
    if not key:
        return None
    return f"{key[:7]}...{key[-4:]}" if len(key) > 14 else "***"


def save_key(key: str) -> None:
    key = key.strip()
    if not key.startswith("sk-"):
        raise ValueError("That does not look like an Anthropic API key")
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    lines = [ln for ln in lines if not ln.startswith(f"{KEY_VAR}=")] + [f"{KEY_VAR}={key}"]
    ENV_FILE.write_text("\n".join(lines) + "\n")
    os.chmod(ENV_FILE, stat.S_IRUSR | stat.S_IWUSR)
    os.environ[KEY_VAR] = key


def clear_key() -> None:
    if ENV_FILE.exists():
        lines = [ln for ln in ENV_FILE.read_text().splitlines() if not ln.startswith(f"{KEY_VAR}=")]
        ENV_FILE.write_text("\n".join(lines) + ("\n" if lines else ""))
    os.environ.pop(KEY_VAR, None)


def save_local(model: str | None = None, effort: str | None = None) -> dict:
    local = yaml.safe_load(LOCAL_CONFIG.read_text()) if LOCAL_CONFIG.exists() else {}
    local = local or {}
    llm = local.setdefault("llm", {})
    if model:
        llm["model"] = model
    if effort:
        llm["effort"] = effort
    LOCAL_CONFIG.write_text(yaml.safe_dump(local, sort_keys=False))
    reload_settings()
    return llm


def get_client(**overrides) -> anthropic.Anthropic:
    """An SDK client. With no key configured the SDK falls back to its own credential chain."""
    key = api_key()
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    kwargs = {"max_retries": 4, **overrides}
    if key:
        kwargs["api_key"] = key
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


def status() -> dict:
    cfg = settings()["llm"]
    key = api_key()
    return {
        "provider": "anthropic",
        "key_configured": bool(key or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
        "key_hint": key_hint(key),
        "model": cfg["model"],
        "effort": cfg["effort"],
        "models_available": list(cfg["prices_per_mtok"]),
        "env_file": ENV_FILE.exists(),
    }


def check(model: str | None = None) -> dict:
    """Verify the credential and model with a free Models API lookup (no tokens billed)."""
    model = model or settings()["llm"]["model"]
    try:
        info = get_client(max_retries=1, timeout=20).models.retrieve(model)
        return {"ok": True, "model": info.id, "display_name": info.display_name}
    except anthropic.AuthenticationError:
        return {"ok": False, "error": "authentication failed: check the API key"}
    except anthropic.NotFoundError:
        return {"ok": False, "error": f"model {model} not available to this key"}
    except anthropic.APIConnectionError:
        return {"ok": False, "error": "cannot reach the Anthropic API"}
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as text
        return {"ok": False, "error": type(exc).__name__}
