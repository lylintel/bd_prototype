from core.diagnostics import issue


def check(resolved):
    names = set(resolved.document.get("ports", {}))
    findings = []
    for item in resolved.document.get("instances", []):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        name = item["name"]
        if name in names:
            findings.append(issue("E006", {"instance": name}, name=name))
        names.add(name)
    return findings