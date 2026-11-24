from copy import deepcopy
from dataclasses import replace
import re

import bdtool

from core.expr import ExpressionError, evaluate


AXIS_SIGNALS = {
    "tdata": ("out", "DATA_WIDTH"), "tvalid": ("out", "1"), "tready": ("in", "1"),
    "tkeep": ("out", "DATA_WIDTH / 8"), "tstrb": ("out", "DATA_WIDTH / 8"), "tlast": ("out", "1"),
    "tid": ("out", "ID_WIDTH"), "tdest": ("out", "DEST_WIDTH"), "tuser": ("out", "USER_WIDTH"),
}


class InterfaceError(ValueError):
    def __init__(self, reason, signal="", **params):
        self.reason = reason
        self.signal = signal
        self.params = params
        super().__init__(reason)


def _scope_metadata(scope):
    from bdip import IpMetadata, IpPort, IpSource

    ports = []
    for name, port in scope["ports"].items():
        bounds = tuple(value if type(value) is int else evaluate(value, {}) for value in port["range"]) if "range" in port else None
        width = abs(bounds[0] - bounds[1]) + 1 if bounds is not None else 1
        ports.append(IpPort(name, "in" if port["direction"] == "input" else "out", str(width), port.get("signed", False), bounds))
    return IpMetadata(2, scope["name"], "1.0.0", scope["name"], "", (), IpSource("verilog", f"{scope['name']}.v", "0" * 64, "NOASSERTION"),
                      "verilog-2005", (), tuple(ports), tuple(scope.get("interfaces", [])))


def _endpoint_key(endpoint):
    return (endpoint.get("inst", ""), endpoint.get("port", endpoint.get("ext", "")))


def _scalar_references(endpoint):
    pending = [endpoint]
    while pending:
        current = pending.pop()
        if "inst" in current or "ext" in current:
            yield current
        pending.extend(current.get("concat", []))


