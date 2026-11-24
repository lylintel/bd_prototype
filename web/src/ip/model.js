import { addInstance, clone, validateDocumentShape } from "../model.js";
import { canonicalDesign } from "../copilot.js";
import { t } from "../i18n.js";

export const IP_DRAG_TYPE = "application/x-bd-ip";
export const AXIS_SIGNALS = ["tdata", "tvalid", "tready", "tkeep", "tstrb", "tlast", "tid", "tdest", "tuser"];

export function interfaceDrafts(record) {
  return structuredClone(record.interfaceDrafts ?? [
    ...(record.metadata.interfaces ?? []).map((declaration) => ({ declaration, confidence: 1, diagnostics: [] })),
    ...(record.interface_candidates ?? []),
  ]);
}

export function interfaceConfirmationError(metadata, declaration) {
  if (!/^[A-Za-z_][A-Za-z0-9_$]*$/.test(declaration.name) || declaration.name.length > 256
    || !["master", "slave"].includes(declaration.mode) || !declaration.parameters.DATA_WIDTH?.trim()
    || ["tdata", "tvalid", "tready"].some((signal) => !declaration.signals[signal])) return t("ip.interfaceIncomplete");
  const claimed = new Set();
  for (const [signal, name] of Object.entries(declaration.signals)) {
    const port = metadata.ports.find((item) => item.name === name);
    const direction = (signal === "tready") === (declaration.mode === "master") ? "in" : "out";
    if (!AXIS_SIGNALS.includes(signal) || !port || port.dir !== direction || port.signed || claimed.has(name)) return t("ip.interfaceDirection");
    claimed.add(name);
  }
  return "";
}

export function updateInterfaceDraft(record, index, patch, { confirm = false, remove = false } = {}) {
  const drafts = interfaceDrafts(record);
  let error = "";
  if (remove) drafts.splice(index, 1);
  else {
    const declaration = { ...drafts[index].declaration, ...structuredClone(patch), confirmed: false };
    if (confirm) {
      error = interfaceConfirmationError(record.metadata, declaration);
      const others = drafts.filter((item, ordinal) => ordinal !== index && item.declaration.confirmed).map((item) => item.declaration);
      const occupied = new Set(others.flatMap((item) => Object.values(item.signals)));
      if (others.some((item) => item.name === declaration.name) || Object.values(declaration.signals).some((port) => occupied.has(port))) error = t("ip.interfaceOverlap");
      declaration.confirmed = !error;
    }
    drafts[index] = { ...drafts[index], declaration, diagnostics: [], confidence: Object.keys(patch).length ? 0 : drafts[index].confidence };
  }
  const metadata = structuredClone(record.metadata);
  metadata.interfaces = drafts.filter((item) => item.declaration.confirmed).map((item) => structuredClone(item.declaration));
  if (metadata.interfaces.length) metadata.schema_version = 2;
  return { ...record, metadata, interfaceDrafts: drafts, interfaceError: error };
}

export function addInterfaceDraft(record) {
  const drafts = interfaceDrafts(record);
  if (drafts.length >= 64) return { ...record, interfaceError: t("ip.interfaceLimit") };
  let ordinal = 0;
  while (drafts.some((item) => item.declaration.name === `axis_${ordinal}`)) ordinal++;
  drafts.push({ confidence: 0, diagnostics: [], declaration: { name: `axis_${ordinal}`, protocol: "axi-stream", definition_version: "1.0.0",
    profile: "ready-valid", mode: "master", parameters: { DATA_WIDTH: "" }, signals: {}, confirmed: false } });
  return { ...record, interfaceDrafts: drafts, interfaceError: "" };
}

export function matchesLibrary(entry, query) {
  const metadata = entry.metadata;
  return [metadata.id, metadata.display_name, ...(metadata.tags ?? []), ...(metadata.ports ?? []).map((port) => port.name)]
    .join(" ").toLowerCase().includes(query.trim().toLowerCase());
}

export function addImported(design, entry) {
  if (!entry?.usable || !entry.definition) throw new Error(t("ip.unavailable"));
  const name = entry.metadata.id;
  if (Object.hasOwn(design.modules, name) && canonicalDesign(design.modules[name]) !== canonicalDesign(entry.definition)) {
    throw new Error(t("ip.conflict", { name }));
  }
  const modules = { ...design.modules, [name]: clone(entry.definition) };
  validateDocumentShape({ ...design, modules });
  design.modules = modules;
  return addInstance(design, name);
}

export function findImportedDrop(text, catalog, baseDir) {
  let reference;
  try { reference = JSON.parse(text); } catch { throw new Error(t("ip.dragInvalid")); }
  if (catalog.baseDir !== baseDir || !reference || typeof reference.id !== "string" || typeof reference.version !== "string") {
    throw new Error(t("ip.dragInvalid"));
  }
  const entry = catalog.entries.find((item) => item.metadata.id === reference.id && item.metadata.version === reference.version);
  if (!entry) throw new Error(t("ip.dragInvalid"));
  return entry;
}

export async function encodeUpload(file) {
  if (!file || typeof file.name !== "string" || !/\.(v|sv)$/i.test(file.name) || file.size > 1024 * 1024) {
    throw new Error(t("ip.fileInvalid"));
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let index = 0; index < bytes.length; index += 32768) {
    binary += String.fromCharCode(...bytes.subarray(index, index + 32768));
  }
  return { name: file.name, content_b64: btoa(binary) };
}

export async function droppedFiles(transfer) {
  const roots = Array.from(transfer.items ?? []).map((item) => item.webkitGetAsEntry?.()).filter(Boolean);
  if (!roots.length) {
    const files = Array.from(transfer.files ?? []);
    if (files.length > 200) throw new Error(t("ip.tooManyFiles"));
    return files;
  }
  const files = [];
  let visited = 0;
  async function visit(entry, depth = 0) {
    if (++visited > 5000 || depth > 32) throw new Error(t("ip.directoryLimit"));
    if (entry.isFile) {
      if (depth && !/\.(v|sv)$/i.test(entry.name)) return;
      files.push(await new Promise((resolve, reject) => entry.file(resolve, reject)));
      if (files.length > 200) throw new Error(t("ip.tooManyFiles"));
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      while (true) {
        const batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
        if (!batch.length) break;
        for (const child of batch) await visit(child, depth + 1);
      }
    }
  }
  for (const root of roots) await visit(root);
  return files;
}

export async function readImportEvents(response, onEvent) {
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || t("ip.httpError", { status: response.status }));
  }
  if (!response.body) throw new Error(t("ip.streamInvalid"));
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;
  function consume(line) {
    if (!line.trim()) return;
    if (line.length > 2 * 1024 * 1024 || completed) throw new Error(t("ip.streamInvalid"));
    let event;
    try { event = JSON.parse(line); } catch { throw new Error(t("ip.streamInvalid")); }
    if (!event || !["file", "ip", "summary"].includes(event.type)) throw new Error(t("ip.streamInvalid"));
    onEvent(event);
    if (event.type === "summary") completed = true;
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let newline;
      while ((newline = buffer.indexOf("\n")) !== -1) {
        consume(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
      }
      if (buffer.length > 2 * 1024 * 1024) throw new Error(t("ip.streamInvalid"));
      if (done) { consume(buffer); break; }
    }
    if (!completed) throw new Error(t("ip.streamEnded"));
  } finally { reader.releaseLock(); }
}

export function originForDefinition(name, definition, entries) {
  return entries.find((entry) => entry.metadata.id === name && entry.definition
    && canonicalDesign(entry.definition) === canonicalDesign(definition))?.origin ?? "manual";
}