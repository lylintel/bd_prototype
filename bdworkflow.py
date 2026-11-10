"""Deterministic, workspace-scoped design operations for the Copilot workflow."""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import math
import os
from pathlib import Path
from uuid import UUID, uuid4

import bdtool


class WorkflowError(ValueError):
    pass


DIMENSIONS = ("inputs", "outputs", "algorithm", "precision", "rate", "frames", "backpressure", "latency", "control", "address", "interrupts", "platform", "acceptance")
CHECKS = ("coverage", "semantics", "cdc", "reset", "framing", "backpressure", "addressability", "interrupts", "initialization", "performance")
SKILL_DIR = Path(__file__).resolve().parent / ".github" / "skills" / "build-bd-design"


def workflow_instructions():
    return (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


def read_catalog(workspace, context):
    base = workspace.path(context["base_dir"])
    current = copy.deepcopy(context["design"]["modules"])
    path = workspace.path("src/ip_catalog.json")
    imported = {}
    if path.is_file():
        document = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=bdtool._unique_keys)
        workspace.sources(document, path.parent)
        bdtool.validate_design(document, path.parent)
        imported = copy.deepcopy(document["modules"])
        for definition in imported.values():
            definition["sources"] = [Path(os.path.relpath((path.parent / source).resolve(), base)).as_posix() for source in definition["sources"]]
    modules = {**imported, **current}
    entries = {}
    for name, definition in modules.items():
        sources = workspace.sources({"modules": {name: definition}}, base)
        entries[name] = {
            "definition": definition,
            "origin": "current_design" if name in current else "src/ip_catalog.json",
            "definition_hash": fingerprint(definition),
            "source_hashes": {workspace.relative(source): hashlib.sha256(source.read_bytes()).hexdigest() for source in sorted(sources)},
        }
    references = {}
    for relative in ("src/README.md", "src/UPSTREAM.json"):
        source = workspace.path(relative)
        if source.is_file():
            references[relative] = {"sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "text": source.read_text(encoding="utf-8")}
    return {"backend": "bdtool", "modules": entries, "references": references,
            "conflicts": [name for name in imported if name in current and imported[name] != current[name]],
            "limits": ["input/output only", "exact ranges and signedness", "no implicit adapters", "no Vivado or hardware execution"]}


def _endpoint(data, value):
    if not isinstance(value, str):
        raise WorkflowError("Endpoint must be a string.")
    if value.startswith("@"):
        name = value[1:]
        spec = data["ports"].get(name)
        if spec is not None:
            return spec["direction"] == "input"
    else:
        instance, dot, port = value.partition(".")
        if dot and instance in data["instances"]:
            module = data["instances"][instance]["module"]
            spec = data["modules"][module]["ports"].get(port)
            if spec is not None:
                return spec["direction"] == "output"
    raise WorkflowError(f"Unknown endpoint: {value}")


def _disconnect(data, endpoint):
    drives = _endpoint(data, endpoint)
    for name, endpoints in list(data["nets"].items()):
        if endpoint in endpoints:
            remaining = [item for item in endpoints if item != endpoint]
            if drives or len(remaining) < 2:
                del data["nets"][name]
            else:
                data["nets"][name] = remaining


def _claim(data, name):
    bdtool._name(name, "operation.name")
    if any(name in data[section] for section in ("instances", "ports", "nets")):
        raise WorkflowError(f"Name already exists: {name}")


def apply_operations(workspace, context, operations):
    if not isinstance(operations, list) or not operations or len(operations) > 100:
        raise WorkflowError("Plan requires 1 to 100 explicit operations.")
    data = copy.deepcopy(context["design"])
    catalog = read_catalog(workspace, context)["modules"]
    for index, operation in enumerate(operations):
        item = bdtool._object(operation, f"operations[{index}]")
        kind = item.get("op")
        if kind == "add_instance":
            _claim(data, item["name"])
            module = item["module"]
            if module not in catalog:
                raise WorkflowError(f"Module is not in the authorized catalog: {module}")
            definition = catalog[module]
            if item.get("definition_hash") != definition["definition_hash"]:
                raise WorkflowError(f"Catalog definition changed or was not identified: {module}")
            data["modules"].setdefault(module, copy.deepcopy(definition["definition"]))
            data["instances"][item["name"]] = {"module": module, "parameters": copy.deepcopy(item.get("parameters", {}))}
        elif kind == "set_parameter":
            instance = data["instances"].get(item["instance"])
            if instance is None:
                raise WorkflowError(f"Unknown instance: {item['instance']}")
            instance.setdefault("parameters", {})[item["parameter"]] = item["value"]
        elif kind == "add_port":
            _claim(data, item["name"])
            bdtool._ports({item["name"]: item["port"]}, {}, "operation.ports")
            data["ports"][item["name"]] = copy.deepcopy(item["port"])
        elif kind == "connect":
            source = item["source"]
            targets = item["targets"]
            if not isinstance(targets, list) or not targets:
                raise WorkflowError("A connection requires at least one target.")
            if not _endpoint(data, source) or any(_endpoint(data, target) for target in targets):
                raise WorkflowError("Connections require one driver and only sink targets.")
            existing = next((name for name, pins in data["nets"].items() if source in pins), None)
            name = item["net"]
            if existing and existing != name:
                raise WorkflowError(f"Driver already belongs to {existing}; extend that net instead.")
            if name in data["nets"]:
                if source not in data["nets"][name]:
                    raise WorkflowError(f"Cannot add another driver to {name}.")
            else:
                _claim(data, name)
                data["nets"][name] = [source]
            for target in targets:
                attached = next((net for net, pins in data["nets"].items() if target in pins), None)
                if attached and attached != name:
                    raise WorkflowError(f"{target} is already connected to {attached}.")
                if target not in data["nets"][name]:
                    data["nets"][name].append(target)
        elif kind == "disconnect":
            _disconnect(data, item["endpoint"])
        elif kind == "remove_instance":
            name = item["name"]
            if name not in data["instances"]:
                raise WorkflowError(f"Unknown instance: {name}")
            module = data["instances"][name]["module"]
            for port in data["modules"][module]["ports"]:
                _disconnect(data, f"{name}.{port}")
            del data["instances"][name]
        elif kind == "remove_port":
            _disconnect(data, f"@{item['name']}")
            del data["ports"][item["name"]]
        elif kind == "rename_design":
            data["name"] = bdtool._name(item["name"], "design.name")
        else:
            raise WorkflowError(f"Unsupported design operation: {kind}")
    workspace.sources(data, workspace.path(context["base_dir"]))
    resolved = bdtool.validate_design(data, workspace.path(context["base_dir"]))
    return data, bdtool.render_verilog(resolved)


def _text(value, where):
    if not isinstance(value, str) or not value.strip():
        raise WorkflowError(f"{where}: expected nonempty text")
    return value


def validate_specification(specification, evidence):
    spec = bdtool._fields(specification, "specification", {"schema_version", "requirements", "dimensions", "open_questions"})
    if spec["schema_version"] != 1:
        raise WorkflowError("specification.schema_version must be 1")
    requirements = spec["requirements"]
    if not isinstance(requirements, list) or not requirements or len(requirements) > 50:
        raise WorkflowError("specification requires 1 to 50 requirements")
    messages = {item["id"]: item["text"] for item in evidence}
    ids = set()
    blockers = []
    for raw in requirements:
        requirement = bdtool._fields(raw, "requirement", {"id", "statement", "kind", "status", "source", "acceptance"})
        identifier = _text(requirement["id"], "requirement.id")
        if identifier in ids:
            raise WorkflowError(f"Duplicate requirement ID: {identifier}")
        ids.add(identifier)
        _text(requirement["statement"], f"{identifier}.statement")
        if requirement["kind"] not in ("hard", "objective") or requirement["status"] not in ("confirmed", "assumed", "unknown"):
            raise WorkflowError(f"{identifier}: invalid requirement kind/status")
        source = bdtool._fields(requirement["source"], f"{identifier}.source", {"message_id", "quote"})
        quote = _text(source["quote"], f"{identifier}.source.quote")
        if source["message_id"] not in messages or quote not in messages[source["message_id"]]:
            raise WorkflowError(f"{identifier}: evidence quote is not present in the cited user message")
        acceptance = bdtool._fields(requirement["acceptance"], f"{identifier}.acceptance", {"method", "criteria"})
        if acceptance["method"] not in ("structural", "review", "simulation", "formal", "timing", "vivado", "hardware"):
            raise WorkflowError(f"{identifier}: unsupported acceptance method")
        _text(acceptance["criteria"], f"{identifier}.acceptance.criteria")
        if requirement["kind"] == "hard" and requirement["status"] != "confirmed":
            blockers.append(f"{identifier}: hard requirement is {requirement['status']}")
    dimensions = bdtool._fields(spec["dimensions"], "dimensions", set(DIMENSIONS))
    for name, raw in dimensions.items():
        dimension = bdtool._fields(raw, f"dimensions.{name}", {"value", "status", "evidence", "blocking_stage"})
        if dimension["status"] not in ("confirmed", "assumed", "unknown", "not_applicable"):
            raise WorkflowError(f"dimensions.{name}: invalid status")
        if dimension["blocking_stage"] not in ("none", "plan", "build", "verify"):
            raise WorkflowError(f"dimensions.{name}: invalid blocking_stage")
        _text(dimension["evidence"], f"dimensions.{name}.evidence")
        if dimension["status"] == "unknown" and dimension["value"] is not None:
            raise WorkflowError(f"dimensions.{name}: unknown values must remain null")
        if dimension["status"] == "confirmed" and dimension["value"] is None:
            raise WorkflowError(f"dimensions.{name}: confirmed value is missing")
        if name in ("rate", "latency") and dimension["status"] in ("confirmed", "assumed"):
            performance = bdtool._fields(dimension["value"], f"dimensions.{name}.value", {"amount", "unit", "basis", "conditions"})
            amount = performance["amount"]
            if type(amount) not in (int, float) or not math.isfinite(amount) or amount < 0:
                raise WorkflowError(f"dimensions.{name}: performance amount must be a finite nonnegative number")
            if performance["basis"] not in ("target", "estimate", "measurement"):
                raise WorkflowError(f"dimensions.{name}: specify target, estimate or measurement")
            _text(performance["unit"], f"dimensions.{name}.unit")
            _text(performance["conditions"], f"dimensions.{name}.conditions")
        if dimension["status"] in ("unknown", "assumed") and dimension["blocking_stage"] in ("plan", "build"):
            blockers.append(f"dimensions.{name}: {dimension['status']} blocks {dimension['blocking_stage']}")
    questions = spec["open_questions"]
    if not isinstance(questions, list) or len(questions) > 30:
        raise WorkflowError("open_questions must be a list of at most 30 questions")
    question_ids = set()
    for raw in questions:
        question = bdtool._fields(raw, "question", {"id", "question", "impact", "alternatives", "blocking_stage", "status", "requirement_ids"})
        identifier = _text(question["id"], "question.id")
        if identifier in question_ids:
            raise WorkflowError(f"Duplicate question ID: {identifier}")
        question_ids.add(identifier)
        for key in ("question", "impact"):
            _text(question[key], f"question.{key}")
        if not isinstance(question["alternatives"], list) or any(not isinstance(item, str) for item in question["alternatives"]):
            raise WorkflowError("question.alternatives must be text options")
        if question["status"] not in ("open", "resolved") or question["blocking_stage"] not in ("none", "plan", "build", "verify"):
            raise WorkflowError("question: invalid status or blocking_stage")
        _requirement_refs(question["requirement_ids"], ids)
        if question["status"] == "open" and question["blocking_stage"] in ("plan", "build"):
            blockers.append(f"{identifier}: {question['question']}")
    return copy.deepcopy(spec), blockers


def _requirement_refs(value, known):
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or item not in known for item in value):
        raise WorkflowError("Each operation/question must cite known requirement_ids")


