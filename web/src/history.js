import { Immer, enablePatches, original } from "immer";

enablePatches();
const engine = new Immer({ autoFreeze: false });
const specialKeys = new Set(["__proto__", "constructor", "prototype"]);

function reconcile(draft, source) {
  const before = original(draft);
  if (Object.is(before, source)) return;
  if (!source || typeof source !== "object" || Array.isArray(before) !== Array.isArray(source)) return source;
  if (!Array.isArray(source) && [...Object.keys(before), ...Object.keys(source)].some((key) => specialKeys.has(key) &&
    (Object.hasOwn(before, key) !== Object.hasOwn(source, key) || JSON.stringify(before[key]) !== JSON.stringify(source[key])))) {
    return source;
  }
  const removed = Array.isArray(source) ? [] : Object.keys(before).filter((key) => !Object.hasOwn(source, key));
  const setValue = (key, value) => {
    const prior = before[key];
    if (Object.is(prior, value) && Object.hasOwn(before, key)) return;
    if (!Object.hasOwn(before, key) && value && typeof value === "object" && removed.length === 1 &&
      JSON.stringify(before[removed[0]]) === JSON.stringify(value)) {
      draft[key] = before[removed[0]];
      return;
    }
    if (prior && value && typeof prior === "object" && typeof value === "object" && Array.isArray(prior) === Array.isArray(value)) {
      const replacement = reconcile(draft[key], value);
      if (replacement !== undefined) draft[key] = replacement;
    } else draft[key] = value;
  };
  if (Array.isArray(source)) {
    const shared = Math.min(before.length, source.length);
    for (let index = 0; index < shared; index++) setValue(index, source[index]);
    if (source.length < before.length) draft.splice(source.length);
    else for (let index = shared; index < source.length; index++) draft.push(source[index]);
  } else {
    for (const key of removed) delete draft[key];
    for (const [key, value] of Object.entries(source)) setValue(key, value);
  }
}

export function createHistory(current) {
  return { past: [], current, future: [] };
}

function hasPrototypeData(value) {
  return value && typeof value === "object" && (Object.hasOwn(value, "__proto__") || Object.values(value).some(hasPrototypeData));
}

function replayPatches(state, patches) {
  if (!patches.some((patch) => hasPrototypeData(patch.value))) return engine.applyPatches(state, patches);
  return patches.reduce((current, patch) => {
    if (!hasPrototypeData(patch.value)) return engine.applyPatches(current, [patch]);
    if (!patch.path.length) return structuredClone(patch.value);
    if (patch.path.some((key) => specialKeys.has(key))) throw new Error("Unsafe history path");
    return engine.produce(current, (draft) => {
      const parent = patch.path.slice(0, -1).reduce((value, key) => value[key], draft);
      const key = patch.path.at(-1);
      const value = structuredClone(patch.value);
      if (Array.isArray(parent) && patch.op === "add") parent.splice(Number(key), 0, value);
      else parent[key] = value;
    });
  }, state);
}

export function commitHistory(history, next) {
  const generate = engine.produceWithPatches((draft) => reconcile(draft, next));
  const [current, patches, inversePatches] = generate(history.current);
  if (!patches.length) return history;
  return { past: [...history.past, { patches, inversePatches }].slice(-100), current, future: [] };
}

export function undoHistory(history) {
  const entry = history.past.at(-1);
  if (!entry) return history;
  return { past: history.past.slice(0, -1), current: replayPatches(history.current, entry.inversePatches), future: [entry, ...history.future] };
}

export function redoHistory(history) {
  const entry = history.future[0];
  if (!entry) return history;
  return { past: [...history.past, entry].slice(-100), current: replayPatches(history.current, entry.patches), future: history.future.slice(1) };
}

export function historyBytes(history) {
  return new TextEncoder().encode(JSON.stringify({ past: history.past, future: history.future })).byteLength;
}