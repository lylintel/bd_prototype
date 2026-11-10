import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import bdtool
from bdgui import Workspace
from bdworkflow import CHECKS, DIMENSIONS, DesignRun, WorkflowError, apply_operations, read_catalog, workflow_instructions


ROOT = Path(__file__).resolve().parents[1]


class DesignOperationTests(unittest.TestCase):
    def setUp(self):
        self.workspace = Workspace(ROOT, "examples/counter_compare.json")
        self.context = {"design": json.loads((ROOT / "examples/counter_compare.json").read_text(encoding="utf-8")), "base_dir": "examples"}

    def test_parameter_change_preserves_unrelated_design(self):
        before = copy.deepcopy(self.context)
        updated, files = apply_operations(self.workspace, self.context, [
            {"op": "set_parameter", "instance": "compare_0", "parameter": "THRESHOLD", "value": 19}])
        self.assertEqual(self.context, before)
        self.assertEqual(updated["nets"], before["design"]["nets"])
        self.assertEqual(updated["instances"]["counter_0"], before["design"]["instances"]["counter_0"])
        self.assertIn(".THRESHOLD(19)", files["example_bd.v"])

    def test_invalid_plan_is_atomic(self):
        before = copy.deepcopy(self.context)
        with self.assertRaisesRegex(bdtool.DesignError, "width mismatch"):
            apply_operations(self.workspace, self.context, [
                {"op": "set_parameter", "instance": "compare_0", "parameter": "WIDTH", "value": 4}])
        self.assertEqual(self.context, before)

    def test_catalog_hash_and_real_module_are_required(self):
        catalog = read_catalog(self.workspace, self.context)
        self.assertIn("uart_tx", catalog["modules"])
        self.assertTrue(catalog["modules"]["uart_tx"]["source_hashes"])
        with self.assertRaisesRegex(WorkflowError, "not in the authorized catalog"):
            apply_operations(self.workspace, self.context, [{"op": "add_instance", "name": "missing_0", "module": "invented"}])
        with self.assertRaisesRegex(WorkflowError, "changed or was not identified"):
            apply_operations(self.workspace, self.context, [{"op": "add_instance", "name": "tx_0", "module": "uart_tx", "definition_hash": "wrong"}])

    def test_fanout_extends_existing_net_and_disconnect_rejects_orphans(self):
        updated, _ = apply_operations(self.workspace, self.context, [
            {"op": "add_port", "name": "count_out", "port": {"direction": "output", "range": [7, 0]}},
            {"op": "connect", "net": "count_bus", "source": "counter_0.count", "targets": ["@count_out"]}])
        self.assertEqual(updated["nets"]["count_bus"], ["counter_0.count", "compare_0.value", "@count_out"])
        with self.assertRaisesRegex(bdtool.DesignError, "required input is unconnected"):
            apply_operations(self.workspace, self.context, [{"op": "disconnect", "endpoint": "counter_0.count"}])


class DesignRunTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bd-workflow-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / "examples", self.root / "examples")
        shutil.copytree(ROOT / "src", self.root / "src")
        self.workspace = Workspace(self.root, "examples/counter_compare.json")
        self.context = {"design": json.loads((self.root / "examples/counter_compare.json").read_text(encoding="utf-8")), "base_dir": "examples"}
        self.evidence = [{"id": "user-1", "text": "Set the threshold to 19 and preserve all other connections."}]
        self.run = DesignRun(self.workspace, self.context, self.evidence)
        self.specification = {"schema_version": 1, "requirements": [{"id": "REQ-001", "statement": "Set threshold to 19", "kind": "hard", "status": "confirmed",
            "source": {"message_id": "user-1", "quote": "Set the threshold to 19"}, "acceptance": {"method": "structural", "criteria": "compare_0.THRESHOLD is 19"}}],
            "dimensions": {name: {"value": None, "status": "not_applicable", "evidence": "Parameter-only modification preserves this aspect of the existing design", "blocking_stage": "none"} for name in DIMENSIONS}, "open_questions": []}
        self.plan = {"schema_version": 1, "base_hash": self.run.base_hash,
            "operations": [{"op": "set_parameter", "instance": "compare_0", "parameter": "THRESHOLD", "value": 19, "requirement_ids": ["REQ-001"], "evidence": "user-1 and existing compare_0 metadata"}],
            "checks": {name: {"status": "not_applicable", "evidence": "Existing topology is preserved; no new protocol, clock, frame or address path"} for name in CHECKS}}

    def test_traced_generation_is_isolated_and_portable(self):
        original = (self.root / "examples/counter_compare.json").read_bytes()
        self.run.requirements(self.specification)
        checked = self.run.plan_changes(self.plan)
        self.assertTrue(checked["valid"])
        self.assertIn("19", checked["diff"])
        result = self.run.generate()
        self.assertTrue(result["run_dir"].startswith("build/copilot/"))
        self.assertEqual((self.root / "examples/counter_compare.json").read_bytes(), original)
        portable = bdtool.load_design(self.root / result["design_path"])
        self.assertEqual(portable.instances["compare_0"].parameters["THRESHOLD"], 19)
        self.assertEqual(result["verification"]["functional_simulation"], "not_run")
        for folder in ("catalog", "requirements", "plans", "generated", "verification"):
            self.assertTrue((self.run.directory / folder).is_dir())
        state = json.loads((self.run.directory / "run_state.json").read_text())
        self.assertEqual(state["last_passed_stage"], "generated")
        self.assertEqual(self.run.generate(), result)

    def test_unquoted_requirements_and_unknowns_cannot_be_faked(self):
        bad = copy.deepcopy(self.specification)
        bad["requirements"][0]["source"]["quote"] = "Invented user instruction"
        with self.assertRaisesRegex(WorkflowError, "not present"):
            self.run.requirements(bad)
        bad = copy.deepcopy(self.specification)
        bad["dimensions"]["precision"] = {"value": None, "status": "unknown", "evidence": "Numeric format is missing", "blocking_stage": "build"}
        result = self.run.requirements(bad)
        self.assertTrue(result["blockers"])
        with self.assertRaisesRegex(WorkflowError, "Unresolved"):
            self.run.plan_changes(self.plan)
        self.assertFalse((self.run.directory / "generated/example_bd.v").exists())

    def test_untraced_operations_and_unreviewed_checks_are_rejected(self):
        self.run.requirements(self.specification)
        bad = copy.deepcopy(self.plan)
        bad["operations"][0]["requirement_ids"] = ["invented"]
        with self.assertRaisesRegex(WorkflowError, "requirement_ids"):
            self.run.plan_changes(bad)
        bad = copy.deepcopy(self.plan)
        bad["checks"]["cdc"]["status"] = "pending"
        with self.assertRaisesRegex(WorkflowError, "planning obligation"):
            self.run.plan_changes(bad)

    def test_repair_limit_and_stale_source_guard(self):
        self.run.requirements(self.specification)
        bad = copy.deepcopy(self.plan)
        bad["base_hash"] = "stale"
        for attempt in range(3):
            with self.assertRaisesRegex(WorkflowError, "base design hash"):
                self.run.plan_changes(bad)
        with self.assertRaisesRegex(WorkflowError, "three-attempt"):
            self.run.plan_changes(self.plan)
        another = DesignRun(self.workspace, self.context, self.evidence)
        another.requirements(self.specification)
        another.plan_changes(self.plan)
        source = self.root / "examples/rtl/counter.v"
        source.write_text(source.read_text() + "\n", encoding="utf-8")
        with self.assertRaisesRegex(WorkflowError, "inputs changed"):
            another.generate()

    def test_skill_is_present_and_backend_specific(self):
        skill = workflow_instructions()
        self.assertTrue(skill.startswith("---\nname: build-bd-design\n"))
        self.assertIn("description:", skill)
        self.assertIn("bd_generate", skill)
        self.assertIn("not_run", skill)

    def test_existing_output_directory_is_never_overwritten(self):
        self.run.directory.mkdir(parents=True)
        sentinel = self.run.directory / "keep.txt"
        sentinel.write_text("existing work", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.run.requirements(self.specification)
        self.assertEqual(sentinel.read_text(), "existing work")
        with self.assertRaisesRegex(WorkflowError, "Record a traced specification"):
            self.run.plan_changes(self.plan)

    def test_performance_numbers_require_conditions_and_units(self):
        bad = copy.deepcopy(self.specification)
        bad["dimensions"]["rate"] = {"value": 100, "status": "confirmed", "evidence": "User target", "blocking_stage": "verify"}
        with self.assertRaises(bdtool.DesignError):
            self.run.requirements(bad)
        bad["dimensions"]["rate"]["value"] = {"amount": 100, "unit": "MS/s", "basis": "target", "conditions": "one sample per cycle, no stalls, 100 MHz target clock"}
        self.assertFalse(self.run.requirements(bad)["blockers"])

    @unittest.skipUnless(shutil.which("iverilog"), "iverilog is required for workflow RTL compilation")
    def test_catalog_ip_selection_connections_and_generated_rtl_compile(self):
        evidence = [{"id": "user-1", "text": "Add an 8-bit priority encoder with request input, encoded output and valid output; preserve the existing design."}]
        run = DesignRun(self.workspace, self.context, evidence)
        specification = copy.deepcopy(self.specification)
        requirement = specification["requirements"][0]
        requirement.update(statement="Add an 8-bit priority encoder", source={"message_id": "user-1", "quote": evidence[0]["text"]},
                           acceptance={"method": "structural", "criteria": "priority_0 exposes an 8-bit request, 3-bit index and scalar valid"})
        for name in DIMENSIONS:
            specification["dimensions"][name]["evidence"] = "Existing design is preserved; new priority encoder is combinational, without protocol sidebands, clock, reset or address space"
        run.requirements(specification)
        trace = {"requirement_ids": ["REQ-001"], "evidence": "user-1 plus priority_encoder definition and source hashes from the catalog"}
        operations = [
            {**trace, "op": "add_instance", "name": "priority_0", "module": "priority_encoder", "definition_hash": run.catalog["modules"]["priority_encoder"]["definition_hash"], "parameters": {"WIDTH": 8}},
            {**trace, "op": "add_port", "name": "requests", "port": {"direction": "input", "range": [7, 0]}},
            {**trace, "op": "add_port", "name": "priority_index", "port": {"direction": "output", "range": [2, 0]}},
            {**trace, "op": "add_port", "name": "priority_valid", "port": {"direction": "output"}},
            {**trace, "op": "connect", "net": "requests_net", "source": "@requests", "targets": ["priority_0.input_unencoded"]},
            {**trace, "op": "connect", "net": "index_net", "source": "priority_0.output_encoded", "targets": ["@priority_index"]},
            {**trace, "op": "connect", "net": "valid_net", "source": "priority_0.output_valid", "targets": ["@priority_valid"]},
        ]
        plan = copy.deepcopy(self.plan)
        plan.update(base_hash=run.base_hash, operations=operations)
        for name in CHECKS:
            plan["checks"][name]["evidence"] = "Combinational IP, exact declared ranges, original topology preserved; no new clocked or framed interface"
        plan["checks"]["coverage"]["status"] = "pass"
        plan["checks"]["semantics"]["status"] = "pass"
        run.plan_changes(plan)
        result = run.generate()
        portable = bdtool.load_design(self.root / result["design_path"])
        self.assertEqual(portable.instances["priority_0"].module, "priority_encoder")
        for name, net in self.context["design"]["nets"].items():
            self.assertEqual(run.candidate["nets"][name], net)
        compiled = subprocess.run([shutil.which("iverilog"), "-g2005", "-Wportbind", "-s", portable.wrapper_name, "-tnull",
            *map(str, portable.sources), *(str(self.root / path) for path in result["files"])], capture_output=True, text=True, timeout=30)
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        self.assertEqual(compiled.stderr, "")

    def test_artifacts_cannot_escape_the_run_directory(self):
        self.run.requirements(self.specification)
        with self.assertRaisesRegex(WorkflowError, "escaped"):
            self.run._json("../outside.json", {})


if __name__ == "__main__":
    unittest.main()