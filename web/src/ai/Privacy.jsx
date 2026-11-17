import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ShieldCheck, X } from "lucide-react";
import { t } from "../i18n.js";

export function useAIPrivacy(api, settingsOpen) {
  const apiRef = useRef(api);
  const waiting = useRef(null);
  const dialog = useRef(null);
  const [state, setState] = useState(null);
  const [pending, setPending] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { apiRef.current = api; }, [api]);
  useEffect(() => {
    const controller = new AbortController();
    apiRef.current("/api/ai/settings", undefined, controller.signal).then(setState).catch(() => {});
    return () => controller.abort();
  }, [settingsOpen]);
  useEffect(() => { if (pending) dialog.current?.showModal(); }, [pending]);
  useEffect(() => () => waiting.current?.reject(new Error(t("ai.consentDeclined"))), []);

  async function authorize(provider = "configured") {
    const current = await apiRef.current("/api/ai/settings");
    setState(current);
    if (provider === "configured" && !current.endpoint_configured) throw new Error(t("diagnostic.AI_ENDPOINT_REQUIRED"));
    if (!(provider === "configured" ? current.consent_required : current.copilot_consent_required)) return;
    if (waiting.current) throw new Error(t("ai.consentPending"));
    setError("");
    return new Promise((resolve, reject) => {
      waiting.current = { resolve, reject };
      setPending({ provider, revision: provider === "configured" ? current.endpoint_revision : current.copilot_revision,
        kind: provider === "configured" ? current.endpoint_kind : "copilot" });
    });
  }

  function cancel() {
    waiting.current?.reject(new Error(t("ai.consentDeclined")));
    waiting.current = null;
    setPending(null);
  }

  async function confirm() {
    setBusy(true); setError("");
    try {
      const current = await apiRef.current("/api/ai/consent", { ...pending, confirmed: true });
      setState(current);
      waiting.current?.resolve();
      waiting.current = null;
      setPending(null);
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }

  return { authorize, confirming: Boolean(pending), view: <>
    <div className="ai-disclosure" role="note"><ShieldCheck size={14} /><span>{t("ai.requestDisclosure")}</span><strong>{t(`ai.endpoint.${state?.endpoint_kind ?? "unconfigured"}`)}</strong></div>
    {pending && createPortal(<dialog ref={dialog} className="ai-consent" aria-label={t("ai.consentTitle")} onCancel={(event) => { event.preventDefault(); if (!busy) cancel(); }}>
      <h2>{t("ai.consentTitle")}</h2><p>{t(pending.provider === "copilot" ? "ai.sdkDisclosure" : "ai.requestDisclosure")}</p>
      <strong>{t(`ai.endpoint.${pending.kind}`)}</strong>
      {error && <p role="alert" className="ai-error">{error}</p>}
      <footer><button type="button" className="button" disabled={busy} onClick={cancel}><X size={14} />{t("common.cancel")}</button>
        <button type="button" className="button primary" disabled={busy} onClick={confirm}><Check size={14} />{t("ai.confirmConsent")}</button></footer>
    </dialog>, document.body)}
  </> };
}