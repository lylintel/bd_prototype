import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Background, BackgroundVariant, ConnectionLineType, ConnectionMode, Position, ReactFlow, applyNodeChanges, getNodesBounds, getViewportForBounds, useReactFlow, useStore, useViewport } from "@xyflow/react";
import * as FlowComponents from "@xyflow/react";
import { ArrowUpRight, Blocks, Bot, Check, CheckCheck, ChevronDown, CircleAlert, CircleCheck, CircuitBoard, Code2, Copy, Cpu, Download, FilePlus2, FolderOpen, GripVertical, LayoutGrid, ListTree, LoaderCircle, Maximize2, PanelLeft, PanelRight, Plus, Redo2, Save, Search, Settings2, ShieldCheck, Trash2, Undo2, Unplug, Workflow, X, ZoomIn, ZoomOut } from "lucide-react";
import { addInstance, checkName, clone, connectionError, connectPorts, deleteNode, disconnectPort, endpointInfo, externalId, makeExternal, parseInteger, rangeLabel, renameNet, renameNode, uniqueName, validateDocumentShape } from "./model.js";
import OutputWindow from "./OutputWindow.jsx";
import OutputEditor, { prepareOutputEditor } from "./output/Loader.jsx";
import CircuitEdge from "./CircuitEdge.jsx";
import CopilotPanel from "./CopilotPanel.jsx";
import AISettings from "./ai/Settings.jsx";
import { useAIPrivacy } from "./ai/Privacy.jsx";
import AIAssistant from "./ai/Assistant.jsx";
import { candidateGraph, designChanges, mergePreview } from "./ai/model.js";
import { Sparkles } from "lucide-react";
import { ImportButton, LibraryList, OriginBadge } from "./ip/Library.jsx";
import { IP_DRAG_TYPE, addImported, findImportedDrop, originForDefinition } from "./ip/model.js";
import { t } from "./i18n.js";
import Parameters from "./semantic/Parameters.jsx";
import Diagnostics from "./semantic/Diagnostics.jsx";
import Connections from "./semantic/Connections.jsx";
import ExpressionNode from "./semantic/ExpressionNode.jsx";
import { markLayout, markOutput, nodeGeometry, recordRender, sameNodeData, visibleLabelEdges } from "./performance.js";
import { bundleHierarchyEdges, hasSubdesign, mergeScopeState, scopeState } from "./semantic/hierarchy.js";
import { publishPositions, requestLayout } from "./layout/client.js";
import { createHistory, commitHistory, undoHistory, redoHistory } from "./history.js";
import { expressionId, normalizeInspection, projectConnections, renameSemantic, replaceEndpoint, scheduleInspection, syncDocument } from "./semantic/model.js";
import "./semantic/semantic.css";

const { Handle } = FlowComponents;
const initialLayout = { nodes: {}, viewport: { x: 0, y: 0, zoom: 1 } };
const emptyInspection = { valid: false, diagnostics: [], files: {}, interfaces: { ports: {}, instances: {} } };

function IconButton({ icon: Icon, label, className = "", ...props }) {
  return <button type="button" className={`icon-button ${className}`} title={label} aria-label={label} {...props}><Icon size={16} strokeWidth={1.7} /></button>;
}

function CommitInput({ value, onCommit, label, ...props }) {
  const [draft, setDraft] = useState(String(value ?? ""));
  const cancel = useRef(false);
  useEffect(() => setDraft(String(value ?? "")), [value]);
  return <input aria-label={label} value={draft} {...props} onChange={(event) => setDraft(event.target.value)} onBlur={() => {
    if (!cancel.current && draft !== String(value ?? "") && onCommit(draft) === false) setDraft(String(value ?? ""));
    cancel.current = false;
  }} onKeyDown={(event) => {
    if (event.key === "Enter") event.currentTarget.blur();
    if (event.key === "Escape") { cancel.current = true; setDraft(String(value ?? "")); event.currentTarget.blur(); }
  }} />;
}

function Pin({ port, side, onPin, active, connectable }) {
  return <div className={`node-pin ${side}`} title={`${port.endpoint} ${rangeLabel(port)}`}>
    <Handle type={port.drives ? "source" : "target"} position={side === "left" ? Position.Left : Position.Right} id={port.endpoint}
      className={`${port.width > 1 || port.range ? "bus-handle" : ""} ${active === port.endpoint ? "active-handle" : ""}`}
      aria-label={port.endpoint} role="button" tabIndex={0} isConnectable={connectable} aria-disabled={!connectable}
      onClick={(event) => { event.stopPropagation(); onPin(port.endpoint); }}
      onKeyDown={(event) => { if (event.key === "Enter") { event.stopPropagation(); onPin(port.endpoint); } }} />
    <span className="pin-name">{port.name}</span><span className="pin-range">{rangeLabel(port)}</span>
  </div>;
}

function BlockNode({ data, selected }) {
  recordRender("node", data.external ? `@${data.name}` : data.name);
  if (data.external) {
    const port = data.ports[0];
    return <div className={`external-node ${selected ? "is-selected" : ""} ${data.highlight ? "has-error" : ""}`}>
      <div className="external-icon"><ArrowUpRight size={16} /></div>
      <div><span className="external-name">{data.name}</span><span className="external-detail">{port?.direction === "input" ? "INPUT" : "OUTPUT"} <b>{rangeLabel(port)}</b></span></div>
      {port && <Handle type={port.drives ? "source" : "target"} position={port.drives ? Position.Right : Position.Left} id={port.endpoint}
        role="button" tabIndex={0} aria-label={port.endpoint} isConnectable={data.connectable} aria-disabled={!data.connectable} className={data.active === port.endpoint ? "active-handle" : ""}
        onClick={(event) => { event.stopPropagation(); data.onPin(port.endpoint); }}
        onKeyDown={(event) => { if (event.key === "Enter") data.onPin(port.endpoint); }} />}
    </div>;
  }
  const inputs = data.ports.filter((port) => !port.drives);
  const outputs = data.ports.filter((port) => port.drives);
  return <div className={`block-node ${selected ? "is-selected" : ""} ${data.highlight ? "has-error" : ""} ${data.module.includes("compare") ? "tone-amber" : "tone-blue"}`}>
    <div className="block-heading"><div className="block-symbol"><Cpu size={20} strokeWidth={1.5} /></div><div><strong>{data.name}</strong><span>{data.module}</span></div><GripVertical size={14} className="block-grip" /></div>
    {data.compact ? <div className="compact-pins">
      <span>{t("hierarchy.inputs", { count: inputs.length })}</span><IconButton icon={ChevronDown} label={t("hierarchy.expandPorts", { name: data.name })} onClick={() => data.onTogglePins(data.name)} /><span>{t("hierarchy.outputs", { count: outputs.length })}</span>
      {inputs.length > 0 && <Handle id="~compact-in" type="target" position={Position.Left} style={{ top: 46 }} className="compact-handle" isConnectable={false} />}
      {outputs.length > 0 && <Handle id="~compact-out" type="source" position={Position.Right} style={{ top: 46 }} className="compact-handle" isConnectable={false} />}
    </div> : <div className="block-pins"><div>{inputs.map((port) => <Pin key={port.endpoint} port={port} side="left" onPin={data.onPin} active={data.active} connectable={data.connectable} />)}</div><div>{outputs.map((port) => <Pin key={port.endpoint} port={port} side="right" onPin={data.onPin} active={data.active} connectable={data.connectable} />)}</div></div>}
    <div className="block-footer"><span className="rtl-dot" />RTL<span className="block-parameters">{Object.entries(data.parameters).map(([name, value]) => `${name} ${value}`).join(" · ")}</span>{data.foldable && !data.compact && <IconButton icon={ChevronDown} label={t("hierarchy.collapsePorts", { name: data.name })} onClick={() => data.onTogglePins(data.name)} />}</div>
  </div>;
}

const nodeTypes = { block: memo(BlockNode, (previous, next) => previous.selected === next.selected && sameNodeData(previous.data, next.data)), expression: memo(ExpressionNode) };
const edgeTypes = { circuit: CircuitEdge };

function defaultPosition(id, design) {
  if (!id.startsWith("@")) {
    const index = Object.keys(design.instances).indexOf(id);
    return { x: 240 + (index % 3) * 350, y: 140 + Math.floor(index / 3) * 230 };
  }
  const name = id.slice(1);
  const direction = design.ports[name]?.direction;
  const peers = Object.keys(design.ports).filter((key) => design.ports[key].direction === direction);
  return { x: direction === "input" ? 0 : 240 + Math.min(3, Math.max(1, Object.keys(design.instances).length)) * 350, y: 160 + peers.indexOf(name) * 100 };
}

function nodeId(endpoint) { return endpoint.startsWith("@") ? endpoint : endpoint.split(".")[0]; }

