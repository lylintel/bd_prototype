from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

import bdtool
from bdip import IpMetadata, IpMetadataError, MESSAGES, load_ip, save_ip
from core.expr import ExpressionError, evaluate
from .parser import MAX_SOURCE_BYTES, parse_file
from .roles import suggest_roles


MAX_FILES = 200
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{number}" for number in range(1, 10)), *(f"LPT{number}" for number in range(1, 10))}


class LibraryError(bdtool.DesignError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(MESSAGES[code].format(detail=detail))


@dataclass(frozen=True)
class Upload:
    name: str
    content: bytes

    def __post_init__(self):
        if (not isinstance(self.name, str) or not 1 <= len(self.name) <= 128
                or re.search(r'[\\/<>:"|?*\x00-\x1f]', self.name)
                or self.name.endswith((" ", ".")) or self.name.split(".")[0].upper() in RESERVED
                or Path(self.name).suffix.lower() not in {".v", ".sv"}):
            raise LibraryError("IP_LIBRARY_INPUT")
        if not isinstance(self.content, bytes) or len(self.content) > MAX_SOURCE_BYTES:
            raise LibraryError("IP_LIBRARY_SIZE", self.name)


def defaults(metadata: IpMetadata) -> dict[str, int]:
    pending = {parameter.name: parameter for parameter in metadata.parameters}
    values = {}
    while pending:
        progress = False
        for name, parameter in list(pending.items()):
            try:
                value = evaluate(parameter.default, values)
            except ExpressionError as error:
                if error.code == "EXPR_UNKNOWN":
                    continue
                raise LibraryError("IP_LIBRARY_PARAMETER", name) from error
            if not -(2**31) <= value < 2**31 or (parameter.min is not None and value < parameter.min) or (parameter.max is not None and value > parameter.max):
                raise LibraryError("IP_LIBRARY_PARAMETER", name)
            values[name] = value
            del pending[name]
            progress = True
        if not progress:
            raise LibraryError("IP_LIBRARY_PARAMETER", ", ".join(pending))
    for port in metadata.ports:
        try:
            if evaluate(port.width, values) < 1:
                raise LibraryError("IP_LIBRARY_PARAMETER", port.name)
        except ExpressionError as error:
            raise LibraryError("IP_LIBRARY_PARAMETER", port.name) from error
    return values


def _signature(metadata: IpMetadata) -> str:
    data = {"parameters": [parameter.to_dict() for parameter in metadata.parameters],
            "ports": [{key: value for key, value in port.to_dict().items() if key != "role"} for port in metadata.ports]}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _version(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or len(value) > 64 or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise LibraryError("IP_LIBRARY_VERSION")
    return tuple(int(part) for part in value.split("."))


def interface_diff(previous: IpMetadata, current: IpMetadata) -> dict:
    result = {}
    for section in ("ports", "parameters"):
        before = {item.name: item.to_dict() for item in getattr(previous, section)}
        after = {item.name: item.to_dict() for item in getattr(current, section)}
        result[f"added_{section}"] = sorted(after.keys() - before.keys())
        result[f"removed_{section}"] = sorted(before.keys() - after.keys())
        result[f"changed_{section}"] = sorted(name for name in before.keys() & after.keys() if before[name] != after[name])
    return result


def _edited(original: IpMetadata, document: dict) -> IpMetadata:
    metadata = IpMetadata.from_dict(document, base_dir=original.base_dir)
    if (metadata.id != original.id or metadata.language != original.language or metadata.additional_sources
            or (metadata.source.kind, metadata.source.path, metadata.source.sha256) != (original.source.kind, original.source.path, original.source.sha256)
            or [item.name for item in metadata.parameters] != [item.name for item in original.parameters]
            or [item.name for item in metadata.ports] != [item.name for item in original.ports]):
        raise LibraryError("IP_LIBRARY_INTERFACE", original.id)
    values = defaults(metadata)
    for port, expected in zip(metadata.ports, original.ports):
        if (port.dir, port.range, port.signed) != (expected.dir, expected.range, expected.signed):
            raise LibraryError("IP_LIBRARY_INTERFACE", port.name)
        if evaluate(port.width, values) != evaluate(expected.width, values):
            raise LibraryError("IP_LIBRARY_INTERFACE", port.name)
    return metadata


def _external_dependencies(name: str, dependencies: dict[str, tuple[str, ...]]) -> list[str]:
    pending, visited, external = [name], set(), set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        for dependency in dependencies.get(current, ()):
            if dependency in dependencies:
                pending.append(dependency)
            else:
                external.add(dependency)
    return sorted(external)


class IpLibrary:
    def __init__(self, workspace: Path):
        self.root = Path(workspace).resolve()
        self.directory = self.root / "ip_library"

    def _path(self, relative: str) -> Path:
        raw = self.directory / relative
        path = raw.resolve()
        if not path.is_relative_to(self.directory) or any(parent.is_symlink() for parent in (raw, *raw.parents) if parent != self.root):
            raise LibraryError("IP_LIBRARY_PATH")
        return path

    def _index(self) -> dict:
        path = self._path("index.json")
        if not path.exists():
            return {"schema_version": 1, "entries": {}, "sources": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=bdtool._unique_keys)
            if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1 or not isinstance(data.get("entries"), dict) or not isinstance(data.get("sources"), dict):
                raise ValueError()
            for entry in data["entries"].values():
                if not all(isinstance(entry[key], str) for key in ("id", "version", "metadata", "source_sha256", "interface_hash", "origin")):
                    raise ValueError()
                _version(entry["version"])
                if not isinstance(entry.get("dependencies", []), list) or not all(isinstance(name, str) for name in entry.get("dependencies", [])):
                    raise ValueError()
            for source in data["sources"].values():
                if not isinstance(source["path"], str) or not isinstance(source["modules"], list) or not all(isinstance(name, str) for name in source["modules"]):
                    raise ValueError()
            return data
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise LibraryError("IP_LIBRARY_INDEX") from error

    @contextmanager
    def _locked(self):
        self._path("index.json")
        self.directory.mkdir(parents=True, exist_ok=True)
        lock = self.directory / ".lock"
        try:
            handle = lock.open("x", encoding="ascii")
        except FileExistsError as error:
            raise LibraryError("IP_LIBRARY_BUSY") from error
        try:
            with handle:
                handle.write(str(os.getpid()))
                handle.flush()
                yield
        finally:
            lock.unlink(missing_ok=True)

    def _latest(self, index: dict, name: str) -> dict | None:
        return max((entry for entry in index["entries"].values() if entry["id"] == name),
                   key=lambda entry: _version(entry["version"]), default=None)

    def _decision(self, index: dict, metadata: IpMetadata, version: str | None) -> tuple[str, str, dict]:
        latest = self._latest(index, metadata.id)
        selected_version = version or (latest["version"] if latest else "1.0.0")
        _version(selected_version)
        signature = _signature(metadata)
        existing = index["entries"].get(f"{metadata.id}@{selected_version}")
        if existing and existing["source_sha256"] == metadata.source.sha256 and existing["interface_hash"] == signature:
            return "skipped", selected_version, {}
        diff = interface_diff(load_ip(self._path(latest["metadata"])), metadata) if latest else {}
        if latest and (version is None or _version(selected_version) <= _version(latest["version"])):
            return "needs_version", selected_version, diff
        return "ready", selected_version, diff

    def _publish(self, metadata: IpMetadata, upload: Upload, version: str | None, origin: str, names: list[str], dependencies: list[str]) -> tuple[str, str, dict]:
        if metadata.id == "builtin":
            raise LibraryError("IP_LIBRARY_INPUT", metadata.id)
        with self._locked():
            index = self._index()
            status, selected_version, diff = self._decision(index, metadata, version)
            if status != "ready":
                return status, selected_version, diff
            relative = f"{metadata.id}/{selected_version}"
            target = self._path(relative)
            if target.exists():
                raise LibraryError("IP_LIBRARY_EXISTS", relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.directory, prefix=".stage-") as directory:
                staging = Path(directory)
                (staging / "src").mkdir()
                (staging / "src" / upload.name).write_bytes(upload.content)
                stored = replace(metadata, version=selected_version, base_dir=staging,
                                 source=replace(metadata.source, path=f"src/{upload.name}"))
                save_ip(stored, staging / "ip.json")
                staging.rename(target)
            try:
                index["entries"][f"{metadata.id}@{selected_version}"] = {
                    "id": metadata.id, "version": selected_version, "metadata": f"{relative}/ip.json",
                    "source_sha256": metadata.source.sha256, "interface_hash": _signature(metadata),
                    "origin": origin, "dependencies": dependencies,
                }
                index["sources"].setdefault(metadata.source.sha256, {"path": f"{relative}/src/{upload.name}", "modules": names})
                bdtool._write_outputs({"index.json": json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False) + "\n"}, self.directory, set())
            except (OSError, ValueError):
                shutil.rmtree(target)
                raise
            return "imported", selected_version, diff

    def import_sources(self, sources: list[Upload], *, dry_run: bool = False, version: str | None = None,
                       selections: dict | None = None, license_name: str = "NOASSERTION", origin: str = "imported"):
        if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_FILES or not all(isinstance(source, Upload) for source in sources):
            raise LibraryError("IP_LIBRARY_INPUT")
        if selections is not None and (not isinstance(selections, dict) or len(sources) != 1):
            raise LibraryError("IP_LIBRARY_SELECTION")
        if type(dry_run) is not bool or not isinstance(license_name, str) or not 1 <= len(license_name) <= 256 or origin not in {"imported", "builtin", "manual"}:
            raise LibraryError("IP_LIBRARY_INPUT")
        if version is not None:
            _version(version)
        return self._events(sources, dry_run=dry_run, version=version, selections=selections,
                            license_name=license_name, origin=origin)

    def _events(self, sources, *, dry_run, version, selections, license_name, origin):
        counts = dict.fromkeys(("preview", "imported", "skipped", "needs_version", "invalid"), 0)
        for upload in sources:
            yield {"type": "file", "file": upload.name, "status": "parsing"}
            try:
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / upload.name
                    path.write_bytes(upload.content)
                    parsed = parse_file(path, workspace_root=Path(directory), license_name=license_name)
                    names = [metadata.id for metadata in parsed.modules]
                    if selections is not None and selections.keys() - set(names):
                        raise LibraryError("IP_LIBRARY_SELECTION")
                    for item in parsed.diagnostics:
                        if item.severity == "error":
                            counts["invalid"] += 1
                            yield {"type": "ip", "file": upload.name, "status": "invalid", "diagnostics": [asdict(item)]}
                    for metadata in parsed.modules:
                        if selections is not None and metadata.id not in selections:
                            continue
                        try:
                            metadata = suggest_roles(metadata)
                            if selections is not None:
                                metadata = _edited(metadata, selections[metadata.id])
                            defaults(metadata)
                            requested = version or (metadata.version if selections is not None else None)
                            index = self._index()
                            status, chosen_version, diff = self._decision(index, metadata, requested)
                            if status == "ready":
                                if dry_run:
                                    status = "preview"
                                else:
                                    status, chosen_version, diff = self._publish(metadata, upload, requested, origin, names,
                                                                                _external_dependencies(metadata.id, parsed.dependencies))
                            counts[status] += 1
                            yield {"type": "ip", "file": upload.name, "id": metadata.id, "version": chosen_version,
                                   "status": status, "diff": diff, "metadata": replace(metadata, version=chosen_version).to_dict(),
                                   "diagnostics": [asdict(item) for item in parsed.diagnostics if item.severity == "warning"]}
                        except (LibraryError, IpMetadataError, ExpressionError, OSError) as error:
                            counts["invalid"] += 1
                            yield {"type": "ip", "file": upload.name, "id": metadata.id, "status": "invalid",
                                   "diagnostics": [{"code": getattr(error, "code", "IP_LIBRARY_IO"), "severity": "error", "message": str(error)}]}
            except (LibraryError, OSError) as error:
                counts["invalid"] += 1
                yield {"type": "ip", "file": upload.name, "status": "invalid", "diagnostics": [{"code": getattr(error, "code", "IP_LIBRARY_IO"), "severity": "error", "message": str(error)}]}
        yield {"type": "summary", "counts": counts}

    def import_paths(self, paths: list[Path], *, recursive: bool = False, **options):
        files = []
        for supplied in paths:
            path = Path(supplied).resolve()
            if path.is_dir():
                candidates = path.rglob("*") if recursive else path.glob("*")
                for candidate in candidates:
                    if candidate.is_file() and candidate.suffix.lower() in {".v", ".sv"}:
                        if not candidate.resolve().is_relative_to(path):
                            raise LibraryError("IP_LIBRARY_PATH")
                        files.append(candidate)
                        if len(files) > MAX_FILES:
                            raise LibraryError("IP_LIBRARY_SIZE")
            else:
                files.append(path)
        if not 1 <= len(files) <= MAX_FILES:
            raise LibraryError("IP_LIBRARY_INPUT")
        uploads, errors = [], []
        for path in sorted(set(files)):
            try:
                with path.open("rb") as stream:
                    uploads.append(Upload(path.name, stream.read(MAX_SOURCE_BYTES + 1)))
            except (LibraryError, OSError) as error:
                errors.append({"type": "ip", "file": path.name, "status": "invalid", "diagnostics": [{
                    "code": getattr(error, "code", "IP_LIBRARY_IO"), "severity": "error",
                    "message": str(error) if isinstance(error, LibraryError) else MESSAGES["IP_LIBRARY_IO"].format(detail=path.name)}]})
        yield from errors
        if not uploads:
            counts = dict.fromkeys(("preview", "imported", "skipped", "needs_version", "invalid"), 0)
            counts["invalid"] = len(errors)
            yield {"type": "summary", "counts": counts}
            return
        for event in self.import_sources(uploads, **options):
            if event["type"] == "summary":
                event["counts"]["invalid"] += len(errors)
            yield event

    def _source_paths(self, entry: dict, index: dict) -> list[Path]:
        paths = []
        seen = set()

        def collect(current):
            digest = current["source_sha256"]
            if digest in seen:
                return
            seen.add(digest)
            source = index["sources"][digest]
            path = self._path(source["path"])
            if path.stat().st_size > MAX_SOURCE_BYTES or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise LibraryError("IP_LIBRARY_SOURCE", current["id"])
            paths.append(path)
            for name in current.get("dependencies", []):
                if name in source["modules"]:
                    continue
                dependency = self._latest(index, name)
                if dependency is None:
                    raise LibraryError("IP_LIBRARY_DEPENDENCY", name)
                collect(dependency)

        collect(entry)
        return paths

    def entries(self, *, base_dir: Path | None = None) -> list[dict]:
        base = Path(base_dir).resolve() if base_dir is not None else self.root
        if not base.is_relative_to(self.root):
            raise LibraryError("IP_LIBRARY_PATH")
        index = self._index()
        result = []
        for entry in sorted(index["entries"].values(), key=lambda item: (item["id"], _version(item["version"]))):
            metadata = load_ip(self._path(entry["metadata"]))
            row = {"metadata": metadata.to_dict(), "origin": entry["origin"], "usable": True, "diagnostics": []}
            try:
                if ((metadata.id, metadata.version, metadata.source.sha256) != (entry["id"], entry["version"], entry["source_sha256"])
                        or _signature(metadata) != entry["interface_hash"]):
                    raise LibraryError("IP_LIBRARY_INTEGRITY", metadata.id)
                values = defaults(metadata)
                ports = {}
                for port in metadata.ports:
                    if port.dir == "inout":
                        raise LibraryError("IP_LIBRARY_INOUT", metadata.id)
                    specification = {"direction": {"in": "input", "out": "output"}[port.dir], "signed": bool(port.signed)}
                    if port.range is not None:
                        specification["range"] = list(port.range)
                    elif evaluate(port.width, values) != 1:
                        specification["range"] = [f"({port.width}) - 1", 0]
                    ports[port.name] = specification
                parameters = {parameter.name: {"default": values[parameter.name],
                              **{key: value for key, value in parameter.to_dict().items() if key in {"min", "max"}}}
                              for parameter in metadata.parameters}
                bdtool._ports(ports, values, metadata.id)
                row["definition"] = {"sources": [Path(os.path.relpath(path, base)).as_posix() for path in self._source_paths(entry, index)],
                                     "parameters": parameters, "ports": ports}
            except (bdtool.DesignError, ExpressionError, OSError, KeyError) as error:
                row.update(usable=False, diagnostics=[{"code": getattr(error, "code", "IP_LIBRARY_SOURCE"), "message": str(error)}])
            result.append(row)
        return result