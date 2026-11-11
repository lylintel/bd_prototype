from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import tempfile

from jsonschema import Draft202012Validator

import bdtool


ROOT = Path(__file__).resolve().parent
MAX_METADATA_BYTES = 1024 * 1024
IP_VALIDATOR = Draft202012Validator(json.loads((ROOT / "ip.schema.json").read_text(encoding="utf-8")))
MESSAGES = json.loads((ROOT / "locales" / "zh-CN.json").read_text(encoding="utf-8"))


class IpMetadataError(bdtool.DesignError):
    def __init__(self, code: str, location: str, **values: object):
        self.code = code
        self.location = location
        super().__init__(MESSAGES[code].format(location=location, **values))


def _validate(document: object) -> bytes:
    try:
        payload = (json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise IpMetadataError("IP_JSON_INVALID", "$") from error
    if len(payload) > MAX_METADATA_BYTES:
        raise IpMetadataError("IP_METADATA_TOO_LARGE", "$")
    if isinstance(document, dict) and (type(document.get("schema_version")) is not int or document["schema_version"] != 1):
        raise IpMetadataError("IP_SCHEMA_VERSION", "$.schema_version")
    error = next(IP_VALIDATOR.iter_errors(document), None)
    if error is not None:
        location = "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path)
        raise IpMetadataError("IP_SCHEMA_INVALID", location, rule=error.validator)
    names = set()
    for section in ("parameters", "ports"):
        for index, item in enumerate(document[section]):
            location = f"$.{section}[{index}]"
            if item["name"] in names:
                raise IpMetadataError("IP_DUPLICATE_NAME", f"{location}.name", name=item["name"])
            names.add(item["name"])
            if section == "parameters" and item.get("min", -(2**31)) > item.get("max", 2**31 - 1):
                raise IpMetadataError("IP_PARAMETER_LIMITS", location)
    return payload


@dataclass(frozen=True)
class IpSource:
    kind: str
    path: str
    sha256: str
    license: str


@dataclass(frozen=True)
class IpParameter:
    name: str
    type: str
    default: str
    min: int | None = None
    max: int | None = None

    def to_dict(self) -> dict:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class IpRole:
    kind: str
    confidence: float
    confirmed: bool
    polarity: str | None = None
    asynchronous: bool | str | None = None

    def to_dict(self) -> dict:
        data = {"kind": self.kind, "confidence": self.confidence, "confirmed": self.confirmed}
        if self.polarity is not None:
            data["polarity"] = self.polarity
        if self.asynchronous is not None:
            data["async"] = self.asynchronous
        return data


@dataclass(frozen=True)
class IpPort:
    name: str
    dir: str
    width: str
    signed: bool | None = None
    range: tuple[int | str, int | str] | None = None
    role: IpRole | None = None

    def to_dict(self) -> dict:
        data = {"name": self.name, "dir": self.dir, "width": self.width}
        if self.signed is not None:
            data["signed"] = self.signed
        if self.range is not None:
            data["range"] = list(self.range)
        if self.role is not None:
            data["role"] = self.role.to_dict()
        return data


@dataclass(frozen=True)
class IpMetadata:
    schema_version: int
    id: str
    version: str
    display_name: str
    description: str
    tags: tuple[str, ...]
    source: IpSource
    language: str
    parameters: tuple[IpParameter, ...]
    ports: tuple[IpPort, ...]
    interfaces: tuple = ()
    additional_sources: tuple[IpSource, ...] = ()
    base_dir: Path | None = field(default=None, compare=False, repr=False)

    @classmethod
    def from_dict(cls, document: dict, *, base_dir: Path | None = None) -> IpMetadata:
        _validate(document)
        ports = []
        for item in document["ports"]:
            raw_role = item.get("role")
            role = None if raw_role is None else IpRole(raw_role["kind"], raw_role["confidence"], raw_role["confirmed"], raw_role.get("polarity"), raw_role.get("async"))
            ports.append(IpPort(item["name"], item["dir"], item["width"], item.get("signed"),
                                tuple(item["range"]) if "range" in item else None, role))
        return cls(document["schema_version"], document["id"], document["version"], document["display_name"],
                   document["description"], tuple(document["tags"]), IpSource(**document["source"]), document["language"],
                   tuple(IpParameter(**item) for item in document["parameters"]), tuple(ports), tuple(document["interfaces"]),
                   tuple(IpSource(**item) for item in document.get("additional_sources", [])),
                   Path(base_dir).resolve() if base_dir is not None else None)

    def to_dict(self) -> dict:
        data = {
            "schema_version": self.schema_version, "id": self.id, "version": self.version,
            "display_name": self.display_name, "description": self.description, "tags": list(self.tags),
            "source": asdict(self.source), "language": self.language,
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "ports": [port.to_dict() for port in self.ports], "interfaces": list(self.interfaces),
        }
        if self.additional_sources:
            data["additional_sources"] = [asdict(source) for source in self.additional_sources]
        return data


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise IpMetadataError("IP_JSON_DUPLICATE", key)
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise IpMetadataError("IP_JSON_INVALID", value)


def _read_json(path: Path) -> object:
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_METADATA_BYTES + 1)
    except (OSError, ValueError) as error:
        raise IpMetadataError("IP_FILE_READ", str(path)) from error
    if len(raw) > MAX_METADATA_BYTES:
        raise IpMetadataError("IP_METADATA_TOO_LARGE", str(path))
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except IpMetadataError:
        raise
    except (UnicodeError, ValueError, RecursionError) as error:
        raise IpMetadataError("IP_JSON_INVALID", str(path)) from error


