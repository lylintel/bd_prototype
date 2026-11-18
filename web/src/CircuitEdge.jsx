import React, { memo } from "react";
import { BaseEdge, StepEdge, getSmoothStepPath, useNodes, useStore } from "@xyflow/react";
import { getSmartEdge, smartEdgePresets } from "@tisoap/react-flow-smart-edge";
import { edgeLabelPosition, recordRender } from "./performance.js";

const routingOptions = { drawEdge: smartEdgePresets.step.drawEdge, generatePath: smartEdgePresets.step.generatePath, nodePadding: 14, gridRatio: 10 };

function NetLabel({ text, x, y, end = false }) {
  const value = String(text ?? "");
  const shown = value.length > 15 ? `${value.slice(0, 12)}...` : value;
  const width = shown.length * 6 + 8;
  return <g className="react-flow__edge-textwrapper" transform={`translate(${x},${y})`}><title>{value}</title>
    <rect x={end ? -width : 0} y={-7} width={width} height={14} rx={2} fill="#f8fafb" />
    <text className="react-flow__edge-text" x={end ? -4 : 4} y={3} textAnchor={end ? "end" : "start"}
      style={{ fill: "#526c7c", fontSize: 10, fontFamily: "IBM Plex Mono, monospace" }}>{shown}</text>
  </g>;
}

function RoutedEdge(props) {
  const nodes = useNodes();
  const route = getSmartEdge({ ...props, nodes, options: routingOptions });
  if (route instanceof Error) return <g data-routing="unavailable"><title>节点重叠或通道不足，暂无法完成避障走线</title><StepEdge {...props} style={{ ...props.style, stroke: "#bd765f", strokeDasharray: "4 3" }} /></g>;
  const label = edgeLabelPosition(props, nodes, { x: route.edgeCenterX, y: route.edgeCenterY });
  return <g data-routing="routed"><BaseEdge id={props.id} path={route.svgPathString} style={props.style}
    markerStart={props.markerStart} markerEnd={props.markerEnd} interactionWidth={16}
    label={props.label} labelX={label.x} labelY={label.y} labelStyle={props.labelStyle}
    labelShowBg={props.labelShowBg} labelBgStyle={props.labelBgStyle} labelBgPadding={props.labelBgPadding} labelBgBorderRadius={props.labelBgBorderRadius} /></g>;
}

function CircuitEdge(props) {
  recordRender("edge", props.id);
  const dense = useStore((state) => state.nodes.length > 64 || state.edges.length > 256 || state.nodes.some((node) => node.data.compact));
  const small = useStore((state) => state.transform[2] < 0.5);
  const denseLabels = useStore((state) => state.edges.length > 256);
  const labelMode = props.data?.labelMode ?? denseLabels;
  const visibleEnds = useStore((state) => {
    if (!labelMode) return 0;
    const [offsetX, offsetY, zoom] = state.transform;
    const visible = (x, y) => x * zoom + offsetX >= -120 && x * zoom + offsetX <= state.width + 120 && y * zoom + offsetY >= -40 && y * zoom + offsetY <= state.height + 40;
    return (visible(props.sourceX, props.sourceY) ? 1 : 0) | (visible(props.targetX, props.targetY) ? 2 : 0);
  });
  if (!dense && !small) return <RoutedEdge {...props} />;
  const emphasized = props.selected || props.className?.includes("ai-preview");
  const style = { ...props.style, strokeWidth: small ? 1 : props.data?.width > 1 ? 2.5 : 1.5,
    ...(!emphasized && small ? { stroke: "#82978b" } : {}) };
  if (labelMode && !emphasized && !props.data?.bundle) {
    if (!visibleEnds) return null;
    const source = (visibleEnds & 1) !== 0 && props.data?.sourceLabel !== false;
    const target = (visibleEnds & 2) !== 0;
    if (!source && !target) return null;
    const path = `${source ? `M${props.sourceX} ${props.sourceY}h36` : ""} ${target ? `M${props.targetX} ${props.targetY}h-36` : ""}`;
    return <g data-routing="labels"><title>{props.label}</title><BaseEdge id={props.id} path={path} style={style} interactionWidth={16} />
      {source && !small && <NetLabel text={props.label} x={props.sourceX + 8} y={props.sourceY - 8} />}
      {target && !small && <NetLabel text={props.label} x={props.targetX - 8} y={props.targetY + 8} end />}</g>;
  }
  if (props.data?.bundle && !small) {
    const [path, labelX, labelY] = getSmoothStepPath({ ...props, borderRadius: 0 });
    return <g data-routing="bundle"><BaseEdge id={props.id} path={path} style={style} interactionWidth={16}
      label={props.label} labelX={labelX} labelY={labelY + (props.source < props.target ? -16 : 16)} labelStyle={props.labelStyle}
      labelBgStyle={props.labelBgStyle} labelBgPadding={props.labelBgPadding} labelBgBorderRadius={props.labelBgBorderRadius} /></g>;
  }
  return <g data-routing="dense"><StepEdge {...props} label={small || (dense && !props.data?.bundle) ? undefined : props.label} style={style} /></g>;
}

export default memo(CircuitEdge);