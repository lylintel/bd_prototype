import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { getHeapSnapshot } from "node:v8";
import { commitHistory, createHistory, historyBytes, redoHistory, undoHistory } from "../web/src/history.js";
import { canvasDocument } from "../web/src/semantic/hierarchy.js";

const argument = (name, fallback) => { const index = process.argv.indexOf(name); return index < 0 ? fallback : process.argv[index + 1]; };
const fixture = path.resolve(argument("--fixture", "build/phase4-history-fixture"));
const text = readFileSync(path.join(fixture, "design.json"), "utf8");
const layoutText = readFileSync(path.join(fixture, "design.layout.json"), "utf8");

function initialState() {
  const document = JSON.parse(text);
  assert.equal(document.instances.length, 2000);
  const modules = Object.fromEntries(document.project_ips.map((metadata) => [metadata.id, {
    sources: [metadata.source.path], parameters: {}, ports: Object.fromEntries(metadata.ports.map((port) => [port.name, {
      direction: port.dir === "in" ? "input" : "output", ...(port.range ? { range: port.range } : {}),
    }])),
  }]));
  return { document, design: structuredClone(canvasDocument(document, modules)), layout: JSON.parse(layoutText) };
}

function edit(history, scenario) {
  if (scenario === "position") {
    const state = history.current;
    return commitHistory(history, { ...state, layout: { ...state.layout, nodes: { ...state.layout.nodes,
      unit_0: { ...state.layout.nodes.unit_0, x: state.layout.nodes.unit_0.x + 10 } } } });
  }
  const next = structuredClone(history.current);
  if (scenario === "parameter") {
    next.document.instances[0].params.WIDTH++;
    next.design.instances.unit_0.parameters.WIDTH++;
  } else {
    const net = next.document.nets[0];
    const previous = net.name;
    net.name = previous === "clock_net" ? "renamed_clock" : "clock_net";
    next.design.nets[net.name] = next.design.nets[previous];
    delete next.design.nets[previous];
  }
  return commitHistory(history, next);
}

function validateHistory(history) {
  assert.deepEqual(undoHistory(history).current, initialState());
  assert.deepEqual(redoHistory(undoHistory(history)).current, history.current);
}

async function exclusiveHistoryBytes(history) {
  const collect = (value, objects = new Set(), strings = []) => {
    if (typeof value === "string") strings.push(value);
    if (!value || typeof value !== "object" || objects.has(value)) return { objects, strings };
    objects.add(value);
    for (const [key, child] of Object.entries(value)) { strings.push(key); collect(child, objects, strings); }
    return { objects, strings };
  };
  const current = collect(history.current);
  const stacks = collect(history.past);
  collect(history.future, stacks.objects, stacks.strings);
  globalThis.__bdCurrentData = [...current.objects, ...current.strings];
  globalThis.__bdHistoryData = [...stacks.objects, ...stacks.strings];
  const chunks = [];
  for await (const chunk of getHeapSnapshot()) chunks.push(chunk);
  const snapshot = JSON.parse(Buffer.concat(chunks).toString());
  delete globalThis.__bdCurrentData;
  delete globalThis.__bdHistoryData;
  const meta = snapshot.snapshot.meta;
  const nodeSize = meta.node_fields.length, edgeSize = meta.edge_fields.length;
  const edgeCount = meta.node_fields.indexOf("edge_count"), selfSize = meta.node_fields.indexOf("self_size");
  const edgeType = meta.edge_fields.indexOf("type"), edgeName = meta.edge_fields.indexOf("name_or_index"), edgeTarget = meta.edge_fields.indexOf("to_node");
  const starts = new Map();
  let edgeOffset = 0;
  for (let node = 0; node < snapshot.nodes.length; node += nodeSize) {
    starts.set(node, edgeOffset);
    edgeOffset += snapshot.nodes[node + edgeCount] * edgeSize;
  }
  const outgoing = (node, predicate) => {
    const result = [];
    const begin = starts.get(node);
    for (let offset = begin; offset < begin + snapshot.nodes[node + edgeCount] * edgeSize; offset += edgeSize) {
      const type = meta.edge_types[edgeType][snapshot.edges[offset + edgeType]];
      const name = snapshot.strings[snapshot.edges[offset + edgeName]];
      if (predicate(type, name)) result.push(snapshot.edges[offset + edgeTarget]);
    }
    return result;
  };
  const probe = (name) => {
    for (let offset = 0; offset < snapshot.edges.length; offset += edgeSize) {
      if (meta.edge_types[edgeType][snapshot.edges[offset + edgeType]] === "property" && snapshot.strings[snapshot.edges[offset + edgeName]] === name) {
        return new Set(outgoing(snapshot.edges[offset + edgeTarget], (type) => type === "element"));
      }
    }
    throw new Error("Heap probe not found");
  };
  const storage = (nodes) => new Set([...nodes, ...[...nodes].flatMap((node) => outgoing(node, (type, name) => type === "internal" && ["elements", "properties"].includes(name)))]);
  const shared = storage(probe("__bdCurrentData"));
  const owned = storage(probe("__bdHistoryData"));
  return [...owned].filter((node) => !shared.has(node)).reduce((bytes, node) => bytes + snapshot.nodes[node + selfSize], 0);
}

