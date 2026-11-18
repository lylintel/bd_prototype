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
import { edgeLabelPosition, nodeGeometry, sameNodeData } from "./performance.js";

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