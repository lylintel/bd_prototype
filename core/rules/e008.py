import bdtool
from core.diagnostics import issue


def check(resolved):
    findings = []
    valid_names = set()

    def check_name(name, location):
        if isinstance(name, str) and name in valid_names:
            return
        try:
            bdtool._name(name, "identifier")
            if len(name) > 256:
                raise bdtool.DesignError("length")
            valid_names.add(name)
        except bdtool.DesignError:
            findings.append(issue("E008", location, name=str(name), reason="identifier"))

    name = resolved.document.get("name")
    if name is not None:
        check_name(name, {"path": "$.name"})
    for port in resolved.document.get("ports", {}):
        check_name(port, {"external": port})
    module_names = {instance.metadata.id for instance in resolved.instances.values()}
    for metadata in resolved.document.get("project_ips", []):
        if isinstance(metadata, dict) and isinstance(metadata.get("id"), str):
            module_names.add(metadata["id"])
    if name in module_names or f"{name}_wrapper" in module_names:
        findings.append(issue("E008", {"path": "$.name"}, name=name, reason="generated_module_conflict"))
    for index, item in enumerate(resolved.document.get("instances", [])):
        if isinstance(item, dict):
            location = {"instance": item["name"]} if isinstance(item.get("name"), str) else {"path": f"$.instances[{index}]"}
            check_name(item.get("name"), location)
            if isinstance(item.get("ip"), dict):
                check_name(item["ip"].get("id"), location)
    for net in resolved.nets:
        check_name(net.name, {"net": net.name})
    for net in resolved.document.get("nets", []):
        if not isinstance(net, dict) or not isinstance(net.get("name"), str) or not isinstance(net.get("endpoints"), list):
            continue
        pending = list(net["endpoints"])
        visited = 0
        limit = 256 * max(1, len(pending))
        while pending and visited < limit:
            endpoint = pending.pop()
            visited += 1
            if not isinstance(endpoint, dict):
                continue
            if (len(endpoint) == 2 and isinstance(endpoint.get("inst"), str) and isinstance(endpoint.get("port"), str)
                    and endpoint["inst"] in valid_names and endpoint["port"] in valid_names):
                continue
            if isinstance(endpoint.get("concat"), list):
                pending.extend(endpoint["concat"][:128])
            location = {"net": net["name"]}
            for field, label in (("inst", "instance"), ("port", "port"), ("ext", "external")):
                if field in endpoint and isinstance(endpoint[field], str):
                    location[label] = endpoint[field]
            for field in ("inst", "port", "ext"):
                if field in endpoint:
                    check_name(endpoint[field], location)
    return findings