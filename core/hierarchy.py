from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from threading import Lock

import bdtool
from bdip import IpMetadata, IpPort, IpSource
from core.design import DesignFormatError, check_document, migrate
from core.diagnostics import issue
from core.resolve import resolve


_format_lock = Lock()
_checked_formats = set()


def check_hierarchy_document(document):
    try:
        encoded = json.dumps(document, sort_keys=True, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError):
        check_document(document)
        return
    digest = hashlib.sha256(encoded).digest()
    with _format_lock:
        if digest in _checked_formats:
            return
    check_document(document)
    with _format_lock:
        if len(_checked_formats) >= 16:
            _checked_formats.clear()
        _checked_formats.add(digest)


def _error(reason, name=""):
    return DesignFormatError(issue("D001", {"design": name}, reason=f"hierarchy_{reason}"))


def hierarchy_documents(document, library):
    check_hierarchy_document(document)
    children = document.get("subdesigns", {})
    reserved = {metadata.id for metadata in library} | {document["name"], f"{document['name']}_wrapper"}
    for name, child in children.items():
        try:
            bdtool._name(name, "subdesign")
        except bdtool.DesignError as error:
            raise _error("name", name) from error
        if name in reserved or child["name"] != name:
            raise _error("collision", name)
    ordered, visiting, complete = [], set(), set()

    def visit(name, depth):
        if depth > 16 or name in visiting:
            raise _error("cycle_or_depth", name)
        if name in complete:
            return
        visiting.add(name)
        child = children[name]
        for instance in child["instances"]:
            reference = instance["ip"]
            if reference["id"] in children:
                visit(reference["id"], depth + 1)
        visiting.remove(name)
        complete.add(name)
        ordered.append(child)

    for name in children:
        visit(name, 1)
    root = {key: value for key, value in document.items() if key != "subdesigns"}
    root["schema_version"] = 3
    return [*ordered, root]


def hierarchy_library(document, library, *, resolutions=None):
    documents = hierarchy_documents(document, library)
    expanded = list(library)
    for child in documents[:-1]:
        resolved = resolve(child, expanded)
        if resolutions is not None:
            resolutions[child["name"]] = resolved
        if len(resolved.ports) != len(child["ports"]):
            raise _error("port", child["name"])
        boundary_roles = {}
        for net in resolved.nets:
            external = {endpoint.raw["ext"] for endpoint in net.endpoints if "ext" in endpoint.raw}
            roles = [reference.shape.role for endpoint in net.endpoints for reference in endpoint.references
                     if reference.shape.role is not None]
            for name in external:
                boundary_roles.setdefault(name, []).extend(roles)
        ports = []
        for name, shape in resolved.ports.items():
            roles = boundary_roles.get(name, [])
            role = roles[0] if roles and all(item == roles[0] for item in roles) else None
            ports.append(IpPort(name, "in" if shape.direction == "input" else "out", str(shape.width),
                                shape.signed, shape.bounds, role))
        digest = hashlib.sha256(json.dumps(child, sort_keys=True).encode("utf-8")).hexdigest()
        expanded.append(IpMetadata(1, child["name"], "1.0.0", child["name"], "", ("hierarchy",),
                        IpSource("verilog", f"{child['name']}.v", digest, "NOASSERTION"),
                        "verilog-2005", (), tuple(ports)))
    return documents, tuple(expanded)


def inspect_hierarchy(document, library):
    try:
        resolutions = {}
        documents, expanded = hierarchy_library(document, library, resolutions=resolutions)
    except DesignFormatError as error:
        return {"valid": False, "diagnostics": [error.diagnostic.to_dict()], "files": {},
                "parameters": {}, "interfaces": {"ports": {}, "instances": {}}, "connections": []}
    return inspect_hierarchy_documents(documents, expanded, resolutions=resolutions)


