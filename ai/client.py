from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field
import ipaddress
import json
import math
from time import perf_counter
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator

from core.diagnostics import Diagnostic


MAX_RESPONSE_BYTES = 1024 * 1024
MAX_REQUEST_BYTES = 256 * 1024


class LLMError(ValueError):
    def __init__(self, code, *, retryable=False, **params):
        self.code, self.params, self.retryable = code, params, retryable
        self.diagnostic = Diagnostic(code=code, severity="error", location={}, message=code, params=params)
        super().__init__(code)


def json_object(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("nonfinite value")

    value = json.loads(text, object_pairs_hook=unique, parse_constant=nonfinite)
    if not isinstance(value, dict):
        raise ValueError("object required")
    return value


def origin(url):
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


@dataclass(frozen=True)
class ClientConfig:
    base_url: str = field(default="https://api.openai.com/v1", repr=False)
    model: str = field(default="", repr=False)
    api_key: str = field(default="", repr=False)
    temperature: float = 0
    structured_mode: str = "json_schema"
    timeout: float = 30
    log_enabled: bool = False
    context_token_budget: int = 32_000
    send_ip_descriptions: bool = False

    def __post_init__(self):
        if type(self.send_ip_descriptions) is not bool:
            raise LLMError("AI_LLM_CONFIG", field="send_ip_descriptions")
        if type(self.context_token_budget) is not int or not 512 <= self.context_token_budget <= 2_000_000:
            raise LLMError("AI_LLM_CONFIG", field="context_token_budget")
        try:
            if not isinstance(self.base_url, str) or len(self.base_url) > 2048:
                raise ValueError("base_url")
            parsed = urlsplit(self.base_url.strip())
            if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None
                    or parsed.password is not None or parsed.query or parsed.fragment):
                raise ValueError("base_url")
            parsed.port
        except (ValueError, TypeError):
            raise LLMError("AI_LLM_CONFIG", field="base_url") from None
        if not isinstance(self.model, str) or len(self.model) > 200:
            raise LLMError("AI_LLM_CONFIG", field="model")
        if not isinstance(self.api_key, str) or len(self.api_key) > 4096 or any(ord(value) < 33 or ord(value) > 126 for value in self.api_key.strip()):
            raise LLMError("AI_LLM_CONFIG", field="api_key")
        if type(self.temperature) not in (int, float) or not math.isfinite(self.temperature) or not 0 <= self.temperature <= 2:
            raise LLMError("AI_LLM_CONFIG", field="temperature")
        if type(self.timeout) not in (int, float) or not math.isfinite(self.timeout) or not 1 <= self.timeout <= 120:
            raise LLMError("AI_LLM_CONFIG", field="timeout")
        if self.structured_mode not in ("json_schema", "tool") or type(self.log_enabled) is not bool:
            raise LLMError("AI_LLM_CONFIG", field="mode_or_logging")
        object.__setattr__(self, "base_url", self.base_url.strip().rstrip("/"))
        object.__setattr__(self, "api_key", self.api_key.strip())


class LLMClient(ABC):
    @abstractmethod
    def generate(self, messages, schema):
        raise NotImplementedError

    def test_connection(self):
        raise LLMError("AI_LLM_CONNECTION")


