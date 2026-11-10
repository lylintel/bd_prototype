import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from bdtool import DesignError, render_verilog, validate_design


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "counter_compare.json"
IVERILOG = shutil.which("iverilog")
VVP = shutil.which("vvp")


class BlockDesignTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "bdtool", *map(str, args)],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )

    def test_cli_generation_is_repeatable_and_honors_parameter_changes(self):
        with tempfile.TemporaryDirectory(prefix="bdtool-") as directory:
            work = Path(directory)
            path = work / "design.json"
            shutil.copytree(EXAMPLE.parent / "rtl", work / "rtl")
            path.write_text(json.dumps(self.config), encoding="utf-8")
            result = self.run_cli("validate", path)
            self.assertEqual(result.returncode, 0, result.stderr)

            out = work / "build"
            result = self.run_cli("generate", path, "-o", out)
            self.assertEqual(result.returncode, 0, result.stderr)
            bd = out / "example_bd.v"
            wrapper = out / "example_bd_wrapper.v"
            original_bd = bd.read_bytes()
            original_wrapper = wrapper.read_bytes()
            self.assertIn(b"wire [7:0] count_bus;", original_bd)
            self.assertIn(b".count(count_bus)", original_bd)
            self.assertIn(b".value(count_bus)", original_bd)
            self.assertIn(b".THRESHOLD(9)", original_bd)
            self.assertIn(b"example_bd bd_i (", original_wrapper)

            result = self.run_cli("generate", path, "-o", out)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(bd.read_bytes(), original_bd)
            self.assertEqual(wrapper.read_bytes(), original_wrapper)

            self.config["instances"]["compare_0"]["parameters"]["THRESHOLD"] = 19
            path.write_text(json.dumps(self.config), encoding="utf-8")
            result = self.run_cli("generate", path, "-o", out)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(bd.read_bytes(), original_bd.replace(b".THRESHOLD(9)", b".THRESHOLD(19)"))
            self.assertEqual(wrapper.read_bytes(), original_wrapper)

            self.config["nets"]["count_bus"][1] = "compare_0.missing"
            path.write_text(json.dumps(self.config), encoding="utf-8")
            result = self.run_cli("generate", path, "-o", out)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("nets.count_bus: invalid endpoint", result.stderr)
            self.assertIn(b".THRESHOLD(19)", bd.read_bytes())
            self.assertEqual(wrapper.read_bytes(), original_wrapper)

    def test_rejects_invalid_connections_and_unresolved_parameters(self):
        cases = {
            "invalid endpoint": lambda data: data["nets"]["count_bus"].append("unknown.pin"),
            "width mismatch": lambda data: data["instances"]["compare_0"]["parameters"].update(WIDTH=4),
            "expected exactly one driver, found 2": lambda data: data["nets"]["count_bus"].append("@extra"),
            "unresolved parameter": lambda data: data["modules"]["counter"]["ports"]["count"].update(
                range=["MISSING - 1", 0]),
            "required input is unconnected": lambda data: data["nets"].pop("rst_net"),
            "outside": lambda data: data["instances"]["counter_0"]["parameters"].update(WIDTH=0),
            "invalid Verilog identifier": lambda data: data.update(name="module"),
            "conflicts with a port, instance or net": lambda data: data["nets"].update(
                clk=data["nets"].pop("clk_net")),
            "range expressions allow": lambda data: data["modules"]["counter"]["ports"]["count"].update(
                range=["abs(WIDTH) - 1", 0]),
            "nets.count_bus: expected exactly one driver, found 0": lambda data: data["nets"].update(
                count_bus=["compare_0.value", "@match"]),
            "nets.duplicate_bus: endpoint .* already connected": lambda data: data["nets"].update(
                duplicate_bus=["counter_0.count", "compare_0.value"]),
            "ports.match: external output has no driver": lambda data: data["nets"].pop("match_net"),
            "instances.compare_0: unknown parameter": lambda data: data["instances"]["compare_0"]["parameters"].update(
                TYPO=19),
            "instances.compare_0.parameters.WIDTH: expected a signed 32-bit integer": lambda data: data["instances"]["compare_0"]["parameters"].update(
                WIDTH="MISSING"),
            "ports.extra: direction must be input or output": lambda data: data["ports"]["extra"].update(
                direction="inout"),
            "instances.counter_0: name .* conflicts with a port, instance or net": lambda data: data["ports"].update(
                counter_0={"direction": "input"}),
            "design.name: generated module name conflicts with an IP module": lambda data: data.update(name="counter"),
            "modules.counter.ports.WIDTH: name conflicts with a parameter": lambda data: (
                data["modules"]["counter"]["ports"].update(WIDTH={"direction": "input"}),
                data["nets"]["clk_net"].append("counter_0.WIDTH"),
            ),
        }
        for message, mutate in cases.items():
            with self.subTest(message=message):
                config = copy.deepcopy(self.config)
                config["ports"]["extra"] = {"direction": "input", "range": [7, 0]}
                mutate(config)
                with self.assertRaisesRegex(DesignError, message):
                    validate_design(config, EXAMPLE.parent)

    def test_default_parameters_and_unconnected_outputs(self):
        for instance in self.config["instances"].values():
            instance.pop("parameters")
        self.config["ports"].pop("match")
        self.config["nets"].pop("match_net")
        structural = render_verilog(validate_design(self.config, EXAMPLE.parent))["example_bd.v"]
        self.assertEqual(structural.count(".WIDTH(8)"), 2)
        self.assertIn(".THRESHOLD(9)", structural)
        self.assertIn(".match()", structural)

    def test_wrapper_avoids_port_name_collisions(self):
        config = {
            "name": "passthrough",
            "modules": {},
            "instances": {},
            "ports": {
                "bd_i": {"direction": "input"},
                "bd_i_": {"direction": "input"},
                "result": {"direction": "output"},
            },
            "nets": {"data_net": ["@bd_i", "@result"]},
        }
        wrapper = render_verilog(validate_design(config, ROOT))["passthrough_wrapper.v"]
        self.assertIn("passthrough bd_i__ (", wrapper)
        self.assertIn(".bd_i(bd_i)", wrapper)
        self.assertIn(".bd_i_(bd_i_)", wrapper)

    def test_cli_rejects_duplicate_json_keys_without_writing(self):
        with tempfile.TemporaryDirectory(prefix="bdtool-") as directory:
            work = Path(directory)
            path = work / "design.json"
            path.write_text('{"name": "first", "name": "second"}', encoding="utf-8")
            out = work / "build"
            for args in (("validate", path), ("generate", path, "-o", out)):
                with self.subTest(command=args[0]):
                    result = self.run_cli(*args)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("JSON: duplicate key 'name'", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertFalse(out.exists())

    def test_generation_does_not_overwrite_source(self):
        with tempfile.TemporaryDirectory(prefix="bdtool-") as directory:
            work = Path(directory)
            shutil.copytree(EXAMPLE.parent / "rtl", work / "rtl")
            source = work / "example_bd.v"
            original = "module existing_source; endmodule\n"
            source.write_text(original, encoding="utf-8")
            self.config["modules"]["counter"]["sources"].append(source.name)
            path = work / "design.json"
            path.write_text(json.dumps(self.config), encoding="utf-8")

            result = self.run_cli("generate", path, "-o", work)
            self.assertEqual(result.returncode, 1)
            self.assertIn("output would overwrite an input file", result.stderr)
            self.assertEqual(source.read_text(encoding="utf-8"), original)
            self.assertFalse((work / "example_bd_wrapper.v").exists())

    def test_preserves_scalar_vector_signedness_and_ascending_range(self):
        source_ports = {
            "asc": {"direction": "input", "range": [0, 7], "signed": True},
            "one": {"direction": "input", "range": [0, 0]},
            "bit_in": {"direction": "input"},
        }
        ports = dict(source_ports)
        nets = {}
        for name, spec in source_ports.items():
            ports[f"{name}_out"] = {**spec, "direction": "output"}
            nets[f"{name}_net"] = [f"@{name}", f"@{name}_out"]
        config = {"name": "pass_through", "modules": {}, "ports": ports, "instances": {}, "nets": nets}
        hdl = render_verilog(validate_design(config, ROOT))
        self.assertIn("wire signed [0:7] asc_net;", hdl["pass_through.v"])
        self.assertIn("wire [0:0] one_net;", hdl["pass_through.v"])
        self.assertIn("wire bit_in_net;", hdl["pass_through.v"])
        self.assertIn("output wire signed [0:7] asc_out", hdl["pass_through_wrapper.v"])

        config["ports"]["asc_out"]["range"] = [7, 0]
        with self.assertRaisesRegex(DesignError, "range or signedness mismatch"):
            validate_design(config, ROOT)

    def test_accepts_sequential_feedback_and_fanout(self):
        with tempfile.TemporaryDirectory(prefix="bdtool-") as directory:
            source = Path(directory) / "state_bit.v"
            source.write_text(
                "module state_bit(input clk, input d, output reg q);\n"
                "    always @(posedge clk) q <= d;\nendmodule\n",
                encoding="utf-8",
            )
            config = {
                "name": "feedback_bd",
                "modules": {
                    "state_bit": {
                        "sources": [source.name],
                        "ports": {
                            "clk": {"direction": "input"},
                            "d": {"direction": "input"},
                            "q": {"direction": "output"},
                        },
                    }
                },
                "ports": {"clk": {"direction": "input"}, "state": {"direction": "output"}},
                "instances": {"state_0": {"module": "state_bit"}},
                "nets": {
                    "clock_net": ["@clk", "state_0.clk"],
                    "state_net": ["state_0.q", "state_0.d", "@state"],
                },
            }
            structural = render_verilog(validate_design(config, Path(directory)))["feedback_bd.v"]
            self.assertIn(".q(state_net)", structural)
            self.assertIn(".d(state_net)", structural)
            self.assertIn("assign state = state_net;", structural)

    @unittest.skipUnless(IVERILOG and VVP, "iverilog and vvp are required for HDL simulation")
    def test_counter_compare_in_hdl_simulator(self):
        for threshold in (9, 19):
            with self.subTest(threshold=threshold), tempfile.TemporaryDirectory(prefix="bdtool-") as directory:
                work = Path(directory)
                self.config["instances"]["compare_0"]["parameters"]["THRESHOLD"] = threshold
                design = validate_design(self.config, EXAMPLE.parent)
                generated = []
                for name, contents in render_verilog(design).items():
                    path = work / name
                    path.write_text(contents, encoding="utf-8")
                    generated.append(path)
                executable = work / "sim"
                compilation = subprocess.run(
                    [IVERILOG, "-g2012", "-s", "tb", "-o", str(executable),
                     *map(str, design.sources), *map(str, generated), str(EXAMPLE.parent / "rtl/tb.v")],
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(compilation.returncode, 0, compilation.stderr)
                simulation = subprocess.run(
                    [VVP, str(executable), f"+threshold={threshold}"],
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(simulation.returncode, 0, simulation.stdout + simulation.stderr)
                self.assertIn(f"PASS: threshold={threshold}", simulation.stdout)


if __name__ == "__main__":
    unittest.main()
