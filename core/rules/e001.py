from core.diagnostics import issue


def check(resolved):
    findings = []
    for net in resolved.nets:
        if len(net.drivers) != 1:
            continue
        source = net.drivers[0]
        for target in net.sinks:
            if (source.shape.width, source.shape.bounds, source.shape.signed) != (target.shape.width, target.shape.bounds, target.shape.signed):
                findings.append(issue("E001", {**target.location, "net": net.name}, source=source.key, target=target.key,
                                      source_width=source.shape.width, target_width=target.shape.width,
                                      reason="width" if source.shape.width != target.shape.width else "shape"))
    return findings