function downloadFile(name, content) {
  const url = URL.createObjectURL(new Blob([content], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

export default function App() {
  const flow = useReactFlow();
  const viewport = useViewport();
  const canvasWidth = useStore((state) => state.width);
  const canvasHeight = useStore((state) => state.height);
  const [history, setHistory] = useState(null);
  const [scopePath, setScopePath] = useState([]);
  const [expandedGroups, setExpandedGroups] = useState([]);
  const [baseDir, setBaseDir] = useState("examples");
  const [documentPath, setDocumentPath] = useState("");
  const [token, setToken] = useState("");
  const [inspection, setInspection] = useState(emptyInspection);
  const [checking, setChecking] = useState(false);
  const [fixing, setFixing] = useState(false);
  const [hdlRunning, setHdlRunning] = useState(false);
  const [hdlResult, setHdlResult] = useState(null);
  const [hdlLanguage, setHdlLanguage] = useState("v");
  const hdlLanguageRef = useRef(hdlLanguage);
  hdlLanguageRef.current = hdlLanguage;
  const [busy, setBusy] = useState("");
  const [saved, setSaved] = useState(true);
  const [selection, setSelection] = useState(null);
  const [pendingPin, setPendingPin] = useState(null);
  const [nodes, setNodes] = useState([]);
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState("diagnostics");
  const [panelOpen, setPanelOpen] = useState(true);
  const [mobilePanel, setMobilePanel] = useState(null);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [aiSettingsOpen, setAiSettingsOpen] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [preview, setPreview] = useState(null);
  const [modal, setModal] = useState(null);
  const [ipImportOpen, setIpImportOpen] = useState(false);
  const [connectionOpen, setConnectionOpen] = useState(false);
  const [ipRevision, setIpRevision] = useState(0);
  const [ipCatalog, setIpCatalog] = useState({ baseDir: "", entries: [] });
  const [toast, setToast] = useState(null);
  const [fatal, setFatal] = useState("");
  const [jsonDraft, setJsonDraft] = useState("");
  const jsonDocument = useRef(null);
  const outputStates = useRef(new Map());
  const [activity, setActivity] = useState("本地工作区已就绪");
  const [zoom, setZoom] = useState(100);
  const [viewportRequest, setViewportRequest] = useState(null);
  const [layoutRunning, setLayoutRunning] = useState(false);
  const layoutController = useRef(null);
  const layoutPreview = useRef(null);
  useEffect(() => () => { layoutController.current?.abort(); layoutController.current = null; }, []);
  const modalRef = useRef(null);
  const inspectedDesign = useRef(null);
  const inspectedSnapshot = useRef(null);
  const pinAction = useRef(pickPin);
  const layoutAction = useRef(moveNode);
  const connectionAction = useRef(connect);
  const connectionEndAction = useRef(endConnection);
  const flowStaticProps = useRef(null);
  flowStaticProps.current ??= { snapGrid: [10, 10], fitViewOptions: { padding: 0.16, maxZoom: 1 } };
  const navigationAction = useRef(null);
  const projectionInputs = useRef(null);
  const stablePickPin = useCallback((endpoint) => pinAction.current(endpoint), []);
  const onNodeDragStop = useCallback((event, node) => layoutAction.current(node), []);
  const onConnect = useCallback((connection) => connectionAction.current(connection.sourceHandle, connection.targetHandle), []);
  const onConnectEnd = useCallback((event, state) => connectionEndAction.current(event, state), []);
  useEffect(() => { pinAction.current = pickPin; layoutAction.current = moveNode; connectionAction.current = connect; connectionEndAction.current = endConnection; });
  const editorState = useRef(null);
  const rootDocument = history?.current.document ?? history?.current.design;
  const currentHdlResult = hdlResult?.document === rootDocument && hdlResult?.baseDir === baseDir && hdlResult?.language === hdlLanguage ? hdlResult.result : null;
  const scope = hasSubdesign(rootDocument, scopePath.at(-1)) ? scopePath.at(-1) : "";
  const toggleGroupPins = useCallback((name) => setExpandedGroups((current) => current.includes(`${scope}:${name}`) ? current.filter((item) => item !== `${scope}:${name}`) : [...current, `${scope}:${name}`]), [scope]);
  const logicalView = useMemo(() => scopeState(history?.current, scope), [history?.current.design, history?.current.document, scope]);
  const view = useMemo(() => logicalView ? { ...logicalView, layout: scope ? history.current.layout.scopes?.[scope] ?? initialLayout : history.current.layout } : logicalView,
    [logicalView, history?.current.layout, scope]);
  editorState.current = { history, baseDir, busy, scope, view, preview };
  const design = view?.design;
  const document = view?.document ?? design;
  const layout = view?.layout;
  useEffect(() => { navigationAction.current = (node) => {
    const target = design?.instances[node.id]?.module;
    if (!hasSubdesign(rootDocument, target)) return false;
    setScopePath((current) => [...current, target]);
    setSelection(null); setPendingPin(null); setViewportRequest({ fit: true });
    return true;
  }; }, [design, rootDocument]);
  const connectionReady = !preview && !checking && !busy && inspectedDesign.current === design && inspectedSnapshot.current?.document === document && inspectedSnapshot.current?.baseDir === baseDir;
  const interfaces = connectionReady ? inspection.interfaces : emptyInspection.interfaces;
  const hasExpressions = useMemo(() => inspection.connections?.some((net) => net.endpoints.some((endpoint) => endpoint.expression)), [inspection.connections]);
  const expressionLayout = hasExpressions ? layout?.nodes : null;
  const expressionGraph = useMemo(() => projectConnections(inspection.connections ?? [], expressionLayout ?? {}), [inspection.connections, expressionLayout]);
  const onNodesChange = useCallback((changes) => { if (!preview) setNodes((current) => applyNodeChanges(changes.filter((change) => change.type !== "remove"), current)); }, [preview]);
  const onMoveEnd = useCallback((event, viewport) => setZoom(Math.round(viewport.zoom * 100)), []);
  const onNodeClick = useCallback((event, node) => { if (!preview) {
    setSelection((previous) => node.type === "expression" ? { type: "net", id: node.data.net } : { type: "node", id: node.id,
      ids: event.shiftKey || event.ctrlKey || event.metaKey ? [...new Set([...(previous?.ids ?? (previous?.type === "node" ? [previous.id] : [])), node.id])] : [node.id] });
    setPendingPin(null);
  } }, [preview]);
  const onNodeDoubleClick = useCallback((event, node) => { if (!preview && !navigationAction.current?.(node)) { setSelection(node.type === "expression" ? { type: "net", id: node.data.net } : { type: "node", id: node.id }); setMobilePanel("inspector"); } }, [preview]);
  const onEdgeClick = useCallback((event, edge) => { if (!preview) { if (edge.data.bundle) setModal({ kind: "bundle", edges: edge.data.bundle }); else setSelection({ type: "net", id: edge.data.net, sink: edge.data.sink }); setPendingPin(null); } }, [preview]);
  const onPaneClick = useCallback(() => { setSelection(null); setPendingPin(null); setMobilePanel(null); }, []);
  const isValidConnection = useCallback((connection) => connectionReady && connectionError(design, connection.sourceHandle, connection.targetHandle, interfaces) === null, [connectionReady, design, interfaces]);

  function notify(message, error = false) { setToast({ message, error }); }

  async function rawApi(path, payload, signal) {
    const response = await fetch(path, payload === undefined ? { signal } : { method: "POST", headers: { "Content-Type": "application/json", "X-BD-Token": token }, body: JSON.stringify(payload), signal });
    const result = await response.json();
    if (!response.ok) throw new Error(normalizeInspection(result).diagnostics[0] || result.error || `HTTP ${response.status}`);
    return result;
  }

  const privacy = useAIPrivacy(rawApi, aiSettingsOpen);
  async function api(path, payload, signal) {
    if (path === "/api/ai/propose") await privacy.authorize();
    return rawApi(path, payload, signal);
  }

  function acceptDocument(result) {
    outputStates.current.clear();
    const versioned = [2, 3, 4].includes(result.design.schema_version);
    setScopePath([]);
    const canvas = validateDocumentShape(versioned ? result.inspection.canvas : result.design);
    setHistory(createHistory({ design: canvas, document: versioned ? result.design : null, layout: { ...initialLayout, ...result.layout } }));
    setBaseDir(result.base_dir);
    setDocumentPath(result.path);
    inspectedDesign.current = canvas;
    inspectedSnapshot.current = { document: versioned ? result.design : canvas, baseDir: result.base_dir };
    setInspection(normalizeInspection(result.inspection));
    setSaved(true);
    setSelection(null);
    setPendingPin(null);
    setViewportRequest({ viewport: result.layout.viewport, fit: !Object.keys(result.layout.nodes).length });
  }

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/state", { signal: controller.signal }).then((response) => response.json()).then((result) => {
      if (result.error) throw new Error(result.error);
      setToken(result.token);
      acceptDocument(result);
    }).catch((error) => { if (error.name !== "AbortError") setFatal(error.message); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!design || !token) return;
    if (inspectedSnapshot.current?.document === document && inspectedSnapshot.current?.baseDir === baseDir && (!scope || inspectedSnapshot.current?.rootDocument === rootDocument)) { setChecking(false); return; }
    setChecking(true);
    return scheduleInspection(
      (signal) => api(scope ? "/api/hierarchy/inspect" : "/api/semantic/inspect", { design: scope ? rootDocument : document, scope, base_dir: baseDir }, signal),
      (result) => {
        inspectedDesign.current = design;
        inspectedSnapshot.current = { document, baseDir, rootDocument };
        setInspection(normalizeInspection(result));
        setChecking(false);
      },
      (error) => { setInspection({ ...emptyInspection, diagnostics: [error.message] }); setChecking(false); },
    );
  }, [design, document, rootDocument, scope, baseDir, token]);

  React.useLayoutEffect(() => {
    if (document && panelOpen && tab === "json" && jsonDocument.current !== document) {
      jsonDocument.current = document;
      setJsonDraft(JSON.stringify(document, null, 2));
    }
  }, [document, panelOpen, tab]);
  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(null), 5000); return () => clearTimeout(timer); }, [toast]);
  useEffect(() => {
    const handler = (event) => { if (!saved) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [saved]);
  useEffect(() => {
    if (!modal) return;
    const dialog = modalRef.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, [modal?.kind]);

  function mutate(update, message, upgrade = false, replacement = null, allowPreview = false) {
    if (preview && !allowPreview) { notify(t("ai.previewReadOnly"), true); return false; }
    const current = editorState.current;
    if (!current.history || current.busy) return false;
    try {
      const previous = current.history;
      const previousView = current.view;
      const previousDesign = previousView.design;
      let next = clone(previousView);
      update(next.design, next.layout);
      const changed = JSON.stringify(next.design) !== JSON.stringify(previousDesign);
      if (replacement) next.document = clone(replacement);
      else if (changed && (previousView.document || upgrade)) {
        if (upgrade && inspectedDesign.current !== previousDesign) throw new Error(t("semantic.notReady"));
        next.document = syncDocument(previousView.document ?? inspection.document, next.design,
          [...(inspection.metadata ?? []), ...(ipCatalog.baseDir === current.baseDir ? ipCatalog.entries.map((entry) => entry.metadata) : [])]);
      } else if (!changed) next.document = previousView.document;
      next = mergeScopeState(previous.current, next, current.scope);
      if (JSON.stringify(next) === JSON.stringify(previous.current)) return true;
      if (JSON.stringify(next.design) === JSON.stringify(previousDesign)) next.design = previousDesign;
      else { setChecking(true); setInspection({ ...emptyInspection }); }
      const nextHistory = commitHistory(previous, next);
      editorState.current = { ...current, history: nextHistory };
      setHistory(nextHistory);
      setSaved(false);
      if (message) setActivity(message);
      return true;
    } catch (error) { notify(error.message, true); return false; }
  }

  function moveNode(node) {
    const current = editorState.current;
    if (preview || current.busy || !current.history) return;
    const previous = current.history;
    const before = previous.current;
    const currentView = current.view;
    const position = currentView.layout.nodes[node.id];
    if (position?.x === node.position.x && position?.y === node.position.y) return;
    const next = mergeScopeState(before, { ...currentView, layout: { ...currentView.layout, nodes: { ...currentView.layout.nodes, [node.id]: { ...node.position } } } }, current.scope);
    const nextHistory = commitHistory(previous, next);
    editorState.current = { ...current, history: nextHistory };
    setHistory(nextHistory);
    setSaved(false);
    setActivity(t("layout.nodeMoved"));
  }

  async function applyCopilotProposal(proposal, selected) {
    const current = editorState.current;
    if (current.scope) throw new Error(t("ai.rootOnly"));
    if (!current.history || current.busy) throw new Error(t("semantic.notReady"));
    const original = current.view.document ?? current.view.design;
    const result = await api("/api/ops/accept", { proposal_id: proposal.id, selected, confirmed: true, design: original, base_dir: current.baseDir });
    const latest = editorState.current;
    if ((latest.view.document ?? latest.view.design) !== original || latest.baseDir !== current.baseDir) throw new Error(t("semantic.notReady"));
    const applied = mutate((next, nextLayout) => {
      for (const key of Object.keys(next)) delete next[key];
      Object.assign(next, result.canvas);
      const nodes = new Set([...Object.keys(next.instances), ...Object.keys(next.ports).map(externalId)]);
      for (const id of Object.keys(nextLayout.nodes)) if (!nodes.has(id)) delete nextLayout.nodes[id];
    }, t("ai.accepted"), false, result.document, true);
    if (!applied) throw new Error(t("ai.acceptFailed"));
    setSelection(null);
    setPendingPin(null);
    notify(t("ai.accepted"));
    setPreview(null);
    return true;
  }

  async function generateProposal(prompt, allowRemovals) {
    const current = editorState.current;
    if (current.scope) throw new Error(t("ai.rootOnly"));
    const original = current.view.document ?? current.view.design;
    const selectedInstances = selection?.type === "node" && !selection.id.startsWith("@") ? [selection.id] : [];
    const result = await api("/api/ai/propose", { design: original, base_dir: current.baseDir, prompt, allow_removals: allowRemovals, selected_instances: selectedInstances });
    const latest = editorState.current;
    if ((latest.view.document ?? latest.view.design) !== original || latest.baseDir !== current.baseDir) {
      await api("/api/ops/discard", { proposal_id: result.id });
      throw new Error(t("semantic.notReady"));
    }
    setPreview(result);
    setViewportRequest({ fit: true });
    return result;
  }

  async function selectProposal(proposal, selected) {
    const current = editorState.current;
    const result = await api("/api/ops/select", { proposal_id: proposal.id, selected,
      design: current.view.document ?? current.view.design, base_dir: current.baseDir });
    setPreview(result);
    return result;
  }

  function undo() {
    if (!history?.past.length || busy) return;
    setHistory(undoHistory);
    setSaved(false); setSelection(null); setPendingPin(null);
  }
  function redo() {
    if (!history?.future.length || busy) return;
    setHistory(redoHistory);
    setSaved(false); setSelection(null); setPendingPin(null);
  }

  function connect(first, second) {
    if (!connectionReady) { notify("接口正在解析，请稍后连线", true); return; }
    mutate((next) => { const net = connectPorts(next, first, second, interfaces); setSelection({ type: "net", id: net }); }, "网络连接已更新");
    setPendingPin(null);
  }
  function pickPin(endpoint) {
    if (!connectionReady) { notify("接口正在解析，请稍后连线", true); return; }
    if (pendingPin && pendingPin !== endpoint) connect(pendingPin, endpoint);
    else { setPendingPin(pendingPin === endpoint ? null : endpoint); setSelection({ type: "port", id: endpoint }); }
  }

  function endConnection(event, state) {
    const first = state.fromHandle?.id;
    const second = state.toHandle?.id ?? (event.target instanceof Element ? event.target.closest(".react-flow__handle")?.getAttribute("data-handleid") : undefined);
    if (first && second && first !== second && !state.isValid) {
      const error = connectionReady ? connectionError(design, first, second, interfaces) : "接口正在解析，请稍后连线";
      if (error) notify(error, true);
    }
    setPendingPin(null);
  }

  useEffect(() => {
    if (!design) return;
    if (layoutPreview.current && (layoutPreview.current.snapshot !== history.current || layoutPreview.current.scope !== scope || preview || busy)) {
      layoutPreview.current = null;
      layoutController.current?.abort(t("layout.stale"));
    }
    const inputs = [design, inspection, selection, pendingPin, connectionReady, expandedGroups, scope];
    if (projectionInputs.current?.every((value, index) => value === inputs[index])) {
      const expressionPositions = new Map(expressionGraph.nodes.map((node) => [node.id, node.position]));
      setNodes((previous) => {
        markLayout("projection-start");
        let changed = false;
        const result = previous.map((node) => {
          const position = layoutPreview.current?.positions[node.id] ?? layout.nodes[node.id] ?? (node.type === "expression" ? expressionPositions.get(node.id) : defaultPosition(node.id, design));
          if (!position || node.position.x === position.x && node.position.y === position.y) return node;
          changed = true;
          return { ...node, position };
        });
        markLayout("projection-end");
        return changed ? result : previous;
      });
      return;
    }
    projectionInputs.current = inputs;
    const errors = inspection.diagnostics.join(" ");
    const locations = (inspection.structuredDiagnostics ?? []).filter((item) => item.severity === "error").map((item) => item.location);
    const errorNodes = new Set(locations.flatMap((item) => item.instance ? [item.instance] : item.external ? [externalId(item.external)] : []));
    const structured = Boolean(inspection.structuredDiagnostics?.length);
    const result = [];
    for (const [name, instance] of Object.entries(design.instances)) {
      const definition = design.modules[instance.module];
      const parameters = inspection.parameters?.[name] ?? Object.fromEntries(Object.entries(definition?.parameters ?? {}).map(([key, spec]) => [key, instance.parameters?.[key] ?? spec.default]));
      result.push({ id: name, type: "block", position: layoutPreview.current?.positions[name] ?? layout.nodes[name] ?? defaultPosition(name, design), selected: selection?.ids?.includes(name) || selection?.id === name,
        data: { name, module: instance.module, parameters, foldable: hasSubdesign(rootDocument, instance.module) && Object.keys(definition?.ports ?? {}).length > 32,
          compact: hasSubdesign(rootDocument, instance.module) && Object.keys(definition?.ports ?? {}).length > 32 && !expandedGroups.includes(`${scope}:${name}`), onTogglePins: toggleGroupPins,
          ports: Object.keys(definition?.ports ?? {}).map((port) => endpointInfo(design, `${name}.${port}`, interfaces)).filter(Boolean), onPin: stablePickPin, active: pendingPin?.startsWith(`${name}.`) ? pendingPin : null, connectable: connectionReady, highlight: structured ? errorNodes.has(name) : errors.includes(`instances.${name}.`) || errors.includes(`${name}.`) } });
    }
    for (const name of Object.keys(design.ports)) {
      const id = externalId(name);
      result.push({ id, type: "block", position: layoutPreview.current?.positions[id] ?? layout.nodes[id] ?? defaultPosition(id, design), selected: selection?.id === id,
        data: { name, external: true, ports: [endpointInfo(design, id, interfaces)], onPin: stablePickPin, active: pendingPin === id ? pendingPin : null, connectable: connectionReady, highlight: structured ? errorNodes.has(id) : errors.includes(`ports.${name}:`) } });
    }
      result.push(...expressionGraph.nodes.map((node) => ({ ...node, position: layoutPreview.current?.positions[node.id] ?? node.position,
        selected: selection?.type === "net" && selection.id === node.data.net })));
    setNodes((previous) => {
      const byId = new Map(previous.map((node) => [node.id, node]));
      return result.map((node) => {
        const prior = byId.get(node.id);
        const reusable = node.type === "block" && sameNodeData(prior?.data, node.data);
        if (reusable && prior.selected === node.selected && prior.position.x === node.position.x && prior.position.y === node.position.y) return prior;
        const geometry = reusable ? { initialWidth: prior.initialWidth, initialHeight: prior.initialHeight, handles: prior.handles } : node.type === "block" ? nodeGeometry(node.data) : {};
        const sameGeometry = prior?.initialWidth === geometry.initialWidth && prior?.initialHeight === geometry.initialHeight;
        return { ...node, ...geometry, measured: sameGeometry ? prior?.measured : undefined,
          data: reusable ? prior.data : node.data };
      });
    });
  }, [design, layout, inspection, selection, pendingPin, connectionReady, expandedGroups, scope]);

  const invalidNets = new Set((inspection.structuredDiagnostics ?? []).filter((item) => item.severity === "error").map((item) => item.location.net).filter(Boolean));
  const selectedNetId = selection?.type === "net" ? selection.id : null;
  const selectedSink = selection?.type === "net" ? selection.sink : null;
  const edges = useMemo(() => design ? Object.entries(design.nets).flatMap(([net, pins]) => {
    if (expressionGraph.nets.has(net)) return [];
    const drivers = pins.filter((pin) => endpointInfo(design, pin)?.drives);
    const driver = drivers[0] ?? pins.find((pin) => endpointInfo(design, pin));
    if (!driver) return [];
    const shape = endpointInfo(design, driver, interfaces);
    return pins.filter((pin) => pin !== driver && endpointInfo(design, pin)).map((sink, index) => ({
      id: `${net}|${sink}`, source: nodeId(driver), target: nodeId(sink), sourceHandle: driver, targetHandle: sink,
      type: "circuit", label: net, data: { net, sink, width: shape?.width ?? 1, sourceLabel: index === 0 }, selected: selectedNetId === net && (!selectedSink || selectedSink === sink),
      style: { stroke: selectedNetId === net && (!selectedSink || selectedSink === sink) ? "#0a8f7b" : invalidNets.has(net) ? "#ba4545" : (shape?.range ? "#477caa" : "#8c969f"), strokeWidth: shape?.range ? 2.4 : 1.5 },
      labelStyle: { fill: "#66747e", fontSize: 11, fontFamily: "IBM Plex Mono, monospace" }, labelBgStyle: { fill: "#f8fafb", fillOpacity: 0.95 }, labelBgPadding: [7, 3], labelBgBorderRadius: 3,
    }));
  }).concat(expressionGraph.edges.map((edge) => ({ ...edge, selected: selectedNetId === edge.data.net,
    style: { stroke: selectedNetId === edge.data.net ? "#0a8f7b" : invalidNets.has(edge.data.net) ? "#ba4545" : "#477caa", strokeWidth: edge.data.width > 1 ? 2.4 : 1.5 },
    labelStyle: { fill: "#66747e", fontSize: 11, fontFamily: "IBM Plex Mono, monospace" },
    labelBgStyle: { fill: "#f8fafb", fillOpacity: 0.95 }, labelBgPadding: [7, 3], labelBgBorderRadius: 3,
  }))) : [], [design, interfaces, inspection.structuredDiagnostics, selectedNetId, selectedSink, expressionGraph]);

  const candidate = useMemo(() => preview ? candidateGraph(preview, layout.nodes, defaultPosition) : null, [preview, layout?.nodes]);
  const bundledEdges = useMemo(() => bundleHierarchyEdges(edges, nodes), [edges, nodes]);
  const labeledEdges = useMemo(() => bundledEdges.length > 256 ? bundledEdges.map((edge) => ({ ...edge, data: { ...edge.data, labelMode: true } })) : bundledEdges, [bundledEdges]);
  const displayedEdges = useMemo(() => labeledEdges.length > 256 ? visibleLabelEdges(labeledEdges, nodes, viewport, canvasWidth, canvasHeight) : labeledEdges,
    [labeledEdges, nodes, viewport, canvasWidth, canvasHeight]);
  const previewGraph = useMemo(() => candidate ? mergePreview(nodes, edges, candidate.nodes, candidate.edges, designChanges(design, preview.canvas)) : null,
    [candidate, nodes, edges, design, preview?.canvas]);
  const graph = previewGraph ?? { nodes, edges: displayedEdges };

  useEffect(() => {
    if (!viewportRequest || !canvasWidth || !canvasHeight || !flow.viewportInitialized) return;
    if (!preview) {
      const expected = new Set([...Object.keys(design?.instances ?? {}), ...Object.keys(design?.ports ?? {}).map(externalId), ...expressionGraph.nodes.map((node) => node.id)]);
      if (nodes.length !== expected.size || nodes.some((node) => !expected.has(node.id))) return;
    }
    if (viewportRequest.waitFor && !graph.nodes.some((node) => node.id === viewportRequest.waitFor)) return;
    if (viewportRequest.positions && graph.nodes.some((node) => viewportRequest.positions[node.id] &&
      (node.position.x !== viewportRequest.positions[node.id].x || node.position.y !== viewportRequest.positions[node.id].y))) return;
    if (viewportRequest.fit && graph.nodes.length) {
      const bounds = getNodesBounds(graph.nodes);
      flow.setViewport(getViewportForBounds(bounds, canvasWidth, canvasHeight, 0.25, 1, 0.16));
    } else if (!viewportRequest.fit) flow.setViewport(viewportRequest.viewport);
    setViewportRequest(null);
  }, [viewportRequest, graph.nodes, nodes, design, expressionGraph.nodes, preview, canvasWidth, canvasHeight, flow]);

  function insertModule(module, position) {
    let id;
    if (mutate((next, nextLayout) => { id = addInstance(next, module); nextLayout.nodes[id] = position ?? defaultPosition(id, next); }, `已添加 ${module}`)) {
      setSelection({ type: "node", id }); setMobilePanel(null);
    }
  }

  function insertImported(entry, position, sourceBase) {
    if (sourceBase !== editorState.current.baseDir) { notify(t("ip.dragInvalid"), true); return; }
    let id;
    if (mutate((next, nextLayout) => { id = addImported(next, entry); nextLayout.nodes[id] = position ?? defaultPosition(id, next); }, t("ip.added", { name: entry.metadata.id }))) {
      setSelection({ type: "node", id }); setMobilePanel(null);
    }
  }

  function dropModule(event) {
    event.preventDefault();
    const position = flow.screenToFlowPosition({ x: event.clientX, y: event.clientY });
    const imported = event.dataTransfer.getData(IP_DRAG_TYPE);
    if (imported) {
      try { insertImported(findImportedDrop(imported, ipCatalog, baseDir), position, ipCatalog.baseDir); }
      catch (error) { notify(error.message, true); }
      return;
    }
    const module = event.dataTransfer.getData("application/bd-module");
    if (module) insertModule(module, position);
  }

  function removeSelection() {
    if (!selection) return;
    mutate((next, nextLayout) => {
      if (selection.type === "net" && selection.sink) disconnectPort(next, selection.sink);
      else if (selection.type === "net") delete next.nets[selection.id];
      else if (selection.type === "port") disconnectPort(next, selection.id);
      else { deleteNode(next, selection.id); delete nextLayout.nodes[selection.id]; }
    }, "已删除所选项");
    setSelection(null); setPendingPin(null);
  }

  function exposePort(endpoint) {
    if (!connectionReady) { notify("接口正在解析，请稍后外引端口", true); return; }
    let id;
    if (mutate((next, nextLayout) => { id = makeExternal(next, endpoint, interfaces); nextLayout.nodes[id] = defaultPosition(id, next); }, "已创建外部端口")) setSelection({ type: "node", id });
  }

  async function autoLayout() {
    if (preview || busy || !nodes.length || layoutRunning) return;
    markLayout("requested");
    const initial = editorState.current;
    const snapshot = initial.history.current;
    const originalPositions = new Map(nodes.map((node) => [node.id, node.position]));
    const controller = new AbortController();
    layoutController.current = controller;
    setLayoutRunning(true);
    setActivity(t("layout.running"));
    try {
      const pending = requestLayout(nodes, edges, { signal: controller.signal });
      markLayout("posted");
      const positions = await pending;
      markLayout("received");
      let current = editorState.current;
      if (current.history.current !== snapshot || current.scope !== initial.scope || current.baseDir !== initial.baseDir || current.preview || current.busy) {
        notify(t("layout.stale"));
        return;
      }
      layoutPreview.current = { snapshot, scope: current.scope, positions: Object.create(null) };
      await publishPositions(positions, (batch) => {
        Object.assign(layoutPreview.current.positions, batch);
        setNodes((previous) => previous.map((node) => Object.hasOwn(batch, node.id) && !node.dragging ? { ...node, position: batch[node.id] } : node));
      }, { signal: controller.signal });
      current = editorState.current;
      if (current.history.current !== snapshot || current.scope !== initial.scope || current.baseDir !== initial.baseDir || current.preview || current.busy) {
        controller.abort(t("layout.stale"));
        throw new DOMException("Aborted", "AbortError");
      }
      layoutPreview.current = null;
      const next = mergeScopeState(snapshot, { ...current.view, layout: { ...current.view.layout, nodes: { ...current.view.layout.nodes, ...positions } } }, current.scope);
      const nextHistory = commitHistory(current.history, next);
      editorState.current = { ...current, history: nextHistory };
      setHistory(nextHistory);
      setSaved(false);
      setActivity(t("layout.applied"));
      if (nodes.length <= 500) setViewportRequest({ fit: true, positions });
      markLayout("queued");
    } catch (error) {
      layoutPreview.current = null;
      const current = editorState.current;
      setNodes((previous) => previous.map((node) => {
        if (node.dragging) return node;
        const position = current.history.current === snapshot && current.scope === initial.scope ? originalPositions.get(node.id) :
          current.view.layout.nodes[node.id] ?? (node.type === "block" ? defaultPosition(node.id, current.view.design) : node.position);
        return position ? { ...node, position } : node;
      }));
      if (layoutController.current === controller) notify(error.name === "AbortError" ? typeof controller.signal.reason === "string" ? controller.signal.reason : t("layout.cancelled") : error.message, error.name !== "AbortError");
    } finally {
      if (layoutController.current === controller) { layoutController.current = null; setLayoutRunning(false); }
    }
  }

  function newDocument() {
    if (!saved && !window.confirm("当前设计尚未保存，仍要新建吗？")) return;
    mutate((next, nextLayout) => { next.name = "untitled_bd"; next.instances = {}; next.ports = {}; next.nets = {}; nextLayout.nodes = {}; }, "已新建设计");
    setDocumentPath(""); setSelection(null); setPendingPin(null);
    setViewportRequest({ fit: true });
  }

  async function openDialog() {
    try { const result = await api("/api/designs"); setModal({ kind: "open", path: result.paths[0] ?? "", paths: result.paths }); }
    catch (error) { notify(error.message, true); }
  }
  function saveDialog() { setModal({ kind: "save", path: documentPath.startsWith("designs/") ? documentPath : `designs/${rootDocument.name}.json` }); }

  async function collapseSelection() {
    const selected = (selection?.ids ?? (selection?.type === "node" ? [selection.id] : [])).filter((name) => design.instances[name]);
    const snapshot = editorState.current.history.current;
    const result = await api("/api/hierarchy/collapse", { design: document, base_dir: baseDir, selection: selected, name: modal.name });
    if (editorState.current.history.current !== snapshot) throw new Error(t("semantic.notReady"));
    if (!result.valid) throw new Error(normalizeInspection(result).diagnostics[0]);
    const applied = mutate((next, nextLayout) => {
      const childNodes = Object.fromEntries(selected.map((name) => [name, nextLayout.nodes[name] ?? defaultPosition(name, design)]));
      const position = childNodes[selected[0]];
      for (const key of Object.keys(next)) delete next[key];
      Object.assign(next, result.canvas);
      for (const name of selected) delete nextLayout.nodes[name];
      nextLayout.nodes[modal.name] = position;
      nextLayout.schema_version = 1;
      nextLayout.scopes = { ...nextLayout.scopes, [modal.name]: { nodes: childNodes, viewport: initialLayout.viewport } };
    }, t("hierarchy.folded"), false, result.document);
    if (!applied) throw new Error(t("semantic.notReady"));
    setSelection({ type: "node", id: modal.name });
  }

  async function submitModal(event) {
    event.preventDefault();
    try {
      if (modal.kind === "save") {
        setBusy("保存中");
        const savedLayout = scope ? mergeScopeState(history.current, { ...view, layout: { ...layout, viewport: flow.getViewport() } }, scope).layout : { ...layout, viewport: flow.getViewport() };
        const result = await api("/api/save", { design: rootDocument, layout: savedLayout, base_dir: baseDir, path: modal.path });
        acceptDocument(result);
        notify(`已保存 ${result.path}`); setActivity(`设计与布局已保存 · ${result.path}`);
      } else if (modal.kind === "open") {
        if (!saved && !window.confirm("当前设计尚未保存，仍要打开其他设计吗？")) return;
        setBusy("打开中");
        acceptDocument(await api(`/api/load?path=${encodeURIComponent(modal.path)}`));
        setActivity(`已打开 ${modal.path}`);
      } else if (modal.kind === "hierarchy") {
        await collapseSelection();
      } else if (modal.kind === "external") {
        let id;
        const ok = mutate((next, nextLayout) => {
          checkName(next, modal.name);
          const spec = { direction: modal.direction };
          if (modal.vector) spec.range = [parseInteger(modal.left), parseInteger(modal.right)];
          if (modal.signed) spec.signed = true;
          next.ports[modal.name] = spec;
          id = externalId(modal.name); nextLayout.nodes[id] = defaultPosition(id, next);
        }, "已添加外部端口");
        if (!ok) return;
        setSelection({ type: "node", id });
      } else if (modal.kind === "module") {
        const definition = JSON.parse(modal.json);
        const ok = mutate((next) => {
          checkName({ instances: {}, ports: {}, nets: next.modules }, modal.name);
          next.modules[modal.name] = definition;
          validateDocumentShape(next);
        }, "模块元数据已登记");
        if (!ok) return;
      }
      setModal(null);
    } catch (error) { notify(error.message, true); }
    finally { setBusy(""); }
  }

  async function generate() {
    try {
      setBusy("生成中");
      const result = await api("/api/generate", { design: rootDocument, base_dir: baseDir, design_path: documentPath, quality: true, lang: hdlLanguage });
      setInspection((previous) => ({ ...previous, files: result.files }));
      setTab("bd"); setPanelOpen(true);
      setActivity(`已生成 ${result.paths.join(" / ")}`); notify(t("hdl.generated", { language: t(hdlLanguage === "sv" ? "hdl.systemVerilog" : "hdl.verilog") }));
    } catch (error) { notify(error.message, true); }
    finally { setBusy(""); }
  }

  async function validateNow() {
    try {
      setChecking(true);
      const result = normalizeInspection(await api(scope ? "/api/hierarchy/inspect" : "/api/semantic/inspect", { design: scope ? rootDocument : document, scope, base_dir: baseDir }));
      inspectedDesign.current = design;
      inspectedSnapshot.current = { document, rootDocument, baseDir };
      setInspection(result); setTab("diagnostics"); setPanelOpen(true);
      notify(result.valid ? "设计校验通过" : result.diagnostics[0], !result.valid);
    } catch (error) { notify(error.message, true); }
    finally { setChecking(false); }
  }

  async function checkHdl() {
    if (hdlRunning || checking || busy || preview || !inspection.valid) return;
    const snapshot = rootDocument, sourceBase = baseDir, language = hdlLanguage;
    setHdlRunning(true);
    try {
      const result = await api("/api/check-hdl", { design: snapshot, base_dir: sourceBase, lang: language });
      const latest = editorState.current;
      if ((latest.history.current.document ?? latest.history.current.design) !== snapshot || latest.baseDir !== sourceBase || hdlLanguageRef.current !== language) {
        notify(t("hdl.stale"));
        return;
      }
      setHdlResult({ document: snapshot, baseDir: sourceBase, language, result });
      setInspection((previous) => ({ ...previous, files: result.files }));
      setTab("diagnostics"); setPanelOpen(true);
    } catch (error) { notify(error.message, true); }
    finally { setHdlRunning(false); }
  }

  useEffect(() => {
    const handleKey = (event) => {
      if (!design || busy || preview || modal || ipImportOpen || connectionOpen || aiSettingsOpen || privacy.confirming || /INPUT|TEXTAREA|SELECT/.test(event.target.tagName) || event.target.closest?.(".cm-editor")) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); saveDialog(); }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") { event.preventDefault(); event.shiftKey ? redo() : undo(); }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") { event.preventDefault(); redo(); }
      if (event.key === "Delete" || event.key === "Backspace") { event.preventDefault(); removeSelection(); }
      if (event.key === "Escape") { setSelection(null); setPendingPin(null); setMobilePanel(null); }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  });

  function focusDiagnostic(message) {
    if (typeof message !== "string") {
      const location = message.location ?? {};
      const id = location.instance ?? (location.external ? externalId(location.external) : null);
      setPendingPin(null);
      const destination = hasSubdesign(rootDocument, location.design) ? location.design : "";
      if (destination !== scope) {
        setScopePath(destination ? [destination] : []);
        setSelection(id ? { type: "node", id } : location.net ? { type: "net", id: location.net } : null);
        setViewportRequest({ fit: true, waitFor: id });
        setMobilePanel("inspector");
        return;
      }
      if (id && (Object.hasOwn(design.instances, id) || id.startsWith("@") && Object.hasOwn(design.ports, id.slice(1)))) {
        setSelection({ type: "node", id });
        flow.fitView({ nodes: [{ id }], duration: 250, maxZoom: 1.15, padding: 0.4 });
      } else if (location.net && Object.hasOwn(design.nets, location.net)) {
        setSelection({ type: "net", id: location.net });
        const ids = [...new Set([...design.nets[location.net].map(nodeId), ...flow.getNodes().filter((node) => node.data.net === location.net).map((node) => node.id)])];
        flow.fitView({ nodes: ids.map((id) => ({ id })), duration: 250, maxZoom: 1.15, padding: 0.4 });
      } else setSelection(null);
      setMobilePanel("inspector");
      return;
    }
    const id = Object.keys(design.instances).find((name) => message.includes(`${name}.`));
    if (id) { setSelection({ type: "node", id }); flow.fitView({ nodes: [{ id }], duration: 250, maxZoom: 1.15, padding: 0.4 }); setMobilePanel("inspector"); }
    else {
      const net = Object.keys(design.nets).find((name) => message.includes(`nets.${name}:`));
      if (net) { setSelection({ type: "net", id: net }); setMobilePanel("inspector"); }
    }
  }

  async function applyDiagnosticFix(diagnostic) {
    if (fixing || busy || checking) return;
    const snapshot = editorState.current.history.current;
    const sourceBase = editorState.current.baseDir;
    setFixing(true);
    try {
      const result = await api("/api/semantic/fix", { design: document, base_dir: sourceBase, diagnostic });
      if (editorState.current.history.current !== snapshot || editorState.current.baseDir !== sourceBase) throw new Error(t("semantic.notReady"));
      if (!result.canvas || !result.document) throw new Error(normalizeInspection(result).diagnostics[0]);
      const applied = mutate((next) => { for (const key of Object.keys(next)) delete next[key]; Object.assign(next, result.canvas); }, t("semantic.fixApplied"), false, result.document);
      if (!applied) throw new Error(t("semantic.notReady"));
      notify(t("semantic.fixApplied"));
    } catch (error) { notify(error.message, true); }
    finally { setFixing(false); }
  }

  async function applyJson() {
    try {
      const parsed = JSON.parse(jsonDraft);
      setChecking(true);
      const snapshot = editorState.current.history.current;
      const result = await api("/api/semantic/inspect", { design: parsed, base_dir: baseDir });
      if (editorState.current.history.current !== snapshot) throw new Error(t("semantic.notReady"));
      if (!result.canvas || !result.document) throw new Error(normalizeInspection(result).diagnostics[0]);
      validateDocumentShape(result.canvas);
      mutate((next) => { for (const key of Object.keys(next)) delete next[key]; Object.assign(next, result.canvas); }, t("semantic.jsonApplied"), false, result.document);
    } catch (error) { notify(error.message, true); }
    finally { setChecking(false); }
  }

  async function applyConnection(name, index, endpoint) {
    const current = editorState.current;
    const snapshot = current.history.current;
    if (!connectionReady || current.busy) throw new Error(t("semantic.notReady"));
    const candidate = replaceEndpoint(current.view.document ?? inspection.document, name, index, endpoint);
    const result = await api("/api/semantic/inspect", { design: candidate, base_dir: current.baseDir });
    if (editorState.current.history.current !== snapshot || editorState.current.baseDir !== current.baseDir) throw new Error(t("semantic.notReady"));
    if (!result.canvas || !result.document) throw new Error(normalizeInspection(result).diagnostics[0]);
    const applied = mutate((next) => { for (const key of Object.keys(next)) delete next[key]; Object.assign(next, result.canvas); }, t("semantic.connectionChanged"), false, result.document);
    if (applied && (endpoint.const !== undefined || endpoint.concat)) setViewportRequest({ fit: true, waitFor: expressionId(name, index) });
    return applied;
  }

  const connectionPorts = useMemo(() => design ? [...Object.keys(design.ports).map(externalId), ...Object.entries(design.instances).flatMap(([name, item]) =>
    Object.keys(design.modules[item.module]?.ports ?? {}).map((port) => `${name}.${port}`))].map((value) => ({ ...endpointInfo(design, value, interfaces), value })) : [], [design, interfaces]);
  const connectedPins = useMemo(() => new Set(Object.values(design?.nets ?? {}).flat()), [design?.nets]);

  if (!design) return <div className="boot-screen"><CircuitBoard size={36} /><h1>BD Studio</h1>{fatal ? <><p role="alert">{fatal}</p><button onClick={() => location.reload()}>重新连接</button></> : <LoaderCircle className="spin" size={20} />}</div>;

  const moduleNames = Object.keys(design.modules).filter((name) => [name, ...Object.keys(design.modules[name].ports)].some((value) => value.toLowerCase().includes(search.toLowerCase())));
  const moduleFilename = tab === "wrapper" ? `${rootDocument.name}_wrapper` : design.name;
  const requestedFilename = `${moduleFilename}.${hdlLanguage === "sv" ? "sv" : "v"}`;
  const filename = Object.hasOwn(inspection.files, requestedFilename) ? requestedFilename : `${moduleFilename}.v`;
  const code = inspection.files[filename] ?? "";
  const selectionNode = selection?.type === "node" ? selection.id : selection?.type === "port" ? nodeId(selection.id) : null;
  const instance = selectionNode && !selectionNode.startsWith("@") ? design.instances[selectionNode] : null;
  const external = selectionNode?.startsWith("@") ? design.ports[selectionNode.slice(1)] : null;
  const definition = instance ? design.modules[instance.module] : null;
  const selectedNet = selection?.type === "net" ? design.nets[selection.id] : null;
  const semanticDocument = view.document ?? inspection.document;
  const selectedNetRecord = selectedNet && semanticDocument?.nets.find((net) => net.name === selection.id);
  const totalPins = Object.values(design.instances).reduce((count, item) => count + Object.keys(design.modules[item.module]?.ports ?? {}).length, 0);

  const renameSelected = (name) => {
    let newId;
    const replacement = view.document ? renameSemantic(view.document, selectionNode, name) : null;
    const ok = mutate((next, nextLayout) => { newId = renameNode(next, nextLayout, selectionNode, name); }, "名称与端点引用已更新", false, replacement);
    if (ok) setSelection({ type: "node", id: newId });
    return ok;
  };

  return <div className="app-shell">
    <header className="app-header">
      <div className="brand"><span className="brand-symbol"><CircuitBoard size={22} strokeWidth={1.6} /></span><span>BD <strong>Studio</strong></span><span className="local-badge">LOCAL</span></div>
      <div className="header-center"><span className="session-dot" />RTL WORKSPACE</div>
      <div className="header-actions">
        <IconButton icon={Bot} label={scope ? t("ai.rootOnly") : "Copilot 助手"} aria-pressed={copilotOpen} disabled={Boolean(preview || scope)} onClick={() => setCopilotOpen(!copilotOpen)} />
        <IconButton icon={Sparkles} label={t(scope ? "ai.rootOnly" : "ai.assistant")} disabled={Boolean(scope)} onClick={() => { setCopilotOpen(false); setAssistantOpen(true); }} />
        <IconButton icon={Settings2} label={t("ai.settings")} onClick={() => setAiSettingsOpen(true)} disabled={Boolean(busy)} />
        <IconButton icon={FilePlus2} label="新建设计" onClick={newDocument} disabled={Boolean(busy || preview)} />
        <IconButton icon={FolderOpen} label="打开设计" onClick={openDialog} disabled={Boolean(busy || preview)} />
        <span className="toolbar-divider" />
        <button className="button secondary" onClick={saveDialog} disabled={Boolean(busy || preview)} title="保存设计" aria-label="保存设计"><Save size={15} /><span>保存</span></button>
        <button className="button primary" onClick={generate} disabled={!connectionReady || !inspection.valid} title="生成 HDL"><Code2 size={16} /><span>生成 HDL</span></button>
      </div>
    </header>

    <div className="design-toolbar">
      <div className="document-title"><Workflow size={17} />{scope ? <nav className="hierarchy-path" aria-label={t("hierarchy.path")}><button onClick={() => { setScopePath([]); setSelection(null); setViewportRequest({ fit: true }); }}>{rootDocument.name}</button>{scopePath.map((name, index) => <React.Fragment key={`${name}-${index}`}><span>/</span><button onClick={() => { setScopePath(scopePath.slice(0, index + 1)); setSelection(null); setViewportRequest({ fit: true }); }}>{name}</button></React.Fragment>)}</nav> : <h1>{design.name}</h1>}<span className={`save-state ${saved ? "" : "dirty"}`}>{saved ? "已保存" : "未保存"}</span></div>
      <div className="design-tools">
        <IconButton icon={PanelLeft} label="模块面板" className={mobilePanel === "library" ? "active" : ""} onClick={() => setMobilePanel(mobilePanel === "library" ? null : "library")} />
        <IconButton icon={Undo2} label="撤销" onClick={undo} disabled={!history.past.length || Boolean(busy || preview)} />
        <IconButton icon={Redo2} label="重做" onClick={redo} disabled={!history.future.length || Boolean(busy || preview)} />
        <span className="toolbar-divider compact-hide" />
        <button className={`validation-badge ${inspection.valid && !checking ? "valid" : ""}`} onClick={validateNow} disabled={checking || Boolean(busy)} title="校验设计" aria-label="校验设计">
          {checking ? <LoaderCircle size={14} className="spin" /> : inspection.valid ? <ShieldCheck size={15} /> : <CircleAlert size={15} />}<span>{checking ? "校验中" : inspection.valid ? "校验通过" : "待修复"}</span>
        </button>
        <IconButton icon={PanelRight} label="属性面板" className={mobilePanel === "inspector" ? "active" : ""} onClick={() => setMobilePanel(mobilePanel === "inspector" ? null : "inspector")} />
      </div>
    </div>

    <main className="workbench" inert={busy ? true : undefined}>
      {mobilePanel && <button className="panel-scrim" aria-label="关闭侧面板" onClick={() => setMobilePanel(null)} />}
      <aside className={`library-panel ${mobilePanel === "library" ? "mobile-open" : ""}`}>
        <div className="panel-heading"><span>模块库</span><span className="count-badge">{Object.keys(design.modules).length}</span><ImportButton token={token} onOpenChange={setIpImportOpen} onComplete={() => setIpRevision((value) => value + 1)} onNotify={notify} /><IconButton icon={Plus} label="登记 RTL 模块" onClick={() => setModal({ kind: "module", name: "my_module", json: JSON.stringify({ sources: ["rtl/my_module.v"], parameters: {}, ports: { clk: { direction: "input" }, result: { direction: "output" } } }, null, 2) })} /></div>
        <label className="search-box"><Search size={14} /><input aria-label="搜索模块" placeholder="搜索模块" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
        <LibraryList baseDir={baseDir} revision={ipRevision} search={search} onCatalogChange={setIpCatalog} onAdd={insertImported} />
        <div className="library-section-title"><ChevronDown size={13} />PROJECT RTL<span>{moduleNames.length}</span></div>
        <div className="module-list">{moduleNames.map((module) => <div className="module-item" key={module} draggable onDragStart={(event) => { event.dataTransfer.setData("application/bd-module", module); event.dataTransfer.effectAllowed = "copy"; }} onDoubleClick={() => insertModule(module)}>
          <div className={`module-icon ${module.includes("compare") ? "amber" : "blue"}`}><Cpu size={19} strokeWidth={1.5} /></div><div className="module-label"><strong>{module}</strong><span>{Object.keys(design.modules[module].ports).length} ports · RTL</span><OriginBadge origin={originForDefinition(module, design.modules[module], ipCatalog.entries)} /></div><IconButton icon={Plus} label={`添加 ${module}`} onClick={() => insertModule(module)} />
        </div>)}</div>
        {!moduleNames.length && <div className="empty-small">没有匹配的模块</div>}
        <div className="library-section-title external-title"><ChevronDown size={13} />EXTERNAL I/O<IconButton icon={Plus} label="添加外部端口" onClick={() => setModal({ kind: "external", name: uniqueName(design, "port"), direction: "input", vector: false, left: "7", right: "0", signed: false })} /></div>
        <div className="external-list">{Object.entries(design.ports).map(([name, port]) => <button key={name} className={`external-item ${selectionNode === externalId(name) ? "active" : ""}`} onClick={() => { setSelection({ type: "node", id: externalId(name) }); setMobilePanel("inspector"); }}><ArrowUpRight size={14} /><span>{name}</span><code>{port.direction === "input" ? "IN" : "OUT"}</code></button>)}</div>
        <div className="library-footer"><span className="session-dot" />Python core<span>CONNECTED</span></div>
      </aside>

      <section className="center-panel">
        <div className="canvas-heading"><div><span className="canvas-tab"><Workflow size={14} />Block Design</span><span className="canvas-meta">{Object.keys(design.instances).length} instances <span>/</span> {Object.keys(design.nets).length} nets</span></div><div><IconButton icon={Blocks} label={t("hierarchy.collapse")} disabled={!connectionReady || !inspection.valid || selection?.type !== "node" || !design.instances[selection.id]} onClick={() => setModal({ kind: "hierarchy", name: uniqueName(design, "group") })} /><IconButton icon={layoutRunning ? LoaderCircle : LayoutGrid} className={layoutRunning ? "spin" : ""} label={layoutRunning ? t("layout.running") : "整理布局"} disabled={layoutRunning || Boolean(preview) || !nodes.length} onClick={autoLayout} />{layoutRunning && <IconButton icon={X} label={t("layout.cancel")} onClick={() => layoutController.current?.abort()} />}<IconButton icon={Maximize2} label="适应画布" onClick={() => flow.fitView({ padding: 0.16, duration: 250 })} /></div></div>
        <div className="canvas" aria-label="设计画布" data-layout-state={layoutRunning ? "running" : "idle"} data-layout-stage={layoutPreview.current ? "applying" : layoutRunning ? "computing" : "idle"} onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }} onDrop={dropModule}>
          <ReactFlow {...flowStaticProps.current} onlyRenderVisibleElements nodes={graph.nodes} edges={graph.edges} nodesDraggable={!preview} nodesConnectable={!preview} elementsSelectable={!preview} nodeTypes={nodeTypes} edgeTypes={edgeTypes} minZoom={0.25} maxZoom={2} deleteKeyCode={null} connectOnClick={false} snapToGrid
            connectionMode={ConnectionMode.Loose} connectionLineType={ConnectionLineType.Step}
            isValidConnection={isValidConnection}
            fitView={!Object.keys(layout.nodes).length} defaultViewport={layout.viewport}
            onNodesChange={onNodesChange}
            onNodeDragStop={onNodeDragStop}
            onNodeClick={onNodeClick}
            onNodeDoubleClick={onNodeDoubleClick}
            onEdgeClick={onEdgeClick}
            onPaneClick={onPaneClick}
            onConnect={onConnect}
            onConnectEnd={onConnectEnd}
            onMoveEnd={onMoveEnd}>
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#cbd4dc" />
          </ReactFlow>
          <div className="canvas-stamp"><CircuitBoard size={13} />STRUCTURAL RTL</div>
          {preview && <div className="ai-preview-legend"><strong>{t("ai.preview")}</strong><span className="added">{t("ai.added")}</span><span className="deleted">{t("ai.deleted")}</span><span className="modified">{t("ai.modified")}</span></div>}
          {pendingPin && <div className="connection-indicator"><span className="session-dot" /><code>{pendingPin}</code><IconButton icon={X} label="取消连线" onClick={() => setPendingPin(null)} /></div>}
          {!graph.nodes.length && <div className="empty-canvas"><Blocks size={38} strokeWidth={1} /><span>空白设计</span><button className="button secondary" onClick={() => setMobilePanel("library")}><Plus size={15} />添加模块</button></div>}
          <div className="canvas-controls"><IconButton icon={ZoomOut} label="缩小" onClick={() => flow.zoomOut({ duration: 150 })} /><span>{zoom}%</span><IconButton icon={ZoomIn} label="放大" onClick={() => flow.zoomIn({ duration: 150 })} /><span className="toolbar-divider" /><IconButton icon={Maximize2} label="适应所有节点" onClick={() => flow.fitView({ padding: 0.16, duration: 250 })} /></div>
        </div>

        <OutputWindow open={panelOpen} onOpenChange={setPanelOpen} tab={tab}
          tabs={[ { id: "diagnostics", label: "诊断", Icon: ListTree }, { id: "bd", label: "BD Verilog", Icon: Code2 }, { id: "wrapper", label: "Wrapper", Icon: Blocks }, { id: "json", label: "设计 JSON", Icon: CircuitBoard } ].map(({ id, label, Icon }) => <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "active" : ""}
            onPointerEnter={() => { if (id !== "diagnostics") prepareOutputEditor().catch(() => undefined); }} onFocus={() => { if (id !== "diagnostics") prepareOutputEditor().catch(() => undefined); }}
            onClick={(event) => { if (id !== "diagnostics") markOutput(`activate:${id}`, event.timeStamp); setTab(id); setPanelOpen(true); }}><Icon size={14} />{label}{id === "diagnostics" && inspection.diagnostics.length > 0 && <b>{inspection.diagnostics.length}</b>}</button>).concat([<select key="hdl-language" className="output-language" aria-label={t("hdl.language")} title={t("hdl.language")} value={hdlLanguage} disabled={Boolean(busy)} onChange={(event) => setHdlLanguage(event.target.value)}><option value="v">{t("hdl.verilog")}</option><option value="sv">{t("hdl.systemVerilog")}</option></select>, <IconButton key="hdl-check" icon={hdlRunning ? LoaderCircle : ShieldCheck} label={t(hdlRunning ? "hdl.running" : "hdl.check")} disabled={hdlRunning || checking || Boolean(busy || preview) || !inspection.valid} onClick={checkHdl} />])}>
          {panelOpen && <div className="output-content" role="tabpanel">
            {tab === "diagnostics" ? <>
              <div className={`diagnostic-summary ${inspection.valid ? "success" : ""}`}>{checking ? <LoaderCircle size={18} className="spin" /> : inspection.valid ? <CircleCheck size={19} /> : <CircleAlert size={19} />}<div><strong>{checking ? "正在校验设计" : inspection.valid ? "所有连接检查通过" : "设计存在待修复项"}</strong><span>{inspection.valid ? `${totalPins} 个实例端口 · ${Object.keys(design.ports).length} 个外部端口 · ${Object.keys(design.nets).length} 条网络` : "DesignError"}</span></div>{inspection.valid && <span className="diagnostic-tag">VALID</span>}</div>
              {inspection.structuredDiagnostics?.length ? <Diagnostics items={inspection.structuredDiagnostics} disabled={checking || Boolean(busy) || fixing} onFocus={focusDiagnostic} onFix={applyDiagnosticFix} />
                : inspection.diagnostics.map((message) => <button className="diagnostic-error" key={message} onClick={() => focusDiagnostic(message)}><CircleAlert size={15} /><code>{message}</code><ArrowUpRight size={14} /></button>)}
              {currentHdlResult && <section aria-label={t("hdl.results")}><div className="activity-line"><ShieldCheck size={14} /><span>{t(currentHdlResult.valid ? "hdl.passed" : "hdl.failed")}</span></div>
                <div className="activity-line">{currentHdlResult.tools.map((tool) => <span key={tool.name} title={tool.version}>{tool.name} {t(`hdl.stage.${tool.stage}`)}: {t(`hdl.status.${tool.status}`)}{tool.cell_count !== undefined && ` · ${t("hdl.cells", { count: tool.cell_count })}`}</span>)}</div>
                <Diagnostics items={currentHdlResult.diagnostics} disabled onFocus={focusDiagnostic} onFix={applyDiagnosticFix} /></section>}
              <div className="activity-line"><CheckCheck size={14} /><span>{activity}</span></div>
            </> : tab === "json" ? <div className="json-editor"><div className="code-toolbar"><div className="code-file-actions"><IconButton icon={Copy} label={t("output.copyJson")} onClick={() => navigator.clipboard.writeText(jsonDraft).catch(() => notify(t("output.copyFailed"), true))} /><IconButton icon={Download} label={t("output.downloadJson")} onClick={() => downloadFile(`${design.name}.json`, jsonDraft)} /><code>{scope ? `${design.name}.json` : documentPath || `${design.name}.json`}</code></div><button className="small-command" onClick={applyJson}><Check size={13} />{t("semantic.applyJson")}</button></div>
              <OutputEditor value={jsonDraft} language="json" readOnly={false} label={t("semantic.designJson")} cache={outputStates.current} cacheKey={`${baseDir}:${documentPath}:${scope}:json`} onChange={setJsonDraft} /></div>
              : <div className="code-view"><div className="code-toolbar"><div className="code-file-actions"><IconButton icon={Copy} label="复制代码" disabled={!code} onClick={() => navigator.clipboard.writeText(code).then(() => notify("代码已复制")).catch((error) => notify(error.message, true))} /><IconButton icon={Download} label="下载 Verilog" disabled={!code} onClick={() => downloadFile(filename, code)} /><code>{filename}</code></div></div>{code ?
                <OutputEditor value={code} language={filename.endsWith(".sv") ? "systemverilog" : "verilog"} readOnly label={t(filename.endsWith(".sv") ? "output.systemVerilog" : "output.verilog")} cache={outputStates.current} cacheKey={`${baseDir}:${documentPath}:${filename}`} />
                : <div className="empty-small">{checking ? "正在生成预览" : "设计通过校验后可预览 HDL"}</div>}</div>}
          </div>}
        </OutputWindow>
      </section>

      <aside className={`inspector-panel ${mobilePanel === "inspector" ? "mobile-open" : ""}`}>
        <div className="panel-heading"><Settings2 size={15} /><span>属性</span>{selection && <IconButton icon={Trash2} label="删除所选项" onClick={removeSelection} />}</div>
        <div className="inspector-content">
          {instance ? <>
            <div className="inspector-object"><div className="inspector-symbol"><Cpu size={24} strokeWidth={1.4} /></div><span>RTL INSTANCE</span><h2>{selectionNode}</h2><code>{instance.module}</code></div>
            <section className="property-section"><h3>实例</h3><label className="field-label">名称<CommitInput label="实例名称" value={selectionNode} onCommit={renameSelected} /></label><div className="source-path"><span>Source</span>{definition?.sources?.map((path) => <code key={path}>{path}</code>)}</div></section>
            <Parameters instance={selectionNode} definition={definition} overrides={instance.parameters} resolved={inspection.parameters?.[selectionNode]}
              disabled={!connectionReady || !inspection.document} onError={notify} onCommit={(name, value) => mutate((next) => {
                next.instances[selectionNode].parameters ??= {};
                if (value === undefined) delete next.instances[selectionNode].parameters[name];
                else Object.defineProperty(next.instances[selectionNode].parameters, name, { value, writable: true, enumerable: true, configurable: true });
              }, t("semantic.parameterChanged"), true)} />
            <section className="property-section"><h3>端口<span>{Object.keys(definition?.ports ?? {}).length}</span></h3>{Object.keys(definition?.ports ?? {}).map((name) => {
              const endpoint = `${selectionNode}.${name}`;
              const port = endpointInfo(design, endpoint, inspection.interfaces);
              if (!port) return null;
              const connected = connectedPins.has(endpoint);
              return <div className={`inspector-port ${selection?.id === endpoint ? "active" : ""}`} key={name}><button onClick={() => { setSelection({ type: "port", id: endpoint }); setPendingPin(null); }}><span className={`port-status ${connected ? "connected" : ""}`} /><span><code>{name}</code><small>{port.direction} · {rangeLabel(port)}</small></span></button><IconButton icon={ArrowUpRight} label={`设为外部端口 ${endpoint}`} onClick={() => exposePort(endpoint)} /><IconButton icon={Unplug} label={`断开 ${endpoint}`} disabled={!connected} onClick={() => mutate((next) => disconnectPort(next, endpoint), `${endpoint} 已断开`)} /></div>;
            })}</section>
          </> : external ? <>
            <div className="inspector-object"><div className="inspector-symbol teal"><ArrowUpRight size={25} /></div><span>EXTERNAL PORT</span><h2>{selectionNode.slice(1)}</h2><code>{external.direction}</code></div>
            <section className="property-section"><h3>外部端口</h3><label className="field-label">名称<CommitInput label="外部端口名称" value={selectionNode.slice(1)} onCommit={renameSelected} /></label><label className="field-label">方向<select aria-label="外部端口方向" value={external.direction} onChange={(event) => mutate((next) => { next.ports[selectionNode.slice(1)].direction = event.target.value; })}><option value="input">Input</option><option value="output">Output</option></select></label>
              <label className="check-field"><input type="checkbox" checked={Boolean(external.range)} onChange={(event) => mutate((next) => { const spec = next.ports[selectionNode.slice(1)]; if (event.target.checked) spec.range = [7, 0]; else delete spec.range; })} />向量端口</label>
              {external.range && <div className="range-fields"><label>Left<CommitInput label="范围左索引" value={external.range[0]} onCommit={(value) => mutate((next) => { next.ports[selectionNode.slice(1)].range[0] = parseInteger(value); })} /></label><span>:</span><label>Right<CommitInput label="范围右索引" value={external.range[1]} onCommit={(value) => mutate((next) => { next.ports[selectionNode.slice(1)].range[1] = parseInteger(value); })} /></label></div>}
              <label className="check-field"><input type="checkbox" checked={Boolean(external.signed)} onChange={(event) => mutate((next) => { next.ports[selectionNode.slice(1)].signed = event.target.checked; })} />Signed</label>
            </section>
          </> : selectedNet ? <>
            <div className="inspector-object"><div className="inspector-symbol teal"><Workflow size={25} /></div><span>SIGNAL NET</span><h2>{selection.id}</h2><code>{t("semantic.endpointCount", { count: selectedNetRecord?.endpoints.length ?? selectedNet.length })}</code></div>
            <section className="property-section"><h3>网络</h3><label className="field-label">名称<CommitInput label="网络名称" value={selection.id} onCommit={(name) => {
              const replacement = history.current.document ? renameSemantic(history.current.document, selection.id, name, "net") : null;
              const ok = mutate((next) => renameNet(next, selection.id, name), undefined, false, replacement);
              if (ok) setSelection({ type: "net", id: name }); return ok;
            }} /></label></section>
            <Connections document={semanticDocument} name={selection.id} ports={connectionPorts} resolved={inspection.connections?.find((net) => net.name === selection.id)}
              disabled={!connectionReady} onApply={applyConnection} onOpenChange={setConnectionOpen} />
          </> : <>
            <div className="inspector-object"><div className="inspector-symbol teal"><Workflow size={25} strokeWidth={1.5} /></div><span>BLOCK DESIGN</span><h2>{design.name}</h2><code>{t(hdlLanguage === "sv" ? "hdl.systemVerilog" : "hdl.verilog2005")}</code></div>
            <section className="property-section"><h3>设计</h3><label className="field-label">模块名称<CommitInput label="设计名称" value={design.name} onCommit={(value) => mutate((next) => { checkName({ instances: {}, ports: {}, nets: {} }, value); next.name = value; })} /></label><div className="source-path"><span>Design file</span><code>{documentPath || "未保存"}</code><span>Source base</span><code>{baseDir}/</code></div></section>
            <section className="property-section"><h3>概览</h3><dl className="design-stats"><div><dt>模块实例</dt><dd>{Object.keys(design.instances).length}</dd></div><div><dt>信号网络</dt><dd>{Object.keys(design.nets).length}</dd></div><div><dt>外部端口</dt><dd>{Object.keys(design.ports).length}</dd></div><div><dt>输出文件</dt><dd>2</dd></div></dl></section>
            <section className="property-section"><h3>生成目标</h3><div className="output-file"><Code2 size={16} /><code>{`${design.name}.${hdlLanguage}`}</code></div><div className="output-file"><Blocks size={16} /><code>{`${rootDocument.name}_wrapper.${hdlLanguage}`}</code></div><span className="directory-label">build/gui/</span></section>
          </>}
        </div>
        <div className="inspector-footer"><ShieldCheck size={14} />{inspection.valid && !checking ? "Design validated" : "Draft design"}<span>v0.1</span></div>
      </aside>
    </main>
    {privacy.view}
    <footer className="status-bar"><span><span className="session-dot" />{busy || "本地连接"}</span><span className="status-path">{documentPath || "Untitled"}</span><span>JSON <span className="status-divider">|</span> {t(hdlLanguage === "sv" ? "hdl.systemVerilog" : "hdl.verilog2005")}</span></footer>

    <CopilotPanel open={copilotOpen && !scope} onClose={() => setCopilotOpen(false)} api={api} token={token} design={document} baseDir={baseDir} onAcceptProposal={applyCopilotProposal} onAuthorize={privacy.authorize} />
    <AISettings open={aiSettingsOpen} onClose={() => setAiSettingsOpen(false)} api={api} />
    <AIAssistant open={assistantOpen && !scope} onClose={() => setAssistantOpen(false)} onSettings={() => setAiSettingsOpen(true)} api={api}
      onGenerate={generateProposal} onAccept={applyCopilotProposal} onSelect={selectProposal} onPreview={setPreview} />

    {toast && <div className={`toast ${toast.error ? "error" : ""}`} role={toast.error ? "alert" : "status"}>{toast.error ? <CircleAlert size={17} /> : <CircleCheck size={17} />}<span>{toast.message}</span><IconButton icon={X} label="关闭通知" onClick={() => setToast(null)} /></div>}

    {modal && <dialog ref={modalRef} aria-labelledby="editor-dialog-title" className={`editor-dialog ${modal.kind === "module" ? "wide" : ""}`} onCancel={(event) => { event.preventDefault(); if (!busy) setModal(null); }} onClick={(event) => { if (event.target === event.currentTarget && !busy) setModal(null); }}>
      <form onSubmit={submitModal}><div className="dialog-heading"><h2 id="editor-dialog-title">{{ save: "保存设计", open: "打开设计", external: "添加外部端口", module: "登记 RTL 模块", hierarchy: t("hierarchy.collapse"), bundle: t("hierarchy.networks") }[modal.kind]}</h2><IconButton icon={X} label="关闭对话框" disabled={Boolean(busy)} onClick={() => setModal(null)} /></div>
        <div className="dialog-body">
          {modal.kind === "bundle" && <div className="hierarchy-net-list">{modal.edges.map((edge) => <button className="small-command" type="button" key={edge.id} onClick={() => { setSelection({ type: "net", id: edge.data.net, sink: edge.data.sink }); setModal(null); setMobilePanel("inspector"); }}>{edge.data.net}<code>{edge.data.width}</code></button>)}</div>}
          {modal.kind === "hierarchy" && <label className="field-label">{t("hierarchy.name")}<input autoFocus required aria-label={t("hierarchy.name")} value={modal.name} onChange={(event) => setModal({ ...modal, name: event.target.value })} /></label>}
          {modal.kind === "save" && <label className="field-label">设计文件路径<input autoFocus required aria-label="保存路径" value={modal.path} onChange={(event) => setModal({ ...modal, path: event.target.value })} /></label>}
          {modal.kind === "open" && <><label className="field-label">工作区设计<select aria-label="工作区设计" value={modal.path} onChange={(event) => setModal({ ...modal, path: event.target.value })}>{modal.paths.map((path) => <option key={path}>{path}</option>)}</select></label><label className="field-label">文件路径<input required aria-label="打开路径" value={modal.path} onChange={(event) => setModal({ ...modal, path: event.target.value })} /></label></>}
          {modal.kind === "external" && <><label className="field-label">端口名称<input autoFocus required aria-label="新端口名称" value={modal.name} onChange={(event) => setModal({ ...modal, name: event.target.value })} /></label><label className="field-label">方向<select value={modal.direction} onChange={(event) => setModal({ ...modal, direction: event.target.value })}><option value="input">Input</option><option value="output">Output</option></select></label><label className="check-field"><input type="checkbox" checked={modal.vector} onChange={(event) => setModal({ ...modal, vector: event.target.checked })} />向量端口</label>{modal.vector && <div className="range-fields"><label>Left<input required value={modal.left} onChange={(event) => setModal({ ...modal, left: event.target.value })} /></label><span>:</span><label>Right<input required value={modal.right} onChange={(event) => setModal({ ...modal, right: event.target.value })} /></label></div>}<label className="check-field"><input type="checkbox" checked={modal.signed} onChange={(event) => setModal({ ...modal, signed: event.target.checked })} />Signed</label></>}
          {modal.kind === "module" && <><label className="field-label">模块名称<input autoFocus required aria-label="新模块名称" value={modal.name} onChange={(event) => setModal({ ...modal, name: event.target.value })} /></label><label className="field-label">模块元数据 JSON<textarea className="metadata-editor" spellCheck={false} required aria-label="模块元数据" value={modal.json} onChange={(event) => setModal({ ...modal, json: event.target.value })} /></label><div className="source-path"><span>Source base</span><code>{baseDir}/</code></div></>}
        </div><div className="dialog-actions"><button type="button" className="button secondary" disabled={Boolean(busy)} onClick={() => setModal(null)}>取消</button><button type="submit" className="button primary" disabled={Boolean(busy)}>{busy ? <LoaderCircle size={15} className="spin" /> : <Check size={15} />}{modal.kind === "save" ? "保存" : modal.kind === "open" ? "打开" : "添加"}</button></div>
      </form>
    </dialog>}
  </div>;
}