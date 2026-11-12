import copy
from http.client import HTTPConnection
import json
from pathlib import Path
import shutil
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

import bdtool
from bdgui import EditorServer, Workspace


ROOT = Path(__file__).resolve().parents[1]


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bdgui-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "examples", self.root / "examples")
        self.workspace = Workspace(self.root, "examples/counter_compare.json")
        self.loaded = self.workspace.load(self.workspace.design_path)
        self.data = self.loaded["design"]

    def test_preview_uses_core_and_resolves_unconnected_drafts(self):
        preview = self.workspace.inspect(self.data, "examples")
        self.assertTrue(preview["valid"])
        expected = bdtool.render_verilog(bdtool.validate_design(self.data, self.root / "examples"))
        self.assertEqual(preview["files"], expected)
        self.data["nets"].pop("count_bus")
        preview = self.workspace.inspect(self.data, "examples")
        self.assertFalse(preview["valid"])
        self.assertEqual(preview["files"], {})
        self.assertIn("required input is unconnected", preview["diagnostics"][0])
        self.assertEqual(preview["interfaces"]["instances"]["compare_0"]["value"]["range"], [7, 0])

    def test_save_separates_layout_and_rebases_sources(self):
        original = copy.deepcopy(self.data)
        layout = {"nodes": {"counter_0": {"x": 100, "y": 80}}, "viewport": {"x": 0, "y": 0, "zoom": 1}}
        saved = self.workspace.save({"design": self.data, "base_dir": "examples", "path": "designs/demo.json", "layout": layout})
        self.assertTrue(saved["inspection"]["valid"])
        self.assertEqual(self.data, original)
        self.assertEqual(saved["layout"], layout)
        self.assertNotIn("layout", saved["design"])
        self.assertEqual(saved["design"]["modules"]["counter"]["sources"], ["../examples/rtl/counter.v"])
        bdtool.load_design(self.root / "designs/demo.json")
        self.assertTrue((self.root / "designs/demo.layout.json").is_file())

    def test_save_incomplete_draft_but_refuse_generation(self):
        self.data["nets"].pop("rst_net")
        saved = self.workspace.save({"design": self.data, "base_dir": "examples", "path": "designs/draft.json"})
        self.assertFalse(saved["inspection"]["valid"])
        with self.assertRaisesRegex(bdtool.DesignError, "required input is unconnected"):
            self.workspace.generate({"design": self.data, "base_dir": "examples"})
        self.assertFalse((self.root / "build").exists())

    def test_generation_changes_parameters_without_touching_example(self):
        self.data["instances"]["compare_0"]["parameters"]["THRESHOLD"] = 19
        generated = self.workspace.generate({"design": self.data, "base_dir": "examples"})
        self.assertIn(".THRESHOLD(19)", generated["files"]["example_bd.v"])
        self.assertEqual(generated["paths"], ["build/gui/example_bd.v", "build/gui/example_bd_wrapper.v"])
        self.assertEqual(self.workspace.load(self.workspace.design_path)["design"]["instances"]["compare_0"]["parameters"]["THRESHOLD"], 9)

    def test_port_conflict_remains_an_os_error(self):
        with patch("http.server.HTTPServer.server_bind", side_effect=OSError("port already in use")):
            with self.assertRaisesRegex(OSError, "port already in use"):
                EditorServer(("127.0.0.1", 0), self.workspace)

    def test_semantic_inspect_preserves_old_response_and_v2_roundtrip(self):
        old = self.workspace.inspect(self.data, "examples")
        semantic = self.workspace.semantic_inspect(self.data, "examples")
        self.assertTrue(semantic["valid"], semantic["diagnostics"])
        self.assertEqual(semantic["files"], old["files"])
        self.assertEqual(self.workspace.inspect(self.data, "examples"), old)
        document = semantic["document"]
        document["instances"][0]["params"]["WIDTH"] = "4 * 3"
        document["instances"][1]["params"]["WIDTH"] = 12
        saved = self.workspace.save({"design": document, "base_dir": "examples", "path": "designs/v2.json"})
        self.assertEqual(saved["design"]["schema_version"], 2)
        self.assertTrue(saved["inspection"]["valid"], saved["inspection"]["diagnostics"])
        self.assertIn(".WIDTH(12)", self.workspace.generate({"design": saved["design"], "base_dir": "designs"})["files"]["example_bd.v"])
        self.assertEqual(self.data["instances"]["counter_0"]["parameters"]["WIDTH"], 8)

    def test_semantic_inspect_checks_sources_before_validation(self):
        document = self.workspace.semantic_inspect(self.data, "examples")["document"]
        document["project_ips"][0]["source"]["sha256"] = "0" * 64
        result = self.workspace.semantic_inspect(document, "examples")
        self.assertFalse(result["valid"])
        self.assertEqual(result["diagnostics"][0]["code"], "D005")
        document["project_ips"][0]["source"]["path"] = "../../outside.v"
        self.assertEqual(self.workspace.semantic_inspect(document, "examples")["diagnostics"][0]["code"], "D005")

    def test_semantic_snapshot_keeps_roles_without_legacy_definition(self):
        shutil.copytree(ROOT / "ip_library/builtin", self.root / "ip_library/builtin")
        document = {"schema_version": 2, "name": "sync_design", "ports": {}, "nets": [],
                    "instances": [{"name": "sync_0", "ip": {"id": "bd_sync_2ff", "version": "1.0.0"}}]}
        with patch("ip_import.library.IpLibrary.entries", side_effect=AssertionError("legacy view forbidden")):
            result = self.workspace.semantic_inspect(document, ".")
        self.assertEqual(result["interfaces"]["instances"]["sync_0"]["clk"]["role"]["kind"], "clock")

    def test_rejects_paths_outside_workspace_and_invalid_layout(self):
        with self.assertRaisesRegex(bdtool.DesignError, "inside the workspace"):
            self.workspace.path("../outside.json")
        with self.assertRaisesRegex(bdtool.DesignError, "save designs under designs/"):
            self.workspace.save({"design": self.data, "base_dir": "examples", "path": "examples/overwrite.json"})
        with self.assertRaisesRegex(bdtool.DesignError, "invalid coordinate"):
            self.workspace.save({"design": self.data, "base_dir": "examples", "path": "designs/demo.json", "layout": {"nodes": {"counter_0": {"x": float("nan"), "y": 0}}}})
        self.data["modules"]["counter"]["sources"] = ["../../outside.v"]
        preview = self.workspace.inspect(self.data, "examples")
        self.assertFalse(preview["valid"])
        self.assertIn("inside the workspace", preview["diagnostics"][0])

    def test_http_requires_same_origin_and_session_token(self):
        server = EditorServer(("127.0.0.1", 0), self.workspace)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        try:
            connection.request("GET", "/api/state")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            state = json.loads(response.read())
            payload = json.dumps({"design": self.data, "base_dir": "examples"})
            connection.request("POST", "/api/inspect", payload, {"Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            headers = {"Content-Type": "application/json", "X-BD-Token": state["token"]}
            connection.request("POST", "/api/inspect", payload, headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertTrue(json.loads(response.read())["valid"])
            connection.request("POST", "/api/semantic/inspect", payload, headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            semantic = json.loads(response.read())
            self.assertTrue(semantic["valid"])
            self.assertEqual(semantic["document"]["schema_version"], 2)
            connection.request("POST", "/api/generate", payload, {**headers, "Origin": "https://example.com"})
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            connection.request("GET", "/api/state", headers={"Host": "example.com"})
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()