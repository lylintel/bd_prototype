import { hasMessage, t } from "../i18n.js";

export function parameterValue(text) {
  const value = text.trim();
  if (!value || value.length > 4096) throw new Error(t("semantic.parameterInvalid"));
  const number = Number(value);
  return /^-?\d+$/.test(value) && Number.isSafeInteger(number) && number >= -(2 ** 31) && number < 2 ** 31 ? number : value;
}

export function diagnosticMessage(item) {
  if (typeof item === "string") return item;
  const key = `diagnostic.${item.code}`;
  const params = { ...item.params };
  if (params.reason && hasMessage(`semantic.reason.${params.reason}`)) params.reason = t(`semantic.reason.${params.reason}`);
  const fallback = item.message || t("semantic.unknownDiagnostic", { code: item.code });
  try { return hasMessage(key) ? t(key, params) : fallback; } catch { return fallback; }
}

export function normalizeInspection(result) {
  return { ...result, structuredDiagnostics: (result.diagnostics ?? []).filter((item) => typeof item !== "string"),
    diagnostics: (result.diagnostics ?? []).map(diagnosticMessage) };
}

export function endpointObject(value) {
  if (value.startsWith("@")) return { ext: value.slice(1) };
  const [inst, port] = value.split(".");
  if (!inst || !port) throw new Error(t("semantic.invalidEndpoint"));
  return { inst, port };
}

export function syncDocument(previous, canvas, metadata) {
  if (!previous || ![2, 3].includes(previous.schema_version)) throw new Error(t("semantic.notReady"));
  if ([previous.instances, previous.nets].some((items) => new Set(items.map((item) => item.name)).size !== items.length)) throw new Error(t("semantic.duplicateDraft"));
  const candidates = [...(previous.project_ips ?? []), ...metadata];
  const instances = Object.entries(canvas.instances).map(([name, item]) => {
    let reference = previous.instances.find((instance) => instance.name === name && instance.ip.id === item.module)?.ip;
    if (!reference) {
      const matches = [...new Map(candidates.filter((candidate) => candidate.id === item.module).map((candidate) => [`${candidate.id}@${candidate.version}`, candidate])).values()];
      if (matches.length !== 1) throw new Error(t("semantic.referenceAmbiguous", { name: item.module }));
      reference = { id: matches[0].id, version: matches[0].version };
    }
    return { name, ip: { ...reference }, params: structuredClone(item.parameters ?? {}) };
  });
  const originalNets = new Map(previous.nets.map((net) => [net.name, net]));
  return { ...structuredClone(previous), name: canvas.name, ports: structuredClone(canvas.ports), instances,
    nets: Object.entries(canvas.nets).map(([name, pins]) => {
      const original = originalNets.get(name);
      if (original?.endpoints.some(isExpression)) {
        const projected = [...new Set(original.endpoints.flatMap((endpoint) => endpointPins(endpoint)))];
        if (JSON.stringify(projected) !== JSON.stringify(pins)) throw new Error(t("semantic.expressionEditRequired"));
        return structuredClone(original);
      }
      return { name, endpoints: pins.map(endpointObject) };
    }) };
}

export function isExpression(endpoint) {
  return endpoint && typeof endpoint === "object" && ["slice", "const", "concat"].some((key) => Object.hasOwn(endpoint, key));
}

export function endpointPins(endpoint, depth = 0) {
  if (!endpoint || typeof endpoint !== "object" || depth > 16) return [];
  if (typeof endpoint.inst === "string" && typeof endpoint.port === "string") return [`${endpoint.inst}.${endpoint.port}`];
  if (typeof endpoint.ext === "string") return [`@${endpoint.ext}`];
  return Array.isArray(endpoint.concat) ? endpoint.concat.slice(0, 128).flatMap((child) => endpointPins(child, depth + 1)) : [];
}

export function formatEndpoint(endpoint, depth = 0) {
  if (!endpoint || typeof endpoint !== "object" || depth > 16) return "?";
  if (Object.hasOwn(endpoint, "const")) return String(endpoint.const);
  if (Array.isArray(endpoint.concat)) return `{${endpoint.concat.map((child) => formatEndpoint(child, depth + 1)).join(", ")}}`;
  const key = endpointPins(endpoint)[0] ?? "?";
  return Array.isArray(endpoint.slice) ? `${key}[${endpoint.slice[0]}:${endpoint.slice[1]}]` : key;
}

