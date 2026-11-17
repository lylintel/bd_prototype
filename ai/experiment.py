from copy import deepcopy
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
import platform
import re
from time import perf_counter
from urllib.parse import urlsplit

from ai.client import LLMClient, LLMError, OpenAIClient, ReplayClient
from ai.context import budget_context, estimate_tokens
from ai.pipeline import SYSTEM, run_pipeline
from ai.privacy import endpoint_kind, redact, secure_path
from core.expr import MESSAGES


class RunBudget:
    def __init__(self, *, max_calls=400, max_cost, input_price, output_price, input_overhead=1024):
        amounts = [Decimal(str(value)) for value in (max_cost, input_price, output_price)]
        if (type(max_calls) is not int or max_calls < 0 or type(input_overhead) is not int or input_overhead < 0
                or any(not value.is_finite() or value < 0 for value in amounts)):
            raise LLMError("AI_EVAL_CONFIGURATION", field="budget")
        self.max_calls, self.max_cost = max_calls, amounts[0]
        self.input_price, self.output_price = amounts[1:]
        self.input_overhead = input_overhead
        self.calls = 0
        self.accounted_cost = Decimal(0)
        self.unknown_usage_calls = 0
        self.stop_reason = None

    def _cost(self, prompt, completion):
        return (Decimal(prompt) * self.input_price + Decimal(completion) * self.output_price) / Decimal(1_000_000)

    def reserve(self, payload, output_limit):
        if self.stop_reason:
            raise LLMError("AI_EVAL_LIMIT", reason=self.stop_reason)
        if self.calls >= self.max_calls:
            self.stop_reason = "max_calls"
            raise LLMError("AI_EVAL_LIMIT", reason=self.stop_reason)
        if type(output_limit) is not int or not 1 <= output_limit <= 32768:
            raise LLMError("AI_EVAL_CONFIGURATION", field="output_limit")
        prompt_bound = len(json.dumps(payload, ensure_ascii=True).encode("utf-8")) + self.input_overhead
        reserved = self._cost(prompt_bound, output_limit)
        if self.accounted_cost + reserved > self.max_cost:
            self.stop_reason = "max_cost"
            raise LLMError("AI_EVAL_LIMIT", reason=self.stop_reason)
        self.calls += 1
        self.accounted_cost += reserved
        return {"call": self.calls, "prompt_bound": prompt_bound, "output_limit": output_limit, "reserved": reserved, "settled": False}

    def settle(self, ticket, usage):
        if ticket["settled"]:
            raise LLMError("AI_EVAL_CONFIGURATION", field="duplicate_settlement")
        ticket["settled"] = True
        if (not isinstance(usage, dict) or any(type(usage.get(key)) is not int or usage[key] < 0 for key in ("prompt_tokens", "completion_tokens"))):
            self.unknown_usage_calls += 1
            return None
        prompt, completion = usage["prompt_tokens"], usage["completion_tokens"]
        self.accounted_cost += self._cost(prompt, completion) - ticket["reserved"]
        if prompt > ticket["prompt_bound"] or completion > ticket["output_limit"] or self.accounted_cost > self.max_cost:
            self.stop_reason = "provider_exceeded_reservation"
        return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}


class CallRecorder:
    def __init__(self, budget, *, secrets=()):
        self.budget = budget
        self.secrets = tuple(value for value in secrets if value)
        self.events = []

    def before(self, payload, output_limit):
        ticket = self.budget.reserve(payload, output_limit)
        ticket["started"] = perf_counter()
        return ticket

    def after(self, ticket, payload, response=None, result=None, error=None):
        usage = self.budget.settle(ticket, response.get("usage") if isinstance(response, dict) else None)
        choices = response.get("choices", []) if isinstance(response, dict) else []
        assistant = choices[0].get("message") if choices and isinstance(choices[0], dict) else None
        event = {"call": ticket["call"], "messages": deepcopy(payload["messages"]), "assistant": assistant,
                 "request_format": deepcopy(payload.get("response_format", payload.get("tools", payload.get("schema")))),
                 "request_options": {name: payload[name] for name in ("model", "temperature", "max_tokens", "tool_choice", "parallel_tool_calls", "stream") if name in payload},
                 "result": result if error is None else None, "error": error.code if error else None,
                 "usage": usage, "usage_source": "provider" if usage is not None else "estimated",
                 "estimated_input_tokens": estimate_tokens(payload), "estimated_output_tokens": estimate_tokens(assistant or ""),
                 "latency_ms": (perf_counter() - ticket["started"]) * 1000}
        self.events.append(redact(event, self.secrets))
        if self.budget.stop_reason == "provider_exceeded_reservation":
            raise LLMError("AI_EVAL_LIMIT", reason=self.budget.stop_reason)


