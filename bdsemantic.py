from copy import deepcopy
from dataclasses import replace
import json
import hashlib
import os
from pathlib import Path

import bdtool
from bdip import IpMetadata, migrate_legacy_modules
from core.design import DesignFormatError, check_document, migrate
from core.diagnostics import Diagnostic, issue
from core.persistence import write_project
from core.resolve import ParameterError, parameters
from core.semantic import inspect_design


def prepare(workspace, document, base_dir):
    base = workspace.path(base_dir)
    if not isinstance(document, dict):
        raise DesignFormatError(issue("D001", {}, reason="object"))
    if "schema_version" not in document:
        workspace.structure(document)
        workspace.sources(document, base)
        project = tuple(migrate_legacy_modules(document, base, workspace_root=workspace.root).values())
        ids = {metadata.id for metadata in project}
    else:
        if document.get("schema_version") not in (2, 3, 4, 5):
            raise DesignFormatError(issue("D001", {}, reason="schema_version"))
        raw_project = document.get("project_ips", [])
        if not isinstance(raw_project, list) or len(raw_project) > 200:
            raise DesignFormatError(issue("D001", {}, reason="project_ips"))
        project = tuple(IpMetadata.from_dict(item, base_dir=base) for item in raw_project)
        ids = {metadata.id for metadata in project}
        scopes = [document]
        if document.get("schema_version") in (4, 5):
            from core.hierarchy import check_hierarchy_document
            check_hierarchy_document(document)
            scopes.extend(document["subdesigns"].values())
        for scope in scopes:
            for instance in scope.get("instances", []) if isinstance(scope.get("instances"), list) else []:
                if isinstance(instance, dict) and isinstance(instance.get("ip"), dict) and isinstance(instance["ip"].get("id"), str):
                    ids.add(instance["ip"]["id"])
        ids.difference_update(document.get("subdesigns", {}))
    published = workspace.ip_library().metadata_snapshot(ids, base_dir=base)
    library = list(published)
    seen_project = set()
    for metadata in project:
        key = (metadata.id, metadata.version)
        if key in seen_project:
            raise DesignFormatError(issue("E005", {}, ip=metadata.id, version=metadata.version, reason="ambiguous", candidates=[metadata.version]))
        seen_project.add(key)
        for source in (metadata.source, *metadata.additional_sources):
            path = (base / source.path).resolve()
            if (not path.is_relative_to(workspace.root) or not path.is_file() or path.stat().st_size > 1024 * 1024
                    or hashlib.sha256(path.read_bytes()).hexdigest() != source.sha256):
                raise DesignFormatError(issue("D005", {"module": metadata.id}, reason="source"))
        candidates = [item for item in published if item.id == metadata.id]
        if "schema_version" not in document:
            if candidates and any(item.source.sha256 != metadata.source.sha256 for item in candidates):
                raise DesignFormatError(issue("E005", {"module": metadata.id}, ip=metadata.id, version="", reason="definition_conflict", candidates=[item.version for item in candidates]))
            if not candidates:
                library.append(metadata)
        else:
            exact = [item for item in candidates if item.version == metadata.version]
            if exact and exact[0].to_dict() != metadata.to_dict():
                raise DesignFormatError(issue("E005", {"module": metadata.id}, ip=metadata.id, version=metadata.version, reason="definition_conflict", candidates=[item.version for item in exact]))
            if not exact:
                library.append(metadata)
    prepared = migrate(document, library) if "schema_version" not in document else deepcopy(document)
    return prepared, tuple(library)


def _canvas_pins(endpoint, depth=0):
    if not isinstance(endpoint, dict) or depth > 16:
        return []
    if "inst" in endpoint and "port" in endpoint:
        return [f"{endpoint['inst']}.{endpoint['port']}"]
    if "ext" in endpoint:
        return [f"@{endpoint['ext']}"]
    if isinstance(endpoint.get("concat"), list):
        return [pin for child in endpoint["concat"][:128] for pin in _canvas_pins(child, depth + 1)]
    return []


