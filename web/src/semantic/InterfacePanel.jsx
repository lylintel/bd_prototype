import React, { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { Blocks, Check, ChevronDown, ChevronUp, ListTree, Unplug, X } from "lucide-react";
import { t } from "../i18n.js";
import { formatEndpoint } from "./model.js";

export function interfaceAddress(endpoint) {
  return endpoint.ext_interface ? `@${endpoint.ext_interface}` : `${endpoint.inst}.${endpoint.interface}`;
}

export default function InterfacePanel({ connection, summary, expanded, disabled, onToggle, onMaterialize, onDisconnect }) {
  const Toggle = expanded ? ChevronUp : ChevronDown;
  return <>
    <div className="inspector-object"><div className="inspector-symbol teal"><Blocks size={25} /></div>
      <span>{t("interfaces.protocol")}</span><h2>{connection.name}</h2></div>
    <section className="property-section"><h3>{t("interfaces.endpoints")}</h3>
      <dl className="interface-properties"><dt>{t("interfaces.from")}</dt><dd><code>{interfaceAddress(connection.from)}</code></dd>
        <dt>{t("interfaces.to")}</dt><dd><code>{interfaceAddress(connection.to)}</code></dd></dl>
      <div className="interface-actions"><button type="button" className="small-command" disabled={disabled} onClick={onToggle}
        title={t(expanded ? "interfaces.collapseView" : "interfaces.expandView")} aria-label={t(expanded ? "interfaces.collapseView" : "interfaces.expandView")}><Toggle size={14} /></button>
        <button type="button" className="small-command" disabled={disabled} onClick={onMaterialize}><ListTree size={14} />{t("interfaces.materialize")}</button>
        <button type="button" className="icon-button" disabled={disabled} title={t("interfaces.disconnect")} aria-label={t("interfaces.disconnect")} onClick={onDisconnect}><Unplug size={15} /></button></div>
    </section>
    <section className="property-section"><h3>{t("interfaces.members")}</h3>
      {Object.entries(summary?.signals ?? {}).map(([signal, member]) => <div className="interface-member" key={signal}>
        <strong>{signal.toUpperCase()}</strong><code>{t("interfaces.binding", { source: formatEndpoint(member.source), target: formatEndpoint(member.sink) })}</code>
        <span>{t("interfaces.width", { width: member.width })}</span></div>)}
    </section>
  </>;
}

export function InterfaceConfirmation({ value, busy, onCancel, onConfirm }) {
  const dialog = useRef(null);
  useEffect(() => {
    if (value && !dialog.current.open) dialog.current.showModal();
    if (!value && dialog.current.open) dialog.current.close();
  }, [value]);
  return createPortal(<dialog ref={dialog} className="editor-dialog interface-confirmation" aria-label={t("interfaces.confirmation")}
    onCancel={(event) => { event.preventDefault(); if (!busy) onCancel(); }}>
    {value && <><div className="dialog-heading"><h2>{t(value.action === "migrate" ? "interfaces.enable" : "interfaces.materialize")}</h2>
      <button type="button" className="icon-button" disabled={busy} title={t("common.close")} aria-label={t("common.close")} onClick={onCancel}><X size={16} /></button></div>
      <div className="dialog-body">
        {value.action === "migrate" ? <p>{t("interfaces.migrationImpact", { version: value.version })}</p> : <>
          <p>{t("interfaces.materializeImpact", { name: value.connection, count: value.plan.nets.length })}</p>
          {value.plan.bindings.map((binding) => <div className="interface-member" key={binding.signal}><strong>{binding.signal.toUpperCase()}</strong>
            <code>{t("interfaces.binding", { source: formatEndpoint(binding.source), target: formatEndpoint(binding.sink) })}</code></div>)}
          {value.plan.bindings.some((binding) => binding.signal === "tlast" && binding.source.const) && <p>{t("interfaces.lastImpact")}</p>}
          {value.plan.omitted_outputs.map((item) => <p key={item.signal}>{t("interfaces.omission", { signal: item.signal.toUpperCase(), endpoint: formatEndpoint(item.endpoint) })}</p>)}
        </>}
      </div><div className="dialog-actions"><button type="button" className="button secondary" disabled={busy} onClick={onCancel}>{t("common.cancel")}</button>
        <button type="button" className="button primary" disabled={busy} onClick={() => onConfirm(value)}><Check size={15} />{t("interfaces.confirm")}</button></div></>}
  </dialog>, document.body);
}