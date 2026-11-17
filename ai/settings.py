import json
import os
from pathlib import Path
from threading import RLock

import bdtool
from ai.client import ClientConfig, LLMError, json_object, origin


FIELDS = ("base_url", "model", "temperature", "structured_mode", "timeout", "log_enabled")


class SettingsStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.lock = RLock()
        path = self._path("ai.json")
        values = {}
        if path.is_file():
            if path.stat().st_size > 16384:
                raise LLMError("AI_LLM_CONFIG", field="size")
            try:
                values = json_object(path.read_text(encoding="utf-8"))
                if values.pop("schema_version", None) != 1 or set(values) - set(FIELDS):
                    raise ValueError("settings schema")
            except (ValueError, UnicodeError):
                raise LLMError("AI_LLM_CONFIG", field="stored_settings") from None
        key = os.environ.get("BD_AI_API_KEY", "")
        self._config = ClientConfig(**values, api_key=key)
        self.key_source = "environment" if key else "none"

    def _path(self, name):
        path = (self.root / ".bdstudio" / name).resolve()
        if not path.is_relative_to(self.root):
            raise LLMError("AI_LLM_CONFIG", field="settings_path")
        return path

    def public(self):
        with self.lock:
            return {"schema_version": 1, "config": {name: getattr(self._config, name) for name in FIELDS},
                    "has_api_key": bool(self._config.api_key), "key_source": self.key_source}

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
            path = self._path("ai.json")
            public = {"schema_version": 1, **{name: getattr(config, name) for name in FIELDS}}
            bdtool._write_outputs({path.name: json.dumps(public, indent=2) + "\n"}, path.parent, set())
            old_key = self._config.api_key
            self._config = config
            self.key_source = "none" if not config.api_key else "session" if config.api_key != old_key else self.key_source
            return self.public()

    def audit(self, event):
        with self.lock:
            if not self._config.log_enabled:
                return
            safe = {name: event[name] for name in ("event", "code", "attempt", "duration_ms", "model") if name in event}
            if self._config.api_key:
                safe = {name: value.replace(self._config.api_key, "[redacted]") if isinstance(value, str) else value for name, value in safe.items()}
            path = self._path("ai-requests.jsonl")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(safe, ensure_ascii=False) + "\n")