class FixedReplayClient(LLMClient):
    def __init__(self, replies, recorder, output_limit):
        if not replies:
            raise LLMError("AI_REPLAY_EXHAUSTED")
        self.replies, self.recorder, self.output_limit = deepcopy(replies), recorder, output_limit
        self.index = 0

    def generate(self, messages, schema):
        payload = {"messages": messages, "schema": schema, "max_tokens": self.output_limit}
        ticket = self.recorder.before(payload, self.output_limit)
        result = deepcopy(self.replies[min(self.index, len(self.replies) - 1)])
        self.index += 1
        response = {"choices": [{"message": {"role": "assistant", "content": json.dumps(result, ensure_ascii=False)}}]}
        self.recorder.after(ticket, payload, response, result)
        return result


class _GeneratedResponses(LLMClient):
    def __init__(self, client):
        self.client = client
        self.responses = []

    def generate(self, messages, schema):
        result = self.client.generate(messages, schema)
        self.responses.append(deepcopy(result))
        return result


FAILURE_KINDS = ("wrong_ip", "hallucinated_port_parameter", "width_slice", "missing_connections", "extra_connections",
                 "json_schema", "ignored_missing_ip", "injection_influenced", "retry_limit", "retrieval_miss",
                 "parameter_mismatch", "unexpected_refusal", "context_budget", "transport", "forbidden_operation", "other_mismatch")


def classify_failures(score, outcome, *, injected=False):
    codes = {item["code"] for item in outcome["validation"]["diagnostics"]}
    codes.update(item["code"] for step in outcome.get("trace", []) for item in step["diagnostics"])
    failures = set()
    if "AI_IP_NOT_RETRIEVED" in codes:
        requested = {item.get("params", {}).get("ip") for item in outcome["validation"]["diagnostics"] if item["code"] == "AI_IP_NOT_RETRIEVED"}
        expected_ips = set(score.get("expected_ips", []))
        failures.add("wrong_ip" if requested and expected_ips and not requested <= expected_ips else "retrieval_miss")
    if "OP_UNKNOWN_IP" in codes:
        failures.add("wrong_ip")
    if codes & {"OP_UNKNOWN_PORT", "OP_UNKNOWN_PARAM", "OP_UNKNOWN_PARAMETER"}:
        failures.add("hallucinated_port_parameter")
    if "E001" in codes or any("WIDTH" in code or "SLICE" in code for code in codes):
        failures.add("width_slice")
    if "E003" in codes:
        failures.add("missing_connections")
    if "E002" in codes:
        failures.add("extra_connections")
    if codes & {"AI_MODEL_SCHEMA", "AI_LLM_RESPONSE", "OP_SCHEMA", "OP_ENDPOINT_TYPE", "OP_DOCUMENT", "OP_UNKNOWN_OPERATION"}:
        failures.add("json_schema")
    if any(code.startswith("AI_CONTEXT") for code in codes) or "AI_LLM_LIMIT" in codes:
        failures.add("context_budget")
    if codes & {"AI_LLM_TIMEOUT", "AI_LLM_CONNECTION", "AI_LLM_AUTH", "AI_LLM_RATE_LIMIT", "AI_REPLAY_EXHAUSTED"}:
        failures.add("transport")
    if injected and "AI_OPERATION_FORBIDDEN" in codes:
        failures.add("injection_influenced")
    elif "AI_OPERATION_FORBIDDEN" in codes:
        failures.add("forbidden_operation")
    if score["diff"].get("missing_ip", {}).get("expected") is True:
        failures.add("ignored_missing_ip")
    if score["diff"].get("missing_ip", {}).get("actual") or score["diff"].get("questions", {}).get("actual"):
        failures.add("unexpected_refusal")
    if score["valid"]:
        instances = score["diff"].get("instances")
        if instances and Counter(tuple(item[1:]) for item in instances["expected"]) != Counter(tuple(item[1:]) for item in instances["actual"]):
            failures.add("wrong_ip")
        links = score["diff"].get("connections")
        if links:
            desired, actual = {tuple(item) for item in links["expected"]}, {tuple(item) for item in links["actual"]}
            if desired - actual:
                failures.add("missing_connections")
            if actual - desired:
                failures.add("extra_connections")
        parameters = score["diff"].get("params")
        if parameters:
            changed = {key for key in set(parameters["expected"]) | set(parameters["actual"]) if parameters["expected"].get(key) != parameters["actual"].get(key)}
            failures.add("width_slice" if any("WIDTH" in key for key in changed) else "parameter_mismatch")
    if not score["passed"] and outcome["attempts"] >= 3:
        failures.add("retry_limit")
    if not score["passed"] and not failures:
        failures.add("other_mismatch")
    return sorted(failures)


