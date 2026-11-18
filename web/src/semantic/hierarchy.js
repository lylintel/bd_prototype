import { endpointPins } from "./model.js";
import { t } from "../i18n.js";

const emptyLayout = { nodes: {}, viewport: { x: 0, y: 0, zoom: 1 } };

export function hasSubdesign(document, name) {
  return typeof name === "string" && Object.hasOwn(document?.subdesigns ?? {}, name);
}

export function bundleHierarchyEdges(edges, nodes) {
  const compact = new Set(nodes.filter((node) => node.data.compact).map((node) => node.id));
  if (!compact.size) return edges;
  const groups = new Map(), result = [];
  for (const edge of edges) {
    if (edge.selected || !compact.has(edge.source) || !compact.has(edge.target)) { result.push(edge); continue; }
    const key = JSON.stringify([edge.source, edge.target]);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(edge);
  }
  for (const bundle of groups.values()) {
    if (bundle.length === 1) { result.push(bundle[0]); continue; }
    const first = bundle[0];
    result.push({ ...first, id: `bundle:${first.source}:${first.target}`, label: t("hierarchy.netCount", { count: bundle.length }),
      data: { ...first.data, bundle, width: bundle.reduce((width, edge) => Math.max(width, edge.data.width ?? 1), 1) } });
  }
  return result.map((edge) => ({ ...edge,
    sourceHandle: compact.has(edge.source) ? "~compact-out" : edge.sourceHandle,
    targetHandle: compact.has(edge.target) ? "~compact-in" : edge.targetHandle }));
}

export function canvasDocument(document, modules) {
  const definitions = { ...modules, ...Object.fromEntries(Object.entries(document.subdesigns ?? {}).map(([name, child]) =>
    [name, { sources: [], parameters: {}, ports: child.ports }])) };
  return { name: document.name, modules: definitions, ports: document.ports,
    instances: Object.fromEntries(document.instances.map((item) => [item.name, { module: item.ip.id, parameters: item.params ?? {} }])),
    nets: Object.fromEntries(document.nets.map((net) => [net.name, [...new Set(net.endpoints.flatMap((endpoint) => endpointPins(endpoint)))]])) };
}

export function scopeState(state, scope) {
  if (!scope || !hasSubdesign(state?.document, scope)) return state;
  const definitions = state.document.subdesigns;
  const reachable = new Set();
  function visit(name) {
    if (reachable.has(name) || name === scope || !Object.hasOwn(definitions, name)) return;
    reachable.add(name);
    for (const instance of definitions[name].instances) visit(instance.ip.id);
  }
  for (const instance of definitions[scope].instances) visit(instance.ip.id);
  const document = { ...definitions[scope], schema_version: 4,
    project_ips: state.document.project_ips ?? [], subdesigns: Object.fromEntries([...reachable].map((name) => [name, definitions[name]])) };
  return { design: canvasDocument(document, state.design.modules), document, layout: state.layout.scopes?.[scope] ?? emptyLayout };
}

export function mergeScopeState(state, next, scope) {
  if (!scope) return next;
  const { subdesigns, project_ips, ...body } = next.document;
  const document = { ...state.document, project_ips,
    subdesigns: { ...state.document.subdesigns, ...subdesigns, [scope]: { ...body, name: scope, schema_version: 3 } } };
  const scopedLayout = { nodes: next.layout.nodes, viewport: next.layout.viewport };
  return { ...state, document, design: canvasDocument(document, { ...state.design.modules, ...next.design.modules }),
    layout: { ...state.layout, schema_version: 1, scopes: { ...state.layout.scopes, ...next.layout.scopes, [scope]: scopedLayout } } };
}