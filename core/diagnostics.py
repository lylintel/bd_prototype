from dataclasses import dataclass

from bdip import MESSAGES


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    location: dict
    message: str
    params: dict
    fix: dict | None = None

    def to_dict(self) -> dict:
        result = {"code": self.code, "severity": self.severity, "location": dict(self.location),
                  "message": self.message, "params": dict(self.params)}
        if self.fix is not None:
            result["fix"] = dict(self.fix)
        return result


def issue(code: str, location: dict, *, fix: dict | None = None, **params) -> Diagnostic:
    return Diagnostic(code, "warning" if code.startswith("W") else "error", dict(location),
                      MESSAGES[code].format(**params), params, fix)