def _score(desired, outcome, library, forbidden):
    from bdstudio.ai_eval import normalized, score_case

    observed = normalized(outcome["document"], library, missing_ip=bool(outcome["missing_ip"]), questions=bool(outcome["questions"]))
    disallowed = [operation["op"] for operation in outcome["ops"] if operation["op"] in forbidden]
    score = score_case(desired, observed, valid=outcome["validation"]["valid"], forbidden=disallowed)
    blocked = desired["missing_ip"] or desired["questions"]
    score["passed"] = score["exact_match"] and (not score["valid"] if blocked else score["valid"])
    score["expected_ips"] = sorted({item[1] for item in desired["instances"]})
    score["signature"] = hashlib.sha256(json.dumps({"design": observed, "valid": score["valid"]}, sort_keys=True).encode()).hexdigest()
    return score


def _failed(document, error):
    return {"ops": [], "document": deepcopy(document), "missing_ip": [], "questions": [], "attempts": 0, "trace": [],
            "validation": {"valid": False, "diagnostics": [error.diagnostic.to_dict()]}}


def _metrics(trials):
    completed = [trial for trial in trials if trial["status"] == "completed"]
    mean = lambda key: sum(trial[key] for trial in completed) / len(completed) if completed else None
    actual = [trial["actual_tokens"] for trial in completed if trial["actual_tokens"] is not None]
    groups = defaultdict(list)
    for trial in completed:
        groups[trial["id"]].append(trial)
    repeated = [values for values in groups.values() if len(values) == 3]
    hits = [trial["retrieval_hit"] for trial in completed if trial["retrieval_hit"] is not None]
    return {"trials": len(completed), "first_pass_rate": mean("first_pass"), "first_semantic_pass_rate": mean("first_semantic_pass"),
            "repair_gain": mean("final_pass") - mean("first_pass") if completed else None,
            "semantic_repair_gain": mean("final_pass") - mean("first_semantic_pass") if completed else None,
            "final_pass_rate": mean("final_pass"), "validation_pass_rate": mean("valid"), "average_attempts": mean("attempts"),
            "average_transport_calls": mean("transport_calls"), "average_latency_ms": mean("latency_ms"),
            "average_actual_tokens": sum(actual) / len(actual) if actual else None, "actual_token_trials": len(actual),
            "average_estimated_tokens": mean("estimated_tokens"),
            "instance_f1": mean("instance_f1"), "connection_f1": mean("connection_f1"), "exact_match_rate": mean("exact_match"),
            "missing_ip_accuracy": mean("missing_ip_correct"), "retrieval_top8_hit_rate": sum(hits) / len(hits) if hits else None,
            "outcome_consistency": sum(len({trial["signature"] for trial in values}) == 1 for values in repeated) / len(repeated) if repeated else None,
            "consistency_cases": len(repeated)}