def inspect_hierarchy_documents(documents, expanded, *, resolutions=None):
    from core.semantic import inspect_design, inspect_resolved

    findings, files = [], {}
    for child in documents:
        resolved = (resolutions or {}).get(child["name"])
        result = inspect_resolved(resolved) if resolved is not None else inspect_design(child, expanded)
        if child is not documents[-1]:
            for diagnostic in result["diagnostics"]:
                diagnostic["location"] = {**diagnostic["location"], "design": child["name"]}
                diagnostic.pop("fix", None)
            files.update({name: text for name, text in result["files"].items() if name == f"{child['name']}.v"})
        else:
            files.update(result["files"])
        findings.extend(result["diagnostics"])
    valid = not any(item["severity"] == "error" for item in findings)
    return {**result, "valid": valid, "diagnostics": findings, "files": files if valid else {}}


def resolve_hierarchy(document, library):
    try:
        documents, expanded = hierarchy_library(document, library)
        return resolve(documents[-1], expanded)
    except DesignFormatError as error:
        return replace(resolve({}, library), diagnostics=(error.diagnostic,))


def collapse_design(document, library, selection, name):
    from core.semantic import inspect_design

    try:
        bdtool._name(name, "subdesign")
    except bdtool.DesignError as error:
        raise _error("name", str(name)) from error
    if document.get("schema_version") == 4:
        check_hierarchy_document(document)
        candidate = deepcopy(document)
    else:
        candidate = migrate(document, library, target_version=4)
    selected = set(selection)
    instances = {item["name"]: item for item in candidate["instances"]}
    occupied = set(instances) | set(candidate["ports"]) | {item["name"] for item in candidate["nets"]}
    if (not selected or len(selected) != len(selection) or not selected <= instances.keys()
            or name in occupied or name in candidate["subdesigns"] or name in {item.id for item in library}
            or name in {candidate["name"], f"{candidate['name']}_wrapper"}):
        raise _error("selection_or_collision", name)
    inspection = inspect_design(candidate, library)
    if not inspection["valid"]:
        raise _error("invalid_design", name)
    resolved = resolve_hierarchy(candidate, library)
    child = {"schema_version": 3, "name": name, "ports": {},
             "instances": [item for item in candidate["instances"] if item["name"] in selected], "nets": []}
    parent_nets = []
    for net in resolved.nets:
        inside, outside = [], []
        for endpoint in net.endpoints:
            membership = {reference.endpoint.instance in selected for reference in endpoint.references}
            if len(membership) > 1:
                raise _error("mixed_concat", name)
            (inside if membership == {True} else outside).append(endpoint)
        if not inside:
            parent_nets.append({"name": net.name, "endpoints": [deepcopy(item.raw) for item in outside]})
            continue
        if all(not item.references for item in outside):
            child["nets"].append({"name": net.name, "endpoints": [deepcopy(item.raw) for item in net.endpoints]})
            continue
        port_name = "boundary_" + net.name
        while port_name in {item["name"] for item in child["instances"]} | {item.name for item in resolved.nets} | set(child["ports"]):
            port_name += "_"
        shape = net.drivers[0].shape
        child["ports"][port_name] = {"direction": "output" if any(item.drives for item in inside) else "input",
                                     "signed": shape.signed,
                                     **({"range": list(shape.bounds)} if shape.bounds is not None else {})}
        child["nets"].append({"name": net.name, "endpoints": [*[deepcopy(item.raw) for item in inside], {"ext": port_name}]})
        parent_nets.append({"name": net.name, "endpoints": [*[deepcopy(item.raw) for item in outside], {"inst": name, "port": port_name}]})
    candidate["instances"] = [item for item in candidate["instances"] if item["name"] not in selected]
    candidate["instances"].append({"name": name, "ip": {"id": name, "version": "1.0.0"}})
    candidate["nets"] = parent_nets
    candidate["subdesigns"][name] = child
    check_hierarchy_document(candidate)
    result = inspect_design(candidate, library)
    if not result["valid"]:
        raise _error("boundary", name)
    return candidate