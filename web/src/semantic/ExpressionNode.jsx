import React from "react";
import * as FlowComponents from "@xyflow/react";
import { Position } from "@xyflow/react";
import { Binary, Braces } from "lucide-react";
import { t } from "../i18n.js";

const { Handle } = FlowComponents;

export default function ExpressionNode({ data, selected }) {
  const Icon = data.kind === "constant" ? Binary : Braces;
  return <div className={`expression-node ${selected ? "is-selected" : ""}`} style={{ height: data.height }}>
    <div className="expression-heading"><Icon size={16} /><strong>{t(`semantic.kind.${data.kind}`)}</strong><span>{t("semantic.bits", { width: data.width })}</span></div>
    <code className="expression-value" title={data.text}>{data.text}</code>
    <Handle id="aggregate" type={data.drives ? "source" : "target"} position={data.drives ? Position.Right : Position.Left} isConnectable={false}
      aria-label={t("semantic.expressionPort", { name: data.net })} />
    {data.references.map((reference, index) => <div className="expression-member" key={index} title={reference.key}>
      <Handle id={`member-${index}`} type={data.drives ? "target" : "source"} position={data.drives ? Position.Left : Position.Right}
        style={{ top: 80 + index * 20 }} isConnectable={false} aria-label={reference.key} />
      <code>{reference.key}</code><span>{reference.width}</span>
    </div>)}
  </div>;
}