def _language(prompt):
    chinese = bool(re.search(r"[\u3400-\u9fff]", prompt))
    return "zh-mixed" if chinese and re.search("[A-Za-z]", prompt) else "zh-only" if chinese else "en"


def run_experiment(cases, library, recordings, *, budget, client_name="mock", config=None, allow_network=False,
                   max_output_tokens=8192, client_factory=None):
    from dataclasses import replace
    from bdstudio.ai_eval import CONVENTIONS, baseline, expected_document, normalized
    from core.semantic import validate

    if client_name not in ("mock", "real") or client_name == "real" and (not allow_network or config is None):
        raise LLMError("AI_EVAL_CONFIGURATION", field="network_permission")
    secrets = (config.api_key, config.base_url, urlsplit(config.base_url).hostname) if config else ()
    trials = []
    stopped = False
    for case in cases:
        local = tuple(replace(item, description=case["metadata_injection"]) if case.get("metadata_injection") and item.id == "counter" else item for item in library)
        original = baseline(case, local)
        expected = expected_document(case, local)
        if any(item.severity == "error" for item in validate(expected, local)):
            raise LLMError("AI_EVAL_CONFIGURATION", field="expected_design")
        desired = normalized(expected, local, missing_ip=bool(case["expect"].get("missing_ip")), questions=bool(case["expect"].get("questions")))
        split = case.get("split", "dev")
        prompt = case["prompt"] + ("\n" + CONVENTIONS if split == "dev" else "")
        language = _language(case["prompt"])
        policy = {"allow_removals": case.get("allow_removals", False), "selected_instances": case.get("selected_instances", []),
                  "context_token_budget": config.context_token_budget if config else 32_000,
                  "send_ip_descriptions": config.send_ip_descriptions if config else False}
        for repetition in range(1, 4):
            recorder = CallRecorder(budget, secrets=secrets)
            if client_factory is not None:
                delegate = client_factory(case, recorder)
            elif client_name == "mock":
                delegate = FixedReplayClient(recordings[case["id"]], recorder, max_output_tokens)
            else:
                delegate = OpenAIClient(config, recorder=recorder, max_output_tokens=max_output_tokens)
            client = _GeneratedResponses(delegate)
            started = perf_counter()
            try:
                outcome = run_pipeline(original, local, prompt, client, **policy)
            except LLMError as error:
                outcome = _failed(original, error)
            except KeyboardInterrupt:
                budget.stop_reason = "interrupted"
                outcome = _failed(original, LLMError("AI_EVAL_LIMIT", reason="interrupted"))
            latency = (perf_counter() - started) * 1000
            final = _score(desired, outcome, local, case["expect"].get("must_not", []))
            first_outcome = _failed(original, LLMError("AI_LLM_RESPONSE"))
            first_reply = recorder.events[0]["result"] if recorder.events and not recorder.events[0]["error"] else None
            if isinstance(first_reply, dict):
                first_outcome = run_pipeline(original, local, prompt, ReplayClient([first_reply]), max_attempts=1, **policy)
            first = _score(desired, first_outcome, local, case["expect"].get("must_not", []))
            semantic = first
            if client.responses:
                semantic_outcome = run_pipeline(original, local, prompt, ReplayClient([client.responses[0]]), max_attempts=1, **policy)
                semantic = _score(desired, semantic_outcome, local, case["expect"].get("must_not", []))
            actual_tokens = sum(event["usage"]["total_tokens"] for event in recorder.events) if recorder.events and all(event["usage"] is not None for event in recorder.events) else None
            status = "partial" if budget.stop_reason else "completed" if recorder.events else "blocked"
            injection_sent = bool(case.get("metadata_injection")) and any(case["metadata_injection"] in json.dumps(event["messages"], ensure_ascii=False) for event in recorder.events)
            required = set(case["expect"]["ips"])
            retrieval_hit = required <= {item["id"] for item in outcome["retrieved"]} if required and "retrieved" in outcome else None
            trials.append({"id": case["id"], "split": split, "tier": case["tier"], "language": language, "repetition": repetition,
                           "status": status, "first_pass": first["passed"], "first_semantic_pass": semantic["passed"], "final_pass": final["passed"],
                           "valid": final["valid"], "signature": final["signature"], "attempts": outcome["attempts"], "transport_calls": len(recorder.events),
                           "latency_ms": latency, "actual_tokens": actual_tokens,
                           "estimated_tokens": sum(event["estimated_input_tokens"] + event["estimated_output_tokens"] for event in recorder.events),
                           "injection_payload_sent": injection_sent,
                           "instance_f1": final["instance_f1"], "connection_f1": final["connection_f1"], "exact_match": final["exact_match"],
                           "missing_ip_correct": final["missing_ip_correct"], "retrieval_hit": retrieval_hit,
                           "first_failures": classify_failures(first, first_outcome, injected=injection_sent) if not first["passed"] else [],
                           "final_failures": classify_failures(final, outcome, injected=injection_sent) if not final["passed"] else [],
                           "diff": final["diff"], "diagnostics": outcome["validation"]["diagnostics"], "trace": outcome["trace"], "conversation": recorder.events})
            if budget.stop_reason:
                stopped = True
                break
        if stopped:
            break
    metrics = _metrics(trials)
    groups = {}
    for field in ("split", "tier", "language"):
        groups[field] = {value: _metrics([trial for trial in trials if trial[field] == value]) for value in sorted({trial[field] for trial in trials})}
    for field in ("tier", "language"):
        groups[f"split_{field}"] = {f"{split}/{value}": _metrics([trial for trial in trials if trial["split"] == split and trial[field] == value])
                                  for split, value in sorted({(trial["split"], trial[field]) for trial in trials})}
    dev = _metrics([trial for trial in trials if trial["split"] == "dev" and trial["tier"] in ("simple", "medium")])
    first_hist = Counter(kind for trial in trials if trial["status"] == "completed" for kind in trial["first_failures"])
    final_hist = Counter(kind for trial in trials if trial["status"] == "completed" for kind in trial["final_failures"])
    report = {"schema_version": 2, "client": client_name, "status": "partial" if stopped else "completed", "count": len(cases),
              "created": datetime.now(timezone.utc).isoformat(), "repeats": 3, "planned_trials": len(cases) * 3,
              "completed_trials": sum(trial["status"] == "completed" for trial in trials), "not_run_trials": len(cases) * 3 - sum(bool(trial["transport_calls"]) for trial in trials),
              "blocked_trials": sum(trial["status"] == "blocked" for trial in trials), "calls": budget.calls,
              "real_model_called": client_name == "real" and budget.calls > 0, "stop_reason": budget.stop_reason,
              "budget": {"max_calls": budget.max_calls, "max_cost": float(budget.max_cost), "accounted_cost_upper_usd": float(budget.accounted_cost),
                         "unknown_usage_calls": budget.unknown_usage_calls, "input_price_per_million": float(budget.input_price),
                         "output_price_per_million": float(budget.output_price), "input_overhead": budget.input_overhead, "max_output_tokens": max_output_tokens},
              "metrics": metrics, "groups": groups, "dev_simple_medium": dev,
              "dev_analysis_required": dev["first_pass_rate"] is not None and dev["first_pass_rate"] < 0.7,
              "first_failure_histogram": {kind: first_hist[kind] for kind in FAILURE_KINDS},
              "final_failure_histogram": {kind: final_hist[kind] for kind in FAILURE_KINDS}, "trials": trials}
    return redact(report, secrets)


