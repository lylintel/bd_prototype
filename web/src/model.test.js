import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { getSmartEdge, smartEdgePresets } from "@tisoap/react-flow-smart-edge";
import { addInstance, clone, connectionError, connectPorts, deleteNode, disconnectPort, makeExternal, parseInteger, renameNet, renameNode, validateDocumentShape } from "./model.js";

const example = JSON.parse(readFileSync(new URL("../../examples/counter_compare.json", import.meta.url), "utf8"));
const exampleInterfaces = { instances: {
  counter_0: { count: { direction: "output", range: [7, 0], signed: false, width: 8 } },
  compare_0: { value: { direction: "input", range: [7, 0], signed: false, width: 8 } },
} };

test("fanout extends one net and rejects another driver", () => {
  const design = clone(example);
  const name = addInstance(design, "compare_eq");
  const interfaces = clone(exampleInterfaces);
  interfaces.instances[name] = clone(interfaces.instances.compare_0);
  assert.equal(connectionError(design, "counter_0.count", `${name}.value`, interfaces), null);
  assert.equal(connectPorts(design, "counter_0.count", `${name}.value`, interfaces), "count_bus");
  assert.equal(connectPorts(design, `${name}.value`, "counter_0.count", interfaces), "count_bus");
  assert.equal(Object.keys(design.nets).length, 4);
  assert.deepEqual(design.nets.count_bus, ["counter_0.count", "compare_0.value", `${name}.value`]);
  assert.throws(() => connectPorts(design, "@clk", "@rst"), /驱动端/);
  assert.throws(() => connectPorts(design, "@clk", "compare_0.value"), /已连接/);
});

test("disconnect and node deletion remove dangling references", () => {
  const design = clone(example);
  disconnectPort(design, "compare_0.value");
  assert.equal(design.nets.count_bus, undefined);
  connectPorts(design, "compare_0.value", "counter_0.count", exampleInterfaces);
  deleteNode(design, "counter_0");
  assert.equal(design.instances.counter_0, undefined);
  assert.deepEqual(design.nets, { match_net: ["compare_0.match", "@match"] });
});

test("renaming updates net endpoints and independent layout", () => {
  const design = clone(example);
  const layout = { nodes: { counter_0: { x: 10, y: 20 } } };
  renameNode(design, layout, "counter_0", "counter_main");
  assert.equal(design.nets.count_bus[0], "counter_main.count");
  assert.deepEqual(layout.nodes.counter_main, { x: 10, y: 20 });
  assert.equal(layout.nodes.counter_0, undefined);
  renameNode(design, layout, "@clk", "sys_clk");
  assert.equal(design.nets.clk_net[0], "@sys_clk");
  renameNet(design, "count_bus", "value_bus");
  assert.deepEqual(design.nets.value_bus, ["counter_main.count", "compare_0.value"]);
  assert.throws(() => renameNode(design, layout, "counter_main", "match"), /已被使用/);
});

test("make external preserves resolved ascending vector and signedness", () => {
  const design = clone(example);
  design.modules.counter.ports.count = { direction: "output", range: [0, "WIDTH - 1"], signed: true };
  delete design.nets.count_bus;
  const interfaces = { instances: { counter_0: { count: { direction: "output", range: [0, 7], signed: true, width: 8 } } } };
  const id = makeExternal(design, "counter_0.count", interfaces);
  assert.equal(id, "@count");
  assert.deepEqual(design.ports.count, { direction: "output", range: [0, 7], signed: true });
  assert.deepEqual(design.nets.count_net, ["counter_0.count", "@count"]);
});

test("integer editing never silently truncates or coerces input", () => {
  assert.equal(parseInteger("19"), 19);
  for (const value of ["", "1.5", "1e3", "WIDTH", "2147483648"]) assert.throws(() => parseInteger(value));
});

test("direct self feedback is accepted by the editing model", () => {
  const design = { name: "feedback", modules: { register: { ports: { data: { direction: "input" }, state: { direction: "output" } } } }, instances: { state_0: { module: "register" } }, ports: {}, nets: {} };
  connectPorts(design, "state_0.state", "state_0.data");
  assert.deepEqual(design.nets.state_net, ["state_0.state", "state_0.data"]);
});

