"""Serve the local block-design editor and reuse bdtool for all HDL operations."""

from __future__ import annotations

import argparse
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import mimetypes
import os
from pathlib import Path
from queue import Empty
import secrets
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser

import bdtool
from bdcopilot import CopilotBridge, CopilotError


ASSETS = Path(__file__).resolve().parent / "web" / "dist"
MAX_BODY = 2 * 1024 * 1024


def port_info(port: bdtool.Port) -> dict:
    return {
        "direction": port.direction,
        "range": list(port.bounds) if port.bounds is not None else None,
        "signed": port.signed,
        "width": port.width,
    }


def check_layout(value: object) -> dict:
    layout = bdtool._fields(value, "layout", set(), {"nodes", "viewport"})
    nodes = bdtool._object(layout.get("nodes", {}), "layout.nodes")
    for name, position in nodes.items():
        bdtool._fields(position, f"layout.nodes.{name}", {"x", "y"})
        for coordinate in position.values():
            if type(coordinate) not in (int, float) or not math.isfinite(coordinate) or abs(coordinate) > 1e7:
                raise bdtool.DesignError(f"layout.nodes.{name}: invalid coordinate")
    viewport = layout.get("viewport", {"x": 0, "y": 0, "zoom": 1})
    bdtool._fields(viewport, "layout.viewport", {"x", "y", "zoom"})
    for coordinate in viewport.values():
        if type(coordinate) not in (int, float) or not math.isfinite(coordinate) or abs(coordinate) > 1e7:
            raise bdtool.DesignError("layout.viewport: invalid coordinate")
    if not 0.1 <= viewport["zoom"] <= 3:
        raise bdtool.DesignError("layout.viewport.zoom: expected a value between 0.1 and 3")
    return {"nodes": nodes, "viewport": viewport}