def write_experiment_report(report, folder, *, mock_report=None, previous=None, secrets=()):
    folder.mkdir(parents=True, exist_ok=True)
    secure_path(folder, directory=True)
    result = redact(deepcopy(report), secrets)
    mock_report = redact(mock_report, secrets)
    previous = redact(previous, secrets)
    failed = Counter(trial["id"] for trial in result["trials"] if trial["status"] == "completed" and (not trial["first_pass"] or not trial["final_pass"]))
    final_failed = Counter(trial["id"] for trial in result["trials"] if trial["status"] == "completed" and not trial["final_pass"])
    worst = sorted(failed, key=lambda name: (-final_failed[name], -failed[name], name))[:5]
    result["worst_cases"] = []
    for identifier in worst:
        if not re.fullmatch(r"[a-zA-Z0-9_]+", identifier):
            raise LLMError("AI_EVAL_CONFIGURATION", field="case_identifier")
        path = folder / f"conversation-{identifier}.json"
        records = [{"repetition": trial["repetition"], "status": trial["status"], "conversation": trial["conversation"]} for trial in result["trials"] if trial["id"] == identifier]
        path.write_text(json.dumps(redact(records), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        secure_path(path)
        result["worst_cases"].append({"id": identifier, "failed_trials": final_failed[identifier], "first_or_final_failed_trials": failed[identifier], "transcript": path.name})
    partial = [trial for trial in result["trials"] if trial["status"] == "partial" and trial["conversation"]]
    if partial:
        path = folder / "conversation-partial.json"
        path.write_text(json.dumps(redact(partial), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        secure_path(path)
        result["partial_transcript"] = path.name
    for trial in result["trials"]:
        trial.pop("conversation", None)
    if mock_report is not None:
        result["mock_comparison"] = {"real": result["metrics"] if result["real_model_called"] else None,
                                     "mock": mock_report.get("metrics"), "mock_status": mock_report.get("status"),
                                     "real_groups": result["groups"] if result["real_model_called"] else None, "mock_groups": mock_report.get("groups"),
                                     "same_dataset": bool(result.get("dataset_sha256")) and result.get("dataset_sha256") == mock_report.get("dataset_sha256"),
                                     "comparable": result["real_model_called"] and bool(result.get("dataset_sha256")) and result.get("dataset_sha256") == mock_report.get("dataset_sha256"),
                                     "real_model_called": result["real_model_called"]}
    if previous is not None:
        comparable = (bool(result.get("dataset_sha256")) and previous.get("schema_version") == 2
                  and previous.get("dataset_sha256") == result.get("dataset_sha256") and previous.get("repeats") == 3
                  and previous.get("client") == result["client"] and previous.get("status") == result["status"] == "completed"
                  and previous.get("completed_trials") == result["completed_trials"] == result["planned_trials"])
        result["comparison"] = {"comparable": comparable}
        if comparable:
            result["comparison"]["metrics_delta"] = {name: value - previous["metrics"][name] for name, value in result["metrics"].items()
                                                       if isinstance(value, (int, float)) and isinstance(previous["metrics"].get(name), (int, float))}
            prior = {(trial["id"], trial["repetition"]): trial for trial in previous["trials"]}
            result["comparison"]["regressions"] = sorted({trial["id"] for trial in result["trials"]
                if (prior[(trial["id"], trial["repetition"])]["first_pass"] and not trial["first_pass"])
                or (prior[(trial["id"], trial["repetition"])]["final_pass"] and not trial["final_pass"])})
    lines = ["# " + MESSAGES["AI_EVAL_TITLE"], "", MESSAGES["AI_EVAL_SCOPE"].format(client=result["client"], count=result["count"]), "",
             MESSAGES["AI_EVAL_PROTOCOL_NOTE"], "",
             f"Status: {result['status']}; completed: {result['completed_trials']}/{result['planned_trials']}; calls: {result['calls']}.", "",
             "| Metric | Value |", "|---|---:|", *[f"| {key} | {value if value is not None else 'N/A'} |" for key, value in result["metrics"].items()], "",
             "| Dimension | Group | Trials | First Pass | Final Pass | Latency ms | Actual Tokens | Estimated Tokens |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for field, entries in result["groups"].items():
        lines.extend(f"| {field} | {name} | {metrics['trials']} | {metrics['first_pass_rate']} | {metrics['final_pass_rate']} | {metrics['average_latency_ms']} | {metrics['average_actual_tokens']} | {metrics['average_estimated_tokens']} |" for name, metrics in entries.items())
    lines.extend(["", "## " + MESSAGES["AI_EVAL_FAILURES"], "", "| Category | First | Final |", "|---|---:|---:|"])
    lines.extend(f"| {MESSAGES['AI_EVAL_FAILURE_' + kind]} | {result['first_failure_histogram'][kind]} | {result['final_failure_histogram'][kind]} |" for kind in FAILURE_KINDS)
    lines.extend(["", "## " + MESSAGES["AI_EVAL_DIALOGUES"], "", *[f"- [{item['id']}]({item['transcript']}): {item['failed_trials']}" for item in result["worst_cases"]]])
    if not result["real_model_called"] and result["client"] == "real":
        lines.extend(["", MESSAGES["AI_EVAL_WAITING"]])
    for key in ("readiness", "mock_comparison", "comparison", "budget", "dev_analysis_required"):
        if key in result:
            lines.extend(["", f"## {key}", "", "```json", json.dumps(result[key], ensure_ascii=False, indent=2), "```"])
    for name, text in (("report.json", json.dumps(redact(result), ensure_ascii=False, indent=2) + "\n"), ("report.md", "\n".join(lines) + "\n")):
        path = folder / name
        path.write_text(text, encoding="utf-8")
        secure_path(path)
    return result


def _prepared_report(cases, budget, client_name, readiness):
    metrics = _metrics([])
    status = "waiting_configuration" if readiness["missing"] and client_name == "real" else "dry_run"
    groups = {}
    prepared = readiness["prepared_cases"]
    for field in ("split", "tier", "language"):
        groups[field] = {value: {**metrics, "planned_trials": sum(item[field] == value for item in prepared) * 3} for value in sorted({item[field] for item in prepared})}
    return {"schema_version": 2, "client": client_name, "status": status, "count": len(cases), "repeats": 3,
            "created": datetime.now(timezone.utc).isoformat(), "planned_trials": len(cases) * 3, "completed_trials": 0,
            "not_run_trials": len(cases) * 3, "blocked_trials": 0, "calls": 0, "real_model_called": False,
            "stop_reason": None, "budget": {"max_calls": budget.max_calls, "max_cost": float(budget.max_cost), "accounted_cost_upper_usd": 0},
            "metrics": metrics, "groups": groups,
            "dev_simple_medium": metrics, "dev_analysis_required": None, "readiness": readiness,
            "first_failure_histogram": {kind: None for kind in FAILURE_KINDS}, "final_failure_histogram": {kind: None for kind in FAILURE_KINDS}, "trials": []}


def _price(value):
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
        if not parsed.is_finite() or parsed < 0:
            raise ValueError()
        return parsed
    except (ValueError, ArithmeticError):
        raise LLMError("AI_EVAL_CONFIGURATION", field="pricing") from None


def run_command(args):
    from ai.settings import SettingsStore
    from bdstudio.ai_eval import CONVENTIONS, ROOT, REPLAYS, baseline, catalog, expected_document, load_cases, load_held_out
    from core.semantic import validate

    cases = ([{**case, "split": "dev"} for case in load_cases()] if args.suite != "held-out" else []) + (load_held_out() if args.suite != "dev" else [])
    library = catalog()
    store = SettingsStore(args.workspace)
    config = store.configuration()
    public = store.public()
    input_price = _price(args.input_price if args.input_price is not None else os.environ.get("BD_AI_INPUT_PRICE"))
    output_price = _price(args.output_price if args.output_price is not None else os.environ.get("BD_AI_OUTPUT_PRICE"))
    max_cost = _price(args.max_cost)
    if max_cost is None or not 1 <= args.max_output_tokens <= 32768:
        raise LLMError("AI_EVAL_CONFIGURATION", field="limits")
    flags = {"endpoint": public["endpoint_configured"], "model": bool(config.model),
             "credential": bool(config.api_key) or public["endpoint_configured"] and endpoint_kind(config.base_url) == "local",
             "input_price": input_price is not None, "output_price": output_price is not None,
             "max_cost": max_cost > 0 or input_price == output_price == 0}
    missing = [name for name, present in flags.items() if not present]
    prepared = []
    for case in cases:
        original = baseline(case, library)
        expected = expected_document(case, library)
        if any(item.severity == "error" for item in validate(expected, library)):
            raise LLMError("AI_EVAL_CONFIGURATION", field="expected_design")
        try:
            _, details = budget_context(original, library, token_budget=config.context_token_budget, selected_instances=case.get("selected_instances", []))
            context = {"scope": details["scope"], "estimated_tokens": details["estimated_tokens"]}
        except LLMError as error:
            context = {"blocked": error.code}
        prepared.append({"id": case["id"], "split": case.get("split", "dev"), "tier": case["tier"], "language": _language(case["prompt"]),
                 "instances": len(original["instances"]), "context": context})
    readiness = {"missing": missing, "provided": flags, "expected_designs_valid": len(cases), "prepared_cases": prepared}
    budget = RunBudget(max_calls=args.max_calls, max_cost=max_cost, input_price=input_price or 0, output_price=output_price or 0, input_overhead=args.input_overhead)
    if args.dry_run or args.client == "real" and missing:
        report = _prepared_report(cases, budget, args.client, readiness)
    else:
        recordings = json.loads(REPLAYS.read_text(encoding="utf-8"))
        recordings.update(json.loads((ROOT / "tests/ai_eval/held_out_replays.json").read_text(encoding="utf-8")))
        if any(case["id"] not in recordings for case in cases):
            raise LLMError("AI_EVAL_CONFIGURATION", field="recordings")
        report = run_experiment(cases, library, recordings, budget=budget, client_name=args.client, config=config,
                                allow_network=args.allow_network, max_output_tokens=args.max_output_tokens)
        report["readiness"] = readiness
    secrets = (config.api_key, config.base_url, urlsplit(config.base_url).hostname)
    report.update(dataset_sha256=hashlib.sha256(json.dumps(cases, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
                  prompt_sha256=hashlib.sha256((SYSTEM + CONVENTIONS).encode("utf-8")).hexdigest(),
                  runtime={"python": platform.python_version(), "platform": platform.system()},
                  model=redact(config.model, secrets) if args.client == "real" and public["endpoint_configured"] else "offline-replay" if args.client == "mock" else None,
                  context_policy={"token_budget": config.context_token_budget, "send_ip_descriptions": config.send_ip_descriptions},
                  usage_note="provider usage only when supplied; otherwise conservative estimates, not measured tokens",
                  pricing_note="user-provided upper-bound USD per million tokens; reserved byte bound plus overhead; provider billing must honor these bounds",
                  replay_note="offline fixtures repeat their final response up to the existing repair limit; not real-model observations")
    mock = json.loads(args.mock_report.read_text(encoding="utf-8")) if args.mock_report else None
    if mock is not None and mock.get("client") != "mock":
        raise LLMError("AI_EVAL_CONFIGURATION", field="mock_report")
    previous = json.loads(args.compare.read_text(encoding="utf-8")) if args.compare else None
    result = write_experiment_report(report, args.report, mock_report=mock, previous=previous, secrets=secrets)
    print(json.dumps({"status": result["status"], "count": result["count"], "completed_trials": result["completed_trials"],
                      "calls": result["calls"], "real_model_called": result["real_model_called"], "metrics": result["metrics"]}, ensure_ascii=False))
    if args.dry_run:
        return 0
    if result["status"] == "waiting_configuration":
        return 2
    if result["status"] == "partial":
        return 3
    dev = result["dev_simple_medium"]["final_pass_rate"]
    traps_pass = all(trial["final_pass"] for trial in result["trials"] if trial["tier"] == "trap")
    return 0 if (dev is None or dev >= 0.8) and traps_pass and result["completed_trials"] == result["planned_trials"] else 1