import test from "node:test";
import assert from "node:assert/strict";
import { syncDocument, parameterValue, diagnosticMessage, normalizeInspection, replaceEndpoint, projectConnections, renameSemantic, scheduleInspection } from "./model.js";

test("canvas edits retain explicit versions and do not mutate the original", () => {
  const original = { schema_version: 2, name: "top", ports: {}, project_ips: [], instances: [{ name: "unit_0", ip: { id: "unit", version: "2.0.0" }, params: { WIDTH: 8 } }], nets: [] };
  const canvas = { name: "top", ports: {}, modules: { unit: { ports: {}, parameters: {}, sources: [] } }, instances: { unit_0: { module: "unit", parameters: { WIDTH: "4 * 3" } } }, nets: {} };
  const result = syncDocument(original, canvas, []);
  assert.equal(result.instances[0].ip.version, "2.0.0");
  assert.equal(result.instances[0].params.WIDTH, "4 * 3");
  assert.equal(original.instances[0].params.WIDTH, 8);
  assert.throws(() => syncDocument({ ...original, instances: [] }, canvas, [{ id: "unit", version: "1.0.0" }, { id: "unit", version: "2.0.0" }]));
  assert.throws(() => syncDocument({ ...original, instances: [original.instances[0], original.instances[0]] }, canvas, []));
});

test("parameter input preserves expressions and rejects empty or excessive text", () => {
  assert.equal(parameterValue("12"), 12);
  assert.equal(parameterValue("WIDTH * 2"), "WIDTH * 2");
  assert.throws(() => parameterValue(" "));
  assert.throws(() => parameterValue("1".repeat(4097)));
});

test("diagnostic UI uses code and params with message only as fallback", () => {
  const item = { code: "E001", message: "untrusted fallback", params: { source: "a", target: "b", source_width: 8, target_width: 4, reason: "width" } };
  assert.match(diagnosticMessage(item), /a.*8.*b.*4/);
  assert.ok(!diagnosticMessage(item).includes("untrusted fallback"));
  assert.equal(diagnosticMessage({ code: "FUTURE", message: "fallback" }), "fallback");
  const view = normalizeInspection({ diagnostics: [item] });
  assert.equal(view.structuredDiagnostics[0], item);
  assert.equal(view.diagnostics[0], diagnosticMessage(item));
});

test("v3 expression trees survive unrelated canvas parameter edits", () => {
  const expression = { concat: [{ inst: "unit_0", port: "out", slice: [3, 0] }, { const: "4'd0" }] };
  const original = { schema_version: 3, name: "top", ports: { out: { direction: "output", range: [7, 0] } }, project_ips: [],
    instances: [{ name: "unit_0", ip: { id: "unit", version: "1.0.0" }, params: {} }], nets: [{ name: "bus", endpoints: [expression, { ext: "out" }] }] };
  const canvas = { name: "top", ports: original.ports, instances: { unit_0: { module: "unit", parameters: { WIDTH: 8 } } }, nets: { bus: ["unit_0.out", "@out"] } };
  const result = syncDocument(original, canvas, []);
  assert.deepEqual(result.nets[0].endpoints[0], expression);
  assert.deepEqual(original.instances[0].params, {});
  const renamed = renameSemantic(original, "unit_0", "renamed");
  assert.equal(renamed.nets[0].endpoints[0].concat[0].inst, "renamed");
  assert.equal(renamed.nets[0].endpoints[0].concat[1].const, "4'd0");
  assert.equal(renameSemantic(original, "bus", "new_bus", "net").nets[0].name, "new_bus");
  canvas.nets.bus.push("unit_0.other");
  assert.throws(() => syncDocument(original, canvas, []));
});

test("explicit endpoint changes upgrade a copy and expression nodes stay presentation-only", () => {
  const document = { schema_version: 2, name: "top", ports: {}, instances: [], nets: [{ name: "bus", endpoints: [{ ext: "a" }, { ext: "b" }] }] };
  const next = replaceEndpoint(document, "bus", 0, { const: "8'd5" });
  assert.equal(next.schema_version, 3);
  assert.equal(document.schema_version, 2);
  const graph = projectConnections([{ name: "bus", endpoints: [
    { index: 0, raw: { const: "8'd5" }, text: "8'd5", width: 8, drives: true, expression: true, references: [] },
    { index: 1, raw: { ext: "b" }, text: "@b", width: 8, drives: false, references: [{ key: "@b", width: 8, drives: false, bounds: [7, 0] }] },
  ] }], {});
  assert.equal(graph.nodes.length, 1);
  assert.equal(graph.edges.length, 1);
  assert.equal(graph.edges[0].target, "@b");
  assert.equal(next.instances.length, 0);
});

test("inspection coalesces changes with exactly 150ms debounce", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  const requests = [], results = [];
  const schedule = (value) => scheduleInspection(async () => { requests.push(value); return value; }, (value) => results.push(value), assert.fail);
  const cancel = schedule("old");
  context.mock.timers.tick(100);
  cancel();
  const stop = schedule("latest");
  context.mock.timers.tick(149);
  assert.deepEqual(requests, []);
  context.mock.timers.tick(1);
  await Promise.resolve();
  assert.deepEqual(requests, ["latest"]);
  assert.deepEqual(results, ["latest"]);
  stop();
});

test("cancelled in-flight inspections cannot publish stale results or errors", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  const results = [], errors = [];
  let complete, reject, signal;
  const cancel = scheduleInspection((value) => { signal = value; return new Promise((resolve) => { complete = resolve; }); },
    (value) => results.push(value), (error) => errors.push(error));
  context.mock.timers.tick(150);
  cancel();
  assert.equal(signal.aborted, true);
  complete("stale");
  await Promise.resolve();
  const cancelFailure = scheduleInspection(() => new Promise((_, fail) => { reject = fail; }),
    (value) => results.push(value), (error) => errors.push(error));
  context.mock.timers.tick(150);
  cancelFailure();
  reject(new Error("stale failure"));
  await Promise.resolve();
  assert.deepEqual(results, []);
  assert.deepEqual(errors, []);
  scheduleInspection(async () => { throw new Error("current failure"); }, assert.fail, (error) => errors.push(error.message));
  context.mock.timers.tick(150);
  await Promise.resolve();
  assert.deepEqual(errors, ["current failure"]);
});