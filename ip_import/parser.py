from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import sysconfig
import tempfile

from bdip import IpMetadata, IpMetadataError, MESSAGES, _legacy_width


MAX_SOURCE_BYTES = 1024 * 1024
MAX_AST_BYTES = 32 * 1024 * 1024
NODE = re.compile(r"^( *)(AST_\w+) <[^<>]+:(\d+)\.\d+-\d+\.\d+> \[[^]]+\](.*)$")
OPERATORS = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "MOD": "%", "POW": "**",
             "LT": "<", "LE": "<=", "GT": ">", "GE": ">=", "EQ": "==", "NE": "!=",
             "LOGIC_AND": "&&", "LOGIC_OR": "||", "SHIFT_LEFT": "<<", "SHIFT_RIGHT": ">>",
             "BIT_AND": "&", "BIT_OR": "|", "BIT_XOR": "^"}


@dataclass(frozen=True)
class ParseDiagnostic:
    code: str
    severity: str
    path: str
    line: int
    message: str


@dataclass(frozen=True)
class ParseResult:
    modules: tuple[IpMetadata, ...] = ()
    diagnostics: tuple[ParseDiagnostic, ...] = ()
    backend: str = "yosys"

    def to_dict(self) -> dict:
        return {"modules": [module.to_dict() for module in self.modules],
                "diagnostics": [asdict(item) for item in self.diagnostics], "backend": self.backend}


@dataclass
class AstNode:
    kind: str
    line: int
    attributes: str
    children: list[AstNode] = field(default_factory=list)

    @property
    def name(self) -> str:
        match = re.search(r"str='([^']*)'", self.attributes)
        return match[1].removeprefix("$abstract").removeprefix("\\") if match else ""


class Unsupported(ValueError):
    def __init__(self, line: int):
        self.line = max(line, 1)


def diagnostic(code: str, path: str, line: int = 1) -> ParseDiagnostic:
    return ParseDiagnostic(code, "error", path, max(line, 1), MESSAGES[code].format(path=path, line=max(line, 1)))


def _tree(output: str) -> list[AstNode]:
    roots = []
    stack = []
    for line in output.splitlines():
        match = NODE.match(line)
        if not match:
            continue
        depth = len(match[1])
        node = AstNode(match[2].removeprefix("AST_"), int(match[3]), match[4])
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if stack:
            stack[-1][1].children.append(node)
        elif node.kind == "MODULE":
            roots.append(node)
        stack.append((depth, node))
    return roots


def _expr(node: AstNode, locals_: dict[str, AstNode], seen: tuple[str, ...] = (), depth: int = 0) -> str:
    if depth > 64:
        raise Unsupported(node.line)
    if node.kind == "IDENTIFIER":
        if node.name in locals_:
            if node.name in seen:
                raise Unsupported(node.line)
            return _expr(locals_[node.name], locals_, (*seen, node.name), depth + 1)
        return node.name
    if node.kind == "CONSTANT":
        match = re.search(r"bits='([01]+)'\((\d+)\)", node.attributes)
        if not match or "is_string" in node.attributes or len(match[1]) > 4096:
            raise Unsupported(node.line)
        value = int(match[1], 2)
        if "signed" in node.attributes.split() and match[1][0] == "1":
            value -= 1 << len(match[1])
        return str(value)
    arguments = [_expr(child, locals_, seen, depth + 1) for child in node.children]
    if node.kind in OPERATORS and len(arguments) == 2:
        return f"({arguments[0]} {OPERATORS[node.kind]} {arguments[1]})"
    if node.kind in {"POS", "NEG", "LOGIC_NOT", "BIT_NOT"} and len(arguments) == 1:
        operator = {"POS": "+", "NEG": "-", "LOGIC_NOT": "!", "BIT_NOT": "~"}[node.kind]
        return f"({operator}{arguments[0]})"
    if node.kind == "TERNARY" and len(arguments) == 3:
        return f"({arguments[0]} ? {arguments[1]} : {arguments[2]})"
    if node.kind == "FCALL" and node.name == "$clog2" and len(arguments) == 1:
        return f"$clog2({arguments[0]})"
    raise Unsupported(node.line)


def _initializer(node: AstNode) -> AstNode:
    children = [child for child in node.children if child.kind not in {"RANGE", "ATTR"}]
    if not children:
        raise Unsupported(node.line)
    return children[0]


