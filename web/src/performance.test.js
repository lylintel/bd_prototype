import { makeLayoutGraph, layoutPositions } from "./layout/model.js";
import { publishPositions, requestLayout } from "./layout/client.js";

test("layout application yields bounded batches and stops on cancellation", async () => {
  const positions = Object.fromEntries(Array.from({ length: 2000 }, (_, index) => [`unit_${index}`, { x: index, y: 0 }]));
  const batches = [];
  await publishPositions(positions, (batch) => batches.push(batch), { nextFrame: () => Promise.resolve() });
  assert.ok(batches.every((batch) => Object.keys(batch).length <= 8));
  assert.deepEqual(Object.assign({}, ...batches), positions);
  const controller = new AbortController();
  let applied = 0;
  await assert.rejects(publishPositions(positions, () => { applied++; controller.abort(); },
    { signal: controller.signal, nextFrame: () => Promise.resolve() }), { name: "AbortError" });
  assert.equal(applied, 1);
});
import ELK from "elkjs/lib/elk.bundled.js";
import { EditorState } from "@codemirror/state";
import { createOutputState, largeDocument } from "./output/model.js";

test("large output profile keeps all text and switches at 5000 lines", () => {
  const text = Array.from({ length: 20000 }, (_, index) => `wire signal_${index};`).join("\n");
  const large = createOutputState(text, { language: "verilog", readOnly: true, label: "Verilog" });
  assert.equal(large.doc.lines, 20000);
  assert.equal(large.doc.toString(), text);
  assert.equal(large.facet(largeDocument), true);
  assert.equal(large.facet(EditorState.readOnly), true);
  const small = createOutputState("{}", { language: "json", readOnly: false, label: "JSON" });
  assert.equal(small.facet(largeDocument), false);
  const expanded = small.update({ changes: { from: 0, to: small.doc.length, insert: text } }).state;
  assert.equal(expanded.facet(largeDocument), true);
  assert.equal(expanded.update({ changes: { from: 0, to: expanded.doc.length, insert: "{}" } }).state.facet(largeDocument), false);
});

test("large cyclic graphs use the real ELK rectangle packer", async () => {
  const nodes = Array.from({ length: 2000 }, (_, index) => ({ id: `unit_${index}`, initialWidth: 250, initialHeight: 246 }));
  const edges = nodes.flatMap((node, index) => [1, 23, 127].map((offset) => ({ source: node.id, target: nodes[(index + offset) % nodes.length].id })));
  const graph = makeLayoutGraph(nodes, edges);
  assert.equal(graph.layoutOptions["elk.algorithm"], "rectpacking");
  const result = layoutPositions(await new ELK().layout(graph));
  assert.equal(Object.keys(result).length, 2000);
  assert.equal(new Set(Object.values(result).map((point) => `${point.x}:${point.y}`)).size, 2000);
});

test("layout graph retains dimensions and excludes dangling display edges", () => {
  const nodes = [{ id: "first", initialWidth: 250, initialHeight: 186 }, { id: "second", measured: { width: 156, height: 59 } }];
  const graph = makeLayoutGraph(nodes, [{ id: "valid", source: "first", target: "second" }, { id: "missing", source: "first", target: "absent" }]);
  assert.equal(graph.children[0].width, 250);
  assert.equal(graph.children[1].height, 59);
  assert.equal(graph.edges.length, 1);
  assert.equal(nodes[0].position, undefined);
  assert.throws(() => layoutPositions({ children: [{ id: "first", x: NaN, y: 0 }] }), /position/);
});

test("layout worker is cancelled and cannot publish a late result", async () => {
  const controller = new AbortController();
  const worker = { postMessage(value) { this.input = value; }, terminate() { this.terminated = true; } };
  const pending = requestLayout([{ id: "first" }], [], { signal: controller.signal, workerFactory: () => worker });
  const rejected = assert.rejects(pending, { name: "AbortError" });
  controller.abort();
  worker.onmessage?.({ data: { positions: { first: { x: 1, y: 2 } } } });
  await rejected;
  assert.equal(worker.terminated, true);
});