test("literal vector connections enforce range and signedness before mutation", () => {
  for (const sink of [
    { direction: "input", range: [3, 0] },
    { direction: "input", range: [0, 7] },
    { direction: "input", range: [7, 0], signed: true },
  ]) {
    const design = clone(example);
    delete design.nets.count_bus;
    design.modules.counter.ports.count.range = [7, 0];
    design.modules.compare_eq.ports.value = sink;
    const before = clone(design);
    assert.throws(() => connectPorts(design, "counter_0.count", "compare_0.value"), /位宽|索引|符号/);
    assert.deepEqual(design, before);
  }
});

test("unresolved parameterized ports cannot bypass connection checks", () => {
  const design = clone(example);
  delete design.nets.count_bus;
  assert.throws(() => connectPorts(design, "counter_0.count", "compare_0.value"), /解析/);
  assert.equal(Object.keys(design.nets).length, 3);
});

test("malformed endpoints and unsupported port directions are rejected", () => {
  const design = clone(example);
  delete design.nets.match_net;
  assert.throws(() => connectPorts(design, "compare_0.match.extra", "@match"), /端点/);
  design.ports.match.direction = "inout";
  assert.throws(() => connectPorts(design, "compare_0.match", "@match"), /方向/);
});

test("disconnecting a fanout driver releases every sink", () => {
  const design = clone(example);
  const name = addInstance(design, "compare_eq");
  design.nets.count_bus.push(`${name}.value`);
  disconnectPort(design, "counter_0.count");
  assert.equal(design.nets.count_bus, undefined);
  assert.ok(design.instances.compare_0);
  assert.ok(design.instances[name]);
});

test("orthogonal fanout routes around intervening blocks", () => {
  const nodes = [
    { id: "source", position: { x: 0, y: 0 }, measured: { width: 250, height: 150 }, data: {} },
    { id: "obstacle", position: { x: 350, y: 0 }, measured: { width: 250, height: 150 }, data: {} },
    { id: "sink", position: { x: 700, y: 0 }, measured: { width: 250, height: 150 }, data: {} },
  ];
  const route = getSmartEdge({ nodes, sourceX: 250, sourceY: 70, targetX: 700, targetY: 70,
    sourcePosition: "right", targetPosition: "left",
    options: { drawEdge: smartEdgePresets.step.drawEdge, generatePath: smartEdgePresets.step.generatePath, nodePadding: 14, gridRatio: 10 } });
  assert.ok(!(route instanceof Error));
  const points = [[250, 70], ...route.points, [700, 70]];
  for (let index = 1; index < points.length; index++) {
    const [startX, startY] = points[index - 1];
    const [endX, endY] = points[index];
    assert.ok(startX === endX || startY === endY, "route must remain orthogonal");
    const crosses = startX === endX
      ? startX > 350 && startX < 600 && Math.max(startY, endY) > 0 && Math.min(startY, endY) < 150
      : startY > 0 && startY < 150 && Math.max(startX, endX) > 350 && Math.min(startX, endX) < 600;
    assert.equal(crosses, false, "route must not cross the middle block");
  }
});

test("malformed imported documents are rejected before reaching the canvas", () => {
  assert.equal(validateDocumentShape(clone(example)).name, "example_bd");
  const design = clone(example);
  design.nets.count_bus = "invalid";
  assert.throws(() => validateDocumentShape(design), /网络必须/);
  for (const mutate of [
    (data) => { data.ports.clk = null; },
    (data) => { data.modules.counter.parameters.WIDTH = null; },
    (data) => { data.modules.counter.parameters.WIDTH.default = {}; },
    (data) => { data.modules.counter.sources = [{}]; },
    (data) => { data.modules.counter.ports.clk.direction = {}; },
    (data) => { data.instances.counter_0.parameters = []; },
  ]) {
    const malformed = clone(example);
    mutate(malformed);
    assert.throws(() => validateDocumentShape(malformed));
  }
});