from copy import deepcopy

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