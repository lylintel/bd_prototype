import os
from pathlib import Path
import re
import shutil
import subprocess
import sysconfig
import tempfile

import bdtool
from bdip import MESSAGES
from core.diagnostics import Diagnostic


MAX_LOG_BYTES = 1024 * 1024


def tool_commands():
    verilator = shutil.which(os.environ.get("BD_VERILATOR", "verilator"))
    if not verilator and not os.environ.get("BD_VERILATOR"):
        verilator = shutil.which("verilator_bin")
    yosys = shutil.which(os.environ.get("BD_YOSYS", "yosys"))
    if not yosys and not os.environ.get("BD_YOSYS"):
        portable = Path(sysconfig.get_path("scripts")) / ("yowasp-yosys.exe" if os.name == "nt" else "yowasp-yosys")
        yosys = str(portable) if portable.is_file() else None
    return {"verilator": [verilator] if verilator else None, "yosys": [yosys] if yosys else None}


def _diagnostic(tool, code, severity, location=None, detail="", rule=""):
    params = {"tool": tool, "detail": detail, "rule": rule}
    return Diagnostic(code, severity, location or {}, MESSAGES[code].format(**params), params).to_dict()


def parse_diagnostics(tool, text, paths):
    result = []
    for line in text.splitlines():
        if tool == "verilator":
            match = re.match(r"^%(Warning|Error)(?:-([A-Z0-9_]+))?:\s*(?:(.+?):(\d+):(?:(\d+):)?\s*)?(.*)$", line)
            if not match:
                continue
            severity, rule, filename, row, column, detail = match.groups()
        else:
            match = re.match(r"^(?:(.+?):(\d+):\s*)?(ERROR|Warning):\s*(.*)$", line)
            if not match:
                continue
            filename, row, severity, detail = match.groups()
            column, rule = None, ""
        severity = "warning" if severity.lower() == "warning" else "error"
        location = {"file": paths.get(filename, filename), "line": int(row), "column": int(column or 1)} if filename and row else {}
        result.append(_diagnostic(tool, "HDL_TOOL_WARNING" if severity == "warning" else "HDL_TOOL_ERROR", severity, location, detail, rule or ""))
    return result


def run_checks(files, sources, top):
    bdtool._name(top, "top")
    for name in files:
        if Path(name).name != name or Path(name).suffix not in {".v", ".sv"}:
            raise ValueError(MESSAGES["HDL_TOOL_INPUT"])
        bdtool._name(Path(name).stem, "generated file")
    commands = tool_commands()
    tools, diagnostics = [], []
    with tempfile.TemporaryDirectory(prefix="bd-hdl-check-") as temporary:
        directory = Path(temporary)
        staged, paths = [], {}
        for name, text in files.items():
            (directory / name).write_bytes(text.encode("utf-8"))
            staged.append(name)
            paths[name] = name
        for index, source in enumerate(dict.fromkeys(Path(item) for item in sources)):
            basename = source.name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*\.(?:v|sv)", source.name) else f"source_{index}.v"
            name = f"sources/{index}/{basename}"
            (directory / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, directory / name)
            paths[name] = str(source)
            staged.append(name)
        for tool, program in commands.items():
            if program is None:
                items = [_diagnostic(tool, "HDL_TOOL_MISSING", "warning")]
                tools.append({"name": tool, "status": "missing", "diagnostics": items, "log": "", "directory": temporary})
                diagnostics.extend(items)
                continue
            if tool == "verilator":
                command = [*program, "--lint-only", "-Wall", "-Wno-fatal", "--top-module", top, *staged]
            else:
                language = "-sv " if any(name.endswith(".sv") for name in staged) else ""
                script = "read_verilog " + language + " ".join(f'"{name}"' for name in staged) + f"; hierarchy -check -top {top}"
                command = [*program, "-Q", "-T", "-p", script]
            with tempfile.TemporaryFile() as log:
                try:
                    completed = subprocess.run(command, cwd=directory, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=30)
                    status = "passed" if completed.returncode == 0 else "failed"
                    items = []
                except subprocess.TimeoutExpired:
                    status, items = "timeout", [_diagnostic(tool, "HDL_TOOL_TIMEOUT", "error")]
                except OSError:
                    status, items = "missing", [_diagnostic(tool, "HDL_TOOL_MISSING", "warning")]
                log.seek(0)
                raw = log.read(MAX_LOG_BYTES + 1)
            text = raw[:MAX_LOG_BYTES].decode("utf-8", errors="replace")
            items.extend(parse_diagnostics(tool, text, paths))
            if len(raw) > MAX_LOG_BYTES:
                status = "failed"
                items.append(_diagnostic(tool, "HDL_TOOL_LOG_LIMIT", "error"))
            if status == "failed" and not any(item["severity"] == "error" for item in items):
                items.append(_diagnostic(tool, "HDL_TOOL_ERROR", "error", detail=text[-2000:]))
            if any(item["severity"] == "error" for item in items):
                status = "timeout" if status == "timeout" else "failed"
            tools.append({"name": tool, "status": status, "diagnostics": items, "log": text, "directory": temporary})
            diagnostics.extend(items)
    return {"valid": all(tool["status"] == "passed" for tool in tools), "tools": tools, "diagnostics": diagnostics}