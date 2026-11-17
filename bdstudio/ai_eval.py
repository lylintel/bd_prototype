import argparse
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform

import yaml

from ai.client import ClientConfig, OpenAIClient, ReplayClient
from ai.pipeline import SYSTEM, run_pipeline
from bdip import load_ip, migrate_legacy_modules
from core.design import migrate
from core.expr import MESSAGES
from core.resolve import endpoint_text, resolve
from core.semantic import validate


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests/ai_eval/cases.yaml"
REPLAYS = ROOT / "tests/ai_eval/replays.json"
CONVENTIONS = "实例名使用 IP ID。未指定参数采用卡片默认值。未连接的端口全部逐信号引出，外部名为实例名_端口名；时钟复位也分别引出。仅基本计数比较案例的外部名为 clk/rst/match；已有设计保持实例名和连线。计数事件链使用 rising 脉冲；比较数据接 left_data；FIFO 与切片间连接 data/valid/ready，切片 m_data 接 input0。"


def _key(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _f1(expected, actual):
    expected, actual = {_key(item) for item in expected}, {_key(item) for item in actual}
    return 2 * len(expected & actual) / (len(expected) + len(actual)) if expected or actual else 1.0


def score_case(expected, actual, *, valid, forbidden):
    diff = {field: {"expected": expected.get(field), "actual": actual.get(field)}
            for field in ("instances", "connections", "params", "ports", "missing_ip", "questions")
            if _key(expected.get(field)) != _key(actual.get(field))}
    return {"valid": valid, "instance_f1": _f1(expected["instances"], actual["instances"]),
            "connection_f1": _f1(expected["connections"], actual["connections"]),
            "exact_match": not diff and not forbidden,
            "missing_ip_correct": bool(expected.get("missing_ip")) == bool(actual.get("missing_ip")),
            "forbidden": forbidden, "diff": diff}


def catalog():
    bundled = tuple(load_ip(path) for path in sorted((ROOT / "ip_library/builtin").glob("*/1.0.0/ip.json")))
    legacy = json.loads((ROOT / "examples/counter_compare.json").read_text(encoding="utf-8"))
    return (*bundled, *migrate_legacy_modules(legacy, ROOT / "examples", workspace_root=ROOT).values())


def baseline(case, library):
    if case.get("baseline") == "counter_compare":
        return migrate(json.loads((ROOT / "examples/counter_compare.json").read_text(encoding="utf-8")), library)
    return {"schema_version": 3, "name": "evaluation_bd", "instances": [], "ports": {}, "nets": []}


def fixture_endpoint(value):
    if isinstance(value, dict):
        return deepcopy(value)
    if value.startswith("@"):
        return {"ext": value[1:]}
    instance, port = value.split(".")
    return {"inst": instance, "port": port}


def _leaves(endpoint):
    if "concat" in endpoint:
        return [leaf for item in endpoint["concat"] for leaf in _leaves(item)]
    return [f'{endpoint["inst"]}.{endpoint["port"]}'] if "inst" in endpoint else []


def expected_document(case, library):
    specification = case["expect"]
    document = baseline(case, library)
    if specification.get("preserve_baseline"):
        for key, value in specification.get("params", {}).items():
            name, parameter = key.split(".")
            next(item for item in document["instances"] if item["name"] == name)["params"][parameter] = value
        return document
    document["instances"] = [{"name": name, "ip": {"id": name, "version": "1.0.0"}, "params": params}
                             for name, params in specification["instances"].items()]
    document["ports"] = deepcopy(specification.get("ports", {}))
    connections = [[fixture_endpoint(item) for item in pair] for pair in specification["connections"]]
    used = {name for pair in connections for endpoint in pair for name in _leaves(endpoint)}
    for name, instance in resolve(document, library).instances.items():
        for port, shape in instance.ports.items():
            if f"{name}.{port}" in used:
                continue
            external = f"{name}_{port}"
            document["ports"][external] = {"direction": shape.direction, "signed": shape.signed,
                                            **({"range": list(shape.bounds)} if shape.bounds is not None else {})}
            pair = [{"ext": external}, {"inst": name, "port": port}]
            connections.append(pair if shape.direction == "input" else pair[::-1])
    groups = {}
    for source, target in connections:
        group = groups.setdefault(_key(source), [source])
        if target not in group:
            group.append(target)
    document["nets"] = [{"name": f"expected_{index}", "endpoints": endpoints} for index, endpoints in enumerate(groups.values())]
    return document


def normalized(document, library, *, missing_ip=False, questions=False):
    resolved = resolve(document, library)
    return {"instances": sorted([[item["name"], item["ip"]["id"], item["ip"]["version"]] for item in document["instances"]]),
            "connections": sorted([[endpoint_text(driver.raw), endpoint_text(sink.raw)] for net in resolved.nets for driver in net.drivers for sink in net.sinks]),
            "params": {f"{name}.{parameter}": value for name, item in resolved.instances.items() for parameter, value in item.parameters.items()},
            "ports": {name: {"dir": shape.direction, "width": shape.width, "signed": shape.signed, "range": shape.bounds}
                      for name, shape in resolved.ports.items()}, "missing_ip": missing_ip, "questions": questions}


def evaluate_cases(cases, library, client_factory):
    results = []
    for case in cases:
        local = tuple(replace(item, description=case["metadata_injection"]) if case.get("metadata_injection") and item.id == "counter" else item for item in library)
        expected = expected_document(case, local)
        errors = [item for item in validate(expected, local) if item.severity == "error"]
        if errors:
            raise ValueError(f"Invalid expectation {case['id']}: {[item.code for item in errors]}")
        desired = normalized(expected, local, missing_ip=bool(case["expect"].get("missing_ip")), questions=bool(case["expect"].get("questions")))
        outcome = run_pipeline(baseline(case, local), local, case["prompt"] + "\n" + CONVENTIONS, client_factory(case))
        observed = normalized(outcome["document"], local, missing_ip=bool(outcome["missing_ip"]), questions=bool(outcome["questions"]))
        forbidden = [item["op"] for item in outcome["ops"] if item["op"] in case["expect"].get("must_not", [])]
        scored = score_case(desired, observed, valid=outcome["validation"]["valid"], forbidden=forbidden)
        blocked = desired["missing_ip"] or desired["questions"]
        scored["passed"] = scored["exact_match"] and (not scored["valid"] if blocked else scored["valid"])
        required = set(case["expect"]["ips"])
        scored["retrieval_hit"] = required <= {item["id"] for item in outcome["retrieved"]} if required else None
        results.append({"id": case["id"], "tier": case["tier"], "attempts": outcome["attempts"], **scored,
                        "diagnostics": outcome["validation"]["diagnostics"], "trace": outcome["trace"]})
    eligible = [item for item in results if item["tier"] != "trap"]
    hits = [item["retrieval_hit"] for item in results if item["retrieval_hit"] is not None]
    mean = lambda field: sum(item[field] for item in results) / len(results)
    metrics = {"validation_pass_rate": mean("valid"), "instance_f1": mean("instance_f1"), "connection_f1": mean("connection_f1"),
               "exact_match_rate": mean("exact_match"), "missing_ip_accuracy": mean("missing_ip_correct"),
               "simple_medium_pass_rate": sum(item["passed"] for item in eligible) / len(eligible),
               "retrieval_top8_hit_rate": sum(hits) / len(hits) if hits else 1.0}
    return {"schema_version": 1, "count": len(results), "metrics": metrics, "cases": results}


def load_cases(path=CASES):
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = document["cases"]
    if document["schema_version"] != 1 or len(cases) != 20 or len({item["id"] for item in cases}) != 20:
        raise ValueError("Expected 20 unique version-1 cases")
    return cases


def write_report(report, folder, previous=None):
    folder.mkdir(parents=True, exist_ok=True)
    if previous is not None:
        prior = {item["id"]: item for item in previous["cases"]}
        report["comparison"] = {"metrics_delta": {key: value - previous["metrics"][key] for key, value in report["metrics"].items()},
                                "regressions": [item["id"] for item in report["cases"] if prior.get(item["id"], {}).get("passed") and not item["passed"]]}
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# " + MESSAGES["AI_EVAL_TITLE"], "", MESSAGES["AI_EVAL_SCOPE"].format(client=report['client'], count=report['count']), "",
             "| Metric | Score |", "|---|---:|", *[f"| {key} | {value:.4f} |" for key, value in report["metrics"].items()], "",
             "| Case | Pass | Valid | Instance F1 | Connection F1 | Attempts |", "|---|---|---|---:|---:|---:|"]
    lines.extend(f"| {item['id']} | {item['passed']} | {item['valid']} | {item['instance_f1']:.3f} | {item['connection_f1']:.3f} | {item['attempts']} |" for item in report["cases"])
    for item in report["cases"]:
        if not item["passed"]:
            lines.extend(["", f"## {item['id']}", "", "```json", json.dumps({"diff": item["diff"], "diagnostics": item["diagnostics"], "forbidden": item["forbidden"]}, ensure_ascii=False, indent=2), "```"])
    if "comparison" in report:
        lines.extend(["", "## Comparison", "", "```json", json.dumps(report["comparison"], ensure_ascii=False, indent=2), "```"])
    (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=MESSAGES["AI_EVAL_DESCRIPTION"])
    parser.add_argument("--client", choices=("mock", "real"), default="mock")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args(argv)
    if args.client == "real" and not args.allow_network:
        parser.error(MESSAGES["AI_EVAL_NETWORK_REQUIRED"])
    cases = load_cases()
    recordings = json.loads(REPLAYS.read_text(encoding="utf-8"))
    if set(recordings) != {item["id"] for item in cases}:
        raise ValueError("Every case requires an independent recording")
    if args.client == "mock":
        factory = lambda case: ReplayClient(recordings[case["id"]])
        model = "offline-replay"
    else:
        model = os.environ.get("BD_AI_MODEL", "")
        if not model:
            parser.error(MESSAGES["AI_EVAL_MODEL_REQUIRED"])
        config = ClientConfig(base_url=os.environ.get("BD_AI_BASE_URL", "https://api.openai.com/v1"), model=model,
                              api_key=os.environ.get("BD_AI_API_KEY", ""))
        factory = lambda case: OpenAIClient(config)
    report = evaluate_cases(cases, catalog(), factory)
    report.update(client=args.client, model=model, python=platform.python_version(), created=datetime.now(timezone.utc).isoformat(),
                  cases_sha256=hashlib.sha256(CASES.read_bytes()).hexdigest(), replays_sha256=hashlib.sha256(REPLAYS.read_bytes()).hexdigest(),
                  prompt_sha256=hashlib.sha256((SYSTEM + CONVENTIONS).encode()).hexdigest())
    previous = json.loads(args.compare.read_text(encoding="utf-8")) if args.compare else None
    write_report(report, args.report, previous)
    print(json.dumps({"count": report["count"], "metrics": report["metrics"]}, ensure_ascii=False))
    return 0 if report["metrics"]["simple_medium_pass_rate"] >= 0.8 and all(item["passed"] for item in report["cases"] if item["tier"] == "trap") else 1


if __name__ == "__main__":
    raise SystemExit(main())