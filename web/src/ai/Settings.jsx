import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { LoaderCircle, Plug, Save, X } from "lucide-react";
import { t } from "../i18n.js";
import "./ai.css";

export default function Settings({ open, onClose, api }) {
  const [draft, setDraft] = useState(null);
  const [publicState, setPublicState] = useState(null);
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const dialog = useRef(null);
  const apiRef = useRef(api);
  useEffect(() => { apiRef.current = api; }, [api]);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    dialog.current?.showModal();
    setLoading(true);
    setError("");
    setStatus("");
    setModels([]);
    apiRef.current("/api/ai/settings", undefined, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      setPublicState(result);
      setDraft({ ...result.config, api_key: "", clear_api_key: false });
    }).catch((failure) => { if (!controller.signal.aborted) setError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); dialog.current?.close(); };
  }, [open]);

  function close() { setDraft(null); onClose(); }
  function update(name, value) { setDraft((previous) => ({ ...previous, [name]: value })); setStatus(""); }
  async function perform(save) {
    if (!draft) return;
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const result = await api(save ? "/api/ai/settings" : "/api/ai/test", draft);
      if (save) close();
      else { setModels(result.models); setStatus(t("ai.connectionOk", { count: result.models.length })); }
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }

  if (!open) return null;
  return createPortal(<dialog className="ai-settings" ref={dialog} aria-label={t("ai.settings")}
    onCancel={(event) => { if (busy) event.preventDefault(); else close(); }}>
    <form onSubmit={(event) => { event.preventDefault(); perform(true); }}>
      <header><h2>{t("ai.settings")}</h2><button type="button" className="icon-button" title={t("common.close")} aria-label={t("common.close")} disabled={busy} onClick={close}><X size={16} /></button></header>
      <div className="ai-settings-body">
        {loading && <p role="status"><LoaderCircle className="spin" size={16} />{t("ai.loadingSettings")}</p>}
        {error && <p className="ai-error" role="alert">{error}</p>}
        {status && <p className="ai-settings-status" role="status">{status}</p>}
        {draft && <fieldset disabled={loading || busy} className="ai-settings-fields">
          <label className="field-label ai-wide">{t("ai.baseUrl")}<input type="url" aria-label={t("ai.baseUrl")} value={draft.base_url} maxLength={2048} spellCheck={false} onChange={(event) => update("base_url", event.target.value)} /></label>
          <label className="field-label ai-wide">{t("ai.model")}<input aria-label={t("ai.model")} value={draft.model} maxLength={200} list="ai-model-options" spellCheck={false} onChange={(event) => update("model", event.target.value)} />
            <datalist id="ai-model-options">{models.map((model) => <option value={model} key={model} />)}</datalist></label>
          <label className="field-label ai-wide">{t("ai.apiKey")}<input type="password" autoComplete="new-password" aria-label={t("ai.apiKey")} value={draft.api_key} maxLength={4096}
            placeholder={t(publicState?.has_api_key ? "ai.keySet" : "ai.keyUnset")} disabled={draft.clear_api_key} onChange={(event) => update("api_key", event.target.value)} /></label>
          <div className="ai-wide ai-key-state"><span>{t("ai.keyState")}{t(`ai.keySource.${publicState?.key_source ?? "none"}`)}</span>
            <label><input type="checkbox" checked={draft.clear_api_key} onChange={(event) => setDraft((previous) => ({ ...previous, api_key: "", clear_api_key: event.target.checked }))} />{t("ai.clearKey")}</label></div>
          <label className="field-label">{t("ai.temperature")}<input type="number" min="0" max="2" step="0.1" aria-label={t("ai.temperature")} value={draft.temperature}
            onChange={(event) => update("temperature", event.target.value === "" ? "" : event.target.valueAsNumber)} /></label>
          <label className="field-label">{t("ai.timeout")}<input type="number" min="1" max="120" step="1" aria-label={t("ai.timeout")} value={draft.timeout}
            onChange={(event) => update("timeout", event.target.value === "" ? "" : event.target.valueAsNumber)} /></label>
          <label className="field-label ai-wide">{t("ai.contextBudget")}<input type="number" min="512" max="2000000" step="1" aria-label={t("ai.contextBudget")} value={draft.context_token_budget}
            onChange={(event) => update("context_token_budget", event.target.value === "" ? "" : event.target.valueAsNumber)} /></label>
          <label className="field-label ai-wide">{t("ai.structuredMode")}<select aria-label={t("ai.structuredMode")} value={draft.structured_mode} onChange={(event) => update("structured_mode", event.target.value)}>
            <option value="json_schema">{t("ai.modeJsonSchema")}</option><option value="tool">{t("ai.modeTool")}</option></select></label>
          <label className="ai-wide check-field"><input type="checkbox" checked={draft.log_enabled} onChange={(event) => update("log_enabled", event.target.checked)} />{t("ai.logEnabled")}</label>
          <label className="ai-wide check-field"><input type="checkbox" aria-label={t("ai.sendDescriptions")} checked={draft.send_ip_descriptions} onChange={(event) => update("send_ip_descriptions", event.target.checked)} />{t("ai.sendDescriptions")}</label>
        </fieldset>}
      </div>
      <footer><button type="button" className="button" disabled={loading || busy || !draft} onClick={() => perform(false)}><Plug size={14} />{t("ai.testConnection")}</button>
        <div><button type="button" className="button" disabled={busy} onClick={close}>{t("common.cancel")}</button>
          <button type="submit" className="button primary" disabled={loading || busy || !draft}><Save size={14} />{t("ai.saveSettings")}</button></div></footer>
    </form>
  </dialog>, document.body);
}