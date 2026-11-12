from core.diagnostics import issue


def check(resolved):
    connected = {endpoint.key for net in resolved.nets for endpoint in net.endpoints}
    findings = []
    for name, instance in resolved.instances.items():
        for port, shape in instance.ports.items():
            if shape.direction == "input" and f"{name}.{port}" not in connected:
                findings.append(issue("E003", {"instance": name, "port": port}, endpoint=f"{name}.{port}"))
    for name, port in resolved.ports.items():
        if port.direction == "output" and f"@{name}" not in connected:
            findings.append(issue("E003", {"external": name}, endpoint=f"@{name}"))
    return findings