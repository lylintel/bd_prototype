import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import bdtool
from bdgui import Workspace


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
CATALOG = SOURCE / "ip_catalog.json"
IVERILOG = shutil.which("iverilog")
VVP = shutil.which("vvp")


class IpCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

    def module_design(self, module, overrides=None):
        definition = copy.deepcopy(self.catalog["modules"][module])
        parameters = bdtool._parameters(definition.get("parameters", {}), overrides or {}, module)
        ports = bdtool._ports(definition["ports"], parameters, f"{module}.ports")
        data = {"name": f"{module}_smoke", "modules": {module: definition},
                "instances": {"ip_inst": {"module": module, "parameters": overrides or {}}},
                "ports": {}, "nets": {}}
        for name, port in ports.items():
            spec = {"direction": port.direction}
            if port.bounds is not None:
                spec["range"] = list(port.bounds)
            if port.signed:
                spec["signed"] = True
            data["ports"][f"ext_{name}"] = spec
            data["nets"][f"net_{name}"] = [f"@ext_{name}", f"ip_inst.{name}"]
        return bdtool.validate_design(data, SOURCE)

    def test_catalog_is_a_valid_portable_design(self):
        design = bdtool.load_design(CATALOG)
        self.assertEqual(len(self.catalog["modules"]), 5)
        self.assertEqual(design.instances, {})
        for module in self.catalog["modules"]:
            with self.subTest(module=module):
                resolved = self.module_design(module)
                self.assertEqual(resolved.instances["ip_inst"].module, module)

    def test_profiles_reject_unsupported_widths(self):
        for module, parameters in (("priority_encoder", {"WIDTH": 16}),
                                   ("axis_register", {"DATA_WIDTH": 16}),
                                   ("uart_rx", {"DATA_WIDTH": 1})):
            with self.subTest(module=module):
                with self.assertRaisesRegex(bdtool.DesignError, "outside"):
                    self.module_design(module, parameters)

    def test_vendor_hashes_and_license_notices(self):
        manifest = json.loads((SOURCE / "UPSTREAM.json").read_text(encoding="utf-8"))
        for item in manifest["files"]:
            with self.subTest(path=item["path"]):
                path = SOURCE / item["path"]
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])
                header = path.read_text(encoding="utf-8").split("module ", 1)[0]
                self.assertIn("Copyright (c)", header)
                self.assertIn("Permission is hereby granted", header)
                self.assertIn('THE SOFTWARE IS PROVIDED "AS IS"', header)

    def test_catalog_is_visible_in_gui(self):
        workspace = Workspace(ROOT, "examples/counter_compare.json")
        self.assertIn("src/ip_catalog.json", workspace.list_designs())
        loaded = workspace.load("src/ip_catalog.json")
        self.assertTrue(loaded["inspection"]["valid"])
        self.assertEqual(len(loaded["design"]["modules"]), 5)
        self.assertEqual(loaded["base_dir"], "src")

    def simulate(self, top, design=None, parameters=()):
        with tempfile.TemporaryDirectory(prefix="bd-ip-sim-") as directory:
            work = Path(directory)
            resolved = design or bdtool.load_design(CATALOG)
            generated = []
            if design:
                for name, contents in bdtool.render_verilog(design).items():
                    path = work / name
                    path.write_text(contents, encoding="utf-8")
                    generated.append(path)
            executable = work / "sim"
            compiled = subprocess.run(
                [IVERILOG, "-g2012", "-s", top, *parameters, "-o", str(executable),
                 *map(str, resolved.sources), *map(str, generated), str(SOURCE / "tb" / f"{top}.v")],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([VVP, str(executable)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout

    @unittest.skipUnless(IVERILOG and VVP, "iverilog and vvp are required for IP simulation")
    def test_buffered_uart_loopback(self):
        design = bdtool.load_design(ROOT / "examples" / "uart_loopback.json")
        self.assertEqual(len(design.instances), 3)
        self.assertIn("PASS: buffered UART loopback", self.simulate("tb_uart_loopback", design))

    @unittest.skipUnless(IVERILOG and VVP, "iverilog and vvp are required for IP simulation")
    def test_stream_register_backpressure(self):
        for mode in (0, 1, 2):
            with self.subTest(mode=mode):
                output = self.simulate("tb_stream_register", parameters=["-P", f"tb_stream_register.REG_TYPE={mode}"])
                self.assertIn(f"PASS: stream mode={mode}, 64 words", output)

    @unittest.skipUnless(IVERILOG and VVP, "iverilog and vvp are required for IP simulation")
    def test_priority_encoder_exhaustive(self):
        self.assertIn("PASS: priority encoder, 256 patterns", self.simulate("tb_priority_encoder"))

    @unittest.skipUnless(IVERILOG, "iverilog is required for IP compilation")
    def test_generated_wrappers_match_upstream_interfaces(self):
        variants = [(name, {}) for name in self.catalog["modules"]]
        variants.extend(("bd_stream_register", {"DATA_WIDTH": width, "REG_TYPE": mode})
                        for width in (1, 16, 32) for mode in (0, 1, 2))
        variants.extend((module, {"DATA_WIDTH": width})
                        for module in ("uart_tx", "uart_rx") for width in (5, 9))
        variants.append(("priority_encoder", {"LSB_HIGH_PRIORITY": 1}))
        variants.append(("axis_register", {"KEEP_ENABLE": 1, "ID_ENABLE": 1, "DEST_ENABLE": 1}))
        for module, parameters in variants:
            with self.subTest(module=module, parameters=parameters), tempfile.TemporaryDirectory(prefix="bd-ip-") as directory:
                work = Path(directory)
                design = self.module_design(module, parameters)
                generated = []
                for name, contents in bdtool.render_verilog(design).items():
                    path = work / name
                    path.write_text(contents, encoding="utf-8")
                    generated.append(path)
                result = subprocess.run(
                    [IVERILOG, "-g2005", "-Wportbind", "-s", design.wrapper_name, "-o", str(work / "smoke"),
                     *map(str, design.sources), *map(str, generated)],
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()