def expand_interfaces(document, library):
    import json
    from core.design import DesignFormatError
    from core.diagnostics import issue
    from core.hierarchy import check_hierarchy_document, hierarchy_documents

    check_hierarchy_document(document)
    projected = deepcopy(document)
    for scope in [projected, *projected["subdesigns"].values()]:
        scope.pop("interfaces")
        scope.pop("interface_connections")
        scope["schema_version"] = 4 if scope is projected else 3
    ordered = hierarchy_documents(projected, library)
    metadata_index = {(metadata.id, metadata.version): metadata for metadata in library}
    originals = {document["name"]: document, **document["subdesigns"]}
    scope_metadata = {}
    for name, child in originals.items():
        try:
            scope_metadata[name] = _scope_metadata(child)
            if name in document["subdesigns"]:
                metadata_index[(name, "1.0.0")] = scope_metadata[name]
        except ExpressionError as error:
            raise DesignFormatError(issue("D003", {"design": name}, reason=error.code)) from error
    diagnostics, information, origins, cache, plans, blocked = [], {}, {}, {}, {}, {}
    for scope in ordered:
        original = originals[scope["name"]]
        instances = {item["name"]: item for item in scope["instances"]}
        external_metadata = scope_metadata[scope["name"]]
        info = {"instances": {}, "external": {}, "connections": []}
        information[scope["name"]] = info
        origins[scope["name"]] = {}
        plans[scope["name"]] = {}
        blocked[scope["name"]] = set()
        declared_names, declared_ports = set(), set()
        for declaration in original["interfaces"]:
            if declaration["name"] in declared_names:
                diagnostics.append(issue("E208", {"design": scope["name"], "interface": declaration["name"]},
                                         reason="duplicate_interface", generated_name=declaration["name"]))
                continue
            declared_names.add(declaration["name"])
            for port in declaration["signals"].values():
                if port in declared_ports:
                    diagnostics.append(issue("E208", {"design": scope["name"], "interface": declaration["name"]},
                                             reason="duplicate_interface_port", generated_name=port))
                declared_ports.add(port)
        scalar_usage = {}
        for net in scope["nets"]:
            for endpoint in net["endpoints"]:
                for reference in _scalar_references(endpoint):
                    scalar_usage.setdefault(_endpoint_key(reference), []).append((net["name"], reference.get("slice")))
        claimed = {}
        names = set(instances) | set(scope["ports"]) | declared_names | {net["name"] for net in scope["nets"]}

        def declaration_info(metadata, declaration, overrides):
            key = (id(metadata), declaration["name"], json.dumps(overrides, sort_keys=True))
            if key not in cache:
                try:
                    cache[key] = {**resolve_interface(metadata, declaration, overrides), "valid": True}
                except InterfaceError as error:
                    cache[key] = {"name": declaration["name"], "mode": declaration["mode"], "protocol": declaration["protocol"],
                                  "valid": False, "reason": error.reason, "signal": error.signal, "signals": {}, "error_params": error.params}
                cache[key]["physical_ports"] = list(declaration["signals"].values())
            return cache[key]

        for name, instance in instances.items():
            metadata = metadata_index.get((instance["ip"]["id"], instance["ip"]["version"]))
            if metadata is not None and metadata.interfaces:
                info["instances"][name] = {declaration["name"]: declaration_info(metadata, declaration, instance.get("params", {}))
                                          for declaration in metadata.interfaces}
        info["external"] = {declaration["name"]: declaration_info(external_metadata, declaration, {}) for declaration in external_metadata.interfaces}

        for connection in original["interface_connections"]:
            location = {"design": scope["name"], "connection": connection["name"]}
            start_errors = len(diagnostics)
            try:
                bdtool._name(connection["name"], "interface connection")
            except bdtool.DesignError:
                diagnostics.append(issue("E208", location, reason="identifier", generated_name=connection["name"]))
                continue
            if connection["name"] in names:
                diagnostics.append(issue("E208", location, reason="duplicate_name", generated_name=connection["name"]))
                continue
            names.add(connection["name"])
            endpoints = []
            member_keys = set()
            for address in (connection["from"], connection["to"]):
                external = "ext_interface" in address
                name = address.get("ext_interface", address.get("interface"))
                found = info["external"].get(name) if external else info["instances"].get(address["inst"], {}).get(name)
                if found is None:
                    diagnostics.append(issue("E203", {**location, "interface": name}, reason="unknown_interface", endpoint=address,
                                             missing_signals=[], unresolved_ports=[]))
                    continue
                member_keys.update(f"@{port}" if external else f"{address['inst']}.{port}" for port in found["physical_ports"])
                if not found["valid"]:
                    code = {"unknown_port": "E203", "required_signals": "E203", "direction_or_signedness": "E206", "width": "E204"}.get(found["reason"], "E209")
                    details = {"reason": found["reason"], "signal": found["signal"], "endpoint": address, **found["error_params"]}
                    if code == "E204":
                        details.update(source_width=details["actual_width"], target_width=details["expected_width"])
                    diagnostics.append(issue(code, {**location, "interface": name}, **details))
                    continue
                mode = found["mode"]
                endpoints.append({**found, "address": address, "effective_mode": ("slave" if mode == "master" else "master") if external else mode})
            if len(endpoints) != 2:
                blocked[scope["name"]].update(member_keys)
                continue
            source, target = endpoints
            if (source["protocol"], source["definition_version"], source["profile"]) != (target["protocol"], target["definition_version"], target["profile"]):
                diagnostics.append(issue("E201", location, source_protocol=source["protocol"], target_protocol=target["protocol"]))
                blocked[scope["name"]].update(member_keys)
                continue
            if source["effective_mode"] == target["effective_mode"]:
                diagnostics.append(issue("E202", location, source_mode=source["mode"], target_mode=target["mode"],
                                         effective_source_mode=source["effective_mode"], effective_target_mode=target["effective_mode"]))
                blocked[scope["name"]].update(member_keys)
                continue
            summary = {**deepcopy(connection), "signals": {}}
            generated, additions, bindings, omissions = [], [], [], []

            def pin_for(endpoint, signal):
                port = endpoint["signals"][signal]["port"]
                return {"ext": port} if "ext_interface" in endpoint["address"] else {"inst": endpoint["address"]["inst"], "port": port}

            for signal, (direction, expression) in AXIS_SIGNALS.items():
                first, second = source["signals"].get(signal), target["signals"].get(signal)
                if first is None and second is None:
                    continue
                present_pins = [pin_for(endpoint, signal) for endpoint in (source, target) if signal in endpoint["signals"]]
                for pin in present_pins:
                    key = _endpoint_key(pin)
                    if key in scalar_usage or key in claimed:
                        diagnostics.append(issue("E205", {**location, "signal": signal}, signal=signal, endpoint=pin,
                                                 conflicting_nets=[item[0] for item in scalar_usage.get(key, [])],
                                                 conflicting_connection=claimed.get(key, ""),
                                                 overlap_range=next((item[1] for item in scalar_usage.get(key, []) if item[1]), None)))
                    claimed[key] = connection["name"]
                if first is None or second is None:
                    diagnostics.append(issue("E207", {**location, "signal": signal}, signal=signal,
                                             present_endpoint=source["address"] if first else target["address"],
                                             missing_endpoint=target["address"] if first else source["address"], required_action="explicit_materialization"))
                    driver = source if source["effective_mode"] == "master" else target
                    receiver = target if driver is source else source
                    if signal in receiver["signals"]:
                        sink = pin_for(receiver, signal)
                        width = receiver["signals"][signal]["width"]
                        if signal == "tstrb" and "tkeep" in driver["signals"]:
                            origin = pin_for(driver, "tkeep")
                        else:
                            value = (1 << width) - 1 if signal in ("tkeep", "tstrb") else 0
                            origin = {"const": f"1'b{value}" if width == 1 else f"{width}'h{value:x}"}
                        net_name = f"__bd_if_{connection['name']}__{signal}"
                        if net_name in names:
                            diagnostics.append(issue("E208", location, reason="generated_collision", generated_name=net_name))
                        names.add(net_name)
                        additions.append({"name": net_name, "endpoints": [origin, sink]})
                        bindings.append({"signal": signal, "source": origin, "sink": sink})
                    else:
                        omissions.append({"signal": signal, "endpoint": pin_for(driver, signal)})
                    continue
                if first["width"] != second["width"]:
                    diagnostics.append(issue("E204", {**location, "signal": signal}, signal=signal, parameter=expression,
                                             source_width=first["width"], target_width=second["width"],
                                             source_value=source["parameters"], target_value=target["parameters"]))
                    continue
                pins = [{"ext": shape["port"]} if "ext_interface" in endpoint["address"] else
                        {"inst": endpoint["address"]["inst"], "port": shape["port"]}
                        for endpoint, shape in ((source, first), (target, second))]
                if (source["effective_mode"] == "master") != (direction == "out"):
                    pins.reverse()
                net_name = f"__bd_if_{connection['name']}__{signal}"
                if net_name in names:
                    diagnostics.append(issue("E208", {**location, "signal": signal}, reason="generated_collision", generated_name=net_name))
                    continue
                names.add(net_name)
                generated.append({"name": net_name, "endpoints": pins})
                summary["signals"][signal] = {"net": net_name, "source": pins[0], "sink": pins[1], "width": first["width"]}
                origins[scope["name"]][net_name] = {**location, "signal": signal}
            summary["valid"] = len(diagnostics) == start_errors
            info["connections"].append(summary)
            scope["nets"].extend(generated)
            if not summary["valid"]:
                blocked[scope["name"]].update(member_keys)
            errors = diagnostics[start_errors:]
            if not errors or all(item.code == "E207" for item in errors):
                materialized = deepcopy(generated)
                for addition in additions:
                    source_pin = addition["endpoints"][0]
                    existing = next((net for net in materialized if "const" not in source_pin and net["endpoints"][0] == source_pin), None)
                    if existing is None:
                        materialized.append(addition)
                    else:
                        existing["endpoints"].extend(addition["endpoints"][1:])
                plans[scope["name"]][connection["name"]] = {"nets": materialized, "bindings": bindings, "omitted_outputs": omissions}
                fix = {"kind": "materialize_interface", "scope": scope["name"], "connection": connection["name"],
                       "bindings": bindings, "omitted_outputs": omissions, "requires_confirmation": True}
                for index in range(start_errors, len(diagnostics)):
                    diagnostics[index] = replace(diagnostics[index], fix=fix)
            if len(scope["nets"]) > 100000:
                diagnostics.append(issue("E208", location, reason="expanded_limit", generated_name="", expanded_nets=len(scope["nets"]), limit=100000))
    return {"document": projected, "diagnostics": diagnostics, "bus_interfaces": information[document["name"]],
            "scope_interfaces": information, "origins": origins, "materialization_plans": plans, "blocked_members": blocked}


