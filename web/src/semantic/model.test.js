import { scopeState, mergeScopeState, bundleHierarchyEdges } from "./hierarchy.js";
import { interfaceHandle, parseInterfaceHandle, projectInterfaceGraph } from "./interfaces.js";

test("interface graph switches between one coarse link and read-only members without changing facts", () => {
  const connection = { name: "link", from: { inst: "first", interface: "m_axis" }, to: { inst: "second", interface: "s_axis" } };
  const source = { name: "m_axis", mode: "master", valid: true, parameters: { DATA_WIDTH: 8 },
    signals: { tdata: { port: "m_data", width: 8 }, tvalid: { port: "m_valid", width: 1 }, tready: { port: "m_ready", width: 1 } } };
  const target = { name: "s_axis", mode: "slave", valid: true, parameters: { DATA_WIDTH: 8 },
    signals: { tdata: { port: "s_data", width: 8 }, tvalid: { port: "s_valid", width: 1 }, tready: { port: "s_ready", width: 1 } } };
  const signals = Object.fromEntries(["tdata", "tvalid", "tready"].map((signal) => [signal, { net: `__bd_if_link__${signal}`, width: signal === "tdata" ? 8 : 1,
    source: signal === "tready" ? { inst: "second", port: "s_ready" } : { inst: "first", port: source.signals[signal].port },
    sink: signal === "tready" ? { inst: "first", port: "m_ready" } : { inst: "second", port: target.signals[signal].port } }]));
  const document = { schema_version: 5, ports: {}, nets: [], interface_connections: [connection] };
  const info = { instances: { first: { m_axis: source }, second: { s_axis: target } }, external: {}, connections: [{ ...connection, signals, valid: true }] };
  const compact = projectInterfaceGraph(document, info);
  assert.equal(compact.edges.length, 1);
  assert.equal(compact.edges[0].data.interfaceConnection, "link");
  assert.equal(compact.edges[0].sourceHandle, interfaceHandle(connection.from));
  assert.equal(compact.hiddenPins.size, 6);
  assert.equal(compact.ports.first[0].drives, true);
  const expanded = projectInterfaceGraph(document, info, ["link"]);
  assert.equal(expanded.edges.length, 3);
  assert.equal(expanded.hiddenPins.size, 0);
  assert.equal(expanded.ownedPins.size, 6);
  assert.deepEqual(parseInterfaceHandle(interfaceHandle(connection.to)), connection.to);
  assert.equal(document.interface_connections[0], connection);
});

test("compact hierarchy bundles keep every distinct electrical net selectable", () => {
  const nodes = [{ id: "first", data: { compact: true } }, { id: "second", data: { compact: true } }];
  const edges = [1, 2, 3].map((value) => ({ id: `edge_${value}`, source: "first", target: "second", data: { net: `net_${value}`, width: value } }));
  const result = bundleHierarchyEdges(edges, nodes);
  assert.equal(result.length, 1);
  assert.deepEqual(result[0].data.bundle.map((edge) => edge.data.net), ["net_1", "net_2", "net_3"]);
  assert.equal(edges.length, 3);
  assert.equal(bundleHierarchyEdges(edges, [{ id: "first", data: { compact: false } }]).length, 3);
});

test("hierarchy scope edits preserve root topology and independent layouts", () => {
  const child = { schema_version: 3, name: "group", ports: {}, instances: [], nets: [] };
  const document = { schema_version: 4, name: "top", ports: {}, instances: [{ name: "first", ip: { id: "group", version: "1.0.0" } }], nets: [], subdesigns: { group: child } };
  const state = { document, design: { name: "top", modules: {}, ports: {}, instances: {}, nets: {} }, layout: { nodes: { first: { x: 10, y: 20 } }, viewport: { x: 0, y: 0, zoom: 1 } } };
  const scoped = scopeState(state, "group");
  assert.equal(scoped.document.name, "group");
  assert.deepEqual(scoped.document.subdesigns, {});
  const next = { ...scoped, document: { ...scoped.document, ports: { clock: { direction: "input" } } }, layout: { ...scoped.layout, nodes: { "@clock": { x: 30, y: 40 } } } };
  const merged = mergeScopeState(state, next, "group");
  assert.deepEqual(merged.document.instances, document.instances);
  assert.deepEqual(merged.document.subdesigns.group.ports, next.document.ports);
  assert.deepEqual(merged.layout.nodes, state.layout.nodes);
  assert.deepEqual(merged.layout.scopes.group.nodes, next.layout.nodes);
  assert.deepEqual(document.subdesigns.group.ports, {});
});

test("hierarchy names do not resolve or overwrite inherited object properties", () => {
  const child = { schema_version: 3, name: "__proto__", ports: {}, instances: [], nets: [] };
  const document = { schema_version: 4, name: "top", ports: {}, instances: [], nets: [], subdesigns: JSON.parse('{"__proto__":null}') };
  document.subdesigns.__proto__ = child;
  const state = { document, design: { modules: {} }, layout: { nodes: {} } };
  assert.equal(scopeState(state, "constructor"), state);
  const scoped = scopeState(state, "__proto__");
  const merged = mergeScopeState(state, { ...scoped, document: { ...scoped.document, ports: { clock: { direction: "input" } } } }, "__proto__");
  assert.ok(Object.hasOwn(merged.design.modules, "__proto__"));
  assert.equal(Object.getPrototypeOf(merged.design.modules), Object.prototype);
});

