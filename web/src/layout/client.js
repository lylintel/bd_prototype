import { t } from "../i18n.js";

export async function publishPositions(positions, applyBatch, { signal = undefined,
  nextFrame = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))) } = {}) {
  const entries = Object.entries(positions);
  for (let offset = 0; offset < entries.length; offset += 8) {
    await nextFrame();
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    applyBatch(Object.fromEntries(entries.slice(offset, offset + 8)));
  }
  await nextFrame();
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
}

export function requestLayout(nodes, edges, { signal = undefined, workerFactory = () => new Worker(new URL("./worker.js", import.meta.url), { type: "module" }) } = {}) {
  if (signal?.aborted) return Promise.reject(new DOMException("Aborted", "AbortError"));
  return new Promise((resolve, reject) => {
    const worker = workerFactory();
    const expected = new Set(nodes.map((node) => node.id));
    let settled = false;
    const finish = (error, result = undefined) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      worker.terminate();
      if (error) reject(error); else resolve(result);
    };
    const abort = () => finish(new DOMException("Aborted", "AbortError"));
    const timer = setTimeout(() => finish(new Error(t("layout.timeout"))), 120000);
    signal?.addEventListener("abort", abort, { once: true });
    worker.onerror = () => finish(new Error(t("layout.failed")));
    worker.onmessage = (event) => {
      const positions = event.data?.positions;
      if (event.data?.error || !positions || Object.keys(positions).length !== expected.size ||
        !Object.entries(positions).every(([name, point]) => expected.has(name) && [point?.x, point?.y].every((value) => Number.isFinite(value) && Math.abs(value) <= 1e7))) {
        finish(new Error(t("layout.failed")));
      } else finish(null, positions);
    };
    try {
      worker.postMessage({ nodes: nodes.map((node) => ({ id: node.id, initialWidth: node.measured?.width ?? node.initialWidth,
        initialHeight: node.measured?.height ?? node.initialHeight })),
      edges: edges.map((edge) => ({ source: edge.source, target: edge.target })) });
    } catch (error) { finish(error); }
  });
}