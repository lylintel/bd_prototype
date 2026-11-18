import React, { memo } from "react";
import { BaseEdge, StepEdge, useNodes, useStore } from "@xyflow/react";
import { getSmartEdge, smartEdgePresets } from "@tisoap/react-flow-smart-edge";
import { edgeLabelPosition, recordRender } from "./performance.js";

const routingOptions = { drawEdge: smartEdgePresets.step.drawEdge, generatePath: smartEdgePresets.step.generatePath, nodePadding: 14, gridRatio: 10 };

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
  const dense = useStore((state) => state.nodes.length > 64 || state.edges.length > 256);
  const small = useStore((state) => state.transform[2] < 0.5);
  if (!dense && !small) return <RoutedEdge {...props} />;
  const emphasized = props.selected || props.className?.includes("ai-preview");
  const style = { ...props.style, strokeWidth: small ? 1 : props.data?.width > 1 ? 2.5 : 1.5,
    ...(!emphasized && small ? { stroke: "#82978b" } : {}) };
  return <g data-routing="dense"><StepEdge {...props} label={small || dense ? undefined : props.label} style={style} /></g>;
}

export default memo(CircuitEdge);