class OpenAIClient(LLMClient):
    def __init__(self, config, *, transport=None, audit=None, recorder=None, max_output_tokens=None):
        self.config, self.transport, self.audit = config, transport, audit
        self.recorder, self.max_output_tokens = recorder, max_output_tokens
        if ((max_output_tokens is not None and (type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 32768))
                or recorder is not None and max_output_tokens is None):
            raise LLMError("AI_LLM_CONFIG", field="max_output_tokens")

    def _http(self):
        host = urlsplit(self.config.base_url).hostname
        loopback = host == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
        headers = {"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {}
        return httpx.Client(base_url=self.config.base_url + "/", headers=headers, timeout=self.config.timeout,
                            follow_redirects=False, transport=self.transport, trust_env=not loopback)

    def _request(self, client, method, path, payload=None):
        try:
            with client.stream(method, path, json=payload) as response:
                status = response.status_code
                if not 200 <= status < 300:
                    code = ("AI_LLM_AUTH" if status in (401, 403) else "AI_LLM_RATE_LIMIT" if status == 429
                            else "AI_LLM_TIMEOUT" if status in (408, 504) else "AI_LLM_CONNECTION" if status >= 500 else "AI_LLM_RESPONSE")
                    raise LLMError(code, status=status)
                content = bytearray()
                for chunk in response.iter_bytes():
                    if len(content) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise LLMError("AI_LLM_LIMIT", limit=MAX_RESPONSE_BYTES)
                    content.extend(chunk)
        except httpx.TimeoutException:
            raise LLMError("AI_LLM_TIMEOUT") from None
        except httpx.RequestError:
            raise LLMError("AI_LLM_CONNECTION") from None
        try:
            return json_object(content.decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError):
            raise LLMError("AI_LLM_RESPONSE", retryable=True, reason="envelope") from None

    def _audit(self, code, attempt, started):
        if self.config.log_enabled and self.audit:
            from ai.privacy import redact

            model = redact(self.config.model, (self.config.api_key, self.config.base_url, urlsplit(self.config.base_url).hostname))
            self.audit({"event": "generate", "code": code, "attempt": attempt,
                        "duration_ms": round((perf_counter() - started) * 1000, 3), "model": model})

    def generate(self, messages, schema):
        if not self.config.model:
            raise LLMError("AI_LLM_CONFIG", field="model")
        if (not isinstance(messages, list) or not 1 <= len(messages) <= 32
                or any(not isinstance(item, dict) or set(item) != {"role", "content"} or item["role"] not in ("system", "user", "assistant")
                       or not isinstance(item["content"], str) for item in messages)):
            raise LLMError("AI_LLM_REQUEST", field="messages")
        try:
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema)
        except Exception:
            raise LLMError("AI_LLM_REQUEST", field="schema") from None
        history = deepcopy(messages)
        with self._http() as client:
            for attempt in range(2):
                started = perf_counter()
                ticket, response, result = None, None, None
                payload = {"model": self.config.model, "messages": history, "temperature": self.config.temperature, "stream": False}
                if self.max_output_tokens is not None:
                    payload["max_tokens"] = self.max_output_tokens
                if self.config.structured_mode == "tool":
                    payload.update(tools=[{"type": "function", "function": {"name": "submit_proposal", "parameters": schema}}],
                                   tool_choice={"type": "function", "function": {"name": "submit_proposal"}}, parallel_tool_calls=False)
                else:
                    payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "bd_proposal", "schema": schema, "strict": False}}
                try:
                    if len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_REQUEST_BYTES:
                        raise LLMError("AI_LLM_LIMIT", limit=MAX_REQUEST_BYTES)
                    if self.recorder is not None:
                        ticket = self.recorder.before(payload, self.max_output_tokens)
                    response = self._request(client, "POST", "chat/completions", payload)
                    try:
                        message = response["choices"][0]["message"]
                        if not isinstance(message, dict):
                            raise ValueError("message")
                        if message.get("refusal"):
                            raise LLMError("AI_LLM_REFUSED")
                        if self.config.structured_mode == "tool":
                            calls = message["tool_calls"]
                            if len(calls) != 1 or calls[0]["function"]["name"] != "submit_proposal":
                                raise ValueError("tool")
                            text = calls[0]["function"]["arguments"]
                        else:
                            text = message["content"]
                        result = json_object(text)
                        from ai.privacy import contains_sensitive

                        sensitive = (self.config.api_key, self.config.base_url, urlsplit(self.config.base_url).hostname)
                        if contains_sensitive(result, sensitive):
                            raise LLMError("AI_LLM_SENSITIVE_RESPONSE")
                        if next(validator.iter_errors(result), None) is not None:
                            raise ValueError("schema")
                    except LLMError:
                        raise
                    except (ValueError, TypeError, KeyError, IndexError, RecursionError):
                        raise LLMError("AI_LLM_RESPONSE", retryable=True, reason="invalid_json_or_schema") from None
                    self._audit("ok", attempt + 1, started)
                    if ticket is not None:
                        self.recorder.after(ticket, payload, response, result)
                    return result
                except LLMError as error:
                    if ticket is not None and not ticket["settled"]:
                        self.recorder.after(ticket, payload, response, result, error)
                    self._audit(error.code, attempt + 1, started)
                    if not error.retryable or attempt:
                        raise
                    history.append({"role": "user", "content": json.dumps({"code": error.code, "params": error.params})})
        raise LLMError("AI_LLM_RESPONSE")

    def test_connection(self):
        with self._http() as client:
            response = self._request(client, "GET", "models")
        data = response.get("data")
        if not isinstance(data, list):
            raise LLMError("AI_LLM_RESPONSE")
        models = [item["id"] for item in data[:200] if isinstance(item, dict) and isinstance(item.get("id"), str) and len(item["id"]) <= 200]
        return {"ok": True, "models": models}


class ReplayClient(LLMClient):
    def __init__(self, responses):
        self.responses = iter(deepcopy(responses))
        self.requests = []

    def generate(self, messages, schema):
        self.requests.append(deepcopy({"messages": messages, "schema": schema}))
        try:
            result = next(self.responses)
        except StopIteration:
            raise LLMError("AI_REPLAY_EXHAUSTED") from None
        if isinstance(result, LLMError):
            raise result
        if not isinstance(result, dict):
            raise LLMError("AI_LLM_RESPONSE")
        return deepcopy(result)