def materialize_connection(document, library, scope, connection, *, confirmed=False):
    from core.design import DesignFormatError, check_document
    from core.diagnostics import issue

    if confirmed is not True:
        raise DesignFormatError(issue("D006", {}, reason="confirmation_required"))
    result = expand_interfaces(document, library)
    plan = result["materialization_plans"].get(scope, {}).get(connection)
    if plan is None:
        raise DesignFormatError(issue("D006", {}, reason="unsafe_interface_materialization"))
    candidate = deepcopy(document)
    target = candidate if scope == candidate["name"] else candidate["subdesigns"][scope]
    target["interface_connections"] = [item for item in target["interface_connections"] if item["name"] != connection]
    target["nets"].extend(deepcopy(plan["nets"]))
    check_document(candidate)
    return candidate


def resolve_interface(metadata, declaration, overrides=None):
    from core.resolve import ParameterError, parameters

    try:
        if declaration.get("confirmed") is not True:
            raise InterfaceError("unconfirmed")
        if (declaration.get("protocol"), declaration.get("definition_version"), declaration.get("profile")) != ("axi-stream", "1.0.0", "ready-valid"):
            raise InterfaceError("unsupported_definition")
        if declaration.get("mode") not in ("master", "slave"):
            raise InterfaceError("mode")
        missing = sorted({"tdata", "tvalid", "tready"} - declaration.get("signals", {}).keys())
        if missing:
            raise InterfaceError("required_signals", missing_signals=missing)
        values = parameters(metadata, overrides or {})
        bindings = {name: evaluate(expression, values) for name, expression in declaration["parameters"].items()}
        if not 8 <= bindings["DATA_WIDTH"] <= 1024 or bindings["DATA_WIDTH"] % 8:
            raise InterfaceError("data_width", parameter="DATA_WIDTH", value=bindings["DATA_WIDTH"], minimum=8, maximum=1024, multiple_of=8)
        if any(not 1 <= value <= 1024 for value in bindings.values()):
            raise InterfaceError("parameter_range")
        ports = {port.name: port for port in metadata.ports}
        signals = {}
        for signal, port_name in declaration["signals"].items():
            port = ports.get(port_name)
            if port is None:
                raise InterfaceError("unknown_port", signal, unresolved_ports=[port_name])
            direction, expression = AXIS_SIGNALS[signal]
            if declaration["mode"] == "slave":
                direction = "in" if direction == "out" else "out"
            if port.dir != direction or port.signed:
                raise InterfaceError("direction_or_signedness", signal, expected_direction=direction, actual_direction=port.dir, actual_signed=bool(port.signed))
            width = evaluate(expression, bindings)
            actual = evaluate(port.width, values)
            if actual != width:
                raise InterfaceError("width", signal, expected_width=width, actual_width=actual)
            signals[signal] = {"port": port_name, "direction": direction, "width": width}
        for association in ("clock", "reset"):
            if association in declaration and declaration[association] not in ports:
                raise InterfaceError("unknown_association", association)
        return {**deepcopy(declaration), "parameters": bindings, "signals": signals}
    except (ExpressionError, ParameterError, KeyError) as error:
        raise InterfaceError("parameter_or_signal") from error


