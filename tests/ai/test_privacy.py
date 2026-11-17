import json
import os
import stat
import subprocess

import httpx
import pytest

from ai.client import ClientConfig, LLMError, OpenAIClient
from ai.privacy import redact
from ai.settings import SettingsStore


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in ("BD_AI_API_KEY", "BD_AI_BASE_URL", "BD_AI_MODEL"):
        monkeypatch.delenv(name, raising=False)


def test_consent_is_explicit_endpoint_bound_and_persistent(tmp_path):
    store = SettingsStore(tmp_path)
    assert not store.public()["endpoint_configured"]
    store.save({"base_url": "https://private.example.invalid/v1", "model": "test"})
    public = store.public()
    assert public["endpoint_kind"] == "remote" and public["consent_required"]
    with pytest.raises(LLMError) as raised:
        store.require_consent()
    assert raised.value.code == "AI_CONSENT_REQUIRED"
    with pytest.raises(LLMError):
        store.confirm({"confirmed": True, "revision": "outdated", "provider": "configured"})
    store.confirm({"confirmed": True, "revision": public["endpoint_revision"], "provider": "configured"})
    store.require_consent()
    SettingsStore(tmp_path).require_consent()
    store.save({"base_url": "http://127.0.0.1:1234/v1"})
    assert store.public()["endpoint_kind"] == "local" and store.public()["consent_required"]


def test_private_files_and_audit_do_not_expose_key_or_endpoint(tmp_path):
    store = SettingsStore(tmp_path)
    key, endpoint = "unit-test-private-key", "https://private.example.invalid/v1"
    store.save({"base_url": endpoint, "model": "test", "api_key": key, "log_enabled": True})
    store.audit({"event": "generate", "code": "ok", "attempt": 1, "model": endpoint + key})
    settings = tmp_path / ".bdstudio/ai.json"
    audit = tmp_path / ".bdstudio/ai-requests.jsonl"
    assert key not in settings.read_text()
    assert all(secret not in audit.read_text() for secret in (key, endpoint, "private.example.invalid"))
    for path in (settings, audit):
        if os.name == "nt":
            result = subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=True)
            assert "(I)" not in result.stdout
        else:
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
    if os.name != "nt":
        assert stat.S_IMODE(settings.parent.stat().st_mode) == 0o700


@pytest.mark.parametrize("escaped", [False, True])
def test_sensitive_model_response_cannot_become_design_or_error_text(escaped):
    key, endpoint = "unit-test-private-key", "https://private.example.invalid/v1"
    config = ClientConfig(base_url=endpoint, model="test", api_key=key)
    content = json.dumps({"value": key})
    if escaped:
        content = content.replace("unit", r"\u0075nit")
    client = OpenAIClient(config, transport=httpx.MockTransport(lambda request: httpx.Response(200,
        json={"choices": [{"message": {"content": content}}]})))
    with pytest.raises(LLMError) as raised:
        client.generate([{"role": "user", "content": "test"}], {"type": "object", "properties": {"value": {"type": "string"}}})
    assert raised.value.code == "AI_LLM_SENSITIVE_RESPONSE"
    assert key not in repr(config) and endpoint not in repr(config)
    assert key not in str(raised.value) and endpoint not in str(raised.value)


def test_redaction_covers_nested_transcripts():
    result = redact({"messages": [{"content": "Bearer token-value https://private.invalid/v1 secret-value"}]}, ("secret-value",))
    assert all(value not in json.dumps(result) for value in ("token-value", "private.invalid", "secret-value"))


def test_service_refuses_generation_before_consent(tmp_path):
    from bdgui import Workspace

    workspace = Workspace(tmp_path, "unused.json")
    workspace.save_ai_settings({"base_url": "http://127.0.0.1:1234/v1", "model": "offline"})
    def forbidden(*args, **kwargs):
        raise AssertionError("must not create a client before consent")
    workspace.llm_client_factory = forbidden
    with pytest.raises(LLMError) as raised:
        workspace.propose_ai({"prompt": "test"})
    assert raised.value.code == "AI_CONSENT_REQUIRED"