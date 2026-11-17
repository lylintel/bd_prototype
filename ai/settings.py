import hashlib
import json
import os
from pathlib import Path
from threading import RLock

import bdtool
from ai.client import ClientConfig, LLMError, json_object, origin
from ai.privacy import endpoint_kind, redact, secure_path


FIELDS = ("base_url", "model", "temperature", "structured_mode", "timeout", "log_enabled", "context_token_budget", "send_ip_descriptions")


class SettingsStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.lock = RLock()
        path = self._path("ai.json")
        values = {}
        self.consents = {}
        self.endpoint_configured = False
        if path.is_file():
            secure_path(path.parent, directory=True)
            secure_path(path)
            if path.stat().st_size > 16384:
                raise LLMError("AI_LLM_CONFIG", field="size")
            try:
                values = json_object(path.read_text(encoding="utf-8"))
                self.consents = values.pop("consents", {})
                self.endpoint_configured = values.pop("endpoint_configured", "base_url" in values)
                if (values.pop("schema_version", None) not in (1, 2, 3, 4) or set(values) - set(FIELDS)
                    or not isinstance(self.consents, dict) or set(self.consents) - {"configured", "copilot"}
                    or any(not isinstance(value, str) for value in self.consents.values()) or type(self.endpoint_configured) is not bool):
                    raise ValueError("settings schema")
            except (ValueError, UnicodeError):
                raise LLMError("AI_LLM_CONFIG", field="stored_settings") from None
        key = os.environ.get("BD_AI_API_KEY", "")
        for field, name in (("base_url", "BD_AI_BASE_URL"), ("model", "BD_AI_MODEL")):
            if os.environ.get(name):
                values[field] = os.environ[name]
                if field == "base_url":
                    self.endpoint_configured = True
        self._config = ClientConfig(**values, api_key=key)
        self.key_source = "environment" if key else "none"

    def _path(self, name):
        path = (self.root / ".bdstudio" / name).resolve()
        if not path.is_relative_to(self.root):
            raise LLMError("AI_LLM_CONFIG", field="settings_path")
        return path

    def public(self):
        with self.lock:
            config = {name: getattr(self._config, name) for name in FIELDS}
            if self._config.api_key:
                config = {name: value.replace(self._config.api_key, "[redacted]") if isinstance(value, str) else value for name, value in config.items()}
            return {"schema_version": 4, "config": config,
                    "has_api_key": bool(self._config.api_key), "key_source": self.key_source,
                    "endpoint_configured": self.endpoint_configured,
                    "endpoint_kind": endpoint_kind(self._config.base_url) if self.endpoint_configured else "unconfigured",
                    "endpoint_revision": self._revision("configured"), "copilot_revision": self._revision("copilot"),
                    "consent_required": self.consents.get("configured") != self._revision("configured"),
                    "copilot_consent_required": self.consents.get("copilot") != self._revision("copilot")}

    def _revision(self, provider):
        value = self._config.base_url if provider == "configured" else "copilot-runtime"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def require_consent(self, provider="configured"):
        with self.lock:
            if provider == "configured" and not self.endpoint_configured:
                raise LLMError("AI_ENDPOINT_REQUIRED")
            if self.consents.get(provider) != self._revision(provider):
                raise LLMError("AI_CONSENT_REQUIRED")

    def confirm(self, payload):
        with self.lock:
            provider = payload.get("provider", "configured")
            if (payload.get("confirmed") is not True or provider not in ("configured", "copilot")
                    or payload.get("revision") != self._revision(provider)):
                raise LLMError("AI_CONSENT_REQUIRED")
            if provider == "configured" and not self.endpoint_configured:
                raise LLMError("AI_ENDPOINT_REQUIRED")
            previous = self.consents.copy()
            self.consents[provider] = self._revision(provider)
            try:
                self._write_record(self._config)
            except Exception:
                self.consents = previous
                raise
            return self.public()

    def _private_directory(self):
        directory = self._path("ai.json").parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        secure_path(directory, directory=True)
        return directory

    def _write_record(self, config):
        path = self._path("ai.json")
        public = {"schema_version": 4, "consents": self.consents, "endpoint_configured": self.endpoint_configured,
                  **{name: getattr(config, name) for name in FIELDS}}
        text = json.dumps(public, indent=2) + "\n"
        if config.api_key and config.api_key in text:
            raise LLMError("AI_LLM_CONFIG", field="secret_in_public_configuration")
        bdtool._write_outputs({path.name: text}, self._private_directory(), set())
        secure_path(path)

    def configuration(self, payload=None):
        with self.lock:
            if payload is None:
                return self._config
            if not isinstance(payload, dict) or set(payload) - {*FIELDS, "api_key", "clear_api_key"}:
                raise LLMError("AI_LLM_CONFIG", field="request")
            values = {name: payload.get(name, getattr(self._config, name)) for name in FIELDS}
            public_config = ClientConfig(**values)
            key = self._config.api_key if origin(public_config.base_url) == origin(self._config.base_url) else ""
            if payload.get("clear_api_key") is True:
                key = ""
            supplied = payload.get("api_key", "")
            if not isinstance(supplied, str):
                raise LLMError("AI_LLM_CONFIG", field="api_key")
            if supplied.strip():
                key = supplied
            return ClientConfig(**values, api_key=key)

    def save(self, payload):
        with self.lock:
            config = self.configuration(payload)
            previous = self.endpoint_configured
            if "base_url" in payload:
                self.endpoint_configured = True
            try:
                self._write_record(config)
            except Exception:
                self.endpoint_configured = previous
                raise
            old_key = self._config.api_key
            self._config = config
            self.key_source = "none" if not config.api_key else "session" if config.api_key != old_key else self.key_source
            return self.public()

    def audit(self, event):
        with self.lock:
            if not self._config.log_enabled:
                return
            safe = {name: event[name] for name in ("event", "code", "attempt", "duration_ms", "model") if name in event}
            safe = redact(safe, (self._config.api_key, self._config.base_url, origin(self._config.base_url)[1]))
            path = self._path("ai-requests.jsonl")
            self._private_directory()
            path.touch(mode=0o600, exist_ok=True)
            secure_path(path)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(safe, ensure_ascii=False) + "\n")