export function replaceEndpoint(document, name, index, endpoint) {
  const result = structuredClone(document);
  const matches = result.nets.filter((net) => net.name === name);
  if (matches.length !== 1 || !Number.isInteger(index) || index < 0 || index >= matches[0].endpoints.length) throw new Error(t("semantic.invalidEndpoint"));
  result.schema_version = 3;
  matches[0].endpoints[index] = structuredClone(endpoint);
  return result;
}

export function expressionId(name, index) { return `~expression:${name}:${index}`; }

export function renameSemantic(document, before, after, kind = "node") {
  const result = structuredClone(document);
  if (kind === "net") {
    for (const net of result.nets) if (net.name === before) net.name = after;
    return result;
  }
  const external = before.startsWith("@");
  const original = external ? before.slice(1) : before;
  if (external) result.ports = Object.fromEntries(Object.entries(result.ports).map(([name, value]) => [name === original ? after : name, value]));
  else for (const instance of result.instances) if (instance.name === original) instance.name = after;
  function visit(endpoint, depth = 0) {
    if (depth > 16 || !endpoint || typeof endpoint !== "object") return;
    const key = external ? "ext" : "inst";
    if (endpoint[key] === original) endpoint[key] = after;
    if (Array.isArray(endpoint.concat)) endpoint.concat.forEach((child) => visit(child, depth + 1));
  }
  for (const net of result.nets) net.endpoints.forEach((endpoint) => visit(endpoint));
  return result;
}

export function projectConnections(connections, positions) {
  const nodes = [], edges = [], nets = new Set();
  let sourceY = 120, sinkY = 120;
  const pinAnchor = (key) => ({ node: key.startsWith("@") ? key : key.split(".")[0], handle: key });
  for (const connection of connections) {
    if (!connection.endpoints.some((endpoint) => endpoint.expression)) continue;
    nets.add(connection.name);
    const anchor = (endpoint) => endpoint.raw.const !== undefined || endpoint.raw.concat
      ? { node: expressionId(connection.name, endpoint.index), handle: "aggregate" }
      : pinAnchor(endpoint.references[0]?.key ?? endpoint.text);
    function connect(from, to, suffix, width, label = connection.name) {
      edges.push({ id: `${connection.name}|${suffix}`, source: from.node, sourceHandle: from.handle, target: to.node, targetHandle: to.handle,
        type: "circuit", label, data: { net: connection.name, sink: null, width } });
    }
    for (const endpoint of connection.endpoints) {
      if (endpoint.raw.const === undefined && !endpoint.raw.concat) continue;
      const id = expressionId(connection.name, endpoint.index);
      const height = 86 + endpoint.references.length * 20;
      nodes.push({ id, type: "expression", position: positions[id] ?? { x: endpoint.drives ? -260 : 1250, y: endpoint.drives ? sourceY : sinkY },
        data: { ...endpoint, net: connection.name, height, kind: endpoint.raw.const !== undefined ? "constant" : "concat" } });
      if (endpoint.drives) sourceY += height + 50; else sinkY += height + 50;
      endpoint.references.forEach((reference, index) => {
        const member = { node: id, handle: `member-${index}` };
        const pin = pinAnchor(reference.key);
        connect(endpoint.drives ? pin : member, endpoint.drives ? member : pin, `expression:${endpoint.index}:member:${index}`, reference.width,
          `[${reference.bounds[0]}:${reference.bounds[1]}]`);
      });
    }
    const driver = connection.endpoints.find((endpoint) => endpoint.drives) ?? connection.endpoints[0];
    if (!driver) continue;
    for (const sink of connection.endpoints) {
      if (sink === driver) continue;
      const slice = driver.raw.slice ?? sink.raw.slice;
      const label = slice ? `${connection.name} [${slice[0]}:${slice[1]}]` : connection.name;
      connect(anchor(driver), anchor(sink), `endpoint:${sink.index}`, driver.width, label);
    }
  }
  return { nodes, edges, nets };
}