import json

import httpx
import pytest

from ai.client import ClientConfig, LLMError, OpenAIClient, ReplayClient
from ai.settings import SettingsStore


SCHEMA = {"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"], "additionalProperties": False}
MESSAGES = [{"role": "user", "content": "private test prompt"}]


def completion(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_structured_generation_and_logs_never_expose_key_or_prompt():
    requests, events = [], []

    def respond(request):
        requests.append(request)
        return completion('{"value":7}')

    config = ClientConfig(base_url="https://example.invalid/v1", model="test-model", api_key="test-only-key", log_enabled=True)
    client = OpenAIClient(config, transport=httpx.MockTransport(respond), audit=events.append)
    assert client.generate(MESSAGES, SCHEMA) == {"value": 7}
    payload = json.loads(requests[0].content)
    assert payload["temperature"] == 0
    assert payload["response_format"]["type"] == "json_schema"
    assert requests[0].headers["authorization"] == "Bearer test-only-key"
    assert "test-only-key" not in repr(config)
    assert events and "test-only-key" not in json.dumps(events)
    assert "private test prompt" not in json.dumps(events)


def test_invalid_json_retries_exactly_once_with_machine_feedback():
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return completion("not json" if len(requests) == 1 else '{"value":3}')

    client = OpenAIClient(ClientConfig(model="test"), transport=httpx.MockTransport(respond))
    assert client.generate(MESSAGES, SCHEMA) == {"value": 3}
    assert len(requests) == 2
    feedback = json.loads(requests[1]["messages"][-1]["content"])
    assert feedback["code"] == "AI_LLM_RESPONSE" and "params" in feedback
    assert MESSAGES == [{"role": "user", "content": "private test prompt"}]


@pytest.mark.parametrize("content", ['{"value":"wrong"}', '{"value":1,"value":2}', '{"value":NaN}', '[]'])
def test_invalid_structured_responses_fail_after_one_retry(content):
    calls = []

    def respond(request):
        calls.append(request)
        return completion(content)

    with pytest.raises(LLMError) as raised:
        OpenAIClient(ClientConfig(model="test"), transport=httpx.MockTransport(respond)).generate(MESSAGES, SCHEMA)
    assert raised.value.code == "AI_LLM_RESPONSE" and len(calls) == 2


@pytest.mark.parametrize("status,code", [(429, "AI_LLM_RATE_LIMIT"), (401, "AI_LLM_AUTH"), (500, "AI_LLM_CONNECTION"), (302, "AI_LLM_RESPONSE")])
def test_http_failures_are_bounded_and_redacted(status, code):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, headers={"location": "https://other.invalid/"}, text="test-only-key private response")

    with pytest.raises(LLMError) as raised:
        OpenAIClient(ClientConfig(model="test", api_key="test-only-key"), transport=httpx.MockTransport(respond)).generate(MESSAGES, SCHEMA)
    assert raised.value.code == code and len(calls) == 1
    assert "test-only-key" not in str(raised.value) and "private response" not in str(raised.value)


def test_timeout_is_not_retried_and_logging_can_be_disabled():
    calls, events = [], []

    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("private transport detail", request=request)

    with pytest.raises(LLMError) as raised:
        OpenAIClient(ClientConfig(model="test", log_enabled=False), transport=httpx.MockTransport(respond), audit=events.append).generate(MESSAGES, SCHEMA)
    assert raised.value.code == "AI_LLM_TIMEOUT" and len(calls) == 1 and events == []


def test_tool_output_mode_and_connection_test_do_not_require_inference():
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "test-model"}]})
        return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [
            {"type": "function", "function": {"name": "submit_proposal", "arguments": '{"value":2}'}}]}}]})

    client = OpenAIClient(ClientConfig(model="test-model", structured_mode="tool"), transport=httpx.MockTransport(respond))
    assert client.test_connection() == {"ok": True, "models": ["test-model"]}
    assert len(requests) == 1 and requests[0].url.path.endswith("/models")
    assert client.generate(MESSAGES, SCHEMA) == {"value": 2}
    assert json.loads(requests[1].content)["tool_choice"]["function"]["name"] == "submit_proposal"


@pytest.mark.parametrize("url", ["file:///secret", "https://user:password@example.invalid/v1", "https://example.invalid/v1?token=secret", "http://", "http://example.invalid:99999/v1"])
def test_invalid_endpoint_configuration_is_rejected(url):
    with pytest.raises(LLMError):
        ClientConfig(base_url=url)


def test_replay_client_returns_independent_records_and_explicit_exhaustion():
    response = {"value": 1}
    client = ReplayClient([response])
    result = client.generate(MESSAGES, SCHEMA)
    result["value"] = 2
    assert response == {"value": 1} and client.requests[0]["messages"] == MESSAGES
    with pytest.raises(LLMError) as raised:
        client.generate(MESSAGES, SCHEMA)
    assert raised.value.code == "AI_REPLAY_EXHAUSTED"


def test_settings_never_persist_or_return_secret_and_clear_it_on_origin_change(tmp_path, monkeypatch):
    monkeypatch.delenv("BD_AI_API_KEY", raising=False)
    settings = SettingsStore(tmp_path)
    public = settings.save({"base_url": "http://127.0.0.1:1234/v1", "model": "local", "api_key": "test-only-key"})
    assert public["has_api_key"] and "api_key" not in public["config"]
    assert settings.configuration().api_key == "test-only-key"
    saved = (tmp_path / ".bdstudio/ai.json").read_text(encoding="utf-8")
    assert "test-only-key" not in saved and "api_key" not in saved
    assert SettingsStore(tmp_path).configuration().api_key == ""
    settings.save({"base_url": "http://127.0.0.1:1234/v1", "model": "other"})
    assert settings.configuration().api_key == "test-only-key"
    settings.save({"base_url": "https://other.invalid/v1", "model": "other"})
    assert settings.configuration().api_key == ""


def test_malformed_message_is_a_bounded_protocol_error():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": "invalid message object"}]})

    with pytest.raises(LLMError) as raised:
        OpenAIClient(ClientConfig(model="test"), transport=httpx.MockTransport(respond)).generate(MESSAGES, SCHEMA)
    assert raised.value.code == "AI_LLM_RESPONSE" and len(calls) == 2


def test_large_responses_and_refusals_are_not_retried():
    from ai.client import MAX_RESPONSE_BYTES

    for response, code in ((httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1)), "AI_LLM_LIMIT"),
                           (httpx.Response(200, json={"choices": [{"message": {"refusal": "private refusal"}}]}), "AI_LLM_REFUSED")):
        calls = []

        def respond(request):
            calls.append(request)
            return response

        with pytest.raises(LLMError) as raised:
            OpenAIClient(ClientConfig(model="test"), transport=httpx.MockTransport(respond)).generate(MESSAGES, SCHEMA)
        assert raised.value.code == code and len(calls) == 1