def _module(node: AstNode, path: Path, raw: bytes, license_name: str) -> IpMetadata:
    locals_ = {child.name: _initializer(child) for child in node.children if child.kind == "LOCALPARAM"}
    parameters = [{"name": child.name, "type": "int", "default": _expr(_initializer(child), locals_)}
                  for child in node.children if child.kind == "PARAMETER"]
    wires = {}
    for child in node.children:
        if child.kind == "WIRE":
            wires.setdefault(child.name, []).append(child)
    ports = []
    for name, declarations in wires.items():
        order = next((re.search(r"\bport=(\d+)", item.attributes) for item in declarations
                      if re.search(r"\bport=(\d+)", item.attributes)), None)
        if order is None:
            continue
        flags = set().union(*(set(item.attributes.split()) for item in declarations))
        if any(child.kind == "MULTIRANGE" for item in declarations for child in item.children):
            raise Unsupported(declarations[0].line)
        ranges = [child for item in declarations for child in item.children if child.kind == "RANGE"]
        bounds = None
        if ranges:
            if len(ranges[-1].children) != 2:
                raise Unsupported(ranges[-1].line)
            expressions = [_expr(child, locals_) for child in ranges[-1].children]
            bounds = [int(value) if re.fullmatch(r"-?[0-9]+", value) else value for value in expressions]
        direction = "inout" if {"input", "output"} <= flags else "in" if "input" in flags else "out"
        port = {"name": name, "dir": direction, "width": _legacy_width(bounds), "signed": "signed" in flags}
        if bounds is not None:
            port["range"] = bounds
        ports.append((int(order[1]), port))
    return IpMetadata.from_dict({
        "schema_version": 1, "id": node.name, "version": "1.0.0", "display_name": node.name,
        "description": "", "tags": [], "source": {"kind": "verilog", "path": path.name,
        "sha256": hashlib.sha256(raw).hexdigest(), "license": license_name},
        "language": "systemverilog" if path.suffix.lower() == ".sv" else "verilog-2005",
        "parameters": parameters, "ports": [port for _, port in sorted(ports)], "interfaces": [],
    }, base_dir=path.parent)


def parse_file(path: Path, *, workspace_root: Path | None = None, license_name: str = "NOASSERTION") -> ParseResult:
    path = Path(path).resolve()
    root = Path(workspace_root).resolve() if workspace_root is not None else path.parent

    def failed(code: str, line: int = 1) -> ParseResult:
        return ParseResult(diagnostics=(diagnostic(code, path.name, line),))

    if not path.is_relative_to(root):
        return failed("IP_PARSE_PATH")
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            return failed("IP_PARSE_SIZE")
        text = raw.decode("utf-8")
    except (OSError, UnicodeError, ValueError):
        return failed("IP_PARSE_READ")
    if "`" in text:
        return failed("IP_PARSE_PREPROCESSOR", text[:text.index("`")].count("\n") + 1)
    executable = Path(sysconfig.get_path("scripts")) / ("yowasp-yosys.exe" if sys.platform == "win32" else "yowasp-yosys")
    try:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "input.v").write_bytes(raw)
            mode = "-sv " if path.suffix.lower() == ".sv" else ""
            with (work / "stdout").open("wb") as stdout, (work / "stderr").open("wb") as stderr:
                process = subprocess.run([str(executable), "-Q", "-T", "-p", f"read_verilog {mode}-defer -dump_ast1 input.v"],
                                         cwd=work, stdout=stdout, stderr=stderr, timeout=180)
            if (work / "stdout").stat().st_size > MAX_AST_BYTES:
                return failed("IP_PARSE_SIZE")
            output = (work / "stdout").read_text(encoding="utf-8", errors="replace")
            errors = (work / "stderr").read_bytes()[:65536].decode("utf-8", errors="replace")
        if process.returncode:
            location = re.search(r"input\.v:(\d+)", errors + output)
            return failed("IP_PARSE_ERROR", int(location[1]) if location else 1)
    except subprocess.TimeoutExpired:
        return failed("IP_PARSE_TIMEOUT")
    except OSError:
        return failed("IP_PARSE_TOOL")
    modules, diagnostics = [], []
    if re.search(r"(?m)^Warning:", output + errors):
        diagnostics.append(ParseDiagnostic("IP_PARSE_WARNING", "warning", path.name, 1,
                                          MESSAGES["IP_PARSE_WARNING"].format(path=path.name, line=1)))
    for node in _tree(output):
        try:
            modules.append(_module(node, path, raw, license_name))
        except Unsupported as error:
            diagnostics.append(diagnostic("IP_PARSE_UNSUPPORTED", path.name, error.line))
        except IpMetadataError:
            diagnostics.append(diagnostic("IP_PARSE_METADATA", path.name, node.line))
    if not modules and not any(item.severity == "error" for item in diagnostics):
        return failed("IP_PARSE_EMPTY")
    return ParseResult(tuple(modules), tuple(diagnostics))