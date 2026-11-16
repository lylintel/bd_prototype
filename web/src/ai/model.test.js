import test from "node:test";
import assert from "node:assert/strict";
import { operationText } from "./model.js";
import { updateCopilotMessages } from "../copilot.js";

test("operation summaries retain versions and expression endpoints", () => {
  assert.equal(operationText({ op: "set_param", inst: "unit", name: "WIDTH", value: "4 * 3" }), "unit.WIDTH = 4 * 3");
  assert.match(operationText({ op: "add_instance", name: "unit", ip: "counter", version: "1.0.0" }), /counter@1.0.0/);
  assert.match(operationText({ op: "connect", from: { type: "const", const: "8'd5" }, to: { type: "port", inst: "unit", port: "value" } }), /8'd5.*unit.value/);
});

test("pending legacy generation is never reported as generated RTL", () => {
  const messages = updateCopilotMessages([], { type: "workflow", stage: "bd_generate", status: "pending_confirmation" }, "request");
  assert.equal(messages.length, 1);
  assert.ok(!messages[0].content.includes("已生成"));
});