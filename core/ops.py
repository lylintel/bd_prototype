from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

from jsonschema import Draft202012Validator

import bdtool
from core.design import DesignFormatError, check_document
from core.diagnostics import Diagnostic
from core.expr import ExpressionError, evaluate
from core.resolve import ParameterError, parameters
from core.semantic import validate


MAX_OPERATIONS = 200
SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "ops.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)
OPERATIONS = frozenset(("add_instance", "remove_instance", "set_param", "add_external_port", "connect", "disconnect"))
ENDPOINT_TYPES = frozenset(("port", "slice", "const", "concat"))


class OperationError(ValueError):
    def __init__(self, code, **params):
        self.diagnostic = Diagnostic(code=code, severity="error", location={}, message=code, params=params)
        super().__init__(code)


def _name(value):
    try:
        bdtool._name(value, "operation")
        if len(value) > 256:
            raise bdtool.DesignError("length")
    except bdtool.DesignError as error:
        raise OperationError("OP_IDENTIFIER", name=str(value)[:256]) from error
    return value


def _endpoint_types(endpoint, budget, depth=0):
    budget[0] += 1
    if depth > 16 or budget[0] > 256:
        raise OperationError("OP_ENDPOINT_LIMIT")
    if not isinstance(endpoint, dict):
        raise OperationError("OP_SCHEMA", path="endpoint", rule="object")
    kind = endpoint.get("type")
    if not isinstance(kind, str) or kind not in ENDPOINT_TYPES:
        raise OperationError("OP_ENDPOINT_TYPE", type=str(kind)[:80])
    if kind == "concat" and isinstance(endpoint.get("concat"), list):
        for child in endpoint["concat"]:
            _endpoint_types(child, budget, depth + 1)


def decode_endpoint(endpoint):
    result = {key: deepcopy(value) for key, value in endpoint.items() if key != "type"}
    if "concat" in result:
        result["concat"] = [decode_endpoint(child) for child in endpoint["concat"]]
    return result


def typed_endpoint(endpoint):
    kind = "concat" if "concat" in endpoint else "const" if "const" in endpoint else "slice" if "slice" in endpoint else "port"
    result = {"type": kind, **deepcopy(endpoint)}
    if kind == "concat":
        result["concat"] = [typed_endpoint(child) for child in endpoint["concat"]]
    return result


def validate_operations(operations):
    payload = {"schema_version": 1, "ops": operations} if isinstance(operations, list) else operations
    if not isinstance(payload, dict) or not isinstance(payload.get("ops"), list):
        raise OperationError("OP_SCHEMA", path="ops", rule="array")
    if len(payload["ops"]) > MAX_OPERATIONS:
        raise OperationError("OP_LIMIT", limit=MAX_OPERATIONS)
    try:
        if len(json.dumps(payload, allow_nan=False).encode("utf-8")) > 2 * 1024 * 1024:
            raise OperationError("OP_LIMIT", limit=2 * 1024 * 1024)
    except (ValueError, TypeError, RecursionError) as error:
        if isinstance(error, OperationError):
            raise
        raise OperationError("OP_SCHEMA", path="ops", rule="json") from error
    for operation in payload["ops"]:
        if not isinstance(operation, dict):
            raise OperationError("OP_SCHEMA", path="ops", rule="object")
        command = operation.get("op")
        if not isinstance(command, str) or command not in OPERATIONS:
            raise OperationError("OP_UNKNOWN_OPERATION", op=str(command)[:80])
        for field in ("from", "to"):
            if field in operation:
                _endpoint_types(operation[field], [0])
    error = next(VALIDATOR.iter_errors(payload), None)
    if error:
        path = "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path)
        raise OperationError("OP_SCHEMA", path=path, rule=str(error.validator))
    return payload["ops"]


def _mentions(endpoint, instance):
    return endpoint.get("inst") == instance or any(_mentions(child, instance) for child in endpoint.get("concat", []))


