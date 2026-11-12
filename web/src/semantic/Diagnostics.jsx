import React from "react";
import { ArrowUpRight, CircleAlert, TriangleAlert, Wrench } from "lucide-react";
import { t } from "../i18n.js";
import { diagnosticMessage } from "./model.js";

export default function Diagnostics({ items, disabled, onFocus, onFix }) {
  return <div className="semantic-diagnostics">{items.map((item, index) => <div className={`semantic-diagnostic ${item.severity}`}
    data-code={item.code} data-net={item.location.net ?? ""} key={`${item.code}:${JSON.stringify(item.location)}:${index}`}>
    <button type="button" className="diagnostic-error" title={t("semantic.locate", { code: item.code })}
      aria-label={t("semantic.locate", { code: item.code })} onClick={() => onFocus(item)}>
      {item.severity === "warning" ? <TriangleAlert size={15} /> : <CircleAlert size={15} />}
      <code><b>{item.code}</b>{diagnosticMessage(item)}</code><ArrowUpRight size={14} />
    </button>
    {item.fix && <button type="button" className="small-command" disabled={disabled} onClick={() => onFix(item)}
      title={t("semantic.applyFix")} aria-label={t("semantic.applyFix")}><Wrench size={14} />{t("semantic.applyFix")}</button>}
  </div>)}</div>;
}