def load_ip(path: Path) -> IpMetadata:
    path = Path(path)
    return IpMetadata.from_dict(_read_json(path), base_dir=path.resolve().parent)


def save_ip(metadata: IpMetadata, path: Path) -> None:
    path = Path(path).resolve()
    data = metadata.to_dict()
    _validate(data)
    sources = [data["source"], *data.get("additional_sources", [])]
    for source in sources:
        original = ((metadata.base_dir or path.parent) / source["path"]).resolve()
        if original == path:
            raise IpMetadataError("IP_SOURCE_OVERWRITE", str(path))
        try:
            source["path"] = Path(os.path.relpath(original, path.parent)).as_posix()
        except ValueError as error:
            raise IpMetadataError("IP_FILE_WRITE", str(path)) from error
    payload = _validate(data)
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        temporary.replace(path)
    except OSError as error:
        raise IpMetadataError("IP_FILE_WRITE", str(path)) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _legacy_width(bounds: list[int | str] | None) -> str:
    if bounds is None:
        return "1"
    left, right = bounds
    if isinstance(left, int) and isinstance(right, int):
        return str(abs(left - right) + 1)
    return f"(({left}) >= ({right}) ? ({left}) - ({right}) + 1 : ({right}) - ({left}) + 1)"


def migrate_legacy_modules(document: dict, base_dir: Path, *, workspace_root: Path,
                           version: str = "1.0.0", license_name: str = "NOASSERTION") -> dict[str, IpMetadata]:
    base_dir, workspace_root = Path(base_dir).resolve(), Path(workspace_root).resolve()
    modules = document.get("modules") if isinstance(document, dict) else None
    stub_name = "_ip_migration"
    while isinstance(modules, dict) and (stub_name in modules or f"{stub_name}_wrapper" in modules):
        stub_name += "_"
    try:
        bdtool.validate_design({"name": stub_name, "modules": modules, "ports": {}, "instances": {}, "nets": {}}, base_dir)
    except bdtool.DesignError as error:
        raise IpMetadataError("IP_LEGACY_INVALID", "$.modules", reason=str(error)) from error
    result = {}
    for name, module in modules.items():
        sources = []
        for filename in module["sources"]:
            source = (base_dir / filename).resolve()
            if not source.is_relative_to(workspace_root):
                raise IpMetadataError("IP_SOURCE_OUTSIDE_WORKSPACE", filename)
            digest = hashlib.sha256()
            try:
                with source.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(65536), b""):
                        digest.update(chunk)
            except OSError as error:
                raise IpMetadataError("IP_SOURCE_READ", filename) from error
            sources.append({"kind": "verilog", "path": Path(os.path.relpath(source, base_dir)).as_posix(),
                            "sha256": digest.hexdigest(), "license": license_name})
        ports = []
        for port_name, port in module["ports"].items():
            item = {"name": port_name, "dir": {"input": "in", "output": "out"}[port["direction"]],
                    "width": _legacy_width(port.get("range"))}
            item.update({key: port[key] for key in ("range", "signed") if key in port})
            ports.append(item)
        data = {
            "schema_version": 1, "id": name, "version": version, "display_name": name, "description": "", "tags": [],
            "source": sources[0], "language": "systemverilog" if any(Path(filename).suffix == ".sv" for filename in module["sources"]) else "verilog-2005",
            "parameters": [{"name": parameter_name, "type": "int", "default": str(parameter["default"]),
                            **{key: parameter[key] for key in ("min", "max") if key in parameter}}
                           for parameter_name, parameter in module.get("parameters", {}).items()],
            "ports": ports, "interfaces": [],
        }
        if len(sources) > 1:
            data["additional_sources"] = sources[1:]
        result[name] = IpMetadata.from_dict(data, base_dir=base_dir)
    return result