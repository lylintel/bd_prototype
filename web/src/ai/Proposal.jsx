import React, { useState } from "react";
import { Check, X } from "lucide-react";
import { hasMessage, t } from "../i18n.js";
import { diagnosticMessage } from "../semantic/model.js";
import { operationText } from "./model.js";
import "./ai.css";

export default function Proposal({ proposal, busy = false, onAccept, onDiscard }) {
  const [selected, setSelected] = useState(() => proposal.ops.map((operation, index) => index));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function perform(action) {
    setPending(true);
    setError("");
    try { await action(); }
    catch (failure) { setError(failure.message); }
    finally { setPending(false); }
  }
  return <section className="ai-proposal" aria-label={t("ai.proposalTitle")}>
    <header><strong>{t("ai.proposalTitle")}</strong><span>{t(proposal.valid ? "ai.pending" : "ai.invalid")}</span></header>
    {proposal.summary && <p className="ai-summary">{proposal.summary}</p>}
    <div className="ai-operation-count">{t("ai.operationCount", { count: selected.length })}</div>
    <ol className="ai-operations">{proposal.ops.map((operation, index) => <li key={index}>
      <label><input type="checkbox" aria-label={t("ai.selectOperation", { index: index + 1 })} checked={selected.includes(index)} disabled={busy || pending}
        onChange={(event) => setSelected((previous) => event.target.checked ? [...previous, index].sort((left, right) => left - right) : previous.filter((value) => value !== index))} />
        <span>{hasMessage(`ai.op.${operation.op}`) ? t(`ai.op.${operation.op}`) : operation.op}</span><code>{operationText(operation)}</code></label>
    </li>)}</ol>
    {!proposal.ops.length && <p>{t("ai.empty")}</p>}
    {proposal.diagnostics?.length > 0 && <div className="ai-proposal-diagnostics">{proposal.diagnostics.map((item, index) =>
      <p className={item.severity === "error" ? "ai-error" : "ai-warning"} key={index}>{diagnosticMessage(item)}</p>)}</div>}
    {error && <p className="ai-error" role="alert">{error}</p>}
    <footer><button type="button" className="button" disabled={busy || pending} onClick={() => perform(() => onDiscard(proposal))}><X size={14} />{t("ai.discard")}</button>
      <button type="button" className="button primary" disabled={busy || pending || !proposal.valid || !selected.length}
        onClick={() => perform(() => onAccept(proposal, selected))}><Check size={14} />{t("ai.accept")}</button></footer>
  </section>;
}