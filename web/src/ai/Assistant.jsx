import React, { useState } from "react";
import { createPortal } from "react-dom";
import { LoaderCircle, Send, Settings2, Sparkles, X } from "lucide-react";
import { t } from "../i18n.js";
import Proposal from "./Proposal.jsx";

export default function Assistant({ open, onClose, onSettings, onGenerate, onAccept, onSelect, onPreview, api }) {
  const [prompt, setPrompt] = useState("");
  const [allowRemovals, setAllowRemovals] = useState(false);
  const [proposal, setProposal] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function generate(event) {
    event.preventDefault();
    if (!prompt.trim() || busy) return;
    setBusy(true); setError("");
    try { setProposal(await onGenerate(prompt.trim(), allowRemovals)); }
    catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }
  async function discard(value) {
    await api("/api/ops/discard", { proposal_id: value.id });
    setProposal(null); onPreview(null);
  }
  async function close() {
    if (busy) return;
    try { if (proposal) await discard(proposal); onClose(); }
    catch (failure) { setError(failure.message); }
  }
  async function accept(value, selected) {
    if (await onAccept(value, selected)) { setProposal(null); onPreview(null); }
  }
  if (!open) return null;
  return createPortal(<aside className="ai-assistant" aria-label={t("ai.assistant")}>
    <header><Sparkles size={18} /><strong>{t("ai.assistant")}</strong>
      <button type="button" className="icon-button" aria-label={t("ai.settings")} title={t("ai.settings")} onClick={onSettings}><Settings2 size={16} /></button>
      <button type="button" className="icon-button" aria-label={t("ai.closeAssistant")} title={t("ai.closeAssistant")} disabled={busy} onClick={close}><X size={16} /></button></header>
    {error && <p className="ai-error" role="alert">{error}</p>}
    {proposal ? <Proposal key={proposal.id} proposal={proposal} busy={busy} onAccept={accept} onDiscard={discard} onSelect={onSelect} />
      : <form className="ai-request" onSubmit={generate}>
        <label className="field-label">{t("ai.prompt")}<textarea aria-label={t("ai.prompt")} rows={7} maxLength={8000} value={prompt} disabled={busy} onChange={(event) => setPrompt(event.target.value)} /></label>
        <label className="check-field"><input type="checkbox" aria-label={t("ai.allowRemovals")} checked={allowRemovals} disabled={busy} onChange={(event) => setAllowRemovals(event.target.checked)} />{t("ai.allowRemovals")}</label>
        <button className="button primary" type="submit" disabled={busy || !prompt.trim()}>{busy ? <LoaderCircle size={14} className="spin" /> : <Send size={14} />}{t(busy ? "ai.generating" : "ai.generateProposal")}</button>
      </form>}
  </aside>, document.body);
}