from core.diagnostics import issue


def check(resolved):
    findings = [item for item in resolved.diagnostics if item.code == "E005"]
    versions = {}
    for instance in resolved.instances.values():
        versions.setdefault(instance.metadata.id, set()).add(instance.metadata.version)
    for name, instance in resolved.instances.items():
        candidates = versions[instance.metadata.id]
        if len(candidates) > 1:
            findings.append(issue("E005", {"instance": name}, ip=instance.metadata.id, version=instance.metadata.version,
                                  reason="hdl_version_conflict", candidates=sorted(candidates)))
    return findings