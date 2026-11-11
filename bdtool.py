"""Validate a small digital block design and emit Verilog-2005."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
import tempfile

from core.expr import ExpressionError, evaluate


class DesignError(ValueError):
    """A diagnostic that can be shown directly to a CLI or GUI user."""


@dataclass(frozen=True)
class Port:
    direction: str
    bounds: tuple[int, int] | None
    signed: bool

    @property
    def width(self) -> int:
        return 1 if self.bounds is None else abs(self.bounds[0] - self.bounds[1]) + 1


@dataclass(frozen=True)
class Instance:
    module: str
    parameters: dict[str, int]
    ports: dict[str, Port]


@dataclass(frozen=True)
class Endpoint:
    instance: str | None
    port: str


@dataclass(frozen=True)
class Net:
    name: str
    shape: Port
    driver: Endpoint
    sinks: tuple[Endpoint, ...]


@dataclass(frozen=True)
class Design:
    name: str
    ports: dict[str, Port]
    instances: dict[str, Instance]
    nets: tuple[Net, ...]
    sources: tuple[Path, ...]

    @property
    def wrapper_name(self) -> str:
        return f"{self.name}_wrapper"


IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
KEYWORDS = frozenset("""
always and assign automatic begin buf bufif0 bufif1 case casex casez cell
cmos config deassign default defparam design disable edge else end endcase
endconfig endfunction endgenerate endmodule endprimitive endspecify endtable
endtask event for force forever fork function generate genvar highz0 highz1
if ifnone incdir include initial inout input instance integer join large
liblist library localparam macromodule medium module nand negedge nmos nor
noshowcancelled not notif0 notif1 or output parameter pmos posedge primitive
pull0 pull1 pulldown pullup pulsestyle_ondetect pulsestyle_onevent rcmos real
realtime reg release repeat rnmos rpmos rtran rtranif0 rtranif1 scalared
showcancelled signed small specify specparam strong0 strong1 supply0 supply1
table task time tran tranif0 tranif1 tri tri0 tri1 triand trior trireg unsigned
use vectored wait wand weak0 weak1 while wire wor xnor xor uwire
""".split())


def _object(value: object, where: str) -> dict:
    if not isinstance(value, dict):
        raise DesignError(f"{where}: expected a JSON object")
    return value


def _fields(value: object, where: str, required: set, optional=()) -> dict:
    obj = _object(value, where)
    missing = required - obj.keys()
    extra = obj.keys() - required - set(optional)
    if missing:
        raise DesignError(f"{where}: missing field(s): {', '.join(sorted(missing))}")
    if extra:
        raise DesignError(f"{where}: unknown field(s): {', '.join(sorted(extra))}")
    return obj


def _name(value: object, where: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value) or value in KEYWORDS:
        raise DesignError(f"{where}: invalid Verilog identifier {value!r}")
    return value


def _integer(value: object, where: str) -> int:
    if type(value) is not int or not -(2**31) <= value < 2**31:
        raise DesignError(f"{where}: expected a signed 32-bit integer")
    return value


def _range_bound(value: object, parameters: dict[str, int], where: str) -> int:
    if not isinstance(value, str):
        return _integer(value, where)
    try:
        return _integer(evaluate(value, parameters), where)
    except ExpressionError as error:
        raise DesignError(f"{where}: {error}") from error


def _parameters(specs: object, overrides: object, where: str) -> dict[str, int]:
    specs = _object(specs, f"{where}.parameters")
    overrides = _object(overrides, f"{where}.parameter_overrides")
    unknown = overrides.keys() - specs.keys()
    if unknown:
        raise DesignError(f"{where}: unknown parameter(s): {', '.join(sorted(unknown))}")
    values = {}
    for name, raw in specs.items():
        location = f"{where}.parameters.{name}"
        _name(name, location)
        spec = _fields(raw, location, {"default"}, {"min", "max"})
        default = _integer(spec["default"], f"{location}.default")
        lower = _integer(spec["min"], f"{location}.min") if "min" in spec else -(2**31)
        upper = _integer(spec["max"], f"{location}.max") if "max" in spec else 2**31 - 1
        if not lower <= default <= upper:
            raise DesignError(f"{location}: default {default} outside [{lower}, {upper}]")
        value = _integer(overrides.get(name, default), location)
        if not lower <= value <= upper:
            raise DesignError(f"{location}: value {value} outside [{lower}, {upper}]")
        values[name] = value
    return values


def _ports(raw: object, parameters: dict[str, int], where: str) -> dict[str, Port]:
    result = {}
    for name, value in _object(raw, where).items():
        location = f"{where}.{name}"
        _name(name, location)
        if name in parameters:
            raise DesignError(f"{location}: name conflicts with a parameter")
        port = _fields(value, location, {"direction"}, {"range", "signed"})
        direction = port["direction"]
        if direction not in ("input", "output"):
            raise DesignError(f"{location}: direction must be input or output")
        signed = port.get("signed", False)
        if type(signed) is not bool:
            raise DesignError(f"{location}.signed: expected a boolean")
        bounds = None
        if "range" in port:
            raw_bounds = port["range"]
            if not isinstance(raw_bounds, list) or len(raw_bounds) != 2:
                raise DesignError(f"{location}.range: expected [left, right]")
            bounds = (
                _range_bound(raw_bounds[0], parameters, f"{location}.range[0]"),
                _range_bound(raw_bounds[1], parameters, f"{location}.range[1]"),
            )
        result[name] = Port(direction, bounds, signed)
    return result


def _resolve_endpoint(
    value: object, ports: dict[str, Port], instances: dict[str, Instance], where: str
) -> tuple[Endpoint, Port, bool]:
    if isinstance(value, str):
        if value.startswith("@") and value[1:] in ports:
            name = value[1:]
            port = ports[name]
            return Endpoint(None, name), port, port.direction == "input"
        instance, dot, name = value.partition(".")
        if dot and instance in instances and name in instances[instance].ports:
            port = instances[instance].ports[name]
            return Endpoint(instance, name), port, port.direction == "output"
    raise DesignError(f"{where}: invalid endpoint {value!r}; expected @port or instance.port")


def validate_design(data: object, base_dir: Path) -> Design:
    """Resolve editable JSON data and check it without writing output files."""
    root = _fields(data, "design", {"name", "modules", "ports", "instances", "nets"})
    name = _name(root["name"], "design.name")
    modules = _object(root["modules"], "modules")
    if name in modules or f"{name}_wrapper" in modules:
        raise DesignError("design.name: generated module name conflicts with an IP module")
    sources: list[Path] = []
    for module, raw in modules.items():
        where = f"modules.{module}"
        _name(module, where)
        spec = _fields(raw, where, {"ports", "sources"}, {"parameters"})
        files = spec["sources"]
        if not isinstance(files, list) or not files:
            raise DesignError(f"{where}.sources: expected a nonempty list of source paths")
        for filename in files:
            if not isinstance(filename, str) or not filename or "\x00" in filename:
                raise DesignError(f"{where}.sources: invalid source path {filename!r}")
            source = (base_dir / filename).resolve()
            if not source.is_file():
                raise DesignError(f"{where}.sources: file not found: {filename}")
            sources.append(source)
        defaults = _parameters(spec.get("parameters", {}), {}, where)
        _ports(spec["ports"], defaults, f"{where}.ports")

    ports = _ports(root["ports"], {}, "ports")
    instances = {}
    used_names = set(ports)

    def claim_name(candidate: str, where: str) -> None:
        _name(candidate, where)
        if candidate in used_names:
            raise DesignError(f"{where}: name {candidate!r} conflicts with a port, instance or net")
        used_names.add(candidate)

    for instance, raw in _object(root["instances"], "instances").items():
        where = f"instances.{instance}"
        claim_name(instance, where)
        spec = _fields(raw, where, {"module"}, {"parameters"})
        module = _name(spec["module"], f"{where}.module")
        if module not in modules:
            raise DesignError(f"{where}: unknown module {module!r}")
        definition = modules[module]
        parameters = _parameters(definition.get("parameters", {}), spec.get("parameters", {}), where)
        instance_ports = _ports(definition["ports"], parameters, f"{where}.ports")
        instances[instance] = Instance(module, parameters, instance_ports)

    nets = []
    connected: dict[Endpoint, str] = {}
    for net_name, endpoints in _object(root["nets"], "nets").items():
        where = f"nets.{net_name}"
        claim_name(net_name, where)
        if not isinstance(endpoints, list) or len(endpoints) < 2:
            raise DesignError(f"{where}: expected a driver and at least one sink")
        drivers = []
        sinks = []
        for value in endpoints:
            endpoint, port, drives = _resolve_endpoint(value, ports, instances, where)
            if endpoint in connected:
                raise DesignError(f"{where}: endpoint {value!r} already connected to {connected[endpoint]!r}")
            connected[endpoint] = net_name
            (drivers if drives else sinks).append((endpoint, port, value))
        if len(drivers) != 1:
            detail = ", ".join(driver[2] for driver in drivers) or "none"
            raise DesignError(f"{where}: expected exactly one driver, found {len(drivers)} ({detail})")
        driver, shape, driver_name = drivers[0]
        for sink, sink_port, sink_name in sinks:
            if shape.width != sink_port.width:
                raise DesignError(
                    f"{where}: width mismatch: {driver_name} ({shape.width}) -> "
                    f"{sink_name} ({sink_port.width})"
                )
            if shape.bounds != sink_port.bounds or shape.signed != sink_port.signed:
                raise DesignError(f"{where}: range or signedness mismatch: {driver_name} -> {sink_name}; use an explicit adapter")
        nets.append(Net(net_name, shape, driver, tuple(sink[0] for sink in sinks)))

    for port_name, port in ports.items():
        if port.direction == "output" and Endpoint(None, port_name) not in connected:
            raise DesignError(f"ports.{port_name}: external output has no driver")
    for instance_name, instance in instances.items():
        for port_name, port in instance.ports.items():
            if port.direction == "input" and Endpoint(instance_name, port_name) not in connected:
                raise DesignError(f"instances.{instance_name}.ports.{port_name}: required input is unconnected")

    return Design(name, ports, instances, tuple(nets), tuple(dict.fromkeys(sources)))


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise DesignError(f"JSON: duplicate key {key!r}")
        result[key] = value
    return result


def load_design(path: Path) -> Design:
    """Load a design from disk, resolving source paths relative to its JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
    return validate_design(data, path.resolve().parent)


