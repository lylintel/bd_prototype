import ELK from "elkjs/lib/elk.bundled.js";
import { layoutPositions, makeLayoutGraph } from "./model.js";

const engine = new ELK();
self.onmessage = async (event) => {
  try {
    const result = await engine.layout(makeLayoutGraph(event.data.nodes, event.data.edges));
    self.postMessage({ positions: layoutPositions(result) });
  } catch {
    self.postMessage({ error: true });
  }
};