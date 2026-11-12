import React, { useEffect, useRef, useState } from "react";
import { Check, Pencil, Plus, Trash2, X } from "lucide-react";
import { t } from "../i18n.js";
import { endpointObject, endpointPins, formatEndpoint } from "./model.js";

function Fields({ value, onChange, ports, path, width = 1, depth = 0 }) {
  if (depth > 16) return <p role="alert">{t("semantic.reason.endpoint_limit")}</p>;
  const kind = value.const !== undefined ? "constant" : Array.isArray(value.concat) ? "concat" : "port";
  const pin = endpointPins(value)[0] ?? "";
  const selected = ports.find((port) => port.value === pin);
  function changeKind(next) {
    if (next === "constant") onChange({ const: `${Math.min(256, width)}'d0` });
    else if (next === "concat") onChange({ concat: [structuredClone(value)] });
    else onChange(ports.length ? endpointObject(ports[0].value) : { ext: "" });
  }
  return <div className="connection-fields">
    <label className="field-label">{t("semantic.endpointType", { path })}<select aria-label={t("semantic.endpointType", { path })}
      value={kind} onChange={(event) => changeKind(event.target.value)}>
      <option value="port">{t("semantic.kind.port")}</option><option value="constant">{t("semantic.kind.constant")}</option>
      <option value="concat" disabled={depth >= 16}>{t("semantic.kind.concat")}</option>
    </select></label>
    {kind === "constant" ? <label className="field-label">{t("semantic.constantValue", { path })}
      <input aria-label={t("semantic.constantValue", { path })} value={value.const} maxLength={4096} spellCheck={false}
        onChange={(event) => onChange({ const: event.target.value })} /></label>
      : kind === "concat" ? <div className="concat-members">{value.concat.map((child, index) => <div className="concat-member" key={index}>
        <div className="concat-member-heading"><strong>{t("semantic.member", { path: `${path}.${index + 1}` })}</strong>
          <button type="button" className="icon-button" disabled={value.concat.length <= 1} title={t("semantic.removeMember", { path: `${path}.${index + 1}` })}
            aria-label={t("semantic.removeMember", { path: `${path}.${index + 1}` })} onClick={() => onChange({ concat: value.concat.filter((_, position) => position !== index) })}><Trash2 size={14} /></button></div>
        <Fields value={child} ports={ports} path={`${path}.${index + 1}`} depth={depth + 1} width={width}
          onChange={(next) => onChange({ concat: value.concat.map((item, position) => position === index ? next : item) })} />
      </div>)}<button type="button" className="small-command" disabled={value.concat.length >= 128} onClick={() => onChange({ concat: [...value.concat, { const: "1'b0" }] })}
        title={t("semantic.addMember", { path })} aria-label={t("semantic.addMember", { path })}><Plus size={14} />{t("semantic.addMember", { path })}</button></div>
        : <>
          <label className="field-label">{t("semantic.endpointPort", { path })}<select aria-label={t("semantic.endpointPort", { path })} value={pin}
            onChange={(event) => onChange({ ...endpointObject(event.target.value), ...(value.slice ? { slice: value.slice } : {}) })}>
            <option value="" disabled>{t("semantic.choosePort")}</option>
            {ports.map((port) => <option key={port.value} value={port.value}>{port.value}</option>)}
          </select></label>
          <label className="check-field"><input type="checkbox" aria-label={t("semantic.useSlice", { path })} checked={Boolean(value.slice)}
            disabled={!value.slice && !selected?.range} onChange={(event) => {
              const next = { ...value };
              if (event.target.checked) next.slice = [...selected.range]; else delete next.slice;
              onChange(next);
            }} />{t("semantic.slice")}</label>
          {value.slice && <div className="connection-range"><label className="field-label">{t("semantic.leftIndex", { path })}
            <input type="number" step="1" aria-label={t("semantic.leftIndex", { path })} value={value.slice[0] ?? ""}
              onChange={(event) => onChange({ ...value, slice: [event.target.value === "" ? null : event.target.valueAsNumber, value.slice[1]] })} /></label>
            <label className="field-label">{t("semantic.rightIndex", { path })}<input type="number" step="1" aria-label={t("semantic.rightIndex", { path })} value={value.slice[1] ?? ""}
              onChange={(event) => onChange({ ...value, slice: [value.slice[0], event.target.value === "" ? null : event.target.valueAsNumber] })} /></label></div>}
        </>}
  </div>;
}

export default function Connections({ document, name, ports, resolved, disabled, onApply, onOpenChange }) {
  const [index, setIndex] = useState(-1);
  const [draft, setDraft] = useState(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const dialog = useRef(null);
  const net = Array.isArray(document?.nets) ? document.nets.find((item) => item.name === name) : null;
  useEffect(() => {
    onOpenChange(index >= 0);
    if (index < 0) return;
    dialog.current?.showModal();
    return () => { dialog.current?.close(); onOpenChange(false); };
  }, [index]);
  if (!net) return null;
  function edit(position) { setDraft(structuredClone(net.endpoints[position])); setError(""); setIndex(position); }
  async function submit(event) {
    event.preventDefault();
    setPending(true);
    try { if (await onApply(name, index, draft)) setIndex(-1); }
    catch (failure) { setError(failure.message); }
    finally { setPending(false); }
  }
  return <section className="property-section connection-settings"><h3>{t("semantic.connections")}</h3>
    {net.endpoints.map((endpoint, position) => <div className="net-endpoint" key={position}><div>
      <span>{t("semantic.endpointIndex", { index: position + 1 })}</span><code title={formatEndpoint(endpoint)}>{formatEndpoint(endpoint)}</code></div>
      <button type="button" className="icon-button" disabled={disabled} title={t("semantic.editEndpoint", { index: position + 1 })}
        aria-label={t("semantic.editEndpoint", { index: position + 1 })} onClick={() => edit(position)}><Pencil size={14} /></button>
    </div>)}
    <dialog className="connection-dialog" ref={dialog} aria-label={t("semantic.connectionTitle", { name })} onCancel={(event) => { if (pending) event.preventDefault(); else setIndex(-1); }}>
      <form onSubmit={submit}><header><h2>{t("semantic.connectionTitle", { name })}</h2><button type="button" className="icon-button" disabled={pending}
        title={t("common.close")} aria-label={t("common.close")} onClick={() => setIndex(-1)}><X size={16} /></button></header>
        <div className="connection-body">{error && <p role="alert">{error}</p>}<fieldset disabled={pending}>
          {draft && <Fields value={draft} onChange={setDraft} ports={ports} path={String(index + 1)} width={resolved?.endpoints.find((item) => item.index === index)?.width ?? 1} />}
        </fieldset></div>
        <footer><button type="button" className="button" disabled={pending} onClick={() => setIndex(-1)}>{t("common.cancel")}</button>
          <button type="submit" className="button primary" disabled={pending}><Check size={14} />{t("semantic.applyConnection")}</button></footer>
      </form>
    </dialog>
  </section>;
}