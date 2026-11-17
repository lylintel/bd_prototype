import test from "node:test";
import assert from "node:assert/strict";
import { operationText, designChanges, mergePreview } from "./model.js";
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

test("preview layers mark additions deletions and modifications without mutating base", () => {
  const before = { instances: { old: { module: "unit" }, kept: { module: "unit", parameters: { WIDTH: 8 } } }, ports: {}, nets: {} };
  const after = { instances: { fresh: { module: "unit" }, kept: { module: "unit", parameters: { WIDTH: 12 } } }, ports: {}, nets: {} };
  const changes = designChanges(before, after);
  assert.deepEqual(changes.nodes, { old: "deleted", kept: "modified", fresh: "added" });
  const original = [{ id: "old", data: {} }, { id: "kept", data: {} }];
  const result = mergePreview(original, [], [{ id: "fresh", data: {} }, { id: "kept", data: {} }], [], changes);
  assert.equal(result.nodes.length, 3);
  assert.match(result.nodes.find((node) => node.id === "old").className, /deleted/);
  assert.match(result.nodes.find((node) => node.id === "fresh").className, /added/);
  assert.match(result.nodes.find((node) => node.id === "kept").className, /modified/);
  assert.ok(result.nodes.every((node) => node.draggable === false));
  assert.deepEqual(original, [{ id: "old", data: {} }, { id: "kept", data: {} }]);
});

test("preview preserves existing positions and places additions beyond deleted ghosts", () => {
  const original = [{ id: "removed", position: { x: 0, y: 0 }, data: {} }, { id: "kept", position: { x: 400, y: 0 }, data: {} }];
  const candidate = [{ id: "kept", position: { x: 0, y: 0 }, data: {} }, { id: "added", position: { x: 400, y: 0 }, data: {} }];
  const result = mergePreview(original, [], candidate, [], { nodes: {}, nets: {} });
  assert.deepEqual(result.nodes.find((node) => node.id === "kept").position, { x: 400, y: 0 });
  assert.ok(result.nodes.find((node) => node.id === "added").position.x > 680);
  assert.deepEqual(result.nodes.find((node) => node.id === "removed").position, { x: 0, y: 0 });
  assert.deepEqual(mergePreview([], [], candidate, [], { nodes: {}, nets: {} }).nodes.map((node) => node.position), candidate.map((node) => node.position));
});