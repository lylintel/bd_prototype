from core.diagnostics import issue


def check(resolved):
    connected = set()
    for key, uses in resolved.usage.items():
        port = uses[0][1].shape
        start, end = min(port.bounds or (0, 0)), max(port.bounds or (0, 0))
        cursor = start
        for low, high in sorted((min(reference.bounds), max(reference.bounds)) for _, reference in uses):
            if low > cursor:
                break
            cursor = max(cursor, high + 1)
        if cursor > end:
            connected.add(key)
    findings = []
    for name, instance in resolved.instances.items():
        for port, shape in instance.ports.items():
            if shape.direction == "input" and f"{name}.{port}" not in connected:
                findings.append(issue("E003", {"instance": name, "port": port}, endpoint=f"{name}.{port}"))
    for name, port in resolved.ports.items():
        if port.direction == "output" and f"@{name}" not in connected:
            findings.append(issue("E003", {"external": name}, endpoint=f"@{name}"))
    return findings