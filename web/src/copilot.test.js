import assert from "node:assert/strict";
import test from "node:test";
import { readCopilotEvents, resolveDesignUpdate, updateCopilotMessages } from "./copilot.js";

test("stream parser handles split UTF-8 and multiple records per chunk", async () => {
  const records = [{ type: "start", request_id: "turn-1" }, { type: "delta", id: "text", content: "检查位宽" }, { type: "done", status: "complete" }];
  const bytes = new TextEncoder().encode(records.map((record) => JSON.stringify(record)).join("\n"));
  const body = new ReadableStream({ start(controller) { for (const byte of bytes) controller.enqueue(new Uint8Array([byte])); controller.close(); } });
  const received = [];
  await readCopilotEvents(new Response(body), (event) => received.push(event));
  assert.deepEqual(received, records);
});

test("final messages replace deltas without duplicating text or earlier turns", () => {
  let messages = [];
  messages = updateCopilotMessages(messages, { type: "delta", id: "message", content: "检查" }, "turn-1");
  messages = updateCopilotMessages(messages, { type: "delta", id: "message", content: "位宽" }, "turn-1");
  messages = updateCopilotMessages(messages, { type: "message", id: "message", content: "检查位宽" }, "turn-1");
  messages = updateCopilotMessages(messages, { type: "message", id: "message", content: "下一轮" }, "turn-2");
  assert.deepEqual(messages.map((message) => message.content), ["检查位宽", "下一轮"]);
});

test("missing terminal event and HTTP failures are surfaced without retries", async () => {
  await assert.rejects(readCopilotEvents(new Response('{"type":"delta","content":"partial"}\n'), () => {}), /连接中断/);
  await assert.rejects(readCopilotEvents(new Response('{"error":"Please sign in"}', { status: 400 }), () => {}), /Please sign in/);
});

test("tool status updates do not expose tool arguments and cancellation is visible", () => {
  let messages = updateCopilotMessages([], { type: "tool", name: "bd_validate", status: "running", arguments: "not displayed" }, "turn");
  messages = updateCopilotMessages(messages, { type: "tool", name: "bd_validate", status: "complete" }, "turn");
  messages = updateCopilotMessages(messages, { type: "done", status: "cancelled" }, "turn");
  assert.equal(messages.length, 2);
  assert.equal(messages[0].status, "complete");
  assert.equal(messages[1].content, "已停止生成");
  assert.equal(JSON.stringify(messages).includes("not displayed"), false);
});

test("design updates accept equivalent key order and return an independent design", () => {
  const current = { name: "old_design", modules: {}, ports: {}, instances: {}, nets: {} };
  const base = { nets: {}, instances: {}, ports: {}, modules: {}, name: "old_design" };
  const candidate = { ...current, name: "new_design" };
  const updated = resolveDesignUpdate(current, "examples", { base_design: base, design: candidate, base_dir: "examples" });
  assert.equal(updated.name, "new_design");
  assert.notEqual(updated, candidate);
  assert.equal(current.name, "old_design");
});

test("stale design or path context cannot overwrite concurrent user work", () => {
  const base = { name: "old_design", modules: {}, ports: {}, instances: {}, nets: {} };
  const event = { base_design: base, design: { ...base, name: "generated" }, base_dir: "examples" };
  assert.throws(() => resolveDesignUpdate({ ...base, name: "user_edit" }, "examples", event), /未覆盖画布/);
  assert.throws(() => resolveDesignUpdate(base, "designs", event), /未覆盖画布/);
  assert.throws(() => resolveDesignUpdate(base, "examples", { ...event, design: null }), /JSON 对象/);
});

test("workflow events retain output paths without claiming simulation passed", () => {
  const messages = updateCopilotMessages([], { type: "workflow", stage: "bd_generate", status: "complete", run_dir: "build/copilot/run" }, "turn");
  assert.equal(messages[0].runDir, "build/copilot/run");
  assert.equal(messages[0].content, "隔离 RTL 产物已生成");
});