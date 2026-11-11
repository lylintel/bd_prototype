import { addInstance, clone, validateDocumentShape } from "../model.js";
import { canonicalDesign } from "../copilot.js";
import { t } from "../i18n.js";

export const IP_DRAG_TYPE = "application/x-bd-ip";

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