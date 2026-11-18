const enabled = typeof location !== "undefined" && new URLSearchParams(location.search).has("perf");
const counters = { node: Object.create(null), edge: Object.create(null) };
if (enabled) Object.defineProperty(globalThis, "__bdPerformance", { value: counters });

export function recordRender(kind, identifier) {
  if (enabled) counters[kind][identifier] = (counters[kind][identifier] ?? 0) + 1;
}