class Workspace:
    def __init__(self, root: Path, design_path: str):
        self.root = root.resolve()
        self.design_path = design_path

    def path(self, value: str) -> Path:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise bdtool.DesignError("path: expected a workspace-relative path")
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root):
            raise bdtool.DesignError("path: must remain inside the workspace")
        return path

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def structure(self, data: object) -> dict:
        root = bdtool._fields(data, "design", {"name", "modules", "instances", "ports", "nets"})
        bdtool._name(root["name"], "design.name")
        for section in ("modules", "instances", "ports", "nets"):
            bdtool._object(root[section], section)
        return root

    def sources(self, data: dict, base: Path) -> set[Path]:
        sources = set()
        for name, raw in bdtool._object(data.get("modules"), "modules").items():
            module = bdtool._object(raw, f"modules.{name}")
            filenames = module.get("sources")
            if not isinstance(filenames, list):
                raise bdtool.DesignError(f"modules.{name}.sources: expected a list")
            for filename in filenames:
                if not isinstance(filename, str) or not filename or "\x00" in filename:
                    raise bdtool.DesignError(f"modules.{name}.sources: invalid path")
                source = (base / filename).resolve()
                if not source.is_relative_to(self.root):
                    raise bdtool.DesignError(f"modules.{name}.sources: must remain inside the workspace")
                sources.add(source)
        return sources

    def inspect(self, data: object, base_dir: str) -> dict:
        base = self.path(base_dir)
        result = {"valid": False, "diagnostics": [], "files": {}, "interfaces": {"ports": {}, "instances": {}}}
        try:
            data = self.structure(data)
            self.sources(data, base)
            design = bdtool.validate_design(data, base)
            result.update(valid=True, files=bdtool.render_verilog(design))
        except (bdtool.DesignError, OSError) as exc:
            result["diagnostics"].append(str(exc))
        if not isinstance(data, dict):
            return result
        try:
            result["interfaces"]["ports"] = {
                name: port_info(port) for name, port in bdtool._ports(data.get("ports"), {}, "ports").items()
            }
        except bdtool.DesignError:
            pass
        modules = data.get("modules", {})
        instances = data.get("instances", {})
        if not isinstance(modules, dict) or not isinstance(instances, dict):
            return result
        for name, raw in instances.items():
            try:
                spec = bdtool._fields(raw, f"instances.{name}", {"module"}, {"parameters"})
                module_name = bdtool._name(spec["module"], f"instances.{name}.module")
                definition = bdtool._object(modules.get(module_name), f"modules.{module_name}")
                parameters = bdtool._parameters(
                    definition.get("parameters", {}), spec.get("parameters", {}), f"instances.{name}"
                )
                ports = bdtool._ports(definition.get("ports"), parameters, f"instances.{name}.ports")
                result["interfaces"]["instances"][name] = {port: port_info(info) for port, info in ports.items()}
            except bdtool.DesignError:
                continue
        return result

    def load(self, filename: str) -> dict:
        path = self.path(filename)
        if path.suffix.lower() != ".json":
            raise bdtool.DesignError("path: expected a JSON design")
        data = self.structure(json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=bdtool._unique_keys))
        self.sources(data, path.parent)
        layout_path = path.with_suffix(".layout.json")
        self.path(self.relative(layout_path))
        layout = json.loads(layout_path.read_text(encoding="utf-8")) if layout_path.is_file() else {}
        return {
            "design": data,
            "path": self.relative(path),
            "base_dir": self.relative(path.parent) or ".",
            "layout": check_layout(layout),
            "inspection": self.inspect(data, self.relative(path.parent) or "."),
        }

    def list_designs(self) -> list[str]:
        paths = {self.design_path}
        if self.path("src/ip_catalog.json").is_file():
            paths.add("src/ip_catalog.json")
        for directory in ("examples", "designs"):
            folder = self.path(directory)
            if folder.exists():
                paths.update(self.relative(path) for path in folder.glob("*.json") if not path.name.endswith(".layout.json"))
        return sorted(paths)

    def save(self, payload: dict) -> dict:
        data = copy.deepcopy(self.structure(payload.get("design")))
        base = self.path(payload.get("base_dir", "."))
        target = self.path(payload.get("path", ""))
        if not target.is_relative_to(self.path("designs")) or target.suffix != ".json" or target.name.endswith(".layout.json"):
            raise bdtool.DesignError("path: save designs under designs/ with a .json extension")
        sources = self.sources(data, base)
        layout = check_layout(payload.get("layout", {}))
        for definition in data["modules"].values():
            definition["sources"] = [Path(os.path.relpath((base / name).resolve(), target.parent)).as_posix() for name in definition["sources"]]
        layout_path = target.with_suffix(".layout.json")
        self.path(self.relative(layout_path))
        bdtool._write_outputs({
            target.name: json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            layout_path.name: json.dumps(layout, indent=2) + "\n",
        }, target.parent, sources)
        return self.load(self.relative(target))

    def generate(self, payload: dict) -> dict:
        data = self.structure(payload.get("design"))
        base = self.path(payload.get("base_dir", "."))
        sources = self.sources(data, base)
        design = bdtool.validate_design(data, base)
        files = bdtool.render_verilog(design)
        out_dir = self.path("build/gui")
        bdtool._write_outputs(files, out_dir, sources)
        return {"files": files, "paths": [self.relative(out_dir / name) for name in files]}


class EditorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], workspace: Workspace):
        self.workspace = workspace
        self.token = secrets.token_urlsafe(32)
        self.copilot = CopilotBridge(workspace)
        super().__init__(address, EditorHandler)

    def server_close(self):
        try:
            self.copilot.close()
        finally:
            super().server_close()


