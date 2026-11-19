const enabled = typeof location !== "undefined" && new URLSearchParams(location.search).has("perf");
const counters = { node: Object.create(null), edge: Object.create(null) };
if (enabled) Object.defineProperty(globalThis, "__bdPerformance", { value: counters });

export function recordRender(kind, identifier) {
  if (enabled) counters[kind][identifier] = (counters[kind][identifier] ?? 0) + 1;
}

export function markLayout(phase) {
  if (enabled) performance.mark(`bd-layout:${phase}`);
}

export function markOutput(phase, startTime = undefined) {
  if (enabled) performance.mark(`bd-output:${phase}`, Number.isFinite(startTime) && startTime >= 0 && startTime <= performance.now() ? { startTime } : undefined);
}

export function visibleLabelEdges(edges, nodes, viewport, width, height) {
  if (!width || !height) return edges;
  const visible = new Set(nodes.filter((node) => {
    const left = node.position.x * viewport.zoom + viewport.x;
    const top = node.position.y * viewport.zoom + viewport.y;
    const nodeWidth = (node.measured?.width ?? node.initialWidth ?? 250) * viewport.zoom;
    const nodeHeight = (node.measured?.height ?? node.initialHeight ?? 186) * viewport.zoom;
    return left <= width + 120 && left + nodeWidth >= -120 && top <= height + 40 && top + nodeHeight >= -40;
  }).map((node) => node.id));
  return edges.filter((edge) => edge.selected || edge.className?.includes("ai-preview") ||
    visible.has(edge.target) || edge.data?.sourceLabel !== false && visible.has(edge.source));
}

export function sameNodeData(previous, next) {
  if (previous === next) return true;
  if (!previous || !next) return false;
  if (["name", "module", "external", "active", "connectable", "highlight", "onPin", "compact", "foldable", "onTogglePins"].some((key) => previous[key] !== next[key])) return false;
  return (previous.parameters === next.parameters || JSON.stringify(previous.parameters) === JSON.stringify(next.parameters))
    && (previous.ports === next.ports || JSON.stringify(previous.ports) === JSON.stringify(next.ports));
}

export function nodeGeometry(data) {
  const ports = (data.ports ?? []).filter(Boolean);
  const initialWidth = data.external ? 156 : 250;
  const inputs = ports.filter((port) => !port.drives), outputs = ports.filter((port) => port.drives);
  const initialHeight = data.external ? 59 : data.compact ? 186 : 94 + Math.max(92, 26 + Math.max(inputs.length, outputs.length) * 30);
  if (data.compact) return { initialWidth, initialHeight, handles: [
    ...(inputs.length ? [{ id: "~compact-in", type: "target", position: "left", x: -5, y: 101, width: 10, height: 10 }] : []),
    ...(outputs.length ? [{ id: "~compact-out", type: "source", position: "right", x: initialWidth - 5, y: 101, width: 10, height: 10 }] : []),
  ] };
  const handles = ports.map((port) => ({ id: port.endpoint, type: port.drives ? "source" : "target", position: port.drives ? "right" : "left",
    x: port.drives ? initialWidth - 5 : -5, y: data.external ? 24.5 : 82 + (port.drives ? outputs : inputs).indexOf(port) * 30, width: 10, height: 10 }));
  return { initialWidth, initialHeight, handles };
}

export function edgeLabelPosition(edge, nodes, fallback) {
  const distance = edge.targetX - edge.sourceX;
  if (distance <= 0 || distance > 200 || Math.abs(edge.sourceY - edge.targetY) > 2) return fallback;
  const point = { x: (edge.sourceX + edge.targetX) / 2, y: (edge.sourceY + edge.targetY) / 2 };
  const blocked = nodes.some((node) => {
    const width = node.measured?.width ?? node.width ?? node.initialWidth ?? 0;
    const height = node.measured?.height ?? node.height ?? node.initialHeight ?? 0;
    return point.x >= node.position.x && point.x <= node.position.x + width && point.y >= node.position.y && point.y <= node.position.y + height;
  });
  return blocked ? fallback : point;
}