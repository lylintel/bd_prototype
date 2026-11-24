from collections import Counter
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sysconfig
import tempfile

import bdtool
from bdip import MESSAGES
from core.diagnostics import Diagnostic


MAX_LOG_BYTES = 1024 * 1024
TOOL_VERSIONS = {"verilator": "Verilator 5.055 devel rev v5.054-302-g2d6aba6ed",
                 "yosys": "Yosys 0.70 (git sha1 28ba3cb92,"}


def tool_version(tool, program, directory):
    expected = TOOL_VERSIONS[tool]
    with tempfile.TemporaryFile() as log:
        try:
            result = subprocess.run([*program, "--version" if tool == "verilator" else "-V"], cwd=directory,
                                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=30)
        except subprocess.TimeoutExpired:
            return "", [_diagnostic(tool, "HDL_TOOL_TIMEOUT", "error")]
        except OSError:
            return "", [_diagnostic(tool, "HDL_TOOL_MISSING", "error")]
        log.seek(0)
        actual = log.read(4096).decode("utf-8", errors="replace").strip()
    matches = actual in (expected, expected + " (mod)") if tool == "verilator" else actual.startswith(expected)
    if result.returncode != 0 or not matches:
        return actual, [_diagnostic(tool, "HDL_TOOL_VERSION", "error", detail=f"expected={expected}; actual={actual}")]
    return actual, []


class UnsafeInclude(ValueError):
    def __init__(self, reason, filename, line):
        super().__init__(reason)
        self.location = {"file": str(filename), "line": line, "column": 1}


def stage_source(source, target, directory, workspace_root, paths, active=()):
    source = source.resolve()
    if source in active or len(active) >= 16 or len(paths) >= 200:
        raise UnsafeInclude("include_cycle_or_limit", source, 1)
    if source.stat().st_size > 2 * 1024 * 1024:
        raise UnsafeInclude("source_size_limit", source, 1)
    text = source.read_text(encoding="utf-8")
    if "``" in text or re.search(r"\\\r?\n", text):
        raise UnsafeInclude("include_preprocessor_form_unsupported", source, 1)
    paths[target] = str(source)
    paths[(directory / target).as_posix()] = str(source)

    def replace_include(match):
        line = text.count("\n", 0, match.start()) + 1
        literal = re.match(r'\s*"([^"\r\n]+)"', text[match.start() + len("`include"):])
        if literal is None or "`" in literal[1] or "\\" in literal[1]:
            raise UnsafeInclude("include_literal_required", source, line)
        dependency = (source.parent / literal[1]).resolve()
        if not dependency.is_relative_to(workspace_root):
            raise UnsafeInclude("include_outside_workspace", source, line)
        if not dependency.is_file():
            raise UnsafeInclude("include_not_found", source, line)
        name = f"includes/{len(paths)}/dependency.vh"
        stage_source(dependency, name, directory, workspace_root, paths, (*active, source))
        return f'`include "{name}"'

    pattern = r'`include\b(?:\s*"[^"\r\n]*")?'
    text = re.sub(pattern, replace_include, text)
    (directory / target).parent.mkdir(parents=True, exist_ok=True)
    (directory / target).write_text(text, encoding="utf-8", newline="\n")


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
        if filename:
            filename = PureWindowsPath(filename).as_posix()
        location = {"file": paths.get(filename, filename), "line": int(row), "column": int(column or 1)} if filename and row else {}
        result.append(_diagnostic(tool, "HDL_TOOL_WARNING" if severity == "warning" else "HDL_TOOL_ERROR", severity, location, detail, rule or ""))
    return result


