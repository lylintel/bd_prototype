import React, { useState } from "react";
import { Check, X } from "lucide-react";
import { hasMessage, t } from "../i18n.js";
import { diagnosticMessage } from "../semantic/model.js";
import { operationMembers, operationText } from "./model.js";
import "./ai.css";

export default function Proposal({ proposal, busy = false, onAccept, onDiscard, onSelect = null }) {
  const [selected, setSelected] = useState(() => proposal.ops.map((operation, index) => index));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [view, setView] = useState(proposal);
  const [checking, setChecking] = useState(false);
  async function selectionChanged(next) {
    setSelected(next);
    if (!onSelect) return;
    setChecking(true); setError("");
    try { setView(await onSelect(proposal, next)); }
    catch (failure) { setError(failure.message); setView((previous) => ({ ...previous, valid: false })); }
    finally { setChecking(false); }
  }
  async function perform(action) {
    setPending(true);
    setError("");
    try { await action(); }
    catch (failure) { setError(failure.message); }
    finally { setPending(false); }
  }
  return <section className="ai-proposal" aria-label={t("ai.proposalTitle")}>
    <header><strong>{t("ai.proposalTitle")}</strong><span>{t(proposal.valid && view.valid ? "ai.pending" : "ai.invalid")}</span></header>
    {proposal.summary && <p className="ai-summary">{proposal.summary}</p>}
    <p className="ai-operation-count">{t("ai.currentScope", { name: proposal.scope || proposal.document.name })}</p>
    {proposal.migration && <p className="ai-warning" role="status">{t("ai.schemaMigration", proposal.migration)}</p>}
    {proposal.context?.scope === "subgraph" && <p className="ai-warning" role="status">{t("ai.subgraphOnly", { count: proposal.context.included_instances.length, total: proposal.context.totals.instances })}</p>}
    {proposal.attempts > 0 && <p className="ai-operation-count">{t("ai.attempts", { count: proposal.attempts })}</p>}
    {["assumptions", "questions", "missing_ip"].map((field) => proposal[field]?.length > 0 && <div className="ai-notes" key={field}><strong>{t(`ai.${field}`)}</strong><ul>{proposal[field].map((value, index) => <li key={index}>{value}</li>)}</ul></div>)}
    <div className="ai-operation-count">{t("ai.operationCount", { count: selected.length })}</div>
    <ol className="ai-operations">{proposal.ops.map((operation, index) => <li key={index}>
      <label><input type="checkbox" aria-label={t("ai.selectOperation", { index: index + 1 })} checked={selected.includes(index)} disabled={busy || pending || checking}
        onChange={(event) => selectionChanged(event.target.checked ? [...selected, index].sort((left, right) => left - right) : selected.filter((value) => value !== index))} />
        <span>{hasMessage(`ai.op.${operation.op}`) ? t(`ai.op.${operation.op}`) : operation.op}</span><code>{operationText(operation)}</code></label>
      {operation.from?.type === "interface" && <details><summary>{t("interfaces.members")}</summary>{operationMembers(proposal, operation).map((member) =>
        <div className="interface-member" key={member.signal}><strong>{member.signal}</strong><code>{t("interfaces.binding", member)}</code><span>{t("interfaces.width", member)}</span></div>)}</details>}
    </li>)}</ol>
    {!proposal.ops.length && <p>{t("ai.empty")}</p>}
    {view.diagnostics?.length > 0 && <div className="ai-proposal-diagnostics">{view.diagnostics.map((item, index) =>
      <p className={item.severity === "error" ? "ai-error" : "ai-warning"} key={index}>{diagnosticMessage(item)}</p>)}</div>}
    {error && <p className="ai-error" role="alert">{error}</p>}
    <footer><button type="button" className="button" disabled={busy || pending} onClick={() => perform(() => onDiscard(proposal))}><X size={14} />{t("ai.discard")}</button>
      <button type="button" className="button primary" disabled={busy || pending || checking || !proposal.valid || !view.valid || !selected.length}
        onClick={() => perform(() => onAccept(proposal, selected))}><Check size={14} />{t("ai.accept")}</button></footer>
  </section>;
}