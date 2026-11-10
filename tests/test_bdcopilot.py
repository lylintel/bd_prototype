import asyncio
from dataclasses import dataclass
from http.client import HTTPConnection
import json
from pathlib import Path
import shutil
import tempfile
from threading import Event, Thread
from types import SimpleNamespace
import unittest

from bdcopilot import CopilotBridge, CopilotError, MAX_TOOL_CALLS, TOOL_NAMES
from bdworkflow import CHECKS, DIMENSIONS
from bdgui import EditorServer, Workspace


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class FakeResult:
    result_type: str
    text_result_for_llm: str


class FakeSession:
    def __init__(self, options):
        self.options = options
        self.handler = None
        self.aborted = False
        self.aborted_event = Event()
        self.send_started = Event()
        self.abort_fails = False
        self.disconnected = False

    def on(self, handler):
        self.handler = handler
        return lambda: setattr(self, "handler", None)

    def emit(self, kind, **data):
        self.handler(SimpleNamespace(type=kind, data=SimpleNamespace(message_id="message-1", **data), agent_id=None))

    async def send_and_wait(self, prompt, **options):
        self.send_started.set()
        if prompt == "hold":
            await asyncio.Event().wait()
        if prompt == "timeout":
            raise TimeoutError()
        if prompt == "failure":
            raise RuntimeError("credential=do-not-expose-this")
        if prompt == "tools":
            result = self.options["tools"][1].handler(SimpleNamespace(arguments={}))
            self.emit("assistant.message", content=result.text_result_for_llm)
            return
        if prompt == "tool loop":
            for attempt in range(MAX_TOOL_CALLS + 2):
                self.options["tools"][0].handler(SimpleNamespace(arguments={}))
                await asyncio.sleep(0)
            return
        if prompt.startswith("workflow threshold"):
            tools = {tool.name: tool for tool in self.options["tools"]}
            def invoke(name, **arguments):
                result = tools[name].handler(SimpleNamespace(arguments=arguments))
                if result.result_type != "success":
                    self.emit("assistant.message", content=result.text_result_for_llm)
                    return None
                return json.loads(result.text_result_for_llm)
            workflow = invoke("bd_workflow")
            if workflow is None:
                return
            evidence = workflow["user_evidence"][-1]
            specification = {"schema_version": 1, "requirements": [{"id": "REQ-001", "statement": "Set threshold to 19", "kind": "hard", "status": "confirmed",
                "source": {"message_id": evidence["id"], "quote": evidence["text"]}, "acceptance": {"method": "structural", "criteria": "THRESHOLD is 19"}}],
                "dimensions": {name: {"value": None, "status": "not_applicable", "evidence": "Existing topology preserved for a parameter-only change", "blocking_stage": "none"} for name in DIMENSIONS}, "open_questions": []}
            invoke("bd_requirements", specification=specification)
            invoke("bd_plan", plan={"schema_version": 1, "base_hash": workflow["base_hash"],
                "operations": [{"op": "set_parameter", "instance": "compare_0", "parameter": "THRESHOLD", "value": 19, "requirement_ids": ["REQ-001"], "evidence": evidence["text"]}],
                "checks": {name: {"status": "not_applicable", "evidence": "No topology or interface change"} for name in CHECKS}})
            generated = invoke("bd_generate")
            if generated:
                self.emit("assistant.message", content=generated["run_dir"])
            return
        self.emit("assistant.reasoning_delta", delta_content="private reasoning")
        self.emit("assistant.message_delta", delta_content="Hello ")
        self.emit("assistant.message_delta", delta_content="RTL")
        self.emit("assistant.message", content="Hello RTL")

    async def abort(self):
        if self.abort_fails:
            raise ConnectionError("abort acknowledgement failed")
        self.aborted = True
        self.aborted_event.set()

    async def disconnect(self):
        self.disconnected = True


class FakeClient:
    def __init__(self, **options):
        if options.get("mode") == "empty" and not options.get("base_directory"):
            raise ValueError("Empty mode requires explicit state storage")
        self.options = options
        self.sessions = []
        self.deleted = []
        self.authenticated = True
        self.started = False
        self.created = Event()
        self.forced = False

    async def start(self):
        self.started = True

    async def get_auth_status(self):
        keychain_enabled = self.options.get("mode") != "empty" and self.options.get("use_logged_in_user") is True
        return SimpleNamespace(isAuthenticated=self.authenticated and keychain_enabled)

    async def list_models(self):
        return [SimpleNamespace(id="test-model", name="Test model")]

    async def create_session(self, **options):
        session = FakeSession(options)
        self.sessions.append(session)
        self.created.set()
        return session

    async def delete_session(self, session_id):
        self.deleted.append(session_id)

    async def stop(self):
        self.started = False

    async def force_stop(self):
        self.forced = True
        self.started = False


