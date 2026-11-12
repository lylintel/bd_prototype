from core.diagnostics import issue


def check(resolved):
    findings, owners = [], {}
    for net in resolved.nets:
        if len(net.drivers) != 1 or not net.sinks:
            findings.append(issue("E002", {"net": net.name}, net=net.name, drivers=len(net.drivers), reason="driver_count"))
        for endpoint in net.endpoints:
            if resolved.advanced:
                continue
            key = endpoint.key
            if key in owners:
                findings.append(issue("E002", {**endpoint.location, "net": net.name}, net=net.name,
                                      drivers=len(net.drivers), reason="endpoint_reused", endpoint=key, other_net=owners[key]))
            else:
                owners[key] = net.name
    if resolved.advanced:
        counts = {net.name: len(net.drivers) for net in resolved.nets}
        for uses in resolved.usage.values():
            sinks = sorted(((min(reference.bounds), max(reference.bounds), name, reference) for name, reference in uses if not reference.drives), key=lambda item: item[:3])
            last_end = None
            last_net = None
            for start, end, name, reference in sinks:
                if last_end is not None and start <= last_end:
                    findings.append(issue("E002", {**reference.location, "net": name}, net=name, drivers=counts[name],
                                          reason="endpoint_reused", endpoint=reference.key, other_net=last_net))
                if last_end is None or end > last_end:
                    last_end, last_net = end, name
    return findings