from copy import deepcopy
import json
import math

from ai.client import LLMError
from core.resolve import resolve


def compact_design(document, library):
    resolved = resolve(document, library)
    return {"name": document["name"], "ports": {name: shape.to_dict() for name, shape in resolved.ports.items()},
            "instances": [{"name": item["name"], "ip": item["ip"], "params": item.get("params", {}),
                           "resolved_params": resolved.instances[item["name"]].parameters if item["name"] in resolved.instances else {},
                           "ports": {name: shape.to_dict() for name, shape in resolved.instances[item["name"]].ports.items()}
                           if item["name"] in resolved.instances else {}} for item in document["instances"]],
            "nets": deepcopy(document["nets"])}


def metadata_card(metadata):
    return {"id": metadata.id, "version": metadata.version,
            "parameters": [parameter.to_dict() for parameter in metadata.parameters],
            "ports": [port.to_dict() for port in metadata.ports]}


def estimate_tokens(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return math.ceil(sum(0.5 if ord(character) < 128 else 2 for character in text))


def endpoint_references(endpoint, field="inst"):
    if "concat" in endpoint:
        return set().union(*(endpoint_references(item, field) for item in endpoint["concat"]))
    return {endpoint[field]} if field in endpoint else set()


def budget_context(document, library, *, token_budget=32_000, selected_instances=()):
    if type(token_budget) is not int or not 512 <= token_budget <= 2_000_000:
        raise LLMError("AI_REQUEST", field="context_token_budget")
    if not isinstance(selected_instances, (list, tuple)) or len(selected_instances) > 256 or any(not isinstance(name, str) for name in selected_instances):
        raise LLMError("AI_REQUEST", field="selected_instances")
    full = compact_design(document, library)
    names = {item["name"] for item in full["instances"]}
    selected = set(selected_instances)
    if not selected <= names:
        raise LLMError("AI_REQUEST", field="selected_instances")
    totals = {"instances": len(names), "nets": len(full["nets"]), "ports": len(full["ports"])}
    estimated = estimate_tokens(full)
    details = {"scope": "full", "estimated_tokens": estimated, "token_budget": token_budget, "totals": totals,
               "included_instances": sorted(names), "selected_instances": sorted(selected), "boundary_nets": 0}
    if estimated <= token_budget:
        return full, details
    if not selected:
        raise LLMError("AI_CONTEXT_SELECTION_REQUIRED", estimated=estimated, limit=token_budget)
    members = [(net, set().union(*(endpoint_references(item) for item in net["endpoints"]))) for net in full["nets"]]
    included = selected | set().union(*(references for _, references in members if references & selected))
    subgraph = {"name": full["name"], "instances": [item for item in full["instances"] if item["name"] in included],
                "ports": {}, "nets": [], "overall_statistics": totals}
    externals = set()
    boundary = 0
    for net, references in members:
        if not references & included:
            continue
        endpoints = [item for item in net["endpoints"] if endpoint_references(item) <= included]
        omitted = len(net["endpoints"]) - len(endpoints)
        subgraph["nets"].append({"name": net["name"], "endpoints": endpoints,
                                **({"boundary": True, "omitted_endpoints": omitted} if omitted else {})})
        boundary += bool(omitted)
        externals.update(set().union(*(endpoint_references(item, "ext") for item in endpoints)))
    subgraph["ports"] = {name: full["ports"][name] for name in sorted(externals)}
    estimated = estimate_tokens(subgraph)
    if estimated > token_budget:
        raise LLMError("AI_CONTEXT_BUDGET", estimated=estimated, limit=token_budget, included=len(included))
    details.update(scope="subgraph", estimated_tokens=estimated, included_instances=sorted(included), boundary_nets=boundary)
    return subgraph, details


def scope_violations(operations, context):
    if context["scope"] != "subgraph":
        return []
    allowed = set(context["included_instances"]) | {item["name"] for item in operations if item["op"] == "add_instance"}
    violations = []
    for operation in operations:
        referenced = {operation["inst"]} if "inst" in operation else set()
        if operation["op"] == "remove_instance":
            referenced.add(operation["name"])
        for key in ("from", "to"):
            if key in operation:
                referenced.update(endpoint_references(operation[key]))
        if not referenced <= allowed:
            violations.append(operation["op"])
    return violations