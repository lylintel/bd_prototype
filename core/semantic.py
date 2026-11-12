from copy import deepcopy
import json

import bdtool
from core.design import DesignFormatError
from core.diagnostics import issue
from core.resolve import endpoint_text, resolve
from core.rules import e001, e002, e003, e004, e005, e006, e007, e008, w010


RULES = (e001, e002, e003, e004, e005, e006, e007, e008, w010)


def _plain(port):
    return bdtool.Port(port.direction, port.bounds, port.signed)


def _endpoint(endpoint):
    return bdtool.Endpoint(endpoint.raw.get("inst"), endpoint.raw.get("port", endpoint.raw.get("ext")))


def render(resolved):
    if resolved.advanced:
        return _render_expressions(resolved)
    ports = {name: _plain(port) for name, port in resolved.ports.items()}
    instances = {name: bdtool.Instance(instance.metadata.id, instance.parameters,
                 {port: _plain(shape) for port, shape in instance.ports.items()}) for name, instance in resolved.instances.items()}
    nets = tuple(bdtool.Net(net.name, _plain(net.drivers[0].shape), _endpoint(net.drivers[0]),
                           tuple(_endpoint(endpoint) for endpoint in net.sinks)) for net in resolved.nets)
    return bdtool.render_verilog(bdtool.Design(resolved.document["name"], ports, instances, nets, ()))


def _render_expressions(resolved):
    name = resolved.document["name"]
    ports = {key: _plain(port) for key, port in resolved.ports.items()}
    symbols = {f"@{key}": key for key in ports}
    used = set(ports) | set(resolved.instances) | {net.name for net in resolved.nets}
    lines = [bdtool._module_header(name, ports), ""]
    for instance_name, instance in resolved.instances.items():
        for port_name, shape in instance.ports.items():
            key = f"{instance_name}.{port_name}"
            if key not in resolved.usage:
                continue
            symbol = f"__bd_{instance_name}_{port_name}"
            while symbol in used:
                symbol += "_"
            used.add(symbol)
            symbols[key] = symbol
            lines.append(f"    {bdtool._declaration(symbol, _plain(shape))};")
    for net in resolved.nets:
        lines.append(f"    {bdtool._declaration(net.name, _plain(net.drivers[0].shape))};")
    lines.append("")
    for net in resolved.nets:
        lines.append(f"    assign {net.name} = {endpoint_text(net.drivers[0].raw, symbols)};")
        for sink in net.sinks:
            lines.append(f"    assign {endpoint_text(sink.raw, symbols)} = {net.name};")
    for instance_name, instance in resolved.instances.items():
        bindings = {port: symbols.get(f"{instance_name}.{port}", "") for port in instance.ports}
        lines.extend(["", bdtool._instance(instance.metadata.id, instance_name, instance.parameters, bindings)])
    lines.append("endmodule")
    wrapper_name = f"{name}_wrapper.v"
    wrapper = bdtool.render_verilog(bdtool.Design(name, ports, {}, (), ()))[wrapper_name]
    return {f"{name}.v": "\n".join(lines) + "\n", wrapper_name: wrapper}


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
            "parameters": {name: instance.parameters for name, instance in resolved.instances.items()},
            "connections": [{"name": net.name, "endpoints": [
                {"index": endpoint.index, "raw": endpoint.raw, "text": endpoint.key, "width": endpoint.shape.width,
                 "drives": endpoint.drives, "expression": endpoint.expression,
                 "references": [{"key": reference.key, "location": reference.location, "bounds": list(reference.bounds),
                                 "width": abs(reference.bounds[0] - reference.bounds[1]) + 1, "drives": reference.drives}
                                for reference in endpoint.references]}
                for endpoint in net.endpoints]} for net in resolved.nets]}