class EditorHandler(BaseHTTPRequestHandler):
    server: EditorServer

    def log_message(self, format: str, *args: object) -> None:
        pass

    def guard(self, write: bool = False) -> None:
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in hosts:
            raise PermissionError("Host is not allowed")
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{host}" for host in hosts}:
            raise PermissionError("Cross-origin requests are not allowed")
        if write and not secrets.compare_digest(self.headers.get("X-BD-Token", ""), self.server.token):
            raise PermissionError("Invalid session token; reload the editor")

    def respond(self, status: int, content: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(content)

    def json_response(self, value: object, status: int = 200) -> None:
        self.respond(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        try:
            self.guard()
            request = urlsplit(self.path)
            workspace = self.server.workspace
            if request.path == "/api/state":
                self.json_response({**workspace.load(workspace.design_path), "token": self.server.token})
            elif request.path == "/api/copilot/status":
                self.json_response(self.server.copilot.status())
            elif request.path == "/api/designs":
                self.json_response({"paths": workspace.list_designs()})
            elif request.path == "/api/load":
                filename = parse_qs(request.query).get("path", [workspace.design_path])[0]
                self.json_response(workspace.load(filename))
            else:
                path = (ASSETS / (unquote(request.path).lstrip("/") or "index.html")).resolve()
                if not path.is_relative_to(ASSETS.resolve()) or not path.is_file():
                    self.json_response({"error": "Not found"}, 404)
                    return
                content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
                if path.suffix == ".js":
                    content_type = "text/javascript"
                self.respond(200, path.read_bytes(), content_type)
        except PermissionError as exc:
            self.json_response({"error": str(exc)}, 403)
        except (bdtool.DesignError, OSError, ValueError) as exc:
            self.json_response({"error": str(exc)}, 400)

    def stream_chat(self, payload):
        turn = self.server.copilot.start_turn(payload)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.connection.settimeout(15)
            while True:
                try:
                    event = turn.events.get(timeout=1)
                except Empty:
                    event = {"type": "ping"}
                self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()
                if event["type"] == "done":
                    break
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass
        finally:
            self.close_connection = True
            if not turn.finished:
                self.server.copilot.cancel(turn.id)

    def do_POST(self) -> None:
        try:
            self.guard(write=True)
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self.json_response({"error": "Content-Type must be application/json"}, 415)
                return
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                self.json_response({"error": "Request body must be between 1 byte and 2 MiB"}, 413)
                return
            payload = bdtool._object(json.loads(self.rfile.read(length), object_pairs_hook=bdtool._unique_keys), "request")
            workspace = self.server.workspace
            if self.path == "/api/copilot/connect":
                self.json_response(self.server.copilot.connect())
            elif self.path == "/api/copilot/chat":
                self.stream_chat(payload)
            elif self.path == "/api/copilot/cancel":
                self.json_response(self.server.copilot.cancel(payload.get("request_id")))
            elif self.path == "/api/copilot/clear":
                self.json_response(self.server.copilot.clear(payload.get("conversation_id")))
            elif self.path == "/api/inspect":
                self.json_response(workspace.inspect(payload.get("design"), payload.get("base_dir", ".")))
            elif self.path == "/api/save":
                self.json_response(workspace.save(payload))
            elif self.path == "/api/generate":
                self.json_response(workspace.generate(payload))
            else:
                self.json_response({"error": "Not found"}, 404)
        except PermissionError as exc:
            self.json_response({"error": str(exc)}, 403)
        except (CopilotError, bdtool.DesignError, OSError, ValueError) as exc:
            self.json_response({"error": str(exc)}, 400)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--design", default="examples/counter_compare.json")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="open the editor in the default browser")
    args = parser.parse_args(argv)
    if not (ASSETS / "index.html").is_file():
        parser.exit(1, "Build the frontend first: npm --prefix web install; npm --prefix web run build\n")
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    workspace = Workspace(args.workspace, args.design)
    workspace.load(args.design)
    server = None
    for port in range(args.port, min(args.port + 20, 65536)):
        try:
            server = EditorServer(("127.0.0.1", port), workspace)
            break
        except OSError as exc:
            if exc.errno not in (98, 10048) and getattr(exc, "winerror", None) != 10048:
                raise
    if server is None:
        parser.exit(1, "No available local port; choose another --port\n")
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"BD Studio: {url}", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())