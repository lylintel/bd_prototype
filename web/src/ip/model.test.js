import test from "node:test";
import assert from "node:assert/strict";
import { addImported, droppedFiles, encodeUpload, findImportedDrop, matchesLibrary, originForDefinition, readImportEvents } from "./model.js";

const entry = {
  metadata: { id: "pulse", version: "1.0.0", display_name: "Pulse", tags: ["timer"], ports: [{ name: "ready" }] },
  usable: true,
  definition: { sources: ["ip_library/pulse/1.0.0/src/pulse.v"], parameters: {}, ports: { ready: { direction: "output" } } },
};
const empty = () => ({ name: "test_bd", modules: {}, instances: {}, ports: {}, nets: {} });

test("library search includes names tags and port names", () => {
  for (const query of ["pulse", "TIMER", "ready", ""]) assert.equal(matchesLibrary(entry, query), true);
  assert.equal(matchesLibrary(entry, "missing"), false);
});

test("import adds an independent definition and instance without replacing a conflict", () => {
  const design = empty();
  assert.equal(addImported(design, entry), "pulse_0");
  assert.equal(addImported(design, entry), "pulse_0_0");
  assert.notEqual(design.modules.pulse, entry.definition);
  design.modules.pulse.sources = ["other.v"];
  const before = structuredClone(design);
  assert.throws(() => addImported(design, entry));
  assert.deepEqual(design, before);
  assert.throws(() => addImported(empty(), { ...entry, usable: false }));
});

test("imported names cannot change object prototypes", () => {
  const design = empty();
  addImported(design, { ...entry, metadata: { ...entry.metadata, id: "__proto__" } });
  assert.equal(Object.getPrototypeOf(design.modules), Object.prototype);
  assert.equal(Object.hasOwn(design.modules, "__proto__"), true);
});

test("drag references must match the current catalog and source base", () => {
  const catalog = { baseDir: "examples", entries: [entry] };
  const payload = JSON.stringify({ id: "pulse", version: "1.0.0" });
  assert.equal(findImportedDrop(payload, catalog, "examples"), entry);
  assert.throws(() => findImportedDrop(payload, catalog, "designs"));
  assert.throws(() => findImportedDrop("{}", catalog, "examples"));
  assert.throws(() => findImportedDrop("invalid", catalog, "examples"));
});

test("uploads preserve bytes and reject oversized files before reading", async () => {
  const upload = await encodeUpload(new File(["module unit; endmodule\n"], "unit.v"));
  assert.equal(upload.name, "unit.v");
  assert.equal(atob(upload.content_b64), "module unit; endmodule\n");
  await assert.rejects(() => encodeUpload(new File(["x"], "unit.txt")));
  await assert.rejects(() => encodeUpload({ name: "large.v", size: 1024 * 1024 + 1, arrayBuffer: () => { throw new Error("must not read"); } }));
});

test("import stream handles split UTF-8 and requires a summary", async () => {
  const text = JSON.stringify({ type: "ip", status: "preview", id: "模块" }) + "\n" + JSON.stringify({ type: "summary", counts: { preview: 1 } }) + "\n";
  const bytes = new TextEncoder().encode(text);
  const events = [];
  const response = new Response(new ReadableStream({ start(controller) {
    for (let index = 0; index < bytes.length; index += 2) controller.enqueue(bytes.slice(index, index + 2));
    controller.close();
  } }));
  await readImportEvents(response, (event) => events.push(event));
  assert.equal(events[0].id, "模块");
  assert.equal(events.at(-1).counts.preview, 1);
  await assert.rejects(() => readImportEvents(new Response('{"type":"file"}\n'), () => {}));
  await assert.rejects(() => readImportEvents(new Response('{"error":"denied"}', { status: 403 }), () => {}));
});

test("directory drops traverse batches and include only RTL files", async () => {
  const file = (name) => ({ isFile: true, name, file: (done) => done(new File(["module unit; endmodule"], name)) });
  const directory = (children) => ({ isDirectory: true, createReader() {
    let sent = false;
    return { readEntries(done) { done(sent ? [] : children); sent = true; } };
  } });
  const root = directory([file("first.v"), directory([file("second.sv"), file("README.md")])]);
  const files = await droppedFiles({ items: [{ webkitGetAsEntry: () => root }], files: [] });
  assert.deepEqual(files.map((item) => item.name), ["first.v", "second.sv"]);
  const excessive = directory(Array.from({ length: 201 }, (_, index) => file(`unit_${index}.v`)));
  await assert.rejects(() => droppedFiles({ items: [{ webkitGetAsEntry: () => excessive }], files: [] }));
});

test("source badges require a matching definition rather than just a name", () => {
  const rows = [{ ...entry, origin: "imported" }];
  assert.equal(originForDefinition("pulse", entry.definition, rows), "imported");
  assert.equal(originForDefinition("pulse", { ...entry.definition, sources: ["manual.v"] }, rows), "manual");
});