def canvas_document(document, library):
    if document.get("schema_version") == 5:
        from core.interfaces import expand_interfaces
        document = expand_interfaces(document, library)["document"]
    if document.get("schema_version") == 4:
        from core.hierarchy import hierarchy_library
        _, library = hierarchy_library(document, library)
    modules = {}
    for metadata in library:
        try:
            values = parameters(metadata, {})
        except ParameterError:
            values = {parameter.name: parameter.default for parameter in metadata.parameters}
        modules[metadata.id] = {"sources": [source.path for source in (metadata.source, *metadata.additional_sources)],
            "parameters": {parameter.name: {"default": values[parameter.name],
                           **{key: value for key, value in parameter.to_dict().items() if key in {"min", "max"}}} for parameter in metadata.parameters},
            "ports": {port.name: {"direction": "input" if port.dir == "in" else "output", "signed": bool(port.signed),
                      **({"range": list(port.range)} if port.range is not None else {})} for port in metadata.ports}}
    instances = {}
    for item in document.get("instances", []):
        if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("ip"), dict):
            module = item["ip"].get("id", "")
            modules.setdefault(module, {"sources": [], "parameters": {}, "ports": {}})
            instances[item["name"]] = {"module": module, "parameters": deepcopy(item.get("params", {}))}
    nets = {}
    for item in document.get("nets", []):
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            nets[item["name"]] = list(dict.fromkeys(pin for endpoint in item.get("endpoints", []) for pin in _canvas_pins(endpoint)))
    return {"name": document.get("name", ""), "modules": modules, "instances": instances,
            "ports": deepcopy(document.get("ports", {})), "nets": nets}


def inspect_workspace(workspace, document, base_dir):
    try:
        prepared, library = prepare(workspace, document, base_dir)
        metadata_library = library
        canvas_source = prepared
        if prepared.get("schema_version") == 5:
            from core.interfaces import expand_interfaces
            from core.hierarchy import hierarchy_library
            from core.semantic import inspect_interface_expansion
            expanded = expand_interfaces(prepared, library)
            result = inspect_interface_expansion(prepared, library, expanded)
            documents, metadata_library = hierarchy_library(expanded["document"], library)
            metadata_library = tuple(replace(metadata, schema_version=2, interfaces=tuple(prepared["subdesigns"][metadata.id]["interfaces"]))
                                     if metadata.id in prepared["subdesigns"] and prepared["subdesigns"][metadata.id]["interfaces"] else metadata
                                     for metadata in metadata_library)
            canvas_source = documents[-1]
        elif prepared.get("schema_version") == 4:
            from core.hierarchy import hierarchy_library, inspect_hierarchy_documents
            resolutions = {}
            documents, metadata_library = hierarchy_library(prepared, library, resolutions=resolutions)
            result = inspect_hierarchy_documents(documents, metadata_library, resolutions=resolutions)
            canvas_source = documents[-1]
        else:
            result = inspect_design(prepared, library)
        result.update(document=prepared, canvas=canvas_document(canvas_source, metadata_library), metadata=[metadata.to_dict() for metadata in metadata_library])
        return result
    except (bdtool.DesignError, DesignFormatError, OSError, ValueError, TypeError, KeyError) as error:
        diagnostic = error.diagnostic if isinstance(error, DesignFormatError) else issue("D005", {}, reason=getattr(error, "code", "source_or_metadata"))
        return {"valid": False, "diagnostics": [diagnostic.to_dict()], "files": {}, "parameters": {},
                "interfaces": {"ports": {}, "instances": {}}}


