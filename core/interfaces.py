from copy import deepcopy
import re

from core.expr import ExpressionError, evaluate


AXIS_SIGNALS = {
    "tdata": ("out", "DATA_WIDTH"), "tvalid": ("out", "1"), "tready": ("in", "1"),
    "tkeep": ("out", "DATA_WIDTH / 8"), "tstrb": ("out", "DATA_WIDTH / 8"), "tlast": ("out", "1"),
    "tid": ("out", "ID_WIDTH"), "tdest": ("out", "DEST_WIDTH"), "tuser": ("out", "USER_WIDTH"),
}


class InterfaceError(ValueError):
    def __init__(self, reason, signal=""):
        self.reason = reason
        self.signal = signal
        super().__init__(reason)


def resolve_interface(metadata, declaration, overrides=None):
    from core.resolve import ParameterError, parameters

    try:
        values = parameters(metadata, overrides or {})
        bindings = {name: evaluate(expression, values) for name, expression in declaration["parameters"].items()}
        if not 8 <= bindings["DATA_WIDTH"] <= 1024 or bindings["DATA_WIDTH"] % 8:
            raise InterfaceError("data_width")
        if any(not 1 <= value <= 1024 for value in bindings.values()):
            raise InterfaceError("parameter_range")
        ports = {port.name: port for port in metadata.ports}
        signals = {}
        for signal, port_name in declaration["signals"].items():
            port = ports.get(port_name)
            if port is None:
                raise InterfaceError("unknown_port", signal)
            direction, expression = AXIS_SIGNALS[signal]
            if declaration["mode"] == "slave":
                direction = "in" if direction == "out" else "out"
            if port.dir != direction or port.signed:
                raise InterfaceError("direction_or_signedness", signal)
            width = evaluate(expression, bindings)
            if evaluate(port.width, values) != width:
                raise InterfaceError("width", signal)
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