class CopilotTests(unittest.TestCase):
    def setUp(self):
        self.clients = []
        self.signed_in = True
        def create_client(**options):
            client = FakeClient(**options)
            client.authenticated = self.signed_in
            self.clients.append(client)
            return client
        sdk = SimpleNamespace(Client=create_client, Connection=SimpleNamespace(for_stdio=lambda **kwargs: kwargs),
            Tool=lambda **kwargs: SimpleNamespace(**kwargs), Result=FakeResult,
            Reject=lambda **kwargs: SimpleNamespace(kind="reject", **kwargs))
        self.bridge = CopilotBridge(Workspace(ROOT, "examples/counter_compare.json"), sdk_loader=lambda: sdk)
        self.addCleanup(self.bridge.close)
        self.design = json.loads((ROOT / "examples/counter_compare.json").read_text(encoding="utf-8"))

    def drain(self, turn):
        events = []
        while True:
            event = turn.events.get(timeout=5)
            events.append(event)
            if event["type"] == "done":
                return events

    def send(self, prompt="hello", **extra):
        return self.bridge.start_turn({"prompt": prompt, "confirm_usage": True, "model": "test-model", **extra})

    def test_status_is_passive_and_connect_does_not_send_a_prompt(self):
        self.assertFalse(self.bridge.status()["connected"])
        self.assertEqual(self.clients, [])
        connected = self.bridge.connect()
        self.assertTrue(connected["authenticated"])
        self.assertEqual(self.clients[0].sessions, [])
        self.assertEqual(self.clients[0].options["mode"], "copilot-cli")
        self.assertTrue(self.clients[0].options["use_logged_in_user"])
        self.assertTrue(self.clients[0].options["base_directory"])
        self.assertNotEqual(self.clients[0].options["working_directory"], str(ROOT))

    def test_streaming_and_multiturn_use_restricted_session(self):
        self.bridge.connect()
        first = self.send()
        events = self.drain(first)
        self.assertEqual([item["content"] for item in events if item["type"] == "delta"], ["Hello ", "RTL"])
        self.assertNotIn("private reasoning", json.dumps(events))
        session = self.clients[0].sessions[0]
        self.assertEqual(session.options["available_tools"], [f"custom:{name}" for name in TOOL_NAMES])
        self.assertEqual(session.options["excluded_tools"], ["builtin:*", "mcp:*"])
        self.assertEqual(session.options["on_permission_request"]({}, {}).kind, "reject")
        self.assertFalse(session.options["infinite_sessions"]["enabled"])
        self.assertFalse(session.options["enable_file_hooks"])
        self.assertFalse(session.options["enable_config_discovery"])
        self.assertFalse(session.options["enable_host_git_operations"])
        self.assertFalse(session.options["enable_on_demand_instruction_discovery"])
        self.assertFalse(session.options["enable_skills"])
        self.assertFalse(session.options["enable_session_store"])
        self.assertTrue(session.options["skip_custom_instructions"])
        self.assertTrue(session.options["skip_embedding_retrieval"])
        second = self.send(conversation_id=first.conversation.id)
        self.drain(second)
        self.assertEqual(len(self.clients[0].sessions), 1)
        self.assertEqual(second.conversation.turns, 2)

    def test_logged_out_connection_refreshes_after_cli_login(self):
        self.signed_in = False
        self.assertFalse(self.bridge.connect()["authenticated"])
        self.signed_in = True
        self.assertTrue(self.bridge.connect()["authenticated"])
        self.assertEqual(len(self.clients), 2)
        self.assertFalse(self.clients[0].started)
        self.assertEqual(self.clients[1].sessions, [])

    def test_usage_and_context_require_explicit_consent(self):
        self.bridge.connect()
        with self.assertRaisesRegex(CopilotError, "confirmation"):
            self.bridge.start_turn({"prompt": "hello"})
        with self.assertRaisesRegex(CopilotError, "sharing consent"):
            self.send(design=self.design)
        turn = self.send("tools")
        events = self.drain(turn)
        self.assertIn("did not share", next(item["content"] for item in events if item["type"] == "message"))

    def test_workflow_permission_is_explicit_and_results_are_isolated(self):
        with tempfile.TemporaryDirectory(prefix="bd-agent-") as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "examples", root / "examples")
            self.bridge.workspace = Workspace(root, "examples/counter_compare.json")
            self.bridge.connect()
            denied = self.send("workflow threshold", share_context=True, design=self.design, base_dir="examples")
            denied_events = self.drain(denied)
            self.assertIn("did not authorize", next(item["content"] for item in denied_events if item["type"] == "message"))
            self.assertFalse((root / "build").exists())
            turn = self.send("workflow threshold to 19", share_context=True, allow_design_changes=True, design=self.design, base_dir="examples")
            events = self.drain(turn)
            update = next(item for item in events if item["type"] == "design_update")
            self.assertEqual(update["base_design"]["instances"]["compare_0"]["parameters"]["THRESHOLD"], 9)
            self.assertEqual(update["design"]["instances"]["compare_0"]["parameters"]["THRESHOLD"], 19)
            self.assertTrue((root / update["run_dir"] / "generated/example_bd.v").is_file())
            self.assertEqual(json.loads((root / "examples/counter_compare.json").read_text())["instances"]["compare_0"]["parameters"]["THRESHOLD"], 9)
            self.assertEqual(update["verification"]["functional_simulation"], "not_run")
            self.assertIn("build-bd-design", self.clients[0].sessions[-1].options["system_message"]["content"])

    def test_tools_validate_an_explicit_snapshot_without_writing(self):
        self.bridge.connect()
        turn = self.send("tools", share_context=True, design=self.design, base_dir="examples")
        self.design["name"] = "changed_after_send"
        events = self.drain(turn)
        result = json.loads(next(item["content"] for item in events if item["type"] == "message"))
        self.assertTrue(result["valid"])
        self.assertIn("counter_0", result["interfaces"]["instances"])
        self.assertIsNone(turn.conversation.context)

    def test_cancel_aborts_sdk_and_rejects_concurrent_requests(self):
        self.bridge.connect()
        turn = self.send("hold")
        with self.assertRaisesRegex(CopilotError, "Another response"):
            self.send()
        self.assertTrue(self.bridge.cancel(turn.id)["cancelled"])
        self.assertEqual(self.drain(turn)[-1]["status"], "cancelled")
        self.assertTrue(self.clients[0].sessions[0].aborted)
        self.assertFalse(self.bridge.status()["busy"])

    def test_timeout_and_errors_do_not_retry_or_expose_secrets(self):
        self.bridge.connect()
        for prompt in ("timeout", "failure"):
            turn = self.send(prompt)
            events = self.drain(turn)
            self.assertEqual(events[-1]["status"], "error")
            self.assertNotIn("do-not-expose-this", json.dumps(events))
            self.assertTrue(self.clients[0].sessions[-1].aborted)

    def test_abort_failure_force_stops_owned_runtime(self):
        self.bridge.connect()
        turn = self.send("hold")
        client = self.clients[0]
        self.assertTrue(client.created.wait(timeout=2))
        session = client.sessions[0]
        self.assertTrue(session.send_started.wait(timeout=2))
        session.abort_fails = True
        self.assertTrue(self.bridge.cancel(turn.id)["cancelled"])
        self.assertEqual(self.drain(turn)[-1]["status"], "cancelled")
        self.assertTrue(client.forced)
        self.assertFalse(self.bridge.status()["authenticated"])

    def test_tool_budget_stops_runaway_requests(self):
        self.bridge.connect()
        turn = self.send("tool loop", share_context=True, design=self.design, base_dir="examples")
        events = self.drain(turn)
        self.assertEqual(events[-1]["status"], "cancelled")
        self.assertTrue(self.clients[0].sessions[0].aborted)

    def test_clear_disconnects_and_deletes_only_owned_session(self):
        self.bridge.connect()
        turn = self.send()
        self.drain(turn)
        self.assertTrue(self.bridge.clear(turn.conversation.id)["cleared"])
        self.assertTrue(self.clients[0].sessions[0].disconnected)
        self.assertEqual(self.clients[0].deleted, [turn.conversation.id])
        with self.assertRaisesRegex(CopilotError, "expired"):
            self.send(conversation_id=turn.conversation.id)

    def test_http_stream_authentication_cancel_and_disconnect(self):
        server = EditorServer(("127.0.0.1", 0), self.bridge.workspace)
        server.copilot = self.bridge
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        control = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        headers = {"Content-Type": "application/json", "X-BD-Token": server.token}
        try:
            connection.request("GET", "/api/copilot/status")
            response = connection.getresponse()
            self.assertFalse(json.loads(response.read())["connected"])
            self.assertEqual(self.clients, [])
            connection.request("POST", "/api/copilot/connect", "{}", {"Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            connection.request("POST", "/api/copilot/connect", "{}", headers)
            response = connection.getresponse()
            self.assertTrue(json.loads(response.read())["authenticated"])
            payload = {"prompt": "hello", "confirm_usage": True, "model": "test-model"}
            connection.request("POST", "/api/copilot/chat", json.dumps(payload), headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn("application/x-ndjson", response.getheader("Content-Type"))
            events = [json.loads(line) for line in response.read().decode("utf-8").splitlines()]
            self.assertEqual(events[0]["type"], "start")
            self.assertEqual(events[-1], {"type": "done", "status": "complete"})

            payload["prompt"] = "hold"
            connection.request("POST", "/api/copilot/chat", json.dumps(payload), headers)
            response = connection.getresponse()
            started = json.loads(response.readline())
            control.request("POST", "/api/copilot/cancel", json.dumps({"request_id": started["request_id"]}), headers)
            self.assertTrue(json.loads(control.getresponse().read())["cancelled"])
            events = [json.loads(line) for line in response.read().decode("utf-8").splitlines()]
            self.assertEqual(events[-1]["status"], "cancelled")

            connection.request("POST", "/api/copilot/chat", json.dumps(payload), headers)
            response = connection.getresponse()
            self.assertEqual(json.loads(response.readline())["type"], "start")
            response.close()
            connection.close()
            self.assertTrue(self.clients[0].sessions[-1].aborted_event.wait(timeout=6), "disconnect must abort SDK generation")
        finally:
            connection.close()
            control.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()