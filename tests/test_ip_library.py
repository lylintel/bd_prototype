import base64
import copy
from http.client import HTTPConnection
import json
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Thread

import pytest

import bdtool
from bdgui import EditorServer, Workspace
from ip_import.library import IpLibrary, LibraryError, Upload


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "import"
SOURCE = b"module item(output [3:0] data); assign data = 4'd3; endmodule\n"


def items(events):
    return [event for event in events if event["type"] == "ip"]


def test_batch_dry_run_idempotence_and_partial_errors(tmp_path):
    library = IpLibrary(tmp_path)
    preview = list(library.import_paths([FIXTURES], dry_run=True))
    assert len([event for event in items(preview) if event["status"] == "preview"]) == 24
    assert not (tmp_path / "ip_library").exists()
    events = list(library.import_paths([FIXTURES]))
    projected = [[event.get("id"), event["status"]] for event in items(events)]
    assert (json.dumps(projected, indent=2) + "\n").encode() == (FIXTURES / "batch.golden.json").read_bytes()
    assert events[-1]["counts"]["imported"] == 24
    assert events[-1]["counts"]["invalid"] == 1
    assert len(library.entries()) == 24
    before = (tmp_path / "ip_library/index.json").read_bytes()
    repeated = list(library.import_paths([FIXTURES]))
    assert repeated[-1]["counts"]["skipped"] == 24
    assert (tmp_path / "ip_library/index.json").read_bytes() == before
    sources = {row["definition"]["sources"][0] for row in library.entries()}
    assert len(sources) == 1


def test_changed_interface_needs_explicit_new_version(tmp_path):
    library = IpLibrary(tmp_path)
    first = items(library.import_sources([Upload("item.v", SOURCE)]))[0]
    assert first["status"] == "imported"
    original = (tmp_path / "ip_library/item/1.0.0/src/item.v").read_bytes()
    changed = SOURCE.replace(b"[3:0]", b"[7:0]")
    conflict = items(library.import_sources([Upload("item.v", changed)]))[0]
    assert conflict["status"] == "needs_version"
    assert conflict["diff"]["changed_ports"] == ["data"]
    assert not (tmp_path / "ip_library/item/1.1.0").exists()
    updated = items(library.import_sources([Upload("item.v", changed)], version="1.1.0"))[0]
    assert updated["status"] == "imported"
    assert (tmp_path / "ip_library/item/1.0.0/src/item.v").read_bytes() == original
    assert len(library.entries()) == 2


def test_preview_edits_confirm_roles_without_forging_interface(tmp_path):
    library = IpLibrary(tmp_path)
    source = Upload("unit.v", b"module unit(input clk, output ready); assign ready=clk; endmodule\n")
    preview = items(library.import_sources([source], dry_run=True))[0]
    metadata = copy.deepcopy(preview["metadata"])
    metadata["display_name"] = "Custom unit"
    metadata["ports"][0]["role"]["confirmed"] = True
    metadata["ports"][1]["dir"] = "in"
    invalid = items(library.import_sources([source], selections={"unit": metadata}))[0]
    assert invalid["status"] == "invalid"
    assert not (tmp_path / "ip_library").exists()
    metadata["ports"][1]["dir"] = "out"
    assert items(library.import_sources([source], selections={"unit": metadata}))[0]["status"] == "imported"
    saved = library.entries()[0]["metadata"]
    assert saved["display_name"] == "Custom unit"
    assert saved["ports"][0]["role"]["confirmed"] is True


@pytest.mark.parametrize("name", ["../escape.v", "dir/file.v", "C:\\file.v", "CON.v", "bad.txt", "bad\u0000.v"])
def test_upload_names_are_portable_and_contained(name):
    with pytest.raises(LibraryError):
        Upload(name, SOURCE)


def test_limits_rejected_before_library_writes(tmp_path):
    library = IpLibrary(tmp_path)
    with pytest.raises(LibraryError):
        Upload("large.v", b" " * (1024 * 1024 + 1))
    with pytest.raises(LibraryError):
        list(library.import_sources([Upload(f"file_{index}.v", SOURCE) for index in range(201)]))
    assert not (tmp_path / "ip_library").exists()


def test_bad_file_does_not_abort_directory_batch(tmp_path):
    source = tmp_path / "sources"
    source.mkdir()
    (source / "good.v").write_bytes(SOURCE)
    (source / "large.v").write_bytes(b" " * (1024 * 1024 + 1))
    events = list(IpLibrary(tmp_path / "workspace").import_paths([source]))
    assert events[-1]["counts"]["imported"] == 1
    assert events[-1]["counts"]["invalid"] == 1


def test_legacy_definition_is_rebased_and_tampering_is_detected(tmp_path):
    library = IpLibrary(tmp_path)
    list(library.import_sources([Upload("item.v", SOURCE)]))
    (tmp_path / "designs").mkdir()
    entry = library.entries(base_dir=tmp_path / "designs")[0]
    assert entry["usable"]
    assert entry["definition"]["sources"][0].startswith("../ip_library/")
    (tmp_path / "ip_library/item/1.0.0/src/item.v").write_bytes(b"tampered")
    assert library.entries()[0]["usable"] is False