test("layout worker returns only complete finite coordinate maps", async () => {
  const worker = { postMessage() {}, terminate() {} };
  const pending = requestLayout([{ id: "first" }], [], { workerFactory: () => worker });
  worker.onmessage({ data: { positions: { first: { x: 12, y: 24 } } } });
  assert.deepEqual(await pending, { first: { x: 12, y: 24 } });
  const failed = requestLayout([{ id: "first" }], [], { workerFactory: () => worker });
  worker.onmessage({ data: { positions: { missing: { x: 12, y: 24 } } } });
  await assert.rejects(failed);
});
test("compact hierarchy geometry uses display anchors without changing logical ports", () => {
  const ports = Array.from({ length: 200 }, (_, index) => ({ endpoint: `group.pin_${index}`, drives: index >= 100 }));
  const compact = { name: "group", compact: true, ports };
  const geometry = nodeGeometry(compact);
  assert.equal(geometry.initialHeight, 186);
  assert.equal(geometry.handles.length, 2);
  assert.equal(compact.ports.length, 200);
  assert.equal(nodeGeometry({ ...compact, compact: false }).handles.length, 200);
  assert.ok(geometry.handles.every((handle) => handle.y >= 82 && handle.y <= 130));
  assert.equal(sameNodeData(compact, { ...compact, compact: false }), false);
});
import test from "node:test";
import assert from "node:assert/strict";
import { edgeLabelPosition, nodeGeometry, sameNodeData, visibleLabelEdges } from "./performance.js";

test("label visibility excludes empty fanout wrappers without deleting logical edges", () => {
  const nodes = [{ id: "near", position: { x: 20, y: 20 }, initialWidth: 100, initialHeight: 100 },
    { id: "far", position: { x: 10000, y: 10000 }, initialWidth: 100, initialHeight: 100 }];
  const edges = [
    { id: "hidden_source_label", source: "near", target: "far", data: { sourceLabel: false } },
    { id: "visible_source", source: "near", target: "far", data: { sourceLabel: true } },
    { id: "visible_target", source: "far", target: "near", data: { sourceLabel: false } },
    { id: "selected", source: "far", target: "far", selected: true },
  ];
  const visible = visibleLabelEdges(edges, nodes, { x: 0, y: 0, zoom: 1 }, 800, 600);
  assert.deepEqual(visible.map((edge) => edge.id), ["visible_source", "visible_target", "selected"]);
  assert.equal(edges.length, 4);
});

test("node rendering reuse preserves width parameter and callback changes", () => {
  const handler = () => {};
  const original = { name: "unit", module: "counter", parameters: { WIDTH: 8 }, ports: [{ endpoint: "unit.count", width: 8 }], onPin: handler };
  const equivalent = { ...original, parameters: { WIDTH: 8 }, ports: [{ endpoint: "unit.count", width: 8 }] };
  assert.ok(sameNodeData(original, equivalent));
  assert.ok(!sameNodeData(original, { ...equivalent, ports: [{ endpoint: "unit.count", width: 12 }] }));
  assert.ok(!sameNodeData(original, { ...equivalent, parameters: { WIDTH: 12 } }));
  assert.ok(!sameNodeData(original, { ...equivalent, onPin: () => {} }));
  assert.ok(!sameNodeData(original, { ...equivalent, connectable: true }));
});

test("initial geometry matches fixed blocks and independently positioned handles", () => {
  const ports = Array.from({ length: 7 }, (_, index) => ({ endpoint: `unit.port_${index}`, drives: index >= 4 }));
  const geometry = nodeGeometry({ ports });
  assert.equal(geometry.initialWidth, 250);
  assert.equal(geometry.initialHeight, 240);
  assert.equal(geometry.handles.length, 7);
  assert.equal(geometry.handles[0].y, 82);
  assert.equal(geometry.handles[4].y, 82);
  const external = nodeGeometry({ external: true, ports: [{ endpoint: "@clk", drives: true }] });
  assert.equal(external.initialHeight, 59);
  assert.equal(external.handles[0].position, "right");
});

test("short clear link labels stay between pins rather than on the receiver", () => {
  const edge = { sourceX: 495, targetX: 585, sourceY: 220, targetY: 220 };
  const fallback = { x: 575, y: 220 };
  assert.deepEqual(edgeLabelPosition(edge, [], fallback), { x: 540, y: 220 });
  assert.equal(edgeLabelPosition(edge, [{ position: { x: 530, y: 200 }, width: 30, height: 40 }], fallback), fallback);
});