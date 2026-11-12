from __future__ import annotations

from dataclasses import dataclass

import bdtool
from bdip import IpMetadata, IpRole
from core.diagnostics import Diagnostic, issue
from core.expr import ExpressionError, evaluate


@dataclass(frozen=True)
class ResolvedPort(bdtool.Port):
    role: IpRole | None = None

    def to_dict(self) -> dict:
        return {"direction": self.direction, "range": list(self.bounds) if self.bounds is not None else None,
                "signed": self.signed, "width": self.width,
                "role": self.role.to_dict() if self.role is not None else None}


@dataclass(frozen=True)
class ResolvedInstance:
    metadata: IpMetadata
    parameters: dict[str, int]
    ports: dict[str, ResolvedPort]


@dataclass(frozen=True)
class ResolvedEndpoint:
    raw: dict
    shape: ResolvedPort
    drives: bool

    @property
    def key(self) -> str:
        return f"{self.raw['inst']}.{self.raw['port']}" if "inst" in self.raw else f"@{self.raw['ext']}"

    @property
    def location(self) -> dict:
        return {"instance": self.raw["inst"], "port": self.raw["port"]} if "inst" in self.raw else {"external": self.raw["ext"]}


@dataclass(frozen=True)
class ResolvedNet:
    name: str
    endpoints: tuple[ResolvedEndpoint, ...]

    @property
    def drivers(self) -> tuple[ResolvedEndpoint, ...]:
        return tuple(endpoint for endpoint in self.endpoints if endpoint.drives)

    @property
    def sinks(self) -> tuple[ResolvedEndpoint, ...]:
        return tuple(endpoint for endpoint in self.endpoints if not endpoint.drives)


@dataclass(frozen=True)
class Resolution:
    document: dict
    ports: dict[str, ResolvedPort]
    instances: dict[str, ResolvedInstance]
    nets: tuple[ResolvedNet, ...]
    diagnostics: tuple[Diagnostic, ...]


class ParameterError(ValueError):
    def __init__(self, name: str, reason: str):
        self.name, self.reason = name, reason


def parameters(metadata: IpMetadata, overrides: dict) -> dict[str, int]:
    if not isinstance(overrides, dict) or len(overrides) > 256:
        raise ParameterError("", "object")
    names = {parameter.name for parameter in metadata.parameters}
    unknown = overrides.keys() - names
    if unknown:
        raise ParameterError(sorted(unknown)[0], "unknown")
    pending = {parameter.name: parameter for parameter in metadata.parameters}
    values = {}
    while pending:
        progressed = False
        for name, parameter in list(pending.items()):
            raw = overrides.get(name, parameter.default)
            if type(raw) not in (int, str):
                raise ParameterError(name, "type")
            try:
                value = evaluate(raw, values) if isinstance(raw, str) else raw
            except ExpressionError as error:
                if error.code == "EXPR_UNKNOWN":
                    continue
                raise ParameterError(name, error.code) from error
            if (not -(2**31) <= value < 2**31 or (parameter.min is not None and value < parameter.min)
                    or (parameter.max is not None and value > parameter.max)):
                raise ParameterError(name, "range")
            values[name] = value
            del pending[name]
            progressed = True
        if not progressed:
            raise ParameterError(next(iter(pending)), "unknown_or_cycle")
    return {parameter.name: values[parameter.name] for parameter in metadata.parameters}


def _bound(raw, values):
    if type(raw) not in (int, str):
        raise ValueError("bound_type")
    value = evaluate(raw, values) if isinstance(raw, str) else raw
    if not -(2**31) <= value < 2**31:
        raise ValueError("bound_range")
    return value


def instance_ports(metadata: IpMetadata, values: dict) -> dict[str, ResolvedPort]:
    result = {}
    for port in metadata.ports:
        if port.dir not in {"in", "out"}:
            raise ValueError("inout")
        width = evaluate(port.width, values)
        if not 1 <= width <= 65536:
            raise ValueError("width_range")
        bounds = tuple(_bound(bound, values) for bound in port.range) if port.range is not None else None
        if bounds is None and width != 1:
            bounds = (width - 1, 0)
        resolved = ResolvedPort("input" if port.dir == "in" else "output", bounds, bool(port.signed), port.role)
        if resolved.width != width:
            raise ValueError("inconsistent_width")
        result[port.name] = resolved
    return result