def run_checks(files, sources, top, *, workspace_root=None, strict_lint=False):
    if type(strict_lint) is not bool:
        raise ValueError(MESSAGES["HDL_TOOL_OPTIONS"])
    bdtool._name(top, "top")
    for name in files:
        if Path(name).name != name or Path(name).suffix not in {".v", ".sv"}:
            raise ValueError(MESSAGES["HDL_TOOL_INPUT"])
        bdtool._name(Path(name).stem, "generated file")
    workspace_root = Path(workspace_root or Path.cwd()).resolve()
    tools, diagnostics = [], []
    with tempfile.TemporaryDirectory(prefix="bd-hdl-check-") as temporary:
        directory = Path(temporary)
        staged, paths = [], {}
        for name, text in files.items():
            if "`include" in text or "``" in text:
                item = _diagnostic("preflight", "HDL_INCLUDE", "error", {"file": name, "line": 1}, "generated_include_unsupported")
                return {"valid": False, "tools": [], "diagnostics": [item]}
            (directory / name).write_bytes(text.encode("utf-8"))
            staged.append(name)
            paths[name] = name
        for index, source in enumerate(dict.fromkeys(Path(item) for item in sources)):
            extension = ".sv" if source.suffix.lower() == ".sv" else ".v"
            basename = source.name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*\.(?:v|sv)", source.name, re.IGNORECASE) else f"source_{index}{extension}"
            name = f"sources/{index}/{basename}"
            try:
                stage_source(source, name, directory, workspace_root, paths)
            except UnsafeInclude as error:
                item = _diagnostic("preflight", "HDL_INCLUDE", "error", error.location, str(error))
                return {"valid": False, "tools": [], "diagnostics": [item]}
            staged.append(name)
        commands = tool_commands()
        for tool, program in commands.items():
            stage = "lint" if tool == "verilator" else "synthesis"
            if program is None:
                items = [_diagnostic(tool, "HDL_TOOL_MISSING", "warning")]
                tools.append({"name": tool, "stage": stage, "status": "missing", "diagnostics": items, "log": "", "directory": temporary})
                diagnostics.extend(items)
                continue
            version, version_errors = tool_version(tool, program, directory)
            if version_errors:
                status = "timeout" if version_errors[0]["code"] == "HDL_TOOL_TIMEOUT" else "failed"
                tools.append({"name": tool, "stage": stage, "status": status, "version": version,
                              "expected_version": TOOL_VERSIONS[tool], "diagnostics": version_errors, "log": "", "directory": temporary})
                diagnostics.extend(version_errors)
                continue
            if tool == "verilator":
                command = [*program, "--lint-only", "-Wall", *([] if strict_lint else ["-Wno-fatal"]), "--top-module", top, *staged]
            else:
                language = "-sv " if any(name.lower().endswith(".sv") for name in staged) else ""
                script = "read_verilog " + language + " ".join(f'"{name}"' for name in staged) + f"; hierarchy -check -top {top}; synth -top {top} -flatten; check -assert; write_json synthesis.json"
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
            statistics = {}
            if tool == "yosys" and status == "passed":
                try:
                    netlist = directory / "synthesis.json"
                    if netlist.stat().st_size > 64 * 1024 * 1024:
                        raise ValueError("synthesis_result_limit")
                    cells = json.loads(netlist.read_text(encoding="utf-8"))["modules"][top]["cells"]
                    counts = Counter(cell["type"] for cell in cells.values())
                    scopeinfo = counts.pop("$scopeinfo", 0)
                    statistics = {"cell_count": sum(counts.values()), "cells": dict(sorted(counts.items())), "scopeinfo_objects": scopeinfo}
                except (OSError, ValueError, KeyError, TypeError):
                    items.append(_diagnostic(tool, "HDL_TOOL_ERROR", "error", detail="synthesis_result_missing_or_invalid"))
            if any(item["severity"] == "error" for item in items):
                status = "timeout" if status == "timeout" else "failed"
            for item in items:
                item["params"]["stage"] = stage
                if tool == "yosys" and item["severity"] == "error" and not item["location"]:
                    item["location"] = {"file": next((name for name in files if Path(name).stem == top), next(iter(files))), "line": 1, "column": 1}
                    item["params"]["location_precision"] = "top_level_fallback"
            tools.append({"name": tool, "stage": stage, "status": status, "version": version, "expected_version": TOOL_VERSIONS[tool],
                          "diagnostics": items, "log": text, "directory": temporary, **statistics})
            diagnostics.extend(items)
    return {"valid": all(tool["status"] == "passed" for tool in tools), "tools": tools, "diagnostics": diagnostics, "strict_lint": strict_lint}