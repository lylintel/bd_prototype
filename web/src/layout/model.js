export function makeLayoutGraph(nodes, edges) {
  const identifiers = new Set(nodes.map((node) => node.id));
  const pairs = new Set();
  return { id: "~layout", layoutOptions: {
    "elk.algorithm": nodes.length > 500 ? "rectpacking" : "layered", "elk.direction": "RIGHT", "elk.spacing.nodeNode": nodes.length > 500 ? "120" : "44",
    "elk.layered.spacing.nodeNodeBetweenLayers": "100",
    "elk.layered.crossingMinimization.strategy": nodes.length > 500 ? "NONE" : "LAYER_SWEEP",
    "elk.layered.nodePlacement.strategy": nodes.length > 500 ? "SIMPLE" : "NETWORK_SIMPLEX",
    "elk.layered.layering.strategy": nodes.length > 500 ? "LONGEST_PATH" : "NETWORK_SIMPLEX",
  }, children: nodes.map((node) => ({ id: node.id, width: node.measured?.width ?? node.initialWidth ?? 250,
    height: node.measured?.height ?? node.initialHeight ?? 186 })),
  edges: edges.filter((edge) => {
    if (!identifiers.has(edge.source) || !identifiers.has(edge.target)) return false;
    const pair = JSON.stringify([edge.source, edge.target]);
    if (pairs.has(pair)) return false;
    pairs.add(pair);
    return true;
  }).map((edge, index) => ({ id: `~edge:${index}`, sources: [edge.source], targets: [edge.target] })) };
}

export function layoutPositions(graph) {
  const positions = Object.fromEntries((graph.children ?? []).map((node) => {
    if (typeof node.id !== "string" || ![node.x, node.y].every((value) => Number.isFinite(value) && Math.abs(value) <= 1e7)) throw new Error("Invalid layout position");
    return [node.id, { x: node.x, y: node.y }];
  }));
  if (Object.keys(positions).length !== (graph.children ?? []).length) throw new Error("Duplicate layout position");
  return positions;
}