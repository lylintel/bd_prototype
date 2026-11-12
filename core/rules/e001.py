from core.diagnostics import issue
from core.resolve import ParameterError, instance_ports, parameters


def _fix(resolved, source, target):
    if source.expression or target.expression:
        return None
    name = target.raw.get("inst")
    instance = resolved.instances.get(name)
    rows = [item for item in resolved.document.get("instances", []) if isinstance(item, dict) and item.get("name") == name]
    if instance is None or len(rows) != 1 or source.shape.width == target.shape.width:
        return None
    candidates = []
    for parameter in instance.metadata.parameters:
        try:
            values = parameters(instance.metadata, {**rows[0].get("params", {}), parameter.name: source.shape.width})
            ports = instance_ports(instance.metadata, values)
            selected = ports[target.raw["port"]]
            if ((selected.width, selected.bounds, selected.signed) == (source.shape.width, source.shape.bounds, source.shape.signed)
                    and all(shape == instance.ports[port] for port, shape in ports.items() if port != target.raw["port"])):
                candidates.append({"op": "set_param", "inst": name, "name": parameter.name, "value": source.shape.width})
        except (ParameterError, ValueError):
            continue
    return candidates[0] if len(candidates) == 1 else None


def check(resolved):
    findings = []
    for net in resolved.nets:
        if len(net.drivers) != 1:
            continue
        source = net.drivers[0]
        for target in net.sinks:
            mismatch = (source.shape.width, source.shape.signed) != (target.shape.width, target.shape.signed)
            mismatch = mismatch or (not source.expression and not target.expression and source.shape.bounds != target.shape.bounds)
            if mismatch:
                findings.append(issue("E001", {**target.location, "net": net.name}, fix=_fix(resolved, source, target), source=source.key, target=target.key,
                                      source_width=source.shape.width, target_width=target.shape.width,
                                      reason="width" if source.shape.width != target.shape.width else "shape"))
    return findings