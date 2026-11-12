from copy import deepcopy
import json

import bdtool
from core.design import DesignFormatError
from core.diagnostics import issue
from core.resolve import resolve
from core.rules import e001, e002, e003, e004, e005, e006, e007, e008, w010


RULES = (e001, e002, e003, e004, e005, e006, e007, e008, w010)


def _plain(port):
    return bdtool.Port(port.direction, port.bounds, port.signed)


def _endpoint(endpoint):
    return bdtool.Endpoint(endpoint.raw.get("inst"), endpoint.raw.get("port", endpoint.raw.get("ext")))


def render(resolved):
    ports = {name: _plain(port) for name, port in resolved.ports.items()}
    instances = {name: bdtool.Instance(instance.metadata.id, instance.parameters,
                 {port: _plain(shape) for port, shape in instance.ports.items()}) for name, instance in resolved.instances.items()}
    nets = tuple(bdtool.Net(net.name, _plain(net.drivers[0].shape), _endpoint(net.drivers[0]),
                           tuple(_endpoint(endpoint) for endpoint in net.sinks)) for net in resolved.nets)
    return bdtool.render_verilog(bdtool.Design(resolved.document["name"], ports, instances, nets, ()))


def _findings(resolved):
    return [*[item for item in resolved.diagnostics if item.code not in {"E004", "E005"}],
            *[item for rule in RULES for item in rule.check(resolved)]]


def validate(document, library):
    return _findings(resolve(document, library))


def _identity(diagnostic):
    raw = diagnostic.to_dict()
    return json.dumps({key: raw[key] for key in ("code", "location", "params")}, sort_keys=True)


def apply_fix(document, library, diagnostic):
    if not isinstance(diagnostic, dict):
        raise DesignFormatError(issue("D006", {}, reason="stale_fix"))
    before = validate(document, library)
    matching = next((item for item in before if item.fix is not None and
                     all(item.to_dict().get(key) == diagnostic.get(key) for key in ("code", "location", "params", "fix"))), None)
    if matching is None:
        raise DesignFormatError(issue("D006", {}, reason="stale_fix"))
    fix = matching.fix
    candidate = deepcopy(document)
    target = next(item for item in candidate["instances"] if item["name"] == fix["inst"])
    target.setdefault("params", {})[fix["name"]] = fix["value"]
    after = validate(candidate, library)
    existing = {_identity(item) for item in before if item.severity == "error"}
    remaining = {_identity(item) for item in after if item.severity == "error"}
    if not remaining < existing:
        raise DesignFormatError(issue("D006", matching.location, reason="unsafe_fix"))
    return candidate


def inspect_design(document, library):
    resolved = resolve(document, library)
    findings = _findings(resolved)
    valid = not any(item.severity == "error" for item in findings)
    return {"valid": valid, "diagnostics": [item.to_dict() for item in findings],
            "files": render(resolved) if valid else {},
            "interfaces": {"ports": {name: port.to_dict() for name, port in resolved.ports.items()},
                           "instances": {name: {port: shape.to_dict() for port, shape in instance.ports.items()}
                                         for name, instance in resolved.instances.items()}},
            "parameters": {name: instance.parameters for name, instance in resolved.instances.items()}}