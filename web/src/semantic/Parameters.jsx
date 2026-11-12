import React, { useEffect, useState } from "react";
import { RotateCcw } from "lucide-react";
import { t } from "../i18n.js";
import { parameterValue } from "./model.js";

function Parameter({ instance, name, spec, value, resolved, disabled, onCommit, onError }) {
  const [draft, setDraft] = useState(String(value ?? spec.default));
  useEffect(() => setDraft(String(value ?? spec.default)), [value, spec.default]);
  function commit() {
    if (draft === String(value ?? spec.default)) return;
    try {
      if (onCommit(name, parameterValue(draft)) === false) setDraft(String(value ?? spec.default));
    } catch (error) { onError(error.message, true); setDraft(String(value ?? spec.default)); }
  }
  return <label className="parameter-field">
    <span><code>{name}</code><small>{t("semantic.defaultValue", { value: spec.default })}</small>
      {resolved !== undefined && <small>{t("semantic.resolvedValue", { value: resolved })}</small>}</span>
    <input aria-label={t("semantic.parameterLabel", { instance, name })} value={draft} disabled={disabled} spellCheck={false}
      onChange={(event) => setDraft(event.target.value)} onBlur={commit}
      onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); if (event.key === "Escape") setDraft(String(value ?? spec.default)); }} />
    <button type="button" className="icon-button" title={t("semantic.resetParameter", { name })} aria-label={t("semantic.resetParameter", { name })}
      disabled={disabled || value === undefined} onClick={() => onCommit(name, undefined)}><RotateCcw size={14} /></button>
  </label>;
}

export default function Parameters({ instance, definition, overrides, resolved, disabled, onCommit, onError }) {
  return <section className="property-section semantic-parameters"><h3>{t("ip.parameters")}<span>{Object.keys(definition?.parameters ?? {}).length}</span></h3>
    {Object.entries(definition?.parameters ?? {}).map(([name, spec]) => <Parameter key={`${instance}.${name}`} instance={instance} name={name}
      spec={spec} value={overrides?.[name]} resolved={resolved?.[name]} disabled={disabled} onCommit={onCommit} onError={onError} />)}
  </section>;
}