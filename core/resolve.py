from __future__ import annotations

from dataclasses import dataclass, field
from itertools import filterfalse
from operator import attrgetter
import re
from typing import NamedTuple

import bdtool
from bdip import IpMetadata, IpRole
from core.diagnostics import Diagnostic, issue
from core.expr import ExpressionError, evaluate


MAX_ENDPOINT_NODES = 256
CONSTANT = re.compile(r"([0-9]+)'([sS]?)[bBoOdDhH][0-9a-fA-F_]+")
DRIVES = attrgetter("drives")


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


class PortReference(NamedTuple):
    endpoint: bdtool.Endpoint
    shape: ResolvedPort
    bounds: tuple[int, int]
    drives: bool

    @property
    def key(self) -> str:
        return f"{self.endpoint.instance}.{self.endpoint.port}" if self.endpoint.instance is not None else f"@{self.endpoint.port}"

    @property
    def location(self) -> dict:
        return {"instance": self.endpoint.instance, "port": self.endpoint.port} if self.endpoint.instance is not None else {"external": self.endpoint.port}


class ResolvedEndpoint(NamedTuple):
    raw: dict
    shape: ResolvedPort
    drives: bool
    references: tuple[PortReference, ...] = ()
    index: int = 0

    @property
    def expression(self) -> bool:
        return "slice" in self.raw or "const" in self.raw or "concat" in self.raw

    @property
    def key(self) -> str:
        return endpoint_text(self.raw)

    @property
    def location(self) -> dict:
        if "inst" in self.raw:
            return {"instance": self.raw["inst"], "port": self.raw["port"]}
        return {"external": self.raw["ext"]} if "ext" in self.raw else {}


@dataclass(frozen=True)
class ResolvedNet:
    name: str
    endpoints: tuple[ResolvedEndpoint, ...]
    drivers: tuple[ResolvedEndpoint, ...] = field(init=False, compare=False, repr=False)
    sinks: tuple[ResolvedEndpoint, ...] = field(init=False, compare=False, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "drivers", tuple(filter(DRIVES, self.endpoints)))
        object.__setattr__(self, "sinks", tuple(filterfalse(DRIVES, self.endpoints)))


@dataclass(frozen=True)
class Resolution:
    document: dict
    ports: dict[str, ResolvedPort]
    instances: dict[str, ResolvedInstance]
    nets: tuple[ResolvedNet, ...]
    diagnostics: tuple[Diagnostic, ...]
    usage: dict[str, tuple[tuple[str, PortReference], ...]] = field(default_factory=dict)
    advanced: bool = False


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


class EndpointError(ValueError):
    def __init__(self, reason, location=None, code="D007"):
        self.reason, self.location, self.code = reason, location or {}, code


def endpoint_text(raw: dict, symbols: dict | None = None) -> str:
    if "const" in raw:
        return raw["const"].strip()
    if "concat" in raw:
        return "{" + ", ".join(endpoint_text(child, symbols) for child in raw["concat"]) + "}"
    key = f"{raw['inst']}.{raw['port']}" if "inst" in raw else f"@{raw['ext']}"
    value = symbols[key] if symbols is not None else key
    if "slice" in raw:
        value += f"[{raw['slice'][0]}:{raw['slice'][1]}]"
    return value