if (process.argv.includes("--control")) {
  const previous = initialState();
  const bytes = await exclusiveHistoryBytes({ current: structuredClone(previous), past: [previous], future: [] });
  assert.ok(bytes > 100 * 1024);
  console.log(JSON.stringify({ control: "retained_full_snapshot", heap_snapshot_exclusive_bytes: bytes, expected_over_budget: true }));
} else if (process.argv.includes("--child")) {
  assert.equal(typeof globalThis.gc, "function");
  const scenario = argument("--case", "parameter");
  let history = createHistory(initialState());
  for (let count = 0; count < 8; count++) history = edit(history, scenario);
  history = createHistory(initialState());
  globalThis.gc();
  const before = process.memoryUsage().heapUsed;
  history = edit(history, scenario);
  globalThis.gc();
  const heapDelta = process.memoryUsage().heapUsed - before;
  const payloadBytes = historyBytes(history) - historyBytes(createHistory(null));
  validateHistory(history);
  const patches = history.past[0].patches.length;
  const inversePatches = history.past[0].inversePatches.length;
  const exclusiveBytes = await exclusiveHistoryBytes(history);
  globalThis.gc();
  const withHistory = process.memoryUsage().heapUsed;
  history = createHistory(history.current);
  globalThis.gc();
  const retainedStack = withHistory - process.memoryUsage().heapUsed;
  assert.equal(history.current.document.instances.length, 2000);
  console.log(JSON.stringify({ scenario, heap_delta_bytes: heapDelta, retained_stack_bytes: retainedStack, heap_snapshot_exclusive_bytes: exclusiveBytes, encoded_history_growth_bytes: payloadBytes,
    patches, inverse_patches: inversePatches,
    passed: exclusiveBytes > 0 && exclusiveBytes < 100 * 1024 && payloadBytes < 100 * 1024 }));
} else {
  const report = { schema_version: 3, instances: 2000, budget_bytes: 100 * 1024,
    fixture_sha256: createHash("sha256").update(text).digest("hex"),
    source_sha256: createHash("sha256").update(readFileSync(new URL("../web/src/history.js", import.meta.url))).digest("hex"),
    node: process.version, platform: process.platform, cpu: os.cpus()[0].model,
    methodology: "Five fresh processes per edit; eight warmups; V8 heap snapshot self sizes of history data and elements/properties storage excluding data shared with current design; shared VM metadata excluded; raw GC deltas and encoded payload remain separate diagnostics", results: [] };
  for (const scenario of ["parameter", "position", "fanout_rename"]) for (let sample = 1; sample <= 5; sample++) {
    const result = spawnSync(process.execPath, ["--expose-gc", fileURLToPath(import.meta.url), "--child", "--case", scenario, "--fixture", fixture], { encoding: "utf8", timeout: 30000 });
    assert.equal(result.status, 0, result.stderr || String(result.error));
    const value = { ...JSON.parse(result.stdout), sample };
    report.results.push(value);
    console.log(JSON.stringify(value));
  }
  const output = path.resolve(argument("--report", "build/phase4-p46-memory.json"));
  mkdirSync(path.dirname(output), { recursive: true });
  writeFileSync(output, JSON.stringify(report, null, 2) + "\n");
  if (report.results.some((item) => !item.passed)) process.exitCode = 1;
}