class _Draft:
    def __init__(self, document, library):
        self.document = document
        self.library = {}
        for metadata in library:
            self.library.setdefault((metadata.id, metadata.version), []).append(metadata)
        self.reindex()

    def reindex(self):
        self.instances, self.nets = {}, {}
        for item in self.document["instances"]:
            self.instances.setdefault(item["name"], []).append(item)
        for item in self.document["nets"]:
            self.nets.setdefault(item["name"], []).append(item)

    def available_name(self, name):
        _name(name)
        if name in self.instances or name in self.nets or name in self.document["ports"]:
            raise OperationError("OP_DUPLICATE_NAME", name=name)

    def instance(self, name):
        _name(name)
        found = self.instances.get(name, [])
        if not found:
            raise OperationError("OP_UNKNOWN_INSTANCE", instance=name)
        if len(found) != 1:
            raise OperationError("OP_AMBIGUOUS_NAME", name=name)
        return found[0]

    def metadata(self, reference):
        _name(reference["id"])
        found = self.library.get((reference["id"], reference["version"]), [])
        if len(found) != 1:
            raise OperationError("OP_UNKNOWN_IP", ip=reference["id"], version=reference["version"], reason="missing" if not found else "ambiguous")
        return found[0]

    def check_parameters(self, instance):
        metadata = self.metadata(instance["ip"])
        try:
            parameters(metadata, instance.get("params", {}))
        except ParameterError as error:
            raise OperationError("OP_INVALID_PARAM", instance=instance["name"], parameter=error.name, reason=error.reason) from error

    def drives(self, endpoint):
        if "const" in endpoint:
            return True
        if "concat" in endpoint:
            directions = {self.drives(child) for child in endpoint["concat"]}
            if len(directions) != 1:
                raise OperationError("OP_DIRECTION")
            return directions.pop()
        if "ext" in endpoint:
            name = _name(endpoint["ext"])
            shape = self.document["ports"].get(name)
            if shape is None:
                raise OperationError("OP_UNKNOWN_PORT", instance="", port=name)
            return shape["direction"] == "input"
        instance = self.instance(endpoint["inst"])
        name = _name(endpoint["port"])
        shape = next((port for port in self.metadata(instance["ip"]).ports if port.name == name), None)
        if shape is None:
            raise OperationError("OP_UNKNOWN_PORT", instance=instance["name"], port=name)
        if shape.dir == "inout":
            raise OperationError("OP_DIRECTION")
        return shape.dir == "out"

    def add_instance(self, operation):
        name = operation["name"]
        self.available_name(name)
        reference = {"id": operation["ip"], "version": operation["version"]}
        metadata = self.metadata(reference)
        instance = {"name": name, "ip": reference, "params": deepcopy(operation.get("params", {}))}
        self.check_parameters(instance)
        self.document["instances"].append(instance)
        snapshots = self.document.setdefault("project_ips", [])
        if not any((item["id"], item["version"]) == (metadata.id, metadata.version) for item in snapshots):
            snapshots.append(metadata.to_dict())

    def remove_instance(self, operation):
        instance = self.instance(operation["name"])
        self.document["instances"].remove(instance)
        self.reindex()
        kept = []
        for net in self.document["nets"]:
            remaining = [endpoint for endpoint in net["endpoints"] if not _mentions(endpoint, operation["name"])]
            if len(remaining) == len(net["endpoints"]):
                kept.append(net)
            elif len(remaining) >= 2:
                try:
                    has_driver = any(self.drives(endpoint) for endpoint in remaining)
                except OperationError:
                    has_driver = True
                if has_driver:
                    net["endpoints"] = remaining
                    kept.append(net)
        self.document["nets"] = kept

    def set_param(self, operation):
        instance = self.instance(operation["inst"])
        name = _name(operation["name"])
        if name not in {parameter.name for parameter in self.metadata(instance["ip"]).parameters}:
            raise OperationError("OP_UNKNOWN_PARAMETER", instance=instance["name"], parameter=name)
        instance.setdefault("params", {})[name] = operation["value"]
        self.check_parameters(instance)

    def add_external_port(self, operation):
        name = operation["name"]
        self.available_name(name)
        try:
            width = evaluate(operation["width"])
        except ExpressionError as error:
            raise OperationError("OP_INVALID_WIDTH", port=name, reason=error.code) from error
        if not 1 <= width <= 65536:
            raise OperationError("OP_INVALID_WIDTH", port=name, reason="range")
        shape = {"direction": "input" if operation["dir"] == "in" else "output"}
        if "range" in operation:
            bounds = operation["range"]
            if abs(bounds[0] - bounds[1]) + 1 != width:
                raise OperationError("OP_INVALID_WIDTH", port=name, reason="range")
            shape["range"] = list(bounds)
        elif width > 1:
            shape["range"] = [width - 1, 0]
        if "signed" in operation:
            shape["signed"] = operation["signed"]
        self.document["ports"][name] = shape

    def connection(self, operation):
        source, target = decode_endpoint(operation["from"]), decode_endpoint(operation["to"])
        if not self.drives(source) or self.drives(target):
            raise OperationError("OP_DIRECTION")
        if "net" in operation:
            _name(operation["net"])
        candidates = self.nets.get(operation["net"], []) if "net" in operation else [net for net in self.document["nets"] if source in net["endpoints"]]
        if operation["op"] == "disconnect":
            candidates = [net for net in candidates if source in net["endpoints"] and target in net["endpoints"]]
        if len(candidates) > 1:
            raise OperationError("OP_AMBIGUOUS_NET")
        if operation["op"] == "disconnect":
            if not candidates:
                raise OperationError("OP_NOT_CONNECTED")
            net = candidates[0]
            net["endpoints"].remove(target)
            if len(net["endpoints"]) < 2:
                self.document["nets"].remove(net)
            return
        if candidates:
            net = candidates[0]
            if source not in net["endpoints"]:
                raise OperationError("OP_NET_CONFLICT", net=net["name"])
            if target not in net["endpoints"]:
                net["endpoints"].append(target)
        else:
            name = operation.get("net")
            if name is None:
                suffix = 1
                while f"net_{suffix}" in self.instances or f"net_{suffix}" in self.nets or f"net_{suffix}" in self.document["ports"]:
                    suffix += 1
                name = f"net_{suffix}"
            self.available_name(name)
            self.document["nets"].append({"name": name, "endpoints": [source, target]})
        if operation["from"]["type"] != "port" or operation["to"]["type"] != "port":
            self.document["schema_version"] = 3


def apply_ops(document, library, operations):
    """Apply an atomic operation batch; semantic errors retain an unaccepted draft."""
    try:
        check_document(document)
    except DesignFormatError as error:
        return deepcopy(document), [error.diagnostic]
    original = deepcopy(document)
    index = None
    try:
        commands = validate_operations(operations)
        library = tuple(library)
        draft = _Draft(deepcopy(document), library)
        for index, operation in enumerate(commands):
            if operation["op"] in ("connect", "disconnect"):
                draft.connection(operation)
            else:
                getattr(draft, operation["op"])(operation)
            draft.reindex()
        check_document(draft.document)
        return draft.document, [item for item in validate(draft.document, library) if item.severity == "error"]
    except OperationError as error:
        return original, [replace(error.diagnostic, location={"operation": index} if index is not None else {"path": "$.ops"})]
    except DesignFormatError as error:
        return original, [error.diagnostic]