def test_dependencies_are_required_and_included_in_generation(tmp_path):
    library = IpLibrary(tmp_path)
    parent = Upload("parent.v", b"module parent(output value); child child_0(.value(value)); endmodule\n")
    child = Upload("child.v", b"module child(output value); assign value=1'b1; endmodule\n")
    list(library.import_sources([parent]))
    assert library.entries()[0]["usable"] is False
    list(library.import_sources([child]))
    row = next(row for row in library.entries() if row["metadata"]["id"] == "parent")
    assert row["usable"]
    assert len(row["definition"]["sources"]) == 2
    design = bdtool.validate_design({"name": "dependency_bd", "modules": {"parent": row["definition"]},
                                    "instances": {"parent_0": {"module": "parent", "parameters": {}}}, "ports": {}, "nets": {}}, tmp_path)
    generated = []
    for name, content in bdtool.render_verilog(design).items():
        path = tmp_path / name
        path.write_bytes(content.encode())
        generated.append(str(path))
    subprocess.run([shutil.which("iverilog"), "-g2012", "-s", design.wrapper_name, "-o", str(tmp_path / "sim"),
                    *generated, *(str(path) for path in design.sources)], check=True, capture_output=True, timeout=30)


def test_recursive_import_includes_transitive_in_file_dependencies(tmp_path):
    sources = tmp_path / "sources"
    (sources / "nested").mkdir(parents=True)
    (sources / "top.v").write_bytes(b"module top(output value); middle unit_0(.value(value)); endmodule\nmodule middle(output value); leaf unit_0(.value(value)); endmodule\n")
    (sources / "nested/leaf.v").write_bytes(b"module leaf(output value); assign value=1'b1; endmodule\n")
    library = IpLibrary(tmp_path / "workspace")
    list(library.import_paths([sources], recursive=True))
    top = next(row for row in library.entries() if row["metadata"]["id"] == "top")
    assert top["usable"]
    assert len(top["definition"]["sources"]) == 2


def test_metadata_tampering_is_not_a_valid_profile(tmp_path):
    library = IpLibrary(tmp_path)
    list(library.import_sources([Upload("item.v", SOURCE)]))
    path = tmp_path / "ip_library/item/1.0.0/ip.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata["ports"][0]["dir"] = "in"
    path.write_text(json.dumps(metadata), encoding="utf-8")
    assert library.entries()[0]["usable"] is False


def test_failed_index_write_rolls_back_new_version(tmp_path, monkeypatch):
    library = IpLibrary(tmp_path)
    list(library.import_sources([Upload("item.v", SOURCE)]))
    index = tmp_path / "ip_library/index.json"
    before = index.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("simulated index failure")

    monkeypatch.setattr("ip_import.library.bdtool._write_outputs", fail)
    events = list(library.import_sources([Upload("other.v", SOURCE.replace(b"module item", b"module other"))]))
    assert items(events)[0]["status"] == "invalid"
    assert index.read_bytes() == before
    assert not (tmp_path / "ip_library/other/1.0.0").exists()
    assert not (tmp_path / "ip_library/.lock").exists()


@pytest.mark.parametrize("change", [{"action": []}, {"metadata": []}, {"version": "../bad"}])
def test_http_request_validation_is_not_deferred_until_streaming(tmp_path, change):
    payload = {"action": "commit", "files": [{"name": "item.v", "content_b64": base64.b64encode(SOURCE).decode()}], **change}
    with pytest.raises(bdtool.DesignError):
        Workspace(tmp_path, "unused.json").import_ips(payload)
    assert not (tmp_path / "ip_library").exists()


def test_missing_optional_import_dependencies_are_user_facing(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "ip_import.library", None)
    with pytest.raises(bdtool.DesignError):
        Workspace(tmp_path, "unused.json").import_ips({"action": "preview", "files": []})


def test_cli_dry_run_has_no_library_outputs(tmp_path):
    result = subprocess.run([sys.executable, "-m", "bdstudio", "ip", "import", str(FIXTURES / "batch.v"),
                             "--workspace", str(tmp_path), "--dry-run"], cwd=ROOT,
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events[-1]["counts"]["preview"] == 24
    assert not (tmp_path / "ip_library").exists()


def test_http_json_preview_commit_and_authentication(tmp_path):
    workspace = Workspace(tmp_path, "unused.json")
    server = EditorServer(("127.0.0.1", 0), workspace)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=180)
    payload = {"action": "preview", "files": [{"name": "item.v", "content_b64": base64.b64encode(SOURCE).decode()}]}
    headers = {"Content-Type": "application/json", "X-BD-Token": server.token}
    try:
        connection.request("POST", "/api/ip/import", json.dumps(payload), {"Content-Type": "application/json"})
        response = connection.getresponse()
        assert response.status == 403
        response.read()
        connection.request("POST", "/api/ip/import", json.dumps(payload), headers)
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type").startswith("application/x-ndjson")
        assert items(json.loads(line) for line in response.read().splitlines())[0]["status"] == "preview"
        assert not (tmp_path / "ip_library").exists()
        payload["action"] = "commit"
        connection.request("POST", "/api/ip/import", json.dumps(payload), headers)
        response = connection.getresponse()
        assert items(json.loads(line) for line in response.read().splitlines())[0]["status"] == "imported"
        connection.request("GET", "/api/ip/library?base_dir=.")
        response = connection.getresponse()
        assert json.loads(response.read())["entries"][0]["metadata"]["id"] == "item"
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)