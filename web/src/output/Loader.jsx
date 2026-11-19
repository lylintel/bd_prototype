import React, { useEffect, useState } from "react";
import { LoaderCircle, RefreshCw } from "lucide-react";
import { t } from "../i18n.js";
import { markOutput } from "../performance.js";

let ready = null;
let pending = null;

export function prepareOutputEditor() {
  if (!pending) {
    markOutput("load-start");
    pending = import("./Editor.jsx").then((module) => { markOutput("load-ready"); ready = module.default; return ready; });
  }
  return pending;
}

export default function OutputLoader(props) {
  const [Editor, setEditor] = useState(() => ready);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (Editor) return;
    let cancelled = false;
    prepareOutputEditor().then((component) => { if (!cancelled) setEditor(() => component); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [Editor, attempt]);
  if (Editor) return <Editor {...props} />;
  return <div className="editor-loading" role={failed ? "alert" : "status"}>{failed ? <>
    <span>{t("output.loadFailed")}</span><button className="icon-button" type="button" title={t("output.retry")} aria-label={t("output.retry")}
      onClick={() => { pending = null; setFailed(false); setAttempt((value) => value + 1); }}><RefreshCw size={16} /></button>
  </> : <LoaderCircle className="spin" aria-label={t("output.loading")} />}</div>;
}