def _endpoint(raw, ports, instances, budget, depth=0, index=0):
    budget[0] += 1
    if depth > 16 or budget[0] > MAX_ENDPOINT_NODES:
        raise EndpointError("endpoint_limit")
    if not isinstance(raw, dict):
        raise EndpointError("endpoint_shape")
    if len(raw) == 2 and isinstance(raw.get("inst"), str) and isinstance(raw.get("port"), str):
        instance = instances.get(raw["inst"])
        shape = instance.ports.get(raw["port"]) if instance else None
        if shape is not None:
            drives = shape.direction == "output"
            reference = PortReference(bdtool.Endpoint(raw["inst"], raw["port"]), shape, shape.bounds or (0, 0), drives)
            return ResolvedEndpoint(dict(raw), shape, drives, (reference,), index)
    if set(raw) == {"const"}:
        text = raw["const"]
        match = CONSTANT.fullmatch(text.strip()) if isinstance(text, str) and len(text) <= 4096 else None
        if match is None or not 1 <= int(match[1]) <= 256:
            raise EndpointError("constant_width")
        try:
            evaluate(text)
        except ExpressionError as error:
            raise EndpointError(error.code) from error
        width = int(match[1])
        return ResolvedEndpoint(dict(raw), ResolvedPort("output", (width - 1, 0), bool(match[2])), True, index=index)
    if set(raw) == {"concat"}:
        if not isinstance(raw["concat"], list) or not 1 <= len(raw["concat"]) <= 128:
            raise EndpointError("concat_size")
        children = [_endpoint(child, ports, instances, budget, depth + 1) for child in raw["concat"]]
        if len({child.drives for child in children}) != 1:
            raise EndpointError("concat_direction")
        width = sum(child.shape.width for child in children)
        if width > 65536:
            raise EndpointError("width_range")
        drives = children[0].drives
        shape = ResolvedPort("output" if drives else "input", (width - 1, 0), False)
        return ResolvedEndpoint(dict(raw), shape, drives, tuple(reference for child in children for reference in child.references), index)
    location = {}
    if set(raw) in ({"ext"}, {"ext", "slice"}) and isinstance(raw["ext"], str):
        shape = ports.get(raw["ext"])
        endpoint = bdtool.Endpoint(None, raw["ext"])
        location = {"external": raw["ext"]}
        drives = shape is not None and shape.direction == "input"
    elif set(raw) in ({"inst", "port"}, {"inst", "port", "slice"}) and isinstance(raw["inst"], str) and isinstance(raw["port"], str):
        instance = instances.get(raw["inst"])
        shape = instance.ports.get(raw["port"]) if instance else None
        endpoint = bdtool.Endpoint(raw["inst"], raw["port"])
        location = {"instance": raw["inst"], "port": raw["port"]}
        drives = shape is not None and shape.direction == "output"
    else:
        raise EndpointError("endpoint_shape")
    if shape is None:
        raise EndpointError("reference", location, "E004")
    selected = shape
    bounds = shape.bounds or (0, 0)
    if "slice" in raw:
        selection = raw["slice"]
        if not isinstance(selection, list) or len(selection) != 2 or any(type(bound) is not int for bound in selection):
            raise EndpointError("slice_shape", location)
        if shape.bounds is None:
            raise EndpointError("scalar_slice", location)
        left, right = selection
        if (min(selection) < min(bounds) or max(selection) > max(bounds)
                or (bounds[0] >= bounds[1] and left < right) or (bounds[0] < bounds[1] and left > right)):
            raise EndpointError("slice_bounds", location)
        bounds = (left, right)
        selected = ResolvedPort(shape.direction, (abs(left - right), 0), False, shape.role)
    reference = PortReference(endpoint, shape, bounds, drives)
    return ResolvedEndpoint(dict(raw), selected, drives, (reference,), index)


def resolve(document: dict, library: tuple[IpMetadata, ...] | list[IpMetadata]) -> Resolution:
    findings, ports, instances, nets = [], {}, {}, []
    if (not isinstance(document, dict) or type(document.get("schema_version")) is not int
            or document["schema_version"] not in (2, 3) or not isinstance(document.get("name"), str)
            or set(document) - {"schema_version", "name", "ports", "instances", "nets", "project_ips"}
            or not isinstance(document.get("instances"), list) or len(document["instances"]) > 20000
            or not isinstance(document.get("nets"), list) or len(document["nets"]) > 100000
            or not isinstance(document.get("project_ips", []), list) or len(document.get("project_ips", [])) > 200
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
            findings.append(issue("D003", {"external": name}, reason=getattr(error, "code", str(error))))
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
            if not isinstance(overrides, dict) or any(not isinstance(key, str) or type(value) not in (str, int) for key, value in overrides.items()):
                raise ParameterError("", "type")
            cache_key = (metadata.id, metadata.version, tuple(sorted(overrides.items())))
            if cache_key not in cache:
                values = parameters(metadata, overrides)
                cache[cache_key] = ResolvedInstance(metadata, values, instance_ports(metadata, values))
            instances.setdefault(name, cache[cache_key])
        except ParameterError as error:
            findings.append(issue("D002", {"instance": name, "parameter": error.name}, parameter=error.name, reason=error.reason))
        except (ValueError, ExpressionError) as error:
            findings.append(issue("D003", {"instance": name}, reason=getattr(error, "code", str(error))))
    for ordinal, item in enumerate(document["nets"]):
        if (not isinstance(item, dict) or set(item) != {"name", "endpoints"} or not isinstance(item["name"], str)
                or not isinstance(item["endpoints"], list) or len(item["endpoints"]) > 20000):
            findings.append(issue("D001", {"path": f"$.nets[{ordinal}]"}, reason="net"))
            continue
        endpoints = []
        for endpoint_index, raw in enumerate(item["endpoints"]):
            if document["schema_version"] == 2 and isinstance(raw, dict) and ("slice" in raw or "const" in raw or "concat" in raw):
                findings.append(issue("D007", {"net": item["name"]}, reason="version"))
                continue
            try:
                endpoints.append(_endpoint(raw, ports, instances, [0], index=endpoint_index))
            except EndpointError as error:
                findings.append(issue(error.code, {**error.location, "net": item["name"]}, reason=error.reason,
                                      **({"reference": str(raw)[:512]} if error.code == "E004" else {})))
        nets.append(ResolvedNet(item["name"], tuple(endpoints)))
    usage = {}
    for net in nets:
        for endpoint in net.endpoints:
            for reference in endpoint.references:
                usage.setdefault(reference.key, []).append((net.name, reference))
    return Resolution(document, ports, instances, tuple(nets), tuple(findings),
                      {key: tuple(values) for key, values in usage.items()},
                      any(endpoint.expression for net in nets for endpoint in net.endpoints))