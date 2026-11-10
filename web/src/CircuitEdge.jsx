import React from "react";
import { BaseEdge, StepEdge, useNodes } from "@xyflow/react";
import { getSmartEdge, smartEdgePresets } from "@tisoap/react-flow-smart-edge";

const routingOptions = { drawEdge: smartEdgePresets.step.drawEdge, generatePath: smartEdgePresets.step.generatePath, nodePadding: 14, gridRatio: 10 };

export default function CircuitEdge(props) {
  const nodes = useNodes();
  const route = getSmartEdge({ ...props, nodes, options: routingOptions });
  if (route instanceof Error) return <g data-routing="unavailable"><title>节点重叠或通道不足，暂无法完成避障走线</title><StepEdge {...props} style={{ ...props.style, stroke: "#bd765f", strokeDasharray: "4 3" }} /></g>;
  return <g data-routing="routed"><BaseEdge id={props.id} path={route.svgPathString} style={props.style}
    markerStart={props.markerStart} markerEnd={props.markerEnd} interactionWidth={16}
    label={props.label} labelX={route.edgeCenterX} labelY={route.edgeCenterY} labelStyle={props.labelStyle}
    labelShowBg={props.labelShowBg} labelBgStyle={props.labelBgStyle} labelBgPadding={props.labelBgPadding} labelBgBorderRadius={props.labelBgBorderRadius} /></g>;
}