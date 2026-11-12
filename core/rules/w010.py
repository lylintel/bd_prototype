from core.diagnostics import issue


def check(resolved):
    consumed = {endpoint.key for net in resolved.nets if net.sinks for endpoint in net.drivers}
    return [issue("W010", {"instance": name, "port": port}, endpoint=f"{name}.{port}")
            for name, instance in resolved.instances.items() for port, shape in instance.ports.items()
            if shape.direction == "output" and f"{name}.{port}" not in consumed]