class DesignRun:
    def __init__(self, workspace, context, evidence, run_id=None):
        self.workspace = workspace
        self.context = copy.deepcopy(context)
        self.base_design = copy.deepcopy(context["design"])
        self.base_hash = fingerprint(self.base_design)
        self.evidence = copy.deepcopy(evidence)
        self.id = str(UUID(run_id)) if run_id else str(uuid4())
        self.directory = workspace.path(f"build/copilot/{self.id}")
        if not self.directory.is_relative_to(workspace.root / "build" / "copilot"):
            raise WorkflowError("Workflow outputs must remain under build/copilot, without redirected parents.")
        self.catalog = read_catalog(workspace, self.context)
        self.specification = None
        self.blockers = []
        self.plan = None
        self.candidate = None
        self.attempts = 0
        self.generated = None
        self.last_stage = "inventory"
        self._initialized = False

    def _ensure_output(self):
        if self._initialized:
            return
        self.directory.mkdir(parents=True, exist_ok=False)
        for folder in ("catalog", "requirements", "plans", "generated", "verification"):
            (self.directory / folder).mkdir()
        self._initialized = True
        self._json("catalog/ip_catalog.json", self.catalog)
        self._json("requirements/user_evidence.json", self.evidence)
        self._json("plans/base_design.json", self.base_design)

    def _json(self, relative, value):
        path = self.workspace.path(self.workspace.relative(self.directory / relative))
        if not path.is_relative_to(self.directory):
            raise WorkflowError("Workflow artifact escaped its isolated run directory.")
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _state(self, status):
        self._json("run_state.json", {"schema_version": 1, "backend": "bdtool", "run_id": self.id,
            "status": status, "last_passed_stage": self.last_stage, "plan_attempts": self.attempts,
            "input_hashes": {"base_design": self.base_hash, "catalog": fingerprint(self.catalog),
                "requirements": fingerprint(self.specification) if self.specification else None,
                "plan": fingerprint(self.plan) if self.plan else None},
            "dependencies": {"plan": ["base_design", "catalog", "requirements"], "generated": ["plan"]},
            "blockers": self.blockers, "original_base_dir": self.context["base_dir"]})

    def requirements(self, specification):
        if self.generated:
            raise WorkflowError("This run is finalized; start a new user turn for further changes.")
        specification, blockers = validate_specification(specification, self.evidence)
        self._ensure_output()
        self.specification, self.blockers = specification, blockers
        self.plan = None
        self.candidate = None
        self._json("requirements/specification.json", self.specification)
        self._json("requirements/open_questions.json", self.specification["open_questions"])
        self.last_stage = "requirements_recorded"
        self._state("blocked" if self.blockers else "requirements_ready")
        return {"run_dir": self.workspace.relative(self.directory), "blockers": self.blockers,
                "next_questions": [item for item in self.specification["open_questions"] if item["status"] == "open"][:3]}

    def plan_changes(self, plan):
        if self.generated:
            raise WorkflowError("This run is finalized; start a new user turn for further changes.")
        if self.specification is None:
            raise WorkflowError("Record a traced specification before planning changes.")
        if self.attempts >= 3:
            raise WorkflowError("The three-attempt repair limit was reached; report the blocker to the user.")
        self.attempts += 1
        self.plan = None
        self.candidate = None
        try:
            candidate_plan = bdtool._fields(plan, "plan", {"schema_version", "base_hash", "operations", "checks"})
            if candidate_plan["schema_version"] != 1 or candidate_plan["base_hash"] != self.base_hash:
                raise WorkflowError("Plan version or base design hash does not match this run.")
            if self.blockers:
                raise WorkflowError("Unresolved specification blockers: " + "; ".join(self.blockers))
            if fingerprint(read_catalog(self.workspace, self.context)) != fingerprint(self.catalog):
                raise WorkflowError("Catalog/source inputs changed; start a new user turn before replanning.")
            requirements = {item["id"]: item for item in self.specification["requirements"]}
            covered = set()
            for operation in candidate_plan["operations"]:
                _requirement_refs(operation.get("requirement_ids"), requirements)
                _text(operation.get("evidence"), "operation.evidence")
                covered.update(operation["requirement_ids"])
            missing = [identifier for identifier, item in requirements.items() if item["kind"] == "hard" and identifier not in covered]
            if missing:
                raise WorkflowError("Hard requirements are not traced to the plan: " + ", ".join(missing))
            checks = bdtool._fields(candidate_plan["checks"], "plan.checks", set(CHECKS))
            for name, check in checks.items():
                bdtool._fields(check, f"checks.{name}", {"status", "evidence"})
                if check["status"] not in ("pass", "not_applicable", "pending", "fail"):
                    raise WorkflowError(f"checks.{name}: invalid status")
                _text(check["evidence"], f"checks.{name}.evidence")
                if check["status"] in ("pending", "fail"):
                    raise WorkflowError(f"checks.{name}: planning obligation is {check['status']}")
            self.candidate, _ = apply_operations(self.workspace, self.context, candidate_plan["operations"])
            self.plan = copy.deepcopy(candidate_plan)
            self._json("plans/plan.json", self.plan)
            self._json("plans/candidate.json", self.candidate)
            self._json("requirements/traceability.json", [{**item, "operation_indexes": [index for index, operation in enumerate(self.plan["operations"]) if item["id"] in operation["requirement_ids"]], "verification": "not_run"} for item in self.specification["requirements"]])
            diff = "".join(difflib.unified_diff(
                (json.dumps(self.base_design, indent=2, sort_keys=True) + "\n").splitlines(keepends=True),
                (json.dumps(self.candidate, indent=2, sort_keys=True) + "\n").splitlines(keepends=True),
                fromfile="original_design.json", tofile="planned_design.json"))
            (self.directory / "plans" / "design.diff").write_text(diff, encoding="utf-8")
            self._json("verification/preflight.json", {"structural": "pass", "requirement_trace": "pass",
                "planning_review": checks, "review_is_not_execution_evidence": True})
            self.last_stage = "plan_preflight"
            self._state("ready_for_generation")
            return {"valid": True, "base_hash": self.base_hash, "plan_hash": fingerprint(self.plan),
                    "diff": diff, "run_dir": self.workspace.relative(self.directory)}
        except (WorkflowError, bdtool.DesignError, KeyError, TypeError) as exc:
            self._json("verification/preflight.json", {"structural": "fail", "diagnostic": str(exc), "attempt": self.attempts})
            self._state("plan_failed")
            raise WorkflowError(str(exc)) from exc

    def generate(self):
        if self.generated:
            return copy.deepcopy(self.generated)
        if self.plan is None or self.candidate is None or self.blockers:
            raise WorkflowError("A traced, valid, unblocked plan is required before generation.")
        if fingerprint(read_catalog(self.workspace, self.context)) != fingerprint(self.catalog):
            raise WorkflowError("Catalog/source inputs changed after preflight; refuse stale generation.")
        base = self.workspace.path(self.context["base_dir"])
        resolved = bdtool.validate_design(self.candidate, base)
        files = bdtool.render_verilog(resolved)
        generated_dir = self.directory / "generated"
        portable = copy.deepcopy(self.candidate)
        for definition in portable["modules"].values():
            definition["sources"] = [Path(os.path.relpath((base / source).resolve(), generated_dir)).as_posix() for source in definition["sources"]]
        self._json("generated/design.json", portable)
        bdtool._write_outputs(files, generated_dir, set(resolved.sources))
        report = {"structure": "pass", "rtl_compile": "not_run", "functional_simulation": "not_run",
                  "formal": "not_run", "vivado": "not_run", "synthesis": "not_run", "cdc": "not_run", "timing": "not_run", "hardware": "not_run"}
        self._json("verification/results.json", report)
        self.last_stage = "generated"
        self._state("generated_unverified")
        self.generated = {"run_dir": self.workspace.relative(self.directory), "design_path": self.workspace.relative(generated_dir / "design.json"),
            "files": [self.workspace.relative(generated_dir / name) for name in files], "verification": report,
            "diff": (self.directory / "plans" / "design.diff").read_text(encoding="utf-8")}
        return copy.deepcopy(self.generated)

    def read_source(self, module):
        entry = self.catalog["modules"].get(module)
        if entry is None:
            raise WorkflowError("Only modules in the authorized catalog may be read.")
        result = {}
        for relative, digest in entry["source_hashes"].items():
            path = self.workspace.path(relative)
            if path.suffix.lower() not in (".v", ".sv", ".vh", ".svh") or path.stat().st_size > 100000:
                raise WorkflowError("Only registered RTL source files up to 100 KB may be read.")
            if any(part in (".venv", ".git", "node_modules") for part in path.relative_to(self.workspace.root).parts):
                raise WorkflowError("Dependency and configuration directories are not authorized RTL sources.")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise WorkflowError("Source changed since catalog capture.")
            result[relative] = {"sha256": digest, "text": path.read_text(encoding="utf-8")}
        return result