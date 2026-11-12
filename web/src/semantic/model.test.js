import test from "node:test";
import assert from "node:assert/strict";
import { syncDocument, parameterValue, diagnosticMessage, normalizeInspection } from "./model.js";

test("canvas edits retain explicit versions and do not mutate the original", () => {
  const original = { schema_version: 2, name: "top", ports: {}, project_ips: [], instances: [{ name: "unit_0", ip: { id: "unit", version: "2.0.0" }, params: { WIDTH: 8 } }], nets: [] };
  const canvas = { name: "top", ports: {}, modules: { unit: { ports: {}, parameters: {}, sources: [] } }, instances: { unit_0: { module: "unit", parameters: { WIDTH: "4 * 3" } } }, nets: {} };
  const result = syncDocument(original, canvas, []);
  assert.equal(result.instances[0].ip.version, "2.0.0");
  assert.equal(result.instances[0].params.WIDTH, "4 * 3");
  assert.equal(original.instances[0].params.WIDTH, 8);
  assert.throws(() => syncDocument({ ...original, instances: [] }, canvas, [{ id: "unit", version: "1.0.0" }, { id: "unit", version: "2.0.0" }]));
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