def _declaration(name: str, port: Port, external: bool = False) -> str:
    pieces = [port.direction, "wire"] if external else ["wire"]
    if port.signed:
        pieces.append("signed")
    if port.bounds is not None:
        pieces.append(f"[{port.bounds[0]}:{port.bounds[1]}]")
    return " ".join([*pieces, name])


def _module_header(name: str, ports: dict[str, Port]) -> str:
    declarations = ",\n".join(f"    {_declaration(port_name, port, external=True)}"
                              for port_name, port in ports.items())
    return f"module {name} (\n{declarations}\n);" if declarations else f"module {name} ();"


def _instance(
    module: str, name: str, parameters: dict[str, int], bindings: dict[str, str]
) -> str:
    opening = f"    {module}"
    if parameters:
        arguments = ",\n".join(f"        .{key}({value})" for key, value in parameters.items())
        opening += f" #(\n{arguments}\n    )"
    pins = ",\n".join(f"        .{key}({value})" for key, value in bindings.items())
    return f"{opening} {name} (\n{pins}\n    );" if pins else f"{opening} {name} ();"


def render_verilog(design: Design) -> dict[str, str]:
    """Return both HDL files as text. Preserve declaration order from the input."""
    bindings = {}
    lines = [_module_header(design.name, design.ports)]
    if design.nets:
        lines.append("")
    for net in design.nets:
        lines.append(f"    {_declaration(net.name, net.shape)};")
        bindings[net.driver] = net.name
        for sink in net.sinks:
            bindings[sink] = net.name

    assigns = []
    for net in design.nets:
        if net.driver.instance is None:
            assigns.append(f"    assign {net.name} = {net.driver.port};")
        for sink in net.sinks:
            if sink.instance is None:
                assigns.append(f"    assign {sink.port} = {net.name};")
    if assigns:
        lines.extend(["", *assigns])

    for name, instance in design.instances.items():
        pins = {port: bindings.get(Endpoint(name, port), "") for port in instance.ports}
        lines.extend(["", _instance(instance.module, name, instance.parameters, pins)])
    lines.append("endmodule")

    wrapper_instance = "bd_i"
    while wrapper_instance in design.ports:
        wrapper_instance += "_"
    wrapper = [
        _module_header(design.wrapper_name, design.ports),
        "",
        _instance(design.name, wrapper_instance, {}, {port: port for port in design.ports}),
        "endmodule",
    ]
    return {
        f"{design.name}.v": "\n".join(lines) + "\n",
        f"{design.wrapper_name}.v": "\n".join(wrapper) + "\n",
    }


def _write_outputs(
    files: dict[str, str], out_dir: Path, protected_paths: set[Path]
) -> None:
    for name in files:
        path = out_dir / name
        if path.resolve() in protected_paths:
            raise DesignError(f"output would overwrite an input file: {path}")
        if path.exists() and not path.is_file():
            raise DesignError(f"output path is not a file: {path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bd-stage-", dir=out_dir) as staging:
        for name, content in files.items():
            (Path(staging) / name).write_text(content, encoding="utf-8", newline="\n")
        for name in files:
            (Path(staging) / name).replace(out_dir / name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="check a design").add_argument("design", type=Path)
    generate = commands.add_parser("generate", help="write structural Verilog and a wrapper")
    generate.add_argument("design", type=Path)
    generate.add_argument("-o", "--out-dir", type=Path, default=Path("build"))
    args = parser.parse_args(argv)

    try:
        design = load_design(args.design)
        if args.command == "validate":
            print(f"Valid: {design.name} ({len(design.instances)} instances, {len(design.nets)} nets)")
        else:
            files = render_verilog(design)
            _write_outputs(files, args.out_dir, {*design.sources, args.design.resolve()})
            for filename in files:
                print(args.out_dir / filename)
    except (DesignError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