def interface_action(workspace, payload):
    from core.interfaces import expand_interfaces, materialize_connection

    action = payload.get("action")
    if action not in ("migrate", "connect", "disconnect", "plan", "materialize"):
        raise DesignFormatError(issue("D006", {}, reason="interface_action"))
    base_dir = payload.get("base_dir", ".")
    document, library = prepare(workspace, payload.get("design"), base_dir)
    if action == "migrate":
        if payload.get("confirmed") is not True:
            raise DesignFormatError(issue("D006", {}, reason="confirmation_required"))
        return inspect_workspace(workspace, migrate(document, library, target_version=5), base_dir)
    if document.get("schema_version") != 5:
        raise DesignFormatError(issue("D006", {}, reason="interface_migration_required"))
    scope = payload.get("scope", "")
    if not isinstance(scope, str) or scope and scope not in document["subdesigns"]:
        raise DesignFormatError(issue("D006", {}, reason="interface_scope"))
    candidate = deepcopy(document)
    target = candidate["subdesigns"][scope] if scope else candidate
    connection = payload.get("connection")
    if action in ("plan", "materialize"):
        expanded = expand_interfaces(document, library)
        plan = expanded["materialization_plans"].get(target["name"], {}).get(connection)
        if plan is None:
            raise DesignFormatError(issue("D006", {}, reason="unsafe_interface_materialization"))
        if action == "plan":
            return {"plan": deepcopy(plan), "scope": target["name"], "connection": connection}
        candidate = materialize_connection(document, library, target["name"], connection, confirmed=payload.get("confirmed", False))
    elif action == "disconnect":
        if sum(item["name"] == connection for item in target["interface_connections"]) != 1:
            raise DesignFormatError(issue("D006", {}, reason="unknown_interface_connection"))
        target["interface_connections"] = [item for item in target["interface_connections"] if item["name"] != connection]
    else:
        names = set(target["ports"]) | {item["name"] for key in ("instances", "nets", "interfaces", "interface_connections") for item in target[key]}
        ordinal = 0
        while f"stream_{ordinal}" in names:
            ordinal += 1
        target["interface_connections"].append({"name": payload.get("name", f"stream_{ordinal}"),
                                                "from": deepcopy(payload.get("from")), "to": deepcopy(payload.get("to"))})
    check_document(candidate)
    result = inspect_workspace(workspace, candidate, base_dir)
    if action == "connect":
        blocked = next((item for item in result["diagnostics"] if item["severity"] == "error" and
                        item["code"] not in ("E003", "E207")), None)
        if blocked is not None:
            raise DesignFormatError(Diagnostic(**blocked))
    return result


def collapse_workspace(workspace, payload):
    from core.hierarchy import collapse_design, scope_document

    document, library = prepare(workspace, payload.get("design"), payload.get("base_dir", "."))
    selection = payload.get("selection")
    if not isinstance(selection, list) or any(not isinstance(name, str) for name in selection):
        raise DesignFormatError(issue("D001", {}, reason="hierarchy_selection"))
    scope = payload.get('scope', '')
    target = scope_document(document, scope)
    crossing = [connection for connection in target.get('interface_connections', [])
                if sum(connection[key].get('inst') in selection for key in ('from', 'to')) == 1]
    if crossing and payload.get('confirmed') is not True:
        raise DesignFormatError(issue('D006', {'design': target['name']}, reason='confirmation_required'))
    if scope and (payload.get('name') in document['subdesigns'] or payload.get('name') in (document['name'], f"{document['name']}_wrapper")):
        raise DesignFormatError(issue('D001', {}, reason='hierarchy_collision'))
    folded = collapse_design(target, library, selection, payload.get('name'))
    result = folded
    if scope:
        result = deepcopy(document)
        result['subdesigns'].update(folded['subdesigns'])
        result['subdesigns'][scope] = {key: value for key, value in folded.items() if key not in ('project_ips', 'subdesigns')}
        result['subdesigns'][scope]['schema_version'] = 5 if result['schema_version'] == 5 else 3
    inspection = inspect_workspace(workspace, result, payload.get('base_dir', '.'))
    if scope and inspection['valid']:
        view = scope_document(result, scope)
        inspection.update(scope_document=view, scope_canvas=canvas_document(view, library))
    return inspection


def inspect_scope(workspace, payload):
    from core.hierarchy import scope_document

    document = payload.get("design")
    root = inspect_workspace(workspace, document, payload.get("base_dir", "."))
    scope = payload.get("scope")
    if not scope or "document" not in root:
        return root
    view = scope_document(root['document'], scope)
    result = inspect_workspace(workspace, view, payload.get("base_dir", "."))
    diagnostics = [{key: value for key, value in item.items() if key != "fix"} for item in root["diagnostics"]]
    return {**result, "valid": root["valid"], "diagnostics": diagnostics, "files": root["files"]}


