import test from "node:test";
import assert from "node:assert/strict";
import { operationMembers, operationText, designChanges, mergePreview, candidateGraph, proposalView } from "./model.js";
import { scopeReferenceCount } from "../semantic/hierarchy.js";
import { updateCopilotMessages } from "../copilot.js";

test("interface proposal views stay local while shared policy counts indirect reuse", () => {
  const root = { name: "root", instances: [{ ip: { id: "outer" } }], subdesigns: {
    outer: { instances: [{ ip: { id: "inner" } }] }, inner: { instances: [] },
  } };
  assert.equal(scopeReferenceCount(root, "inner"), 1);
  root.instances.push({ ip: { id: "outer" } });
  assert.equal(scopeReferenceCount(root, "inner"), 2);
  const local = { name: "inner" };
  const view = proposalView({ document: root, valid: false, diagnostics: ["root error"], scope: "inner", scope_view: { document: local, valid: true, diagnostics: [] } });
  assert.equal(view.rootDocument, root);
  assert.equal(view.document, local);
  assert.equal(view.scope, "inner");
  assert.equal(view.valid, false);
  assert.deepEqual(view.diagnostics, ["root error"]);
  assert.equal(operationText({ op: "connect", from: { type: "interface", inst: "first", interface: "m_axis" },
    to: { type: "interface", ext_interface: "output" } }), "first.m_axis -> @output");
});

test("interface previews retain one atomic coarse edge and never draw derived scalar nets", () => {
  const declaration = (name, mode, prefix) => ({ name, mode, valid: true, parameters: { DATA_WIDTH: 8 }, physical_ports: [`${prefix}_data`, `${prefix}_valid`, `${prefix}_ready`],
    signals: { tdata: { port: `${prefix}_data`, width: 8 }, tvalid: { port: `${prefix}_valid`, width: 1 }, tready: { port: `${prefix}_ready`, width: 1 } } });
  const document = { schema_version: 5, nets: [], interfaces: [], interface_connections: [{ name: "link", from: { inst: "first", interface: "m_axis" }, to: { inst: "second", interface: "s_axis" } }] };
  const canvas = { name: "pair", modules: { unit: { ports: {} } }, ports: {}, nets: { __bd_if_link__tdata: ["first.m_data", "second.s_data"] },
    instances: { first: { module: "unit" }, second: { module: "unit" } } };
  const view = { document, canvas, connections: [{ name: "__bd_if_link__tdata", endpoints: [] }], bus_interfaces: {
    instances: { first: { m_axis: declaration("m_axis", "master", "m") }, second: { s_axis: declaration("s_axis", "slave", "s") } }, external: {},
    connections: [{ ...document.interface_connections[0], valid: true, signals: {
      tdata: { width: 8, source: { inst: "first", port: "m_data" }, sink: { inst: "second", port: "s_data" } },
      tready: { width: 1, source: { inst: "second", port: "s_ready" }, sink: { inst: "first", port: "m_ready" } },
    } }],
  } };
  const graph = candidateGraph(view, {}, () => ({ x: 0, y: 0 }));
  assert.equal(graph.edges.length, 1);
  assert.equal(graph.edges[0].id, "interface:link");
  assert.ok(graph.edges[0].data.coarse);
  assert.equal(graph.nodes[0].data.ports[0].endpoint, "~if:first:m_axis");
  const changes = designChanges(canvas, canvas, { interface_connections: [] }, document);
  assert.equal(changes.nets.link, "added");
  assert.ok(mergePreview([], [], graph.nodes, graph.edges, changes).edges[0].className.endsWith("added"));
  const operation = { op: "connect", from: { type: "interface", ...document.interface_connections[0].from }, to: { type: "interface", ...document.interface_connections[0].to } };
  assert.deepEqual(operationMembers(view, operation)[1], { signal: "TREADY", source: "second.s_ready", target: "first.m_ready", width: 1 });
  assert.equal(operationMembers({ base_bus_interfaces: view.bus_interfaces }, { ...operation, op: "disconnect" }).length, 2);
});

test("preview nodes retain initial dimensions before React Flow measures them", () => {
  const view = { canvas: { name: "demo", modules: { unit: { ports: {} } }, instances: { kept: { module: "unit" } }, ports: { out: { direction: "output", range: [7, 0] } }, nets: {} },
    connections: [{ name: "literal", endpoints: [
      { index: 0, raw: { const: "8'd1" }, expression: true, drives: true, width: 8, text: "8'd1", references: [] },
      { index: 1, raw: { ext: "out" }, expression: false, drives: false, width: 8, text: "@out", references: [{ key: "@out", width: 8, bounds: [7, 0] }] },
    ] }] };
  const candidate = candidateGraph(view, {}, () => ({ x: 0, y: 0 }));
  const result = mergePreview([], [], candidate.nodes, candidate.edges, { nodes: {}, nets: {} });
  assert.ok(result.nodes.every((node) => node.initialWidth > 0 && node.initialHeight > 0));
  const expression = result.nodes.find((node) => node.type === "expression");
  assert.equal(expression.initialWidth, 230);
  assert.equal(expression.initialHeight, 86);
});

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