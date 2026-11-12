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
  if (!previous || previous.schema_version !== 2) throw new Error(t("semantic.notReady"));
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
  return { ...structuredClone(previous), name: canvas.name, ports: structuredClone(canvas.ports), instances,
    nets: Object.entries(canvas.nets).map(([name, pins]) => ({ name, endpoints: pins.map(endpointObject) })) };
}