test("layout-only child updates preserve root logical document identity", () => {
  const document = { schema_version: 4, name: "top", ports: {}, instances: [], nets: [], subdesigns: {
    child: { schema_version: 3, name: "child", ports: {}, instances: [], nets: [] },
  } };
  const state = { document, design: { modules: {} }, layout: { nodes: {} } };
  const scoped = scopeState(state, "child");
  const next = mergeScopeState(state, { ...scoped, layout: { ...scoped.layout, nodes: { block: { x: 2, y: 3 } } } }, "child");
  assert.equal(next.document, state.document);
  assert.equal(next.design, state.design);
});
import test from "node:test";
import assert from "node:assert/strict";
import { editableCanvas, interfaceOwnedPins, syncDocument, parameterValue, diagnosticMessage, normalizeInspection, replaceEndpoint, projectConnections, renameSemantic, scheduleInspection } from "./model.js";

test("v5 editable views never persist derived nets and protect interface members", () => {
  const metadata = { id: "stream", version: "1.1.0", interfaces: [
    { name: "m_axis", signals: { tdata: "m_data", tvalid: "m_valid", tready: "m_ready" } },
    { name: "s_axis", signals: { tdata: "s_data", tvalid: "s_valid", tready: "s_ready" } },
  ] };
  const document = { schema_version: 5, name: "pair", ports: {}, interfaces: [], subdesigns: {}, project_ips: [metadata],
    instances: ["first", "second"].map((name) => ({ name, ip: { id: "stream", version: "1.1.0" }, params: {} })), nets: [],
    interface_connections: [{ name: "link", from: { inst: "first", interface: "m_axis" }, to: { inst: "second", interface: "s_axis" } }] };
  const projected = { name: "pair", modules: {}, ports: {},
    instances: { first: { module: "stream", parameters: {} }, second: { module: "stream", parameters: {} } },
    nets: { __bd_if_link__tdata: ["first.m_data", "second.s_data"] } };
  const editable = editableCanvas(document, projected);
  assert.deepEqual(editable.nets, {});
  assert.ok(interfaceOwnedPins(document, []).has("first.m_data"));
  const changed = syncDocument(document, editable, []);
  assert.deepEqual(changed.interface_connections, document.interface_connections);
  assert.deepEqual(changed.nets, []);
  assert.throws(() => syncDocument(document, { ...editable, nets: { bypass: ["first.m_data", "second.s_data"] } }, []));
  assert.equal(renameSemantic(document, "first", "renamed").interface_connections[0].from.inst, "renamed");
  const removed = syncDocument(document, { ...editable, instances: { second: editable.instances.second } }, []);
  assert.deepEqual(removed.interface_connections, []);
});

test("v5 child interface edits retain their version and are not mistaken for layout-only changes", () => {
  const child = { schema_version: 5, name: "group", ports: {}, instances: [], nets: [], interfaces: [], interface_connections: [] };
  const document = { schema_version: 5, name: "top", ports: {}, instances: [], nets: [], interfaces: [], interface_connections: [], subdesigns: { group: child } };
  const state = { document, design: { modules: {} }, layout: { nodes: {} } };
  const scoped = scopeState(state, "group");
  assert.equal(scoped.document.schema_version, 5);
  const connections = [{ name: "link", from: { inst: "first", interface: "m_axis" }, to: { inst: "second", interface: "s_axis" } }];
  const next = mergeScopeState(state, { ...scoped, document: { ...scoped.document, interface_connections: connections } }, "group");
  assert.equal(next.document.subdesigns.group.schema_version, 5);
  assert.deepEqual(next.document.subdesigns.group.interface_connections, connections);
  assert.deepEqual(child.interface_connections, []);
});

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

for (const version of [4, 5]) test(`v${version} subdesign insertion does not depend on pending inspection metadata`, () => {
  const fields = version === 5 ? { interfaces: [], interface_connections: [] } : {};
  const child = { schema_version: version === 5 ? 5 : 3, name: "group", ports: {}, instances: [], nets: [], ...fields };
  const original = { schema_version: version, name: "top", ports: {}, instances: [], nets: [], subdesigns: { group: child }, ...fields };
  const before = structuredClone(original);
  const canvas = { name: "top", ports: {}, nets: {}, modules: {}, instances: { group_0: { module: "group", parameters: {} } } };
  const changed = syncDocument(original, canvas, []);
  assert.deepEqual(changed.instances, [{ name: "group_0", ip: { id: "group", version: "1.0.0" }, params: {} }]);
  assert.deepEqual(changed.subdesigns, original.subdesigns);
  assert.deepEqual(original, before);
  for (const module of ["missing", "constructor"]) {
    assert.throws(() => syncDocument(original, { ...canvas, instances: { invalid: { module, parameters: {} } } }, []));
  }
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