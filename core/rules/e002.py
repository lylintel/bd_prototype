from core.diagnostics import issue


def check(resolved):
    findings, owners = [], {}
    for net in resolved.nets:
        if len(net.drivers) != 1 or not net.sinks:
            findings.append(issue("E002", {"net": net.name}, net=net.name, drivers=len(net.drivers), reason="driver_count"))
        for endpoint in net.endpoints:
            if endpoint.key in owners:
                findings.append(issue("E002", {**endpoint.location, "net": net.name}, net=net.name,
                                      drivers=len(net.drivers), reason="endpoint_reused", endpoint=endpoint.key, other_net=owners[endpoint.key]))
            else:
                owners[endpoint.key] = net.name
    return findings