from copy import deepcopy
from functools import lru_cache
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import unicodedata

from ai.client import LLMError
from core.design import migrate
from core.hierarchy import resolve_hierarchy, scope_document
from core.interfaces import AXIS_SIGNALS, InterfaceError, expand_interfaces, resolve_interface
from core.ops import apply_ops
from core.resolve import resolve
from core.semantic import validate


def editable_scope(document, scope=''):
    view = scope_document(document, scope)
    if not scope:
        return view
    counts = {}
    children = document['subdesigns']

    def visit(name, amount):
        if name not in children:
            return
        previous = counts.get(name, 0)
        counts[name] = min(2, previous + amount)
        if counts[name] > previous:
            for instance in children[name]['instances']:
                visit(instance['ip']['id'], counts[name] - previous)

    for instance in document['instances']:
        visit(instance['ip']['id'], 1)
    if counts.get(scope, 0) != 1:
        raise LLMError('AI_SHARED_SCOPE', scope=scope, references=counts.get(scope, 0))
    return view


def apply_scoped_ops(document, library, operations, scope=''):
    view = editable_scope(document, scope)
    candidate, errors = apply_ops(view, library, operations)
    if not scope:
        return candidate, errors
    if candidate == view:
        return deepcopy(document), errors
    result = migrate(document, library, target_version=max(document['schema_version'], candidate['schema_version']))
    result['subdesigns'].update(candidate['subdesigns'])
    result['subdesigns'][scope] = {key: value for key, value in candidate.items() if key not in ('project_ips', 'subdesigns')}
    result['subdesigns'][scope]['schema_version'] = 5 if result['schema_version'] == 5 else 3
    if candidate.get('project_ips') or 'project_ips' in result:
        result['project_ips'] = candidate.get('project_ips', [])
    return result, [item for item in validate(result, library) if item.severity == 'error']


def _interface_card(value, *, external=False):
    result = {key: deepcopy(value[key]) for key in ('name', 'protocol', 'definition_version', 'profile', 'mode', 'parameters',
              'signals', 'clock', 'reset', 'valid', 'reason', 'signal', 'error_params') if key in value}
    result['effective_mode'] = ('slave' if value['mode'] == 'master' else 'master') if external else value['mode']
    result['present_signals'] = sorted(value['signals'])
    result['missing_optional_signals'] = sorted(set(AXIS_SIGNALS) - {'tdata', 'tvalid', 'tready'} - value['signals'].keys())
    return result


def compact_design(document, library):
    expansion = expand_interfaces(document, library) if document.get('schema_version') == 5 else None
    projected = expansion['document'] if expansion else document
    resolved = resolve_hierarchy(projected, library) if projected.get("schema_version") == 4 else resolve(projected, library)
    result = {"name": document["name"], "ports": {name: shape.to_dict() for name, shape in resolved.ports.items()},
            "instances": [{"name": item["name"], "ip": item["ip"], "params": item.get("params", {}),
                           **({"hierarchical": True} if item["ip"]["id"] in document.get("subdesigns", {}) else {}),
                           "resolved_params": resolved.instances[item["name"]].parameters if item["name"] in resolved.instances else {},
                           "ports": {name: shape.to_dict() for name, shape in resolved.instances[item["name"]].ports.items()}
                           if item["name"] in resolved.instances else {}} for item in document["instances"]],
            "nets": deepcopy(document["nets"])}
    if expansion:
        info = expansion['bus_interfaces']
        owners, scalar_usage = {}, {}
        for connection in document['interface_connections']:
            for endpoint in (connection['from'], connection['to']):
                owners.setdefault((endpoint.get('inst', ''), endpoint.get('interface', endpoint.get('ext_interface'))), []).append(connection['name'])
        for net in document['nets']:
            pending = list(net['endpoints'])
            while pending:
                endpoint = pending.pop()
                if 'inst' in endpoint or 'ext' in endpoint:
                    scalar_usage.setdefault((endpoint.get('inst', ''), endpoint.get('port', endpoint.get('ext'))), []).append(net['name'])
                pending.extend(endpoint.get('concat', []))

        def cards(declarations, instance=''):
            output = []
            for value in declarations.values():
                if not value.get('confirmed'):
                    continue
                entry = _interface_card(value, external=not instance)
                entry['connections'] = sorted(owners.get((instance, value['name']), []))
                entry['scalar_nets'] = sorted({net for port in value['physical_ports'] for net in scalar_usage.get((instance, port), [])})
                entry['occupied'] = bool(entry['connections'] or entry['scalar_nets'])
                output.append(entry)
            return output

        result['interfaces'] = cards(info['external'])
        result['interface_connections'] = deepcopy(document['interface_connections'])
        for instance in result['instances']:
            instance['interfaces'] = cards(info['instances'].get(instance['name'], {}), instance['name'])
    return result


