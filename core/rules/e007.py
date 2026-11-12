from core.diagnostics import issue


def check(resolved):
    names = set(resolved.document.get("ports", {})) | {item["name"] for item in resolved.document.get("instances", []) if isinstance(item, dict) and isinstance(item.get("name"), str)}
    findings = []
    for net in resolved.nets:
        if net.name in names:
            findings.append(issue("E007", {"net": net.name}, name=net.name))
        names.add(net.name)
    return findings