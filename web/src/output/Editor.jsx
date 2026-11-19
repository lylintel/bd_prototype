import React, { memo, useLayoutEffect, useRef } from "react";
import { EditorView } from "@codemirror/view";
import { Transaction } from "@codemirror/state";
import { createOutputState } from "./model.js";
import { markOutput } from "../performance.js";

markOutput("module-evaluated");

function OutputEditor({ value, language = "verilog", readOnly = true, label, cacheKey, cache, onChange = undefined }) {
  const host = useRef(null);
  const editor = useRef(null);
  const key = `${language}:${readOnly}:${cacheKey}`;
  useLayoutEffect(() => {
    markOutput("construct-start");
    const entry = cache.get(key) ?? {};
    entry.onChange = onChange;
    const state = entry.state ?? createOutputState(value, { language, readOnly, label, onChange: (text) => entry.onChange?.(text) });
    const view = new EditorView({ state, parent: host.current });
    markOutput("mounted");
    let paintedFrame;
    const markReady = () => view.requestMeasure({ read: () => null, write: () => {
      paintedFrame = requestAnimationFrame(() => markOutput("painted"));
    } });
    editor.current = { view, entry };
    cache.delete(key);
    cache.set(key, entry);
    if (cache.size > 8) cache.delete(cache.keys().next().value);
    const frame = entry.scrollTop || entry.scrollLeft ? requestAnimationFrame(() => {
      view.scrollDOM.scrollTop = entry.scrollTop ?? 0;
      view.scrollDOM.scrollLeft = entry.scrollLeft ?? 0;
      view.requestMeasure();
      markReady();
    }) : null;
    if (frame === null) markReady();
    const observer = new MutationObserver(() => view.requestMeasure());
    const panel = host.current.closest(".output-window");
    if (panel) observer.observe(panel, { attributes: true, attributeFilter: ["style"] });
    return () => {
      if (paintedFrame !== undefined) cancelAnimationFrame(paintedFrame);
      if (frame !== null) cancelAnimationFrame(frame);
      observer.disconnect();
      entry.state = view.state;
      entry.scrollTop = view.scrollDOM.scrollTop;
      entry.scrollLeft = view.scrollDOM.scrollLeft;
      view.destroy();
      editor.current = null;
    };
  }, [cache, key, language, readOnly, label]);
  useLayoutEffect(() => {
    const current = editor.current;
    if (!current) return;
    current.entry.onChange = onChange;
    if (current.view.state.doc.toString() !== value) current.view.dispatch({
      changes: { from: 0, to: current.view.state.doc.length, insert: value },
      annotations: Transaction.addToHistory.of(false),
    });
  }, [value, onChange]);
  return <div className="virtual-code-editor" ref={host} />;
}

export default memo(OutputEditor);