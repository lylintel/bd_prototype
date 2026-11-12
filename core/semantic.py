import bdtool
from core.diagnostics import issue
from core.resolve import resolve
from core.rules import e001


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


def _generation_guard(resolved):
    connected = set()
    names = set(resolved.ports)
    try:
        bdtool._name(resolved.document.get("name"), "design")
        for name in resolved.ports:
            bdtool._name(name, "port")
        for name, instance in resolved.instances.items():
            bdtool._name(name, "instance")
            if name in names or resolved.document["name"] in {instance.metadata.id, instance.metadata.id.removesuffix("_wrapper")}:
                return False
            names.add(name)
        if len(resolved.instances) != len(resolved.document.get("instances", [])):
            return False
        for net in resolved.nets:
            bdtool._name(net.name, "net")
            if net.name in names or len(net.drivers) != 1 or not net.sinks:
                return False
            names.add(net.name)
            for endpoint in net.endpoints:
                if endpoint.key in connected:
                    return False
                connected.add(endpoint.key)
        required = {f"@{name}" for name, port in resolved.ports.items() if port.direction == "output"}
        required.update(f"{name}.{port}" for name, instance in resolved.instances.items()
                        for port, shape in instance.ports.items() if shape.direction == "input")
        return required <= connected
    except bdtool.DesignError:
        return False


def inspect_design(document, library):
    resolved = resolve(document, library)
    findings = [*resolved.diagnostics, *e001.check(resolved)]
    if not findings and not _generation_guard(resolved):
        findings.append(issue("D004", {}, reason="connections_or_names"))
    valid = not any(item.severity == "error" for item in findings)
    return {"valid": valid, "diagnostics": [item.to_dict() for item in findings],
            "files": render(resolved) if valid else {},
            "interfaces": {"ports": {name: port.to_dict() for name, port in resolved.ports.items()},
                           "instances": {name: {port: shape.to_dict() for port, shape in instance.ports.items()}
                                         for name, instance in resolved.instances.items()}},
            "parameters": {name: instance.parameters for name, instance in resolved.instances.items()}}