def validate_metadata_interfaces(metadata):
    from bdip import IpMetadataError

    names, claimed = set(), set()
    for index, declaration in enumerate(metadata.interfaces):
        location = f"$.interfaces[{index}]"
        try:
            if declaration["name"] in names:
                raise InterfaceError("duplicate_interface")
            names.add(declaration["name"])
            for signal, port_name in declaration["signals"].items():
                if port_name in claimed:
                    raise InterfaceError("duplicate_port", signal)
                claimed.add(port_name)
            resolve_interface(metadata, declaration)
        except InterfaceError as error:
            raise IpMetadataError("IP_INTERFACE", location, reason=error.reason, signal=error.signal) from error


def suggest_interfaces(metadata):
    from bdip import IpMetadata, IpMetadataError

    claimed = {port for declaration in metadata.interfaces for port in declaration["signals"].values()}
    groups = {}
    for port in metadata.ports:
        if port.name in claimed:
            continue
        match = re.fullmatch(r"([ms]_axis(?:_[A-Za-z0-9_$]+)?)_(tdata|tvalid|tready|tkeep|tstrb|tlast|tid|tdest|tuser)", port.name, re.IGNORECASE)
        confidence = 0.95
        if match:
            name, signal = match[1], match[2].lower()
        else:
            match = re.fullmatch(r"([ms])_(data|valid|ready|keep|strb|last|id|dest|user)", port.name, re.IGNORECASE)
            if not match:
                continue
            name, signal, confidence = f"{match[1]}_axis", "t" + match[2].lower(), 0.6
        group = groups.setdefault(name, {"signals": {}, "confidence": confidence})
        group["confidence"] = min(group["confidence"], confidence)
        group["signals"].setdefault(signal, []).append(port)
    candidates = []
    available = max(0, 64 - len(metadata.interfaces))
    for name, group in sorted(groups.items())[:available]:
        signals = {signal: ports[0].name for signal, ports in group["signals"].items() if len(ports) == 1}
        missing = sorted({"tdata", "tvalid", "tready"} - signals.keys())
        ambiguous = sorted(signal for signal, ports in group["signals"].items() if len(ports) != 1)
        bindings = {}
        for signal, parameter in (("tdata", "DATA_WIDTH"), ("tid", "ID_WIDTH"), ("tdest", "DEST_WIDTH"), ("tuser", "USER_WIDTH")):
            if signal in signals:
                bindings[parameter] = group["signals"][signal][0].width
        bindings.setdefault("DATA_WIDTH", "")
        declaration = {"name": name, "protocol": "axi-stream", "definition_version": "1.0.0", "profile": "ready-valid",
                       "mode": "master" if name.lower().startswith("m_") else "slave", "parameters": bindings,
                       "signals": signals, "confirmed": False}
        valid, diagnostics = not missing and not ambiguous, []
        if valid:
            try:
                IpMetadata.from_dict({**metadata.to_dict(), "schema_version": 2,
                                      "interfaces": [*metadata.to_dict()["interfaces"], {**declaration, "confirmed": True}]})
            except IpMetadataError as error:
                valid = False
                diagnostics.append({"code": error.code, "message": str(error)})
        candidates.append({"declaration": declaration, "confidence": group["confidence"], "valid": valid,
                           "missing_signals": missing, "ambiguous_signals": ambiguous, "diagnostics": diagnostics,
                           "candidate_limit_reached": len(groups) > available})
    return candidates