def save_document(workspace, payload):
    from bdgui import check_layout

    document, library = prepare(workspace, payload.get("design"), payload.get("base_dir", "."))
    check_document(document)
    target = workspace.path(payload.get("path", ""))
    if not target.is_relative_to(workspace.path("designs")) or target.suffix != ".json" or target.name.endswith(".layout.json"):
        raise DesignFormatError(issue("D005", {}, reason="save_path"))
    base = workspace.path(payload.get("base_dir", "."))
    sources = set()
    snapshots = []
    for metadata in library:
        raw = metadata.to_dict()
        for source in [raw["source"], *raw.get("additional_sources", [])]:
            path = (base / source["path"]).resolve()
            sources.add(path)
            source["path"] = Path(os.path.relpath(path, target.parent)).as_posix()
        snapshots.append(raw)
    document["project_ips"] = snapshots
    check_document(document)
    layout = check_layout(payload.get("layout", {}))
    write_project(document, layout, target, sources, workspace.root)
    return workspace.load(workspace.relative(target))


def check_generated(workspace, payload):
    from bdcheck import run_checks
    from core.generation import generate_artifacts

    document, library = prepare(workspace, payload.get("design"), payload.get("base_dir", "."))
    artifacts = generate_artifacts(document, library, language=payload.get("lang", "v"))
    base = workspace.path(payload.get("base_dir", "."))
    sources = sorted({(base / source.path).resolve() for item in library for source in (item.source, *item.additional_sources)})
    result = run_checks(artifacts["files"], sources, f"{document['name']}_wrapper", workspace_root=workspace.root,
                        strict_lint=payload.get("strict_lint", False))
    source_instances = {}
    index = {(item.id, item.version): item for item in library}
    for scope in [document, *document.get("subdesigns", {}).values()]:
        for instance in scope["instances"]:
            metadata = index.get((instance["ip"]["id"], instance["ip"]["version"]))
            if metadata is not None:
                for source in (metadata.source, *metadata.additional_sources):
                    source_instances.setdefault(str((base / source.path).resolve()), []).append({"design": scope["name"], "instance": instance["name"]})
    for diagnostic in result["diagnostics"]:
        location = diagnostic["location"]
        filename, line = location.get("file"), location.get("line", 0)
        ranges = artifacts["source_map"]["files"].get(filename, {}).get("ranges", [])
        matches = [item for item in ranges if item["start_line"] <= line <= item["end_line"]]
        if matches:
            target = min(matches, key=lambda item: item["end_line"] - item["start_line"])["location"]
            location.update(target)
        elif len(source_instances.get(filename, [])) == 1:
            location.update(source_instances[filename][0])
    return {**artifacts, **result}


def generate_document(workspace, payload):
    if type(payload.get("quality", False)) is not bool:
        raise DesignFormatError(issue("D005", {}, reason="generation_options"))
    document, library = prepare(workspace, payload.get("design"), payload.get("base_dir", "."))
    source_map = None
    if payload.get("quality", False) or payload.get("lang", "v") == "sv":
        from core.generation import generate_artifacts
        artifacts = generate_artifacts(document, library, language=payload.get("lang", "v"))
        files, source_map = artifacts["files"], artifacts["source_map"]
    else:
        result = inspect_design(document, library)
        if not result["valid"]:
            raise bdtool.DesignError(result["diagnostics"][0]["message"])
        files = result["files"]
    base = workspace.path(payload.get("base_dir", "."))
    sources = {(base / source.path).resolve() for metadata in library for source in (metadata.source, *metadata.additional_sources)}
    output = workspace.path(payload.get("out_dir", "build/gui"))
    outputs = dict(files)
    if source_map is not None:
        outputs[f"{document['name']}.source-map.json"] = json.dumps(source_map, indent=2, ensure_ascii=False) + "\n"
    if payload.get("design_path"):
        sources.add(workspace.path(payload["design_path"]))
    bdtool._write_outputs(outputs, output, sources)
    return {"files": files, "paths": [workspace.relative(output / name) for name in outputs], **({"source_map": source_map} if source_map is not None else {})}