def metadata_card(metadata, *, include_description=False):
    card = {"id": metadata.id, "version": metadata.version,
            "parameters": [parameter.to_dict() for parameter in metadata.parameters],
            "ports": [port.to_dict() for port in metadata.ports]}
    if include_description and metadata.description:
        card["description"] = clean_description(metadata.description)
    if metadata.interfaces:
        interfaces = []
        for declaration in metadata.interfaces:
            if declaration.get('confirmed') is not True:
                continue
            try:
                value = resolve_interface(metadata, declaration)
            except InterfaceError:
                continue
            interfaces.append({**_interface_card(value), 'parameter_expressions': deepcopy(declaration['parameters'])})
        if interfaces:
            card['interfaces'] = interfaces
    return card


class _DescriptionText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def clean_description(text):
    parser = _DescriptionText()
    parser.feed(text)
    plain = " ".join(parser.parts).replace("BEGIN_BD_DATA", "").replace("END_BD_DATA", "")
    plain = "".join(character if not unicodedata.category(character).startswith("C") else " " for character in plain)
    return " ".join(plain.split())[:200]


@lru_cache(maxsize=1)
def _builtin_descriptions():
    root = Path(__file__).resolve().parents[1] / "ip_library/builtin"
    signatures = set()
    for path in root.glob("*/1.0.0/ip.json"):
        entry = json.loads(path.read_text(encoding="utf-8"))
        signatures.add((entry["id"], entry["version"], entry["source"]["sha256"], entry["description"]))
    return frozenset(signatures)


def is_builtin_description(metadata):
    return (metadata.id, metadata.version, metadata.source.sha256, metadata.description) in _builtin_descriptions()


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
    if 'interface_connections' in full:
        totals['interface_connections'] = len(full['interface_connections'])
    estimated = estimate_tokens(full)
    details = {"scope": "full", "estimated_tokens": estimated, "token_budget": token_budget, "totals": totals,
               "included_instances": sorted(names), "selected_instances": sorted(selected), "boundary_nets": 0}
    if 'interfaces' in full:
        details['included_external_interfaces'] = [item['name'] for item in full['interfaces']]
    if estimated <= token_budget:
        return full, details
    if not selected:
        raise LLMError("AI_CONTEXT_SELECTION_REQUIRED", estimated=estimated, limit=token_budget)
    members = [(net, set().union(*(endpoint_references(item) for item in net["endpoints"]))) for net in full["nets"]]
    buses = [(connection, endpoint_references(connection['from']) | endpoint_references(connection['to'])) for connection in full.get('interface_connections', [])]
    included = selected | set().union(*(references for _, references in [*members, *buses] if references & selected))
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
    if 'interfaces' in full:
        subgraph['interface_connections'] = [deepcopy(connection) for connection, references in buses if references & included and references <= included]
        external_interfaces = {endpoint['ext_interface'] for connection in subgraph['interface_connections']
                               for endpoint in (connection['from'], connection['to']) if 'ext_interface' in endpoint}
        subgraph['interfaces'] = [deepcopy(item) for item in full['interfaces'] if item['name'] in external_interfaces]
        externals.update(member['port'] for item in subgraph['interfaces'] for member in item['signals'].values())
        details['included_external_interfaces'] = sorted(external_interfaces)
        details['boundary_interfaces'] = sum(bool(references & included) and not references <= included for _, references in buses)
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
        external_interfaces = {operation[key]['ext_interface'] for key in ('from', 'to') if 'ext_interface' in operation.get(key, {})}
        if not referenced <= allowed or not external_interfaces <= set(context.get('included_external_interfaces', [])):
            violations.append(operation["op"])
    return violations