def resolve(document: dict, library: tuple[IpMetadata, ...] | list[IpMetadata]) -> Resolution:
    findings, ports, instances, nets = [], {}, {}, []
    if (not isinstance(document, dict) or type(document.get("schema_version")) is not int
            or document["schema_version"] != 2 or not isinstance(document.get("name"), str)
            or set(document) - {"schema_version", "name", "ports", "instances", "nets", "project_ips"}
            or not isinstance(document.get("instances"), list) or len(document["instances"]) > 20000
            or not isinstance(document.get("nets"), list) or len(document["nets"]) > 100000
            or not isinstance(document.get("ports"), dict) or len(document["ports"]) > 20000):
        return Resolution({}, {}, {}, (), (issue("D001", {"path": "$"}, reason="structure"),))
    index = {}
    for metadata in library:
        index.setdefault((metadata.id, metadata.version), []).append(metadata)
    for name, spec in document["ports"].items():
        try:
            if (not isinstance(spec, dict) or set(spec) - {"direction", "range", "signed"}
                    or spec.get("direction") not in {"input", "output"} or type(spec.get("signed", False)) is not bool):
                raise ValueError("port_shape")
            bounds = spec.get("range")
            if bounds is not None and (not isinstance(bounds, list) or len(bounds) != 2):
                raise ValueError("port_range")
            resolved = ResolvedPort(spec["direction"], tuple(_bound(bound, {}) for bound in bounds) if bounds is not None else None, spec.get("signed", False))
            if resolved.width > 65536:
                raise ValueError("port_width")
            ports[name] = resolved
        except (ValueError, ExpressionError) as error:
            findings.append(issue("D003", {"external": name}, reason=str(error)))
    cache = {}
    for ordinal, item in enumerate(document["instances"]):
        if (not isinstance(item, dict) or set(item) - {"name", "ip", "params"} or not isinstance(item.get("name"), str)
                or not isinstance(item.get("ip"), dict) or set(item["ip"]) != {"id", "version"}
                or not all(isinstance(value, str) for value in item["ip"].values())):
            findings.append(issue("D001", {"path": f"$.instances[{ordinal}]"}, reason="instance"))
            continue
        name, reference = item["name"], item["ip"]
        candidates = index.get((reference["id"], reference["version"]), [])
        if len(candidates) != 1:
            findings.append(issue("E005", {"instance": name}, ip=reference["id"], version=reference["version"],
                                  reason="missing" if not candidates else "ambiguous", candidates=[candidate.version for candidate in candidates]))
            continue
        metadata = candidates[0]
        overrides = item.get("params", {})
        try:
            if not isinstance(overrides, dict) or any(type(value) not in (str, int) for value in overrides.values()):
                raise ParameterError("", "type")
            cache_key = (metadata.id, metadata.version, tuple(sorted(overrides.items())))
            if cache_key not in cache:
                values = parameters(metadata, overrides)
                cache[cache_key] = ResolvedInstance(metadata, values, instance_ports(metadata, values))
            instances.setdefault(name, cache[cache_key])
        except ParameterError as error:
            findings.append(issue("D002", {"instance": name, "parameter": error.name}, parameter=error.name, reason=error.reason))
        except (ValueError, ExpressionError) as error:
            findings.append(issue("D003", {"instance": name}, reason=str(error)))
    for ordinal, item in enumerate(document["nets"]):
        if (not isinstance(item, dict) or set(item) != {"name", "endpoints"} or not isinstance(item["name"], str)
                or not isinstance(item["endpoints"], list) or len(item["endpoints"]) > 20000):
            findings.append(issue("D001", {"path": f"$.nets[{ordinal}]"}, reason="net"))
            continue
        endpoints = []
        for raw in item["endpoints"]:
            shape = None
            location = {"net": item["name"]}
            if isinstance(raw, dict) and set(raw) == {"ext"} and isinstance(raw["ext"], str):
                shape = ports.get(raw["ext"])
                location["external"] = raw["ext"]
                drives = shape is not None and shape.direction == "input"
            elif (isinstance(raw, dict) and set(raw) == {"inst", "port"}
                    and isinstance(raw["inst"], str) and isinstance(raw["port"], str)):
                instance = instances.get(raw["inst"])
                shape = instance.ports.get(raw["port"]) if instance else None
                location.update(instance=raw["inst"], port=raw["port"])
                drives = shape is not None and shape.direction == "output"
            if shape is None:
                findings.append(issue("E004", location, reference=str(raw)))
            else:
                endpoints.append(ResolvedEndpoint(dict(raw), shape, drives))
        nets.append(ResolvedNet(item["name"], tuple(endpoints)))
    return Resolution(document, ports, instances, tuple(nets), tuple(findings))