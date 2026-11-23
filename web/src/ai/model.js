import { formatEndpoint } from "../semantic/model.js";
import { projectConnections } from "../semantic/model.js";
import { endpointInfo, externalId } from "../model.js";
import { canonicalDesign } from "../copilot.js";
import { nodeGeometry } from "../performance.js";

const ignorePin = () => {};

export function operationText(operation) {
  switch (operation.op) {
    case "set_param": return `${operation.inst}.${operation.name} = ${operation.value}`;
    case "add_instance": return `${operation.name}: ${operation.ip}@${operation.version} ${JSON.stringify(operation.params ?? {})}`;
    case "remove_instance": return operation.name;
    case "add_external_port": return `${operation.name}: ${JSON.stringify({ dir: operation.dir, width: operation.width, range: operation.range })}`;
    case "connect":
    case "disconnect": return `${formatEndpoint(operation.from)} -> ${formatEndpoint(operation.to)}${operation.net ? ` (${operation.net})` : ""}`;
    default: return JSON.stringify(operation);
  }
}

export function designChanges(before, after) {
  const nodes = {}, nets = {};
  function compare(original, candidate, target, prefix = "") {
    for (const name of new Set([...Object.keys(original ?? {}), ...Object.keys(candidate ?? {})])) {
      if (!Object.hasOwn(candidate ?? {}, name)) target[prefix + name] = "deleted";
      else if (!Object.hasOwn(original ?? {}, name)) target[prefix + name] = "added";
      else if (canonicalDesign(original[name]) !== canonicalDesign(candidate[name])) target[prefix + name] = "modified";
    }
  }
  compare(before.instances, after.instances, nodes);
  compare(before.ports, after.ports, nodes, "@");
  compare(before.nets, after.nets, nets);
  return { nodes, nets };
}

export function candidateGraph(view, positions, positionFor) {
  const design = view.canvas;
  const nodes = [];
  for (const [name, instance] of Object.entries(design.instances)) {
    const definition = design.modules[instance.module];
    nodes.push({ id: name, type: "block", position: positions[name] ?? positionFor(name, design), data: {
      name, module: instance.module, parameters: view.parameters?.[name] ?? instance.parameters ?? {},
      ports: Object.keys(definition?.ports ?? {}).map((port) => endpointInfo(design, `${name}.${port}`, view.interfaces)).filter(Boolean),
    } });
  }
  for (const name of Object.keys(design.ports)) {
    const id = externalId(name);
    nodes.push({ id, type: "block", position: positions[id] ?? positionFor(id, design), data: { name, external: true, ports: [endpointInfo(design, id, view.interfaces)] } });
  }
  const expressions = projectConnections(view.connections ?? [], positions);
  nodes.push(...expressions.nodes);
  const anchor = (endpoint) => {
    const key = endpoint.references[0]?.key;
    return key ? { node: key.startsWith("@") ? key : key.split(".")[0], handle: key } : null;
  };
  const edges = [...expressions.edges];
  for (const net of view.connections ?? []) {
    if (expressions.nets.has(net.name)) continue;
    const driver = net.endpoints.find((endpoint) => endpoint.drives);
    const source = driver && anchor(driver);
    if (!source) continue;
    for (const endpoint of net.endpoints.filter((item) => !item.drives)) {
      const target = anchor(endpoint);
      if (target) edges.push({ id: `${net.name}|${target.handle}`, type: "circuit", source: source.node, sourceHandle: source.handle,
        target: target.node, targetHandle: target.handle, label: net.name, data: { net: net.name, sink: target.handle, width: driver.width } });
    }
  }
  return { nodes: nodes.map((node) => node.type === "block" ? { ...node, ...nodeGeometry(node.data) } : node), edges };
}

export function mergePreview(baseNodes, baseEdges, nextNodes, nextEdges, changes) {
  const colors = { added: "#168767", deleted: "#b7464c", modified: "#ad7719" };
  const nextIds = new Set(nextNodes.map((node) => node.id));
  const baseIds = new Set(baseNodes.map((node) => node.id));
  const basePositions = new Map(baseNodes.map((node) => [node.id, node.position]));
  const addedLeft = Math.max(0, ...baseNodes.map((node) => (node.position?.x ?? 0) + (node.measured?.width ?? 280))) + 100;
  let addedIndex = 0;
  const nodes = [...nextNodes, ...baseNodes.filter((node) => !nextIds.has(node.id))].map((node) => {
    const state = changes.nodes[node.id] ?? (!nextIds.has(node.id) ? "deleted" : !baseIds.has(node.id) ? "added" : "unchanged");
    const position = basePositions.get(node.id) ?? (baseNodes.length ? { x: addedLeft, y: addedIndex++ * 260 } : node.position);
    return { ...node, position, className: `ai-preview-${state}`, draggable: false, connectable: false,
      data: { ...node.data, onPin: ignorePin, connectable: false, highlight: false } };
  });
  const nextEdgeIds = new Set(nextEdges.map((edge) => edge.id));
  const baseEdgeIds = new Set(baseEdges.map((edge) => edge.id));
  const edges = [...nextEdges, ...baseEdges.filter((edge) => !nextEdgeIds.has(edge.id))].map((edge) => {
    const state = !nextEdgeIds.has(edge.id) ? "deleted" : !baseEdgeIds.has(edge.id) ? "added"
      : changes.nets[edge.data?.net] || changes.nodes[edge.source] || changes.nodes[edge.target] ? "modified" : "unchanged";
    return { ...edge, className: `ai-preview-${state}`, style: { stroke: colors[state] ?? "#83948d", strokeWidth: 2, ...(state === "deleted" ? { strokeDasharray: "5 4" } : {}) },
      labelStyle: { fill: colors[state] ?? "#61716b", fontSize: 11 }, labelBgStyle: { fill: "#fff" } };
  });
  return { nodes, edges };
}