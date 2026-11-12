import React, { useEffect, useRef, useState } from "react";
import { Background, BackgroundVariant, ConnectionLineType, ConnectionMode, Position, ReactFlow, applyNodeChanges, useNodesInitialized, useReactFlow } from "@xyflow/react";
import * as FlowComponents from "@xyflow/react";
import { ArrowUpRight, Blocks, Bot, Check, CheckCheck, ChevronDown, CircleAlert, CircleCheck, CircuitBoard, Code2, Copy, Cpu, Download, FilePlus2, FolderOpen, GripVertical, LayoutGrid, ListTree, LoaderCircle, Maximize2, PanelLeft, PanelRight, Plus, Redo2, Save, Search, Settings2, ShieldCheck, Trash2, Undo2, Unplug, Workflow, X, ZoomIn, ZoomOut } from "lucide-react";
import { addInstance, checkName, clone, connectionError, connectPorts, deleteNode, disconnectPort, endpointInfo, externalId, makeExternal, parseInteger, rangeLabel, renameNet, renameNode, uniqueName, validateDocumentShape } from "./model.js";
import OutputWindow from "./OutputWindow.jsx";
import CircuitEdge from "./CircuitEdge.jsx";
import CopilotPanel from "./CopilotPanel.jsx";
import { resolveDesignUpdate } from "./copilot.js";
import { ImportButton, LibraryList, OriginBadge } from "./ip/Library.jsx";
import { IP_DRAG_TYPE, addImported, findImportedDrop, originForDefinition } from "./ip/model.js";
import { t } from "./i18n.js";
import Parameters from "./semantic/Parameters.jsx";
import Diagnostics from "./semantic/Diagnostics.jsx";
import Connections from "./semantic/Connections.jsx";
import ExpressionNode from "./semantic/ExpressionNode.jsx";
import { expressionId, normalizeInspection, projectConnections, renameSemantic, replaceEndpoint, syncDocument } from "./semantic/model.js";
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
    <div className="block-pins"><div>{inputs.map((port) => <Pin key={port.endpoint} port={port} side="left" onPin={data.onPin} active={data.active} connectable={data.connectable} />)}</div><div>{outputs.map((port) => <Pin key={port.endpoint} port={port} side="right" onPin={data.onPin} active={data.active} connectable={data.connectable} />)}</div></div>
    <div className="block-footer"><span className="rtl-dot" />RTL<span className="block-parameters">{Object.entries(data.parameters).map(([name, value]) => `${name} ${value}`).join(" · ")}</span></div>
  </div>;
}

const nodeTypes = { block: BlockNode, expression: ExpressionNode };
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
  const nodesReady = useNodesInitialized();
  const [history, setHistory] = useState(null);
  const [baseDir, setBaseDir] = useState("examples");
  const [documentPath, setDocumentPath] = useState("");
  const [token, setToken] = useState("");
  const [inspection, setInspection] = useState(emptyInspection);
  const [checking, setChecking] = useState(false);
  const [fixing, setFixing] = useState(false);
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
  const [modal, setModal] = useState(null);
  const [ipImportOpen, setIpImportOpen] = useState(false);
  const [connectionOpen, setConnectionOpen] = useState(false);
  const [ipRevision, setIpRevision] = useState(0);
  const [ipCatalog, setIpCatalog] = useState({ baseDir: "", entries: [] });
  const [toast, setToast] = useState(null);
  const [fatal, setFatal] = useState("");
  const [jsonDraft, setJsonDraft] = useState("");
  const [activity, setActivity] = useState("本地工作区已就绪");
  const [zoom, setZoom] = useState(100);
  const [viewportRequest, setViewportRequest] = useState(null);
  const modalRef = useRef(null);
  const inspectedDesign = useRef(null);
  const editorState = useRef(null);
  editorState.current = { history, baseDir, busy };
  const design = history?.current.design;
  const document = history?.current.document ?? design;
  const layout = history?.current.layout;
  const connectionReady = !checking && !busy && inspectedDesign.current === design;
  const interfaces = connectionReady ? inspection.interfaces : emptyInspection.interfaces;
  const expressionGraph = projectConnections(inspection.connections ?? [], layout?.nodes ?? {});

  function notify(message, error = false) { setToast({ message, error }); }

  async function api(path, payload, signal) {
    const response = await fetch(path, payload === undefined ? { signal } : { method: "POST", headers: { "Content-Type": "application/json", "X-BD-Token": token }, body: JSON.stringify(payload), signal });
    const result = await response.json();
    if (!response.ok) throw new Error(normalizeInspection(result).diagnostics[0] || result.error || `HTTP ${response.status}`);
    return result;
  }

  function acceptDocument(result) {
    const versioned = [2, 3].includes(result.design.schema_version);
    const canvas = validateDocumentShape(versioned ? result.inspection.canvas : result.design);
    setHistory({ past: [], current: { design: canvas, document: versioned ? result.design : null, layout: { ...initialLayout, ...result.layout } }, future: [] });
    setBaseDir(result.base_dir);
    setDocumentPath(result.path);
    inspectedDesign.current = canvas;
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
    const controller = new AbortController();
    setChecking(true);
    const timer = setTimeout(() => {
      api("/api/semantic/inspect", { design: document, base_dir: baseDir }, controller.signal).then((result) => {
        inspectedDesign.current = design;
        setInspection(normalizeInspection(result));
        setChecking(false);
      }).catch((error) => {
        if (error.name !== "AbortError") { setInspection({ ...emptyInspection, diagnostics: [error.message] }); setChecking(false); }
      });
    }, 180);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [design, document, baseDir, token]);

  useEffect(() => { if (document) setJsonDraft(JSON.stringify(document, null, 2)); }, [document]);
  useEffect(() => {
    if (!nodesReady || !viewportRequest) return;
    if (viewportRequest.waitFor && !flow.getNode(viewportRequest.waitFor)) return;
    if (viewportRequest.fit) flow.fitView({ padding: 0.16, maxZoom: 1 });
    else flow.setViewport(viewportRequest.viewport);
    setViewportRequest(null);
  }, [nodesReady, viewportRequest, flow]);
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

  function mutate(update, message, upgrade = false, replacement = null) {
    const current = editorState.current;
    if (!current.history || current.busy) return false;
    try {
      const previous = current.history;
      const previousDesign = previous.current.design;
      const next = clone(previous.current);
      update(next.design, next.layout);
      const changed = JSON.stringify(next.design) !== JSON.stringify(previousDesign);
      if (replacement) next.document = clone(replacement);
      else if (changed && (previous.current.document || upgrade)) {
        if (upgrade && inspectedDesign.current !== previousDesign) throw new Error(t("semantic.notReady"));
        next.document = syncDocument(previous.current.document ?? inspection.document, next.design,
          [...(inspection.metadata ?? []), ...(ipCatalog.baseDir === current.baseDir ? ipCatalog.entries.map((entry) => entry.metadata) : [])]);
      } else if (!changed) next.document = previous.current.document;
      if (JSON.stringify(next) === JSON.stringify(previous.current)) return true;
      if (JSON.stringify(next.design) === JSON.stringify(previousDesign)) next.design = previousDesign;
      else { setChecking(true); setInspection({ ...emptyInspection }); }
      const nextHistory = { past: [...previous.past, previous.current].slice(-80), current: next, future: [] };
      editorState.current = { ...current, history: nextHistory };
      setHistory(nextHistory);
      setSaved(false);
      if (message) setActivity(message);
      return true;
    } catch (error) { notify(error.message, true); return false; }
  }

  function applyCopilotDesign(event) {
    try {
      const current = editorState.current;
      if (!current.history || current.busy) throw new Error("编辑器正在处理其他操作，未覆盖画布；请使用隔离产物。");
      const updated = resolveDesignUpdate(current.history.current.design, current.baseDir, event);
      const applied = mutate((next, nextLayout) => {
        for (const key of Object.keys(next)) delete next[key];
        Object.assign(next, updated);
        const nodes = new Set([...Object.keys(next.instances), ...Object.keys(next.ports).map(externalId)]);
        for (const id of Object.keys(nextLayout.nodes)) if (!nodes.has(id)) delete nextLayout.nodes[id];
      }, "Copilot 已按可追踪计划更新设计，可撤销");
      if (!applied) throw new Error("设计更新未应用，隔离产物已保留。");
      setSelection(null);
      setPendingPin(null);
      notify("Copilot 设计已应用到画布，原设计文件未覆盖");
      return { applied: true, message: "设计已自动应用到画布，可撤销；原设计文件未覆盖。" };
    } catch (error) {
      notify(error.message, true);
      return { applied: false, message: error.message };
    }
  }

  function undo() {
    if (!history?.past.length || busy) return;
    setHistory({ past: history.past.slice(0, -1), current: history.past.at(-1), future: [history.current, ...history.future] });
    setSaved(false); setSelection(null); setPendingPin(null);
  }
  function redo() {
    if (!history?.future.length || busy) return;
    setHistory({ past: [...history.past, history.current], current: history.future[0], future: history.future.slice(1) });
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

  useEffect(() => {
    if (!design) return;
    const errors = inspection.diagnostics.join(" ");
    const locations = (inspection.structuredDiagnostics ?? []).filter((item) => item.severity === "error").map((item) => item.location);
    const errorNodes = new Set(locations.flatMap((item) => item.instance ? [item.instance] : item.external ? [externalId(item.external)] : []));
    const structured = Boolean(inspection.structuredDiagnostics?.length);
    const result = [];
    for (const [name, instance] of Object.entries(design.instances)) {
      const definition = design.modules[instance.module];
      const parameters = inspection.parameters?.[name] ?? Object.fromEntries(Object.entries(definition?.parameters ?? {}).map(([key, spec]) => [key, instance.parameters?.[key] ?? spec.default]));
      result.push({ id: name, type: "block", position: layout.nodes[name] ?? defaultPosition(name, design), selected: selection?.id === name,
        data: { name, module: instance.module, parameters, ports: Object.keys(definition?.ports ?? {}).map((port) => endpointInfo(design, `${name}.${port}`, interfaces)).filter(Boolean), onPin: pickPin, active: pendingPin, connectable: connectionReady, highlight: structured ? errorNodes.has(name) : errors.includes(`instances.${name}.`) || errors.includes(`${name}.`) } });
    }
    for (const name of Object.keys(design.ports)) {
      const id = externalId(name);
      result.push({ id, type: "block", position: layout.nodes[id] ?? defaultPosition(id, design), selected: selection?.id === id,
        data: { name, external: true, ports: [endpointInfo(design, id, interfaces)], onPin: pickPin, active: pendingPin, connectable: connectionReady, highlight: structured ? errorNodes.has(id) : errors.includes(`ports.${name}:`) } });
    }
      result.push(...expressionGraph.nodes.map((node) => ({ ...node, selected: selection?.type === "net" && selection.id === node.data.net })));
    setNodes((previous) => result.map((node) => ({ ...node, measured: previous.find((item) => item.id === node.id)?.measured })));
  }, [design, layout, inspection, selection, pendingPin, connectionReady]);

  const invalidNets = new Set((inspection.structuredDiagnostics ?? []).filter((item) => item.severity === "error").map((item) => item.location.net).filter(Boolean));
  const edges = design ? Object.entries(design.nets).flatMap(([net, pins]) => {
    if (expressionGraph.nets.has(net)) return [];
    const drivers = pins.filter((pin) => endpointInfo(design, pin)?.drives);
    const driver = drivers[0] ?? pins.find((pin) => endpointInfo(design, pin));
    if (!driver) return [];
    const shape = endpointInfo(design, driver, interfaces);
    return pins.filter((pin) => pin !== driver && endpointInfo(design, pin)).map((sink) => ({
      id: `${net}|${sink}`, source: nodeId(driver), target: nodeId(sink), sourceHandle: driver, targetHandle: sink,
      type: "circuit", label: net, data: { net, sink }, selected: selection?.type === "net" && selection.id === net && (!selection.sink || selection.sink === sink),
      style: { stroke: selection?.id === net && (!selection.sink || selection.sink === sink) ? "#0a8f7b" : invalidNets.has(net) ? "#ba4545" : (shape?.range ? "#477caa" : "#8c969f"), strokeWidth: shape?.range ? 2.4 : 1.5 },
      labelStyle: { fill: "#66747e", fontSize: 11, fontFamily: "IBM Plex Mono, monospace" }, labelBgStyle: { fill: "#f8fafb", fillOpacity: 0.95 }, labelBgPadding: [7, 3], labelBgBorderRadius: 3,
    }));
  }).concat(expressionGraph.edges.map((edge) => ({ ...edge, selected: selection?.type === "net" && selection.id === edge.data.net,
    style: { stroke: selection?.id === edge.data.net ? "#0a8f7b" : invalidNets.has(edge.data.net) ? "#ba4545" : "#477caa", strokeWidth: edge.data.width > 1 ? 2.4 : 1.5 },
    labelStyle: { fill: "#66747e", fontSize: 11, fontFamily: "IBM Plex Mono, monospace" },
    labelBgStyle: { fill: "#f8fafb", fillOpacity: 0.95 }, labelBgPadding: [7, 3], labelBgBorderRadius: 3,
  }))) : [];

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

  function autoLayout() {
    mutate((next, nextLayout) => { nextLayout.nodes = Object.fromEntries([...Object.keys(next.instances), ...Object.keys(next.ports).map(externalId)].map((id) => [id, defaultPosition(id, next)])); }, "布局已整理");
    requestAnimationFrame(() => flow.fitView({ padding: 0.16, duration: 250 }));
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
  function saveDialog() { setModal({ kind: "save", path: documentPath.startsWith("designs/") ? documentPath : `designs/${design.name}.json` }); }

  async function submitModal(event) {
    event.preventDefault();
    try {
      if (modal.kind === "save") {
        setBusy("保存中");
        const result = await api("/api/save", { design: document, layout: { ...layout, viewport: flow.getViewport() }, base_dir: baseDir, path: modal.path });
        acceptDocument(result);
        notify(`已保存 ${result.path}`); setActivity(`设计与布局已保存 · ${result.path}`);
      } else if (modal.kind === "open") {
        if (!saved && !window.confirm("当前设计尚未保存，仍要打开其他设计吗？")) return;
        setBusy("打开中");
        acceptDocument(await api(`/api/load?path=${encodeURIComponent(modal.path)}`));
        setActivity(`已打开 ${modal.path}`);
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
      const result = await api("/api/generate", { design: document, base_dir: baseDir });
      setInspection((previous) => ({ ...previous, files: result.files }));
      setTab("bd"); setPanelOpen(true);
      setActivity(`已生成 ${result.paths.join(" / ")}`); notify("两层 Verilog 已写入 build/gui/");
    } catch (error) { notify(error.message, true); }
    finally { setBusy(""); }
  }

  async function validateNow() {
    try {
      setChecking(true);
      const result = normalizeInspection(await api("/api/semantic/inspect", { design: document, base_dir: baseDir }));
      inspectedDesign.current = design;
      setInspection(result); setTab("diagnostics"); setPanelOpen(true);
      notify(result.valid ? "设计校验通过" : result.diagnostics[0], !result.valid);
    } catch (error) { notify(error.message, true); }
    finally { setChecking(false); }
  }

  useEffect(() => {
    const handleKey = (event) => {
      if (!design || busy || modal || ipImportOpen || connectionOpen || /INPUT|TEXTAREA|SELECT/.test(event.target.tagName)) return;
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
      const result = await api("/api/semantic/fix", { design: snapshot.document ?? snapshot.design, base_dir: sourceBase, diagnostic });
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
      const snapshot = editorState.current.history.current;
      const result = await api("/api/semantic/inspect", { design: parsed, base_dir: baseDir });
      if (editorState.current.history.current !== snapshot) throw new Error(t("semantic.notReady"));
      if (!result.canvas || !result.document) throw new Error(normalizeInspection(result).diagnostics[0]);
      validateDocumentShape(result.canvas);
      mutate((next) => { for (const key of Object.keys(next)) delete next[key]; Object.assign(next, result.canvas); }, t("semantic.jsonApplied"), false, result.document);
    } catch (error) { notify(error.message, true); }
  }

  async function applyConnection(name, index, endpoint) {
    const current = editorState.current;
    const snapshot = current.history.current;
    if (!connectionReady || current.busy) throw new Error(t("semantic.notReady"));
    const candidate = replaceEndpoint(snapshot.document ?? inspection.document, name, index, endpoint);
    const result = await api("/api/semantic/inspect", { design: candidate, base_dir: current.baseDir });
    if (editorState.current.history.current !== snapshot || editorState.current.baseDir !== current.baseDir) throw new Error(t("semantic.notReady"));
    if (!result.canvas || !result.document) throw new Error(normalizeInspection(result).diagnostics[0]);
    const applied = mutate((next) => { for (const key of Object.keys(next)) delete next[key]; Object.assign(next, result.canvas); }, t("semantic.connectionChanged"), false, result.document);
    if (applied && (endpoint.const !== undefined || endpoint.concat)) setViewportRequest({ fit: true, waitFor: expressionId(name, index) });
    return applied;
  }

  if (!design) return <div className="boot-screen"><CircuitBoard size={36} /><h1>BD Studio</h1>{fatal ? <><p role="alert">{fatal}</p><button onClick={() => location.reload()}>重新连接</button></> : <LoaderCircle className="spin" size={20} />}</div>;

  const moduleNames = Object.keys(design.modules).filter((name) => [name, ...Object.keys(design.modules[name].ports)].some((value) => value.toLowerCase().includes(search.toLowerCase())));
  const filename = tab === "wrapper" ? `${design.name}_wrapper.v` : `${design.name}.v`;
  const code = inspection.files[filename] ?? "";
  const selectionNode = selection?.type === "node" ? selection.id : selection?.type === "port" ? nodeId(selection.id) : null;
  const instance = selectionNode && !selectionNode.startsWith("@") ? design.instances[selectionNode] : null;
  const external = selectionNode?.startsWith("@") ? design.ports[selectionNode.slice(1)] : null;
  const definition = instance ? design.modules[instance.module] : null;
  const selectedNet = selection?.type === "net" ? design.nets[selection.id] : null;
  const semanticDocument = history.current.document ?? inspection.document;
  const selectedNetRecord = selectedNet && semanticDocument?.nets.find((net) => net.name === selection.id);
  const connectionPorts = [...Object.keys(design.ports).map(externalId), ...Object.entries(design.instances).flatMap(([name, item]) =>
    Object.keys(design.modules[item.module]?.ports ?? {}).map((port) => `${name}.${port}`))].map((value) => ({ ...endpointInfo(design, value, interfaces), value }));
  const totalPins = Object.values(design.instances).reduce((count, item) => count + Object.keys(design.modules[item.module]?.ports ?? {}).length, 0);

  const renameSelected = (name) => {
    let newId;
    const replacement = history.current.document ? renameSemantic(history.current.document, selectionNode, name) : null;
    const ok = mutate((next, nextLayout) => { newId = renameNode(next, nextLayout, selectionNode, name); }, "名称与端点引用已更新", false, replacement);
    if (ok) setSelection({ type: "node", id: newId });
    return ok;
  };

  return <div className="app-shell">
    <header className="app-header">
      <div className="brand"><span className="brand-symbol"><CircuitBoard size={22} strokeWidth={1.6} /></span><span>BD <strong>Studio</strong></span><span className="local-badge">LOCAL</span></div>
      <div className="header-center"><span className="session-dot" />RTL WORKSPACE</div>
      <div className="header-actions">
        <IconButton icon={Bot} label="Copilot 助手" aria-pressed={copilotOpen} onClick={() => setCopilotOpen(!copilotOpen)} />
        <IconButton icon={FilePlus2} label="新建设计" onClick={newDocument} disabled={Boolean(busy)} />
        <IconButton icon={FolderOpen} label="打开设计" onClick={openDialog} disabled={Boolean(busy)} />
        <span className="toolbar-divider" />
        <button className="button secondary" onClick={saveDialog} disabled={Boolean(busy)} title="保存设计" aria-label="保存设计"><Save size={15} /><span>保存</span></button>
        <button className="button primary" onClick={generate} disabled={!connectionReady || !inspection.valid} title="生成 HDL"><Code2 size={16} /><span>生成 HDL</span></button>
      </div>
    </header>

    <div className="design-toolbar">
      <div className="document-title"><Workflow size={17} /><h1>{design.name}</h1><span className={`save-state ${saved ? "" : "dirty"}`}>{saved ? "已保存" : "未保存"}</span></div>
      <div className="design-tools">
        <IconButton icon={PanelLeft} label="模块面板" className={mobilePanel === "library" ? "active" : ""} onClick={() => setMobilePanel(mobilePanel === "library" ? null : "library")} />
        <IconButton icon={Undo2} label="撤销" onClick={undo} disabled={!history.past.length || Boolean(busy)} />
        <IconButton icon={Redo2} label="重做" onClick={redo} disabled={!history.future.length || Boolean(busy)} />
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
        <div className="canvas-heading"><div><span className="canvas-tab"><Workflow size={14} />Block Design</span><span className="canvas-meta">{Object.keys(design.instances).length} instances <span>/</span> {Object.keys(design.nets).length} nets</span></div><div><IconButton icon={LayoutGrid} label="整理布局" onClick={autoLayout} /><IconButton icon={Maximize2} label="适应画布" onClick={() => flow.fitView({ padding: 0.16, duration: 250 })} /></div></div>
        <div className="canvas" aria-label="设计画布" onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }} onDrop={dropModule}>
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} minZoom={0.25} maxZoom={2} deleteKeyCode={null} connectOnClick={false} snapToGrid snapGrid={[10, 10]}
            connectionMode={ConnectionMode.Loose} connectionLineType={ConnectionLineType.Step}
            isValidConnection={(connection) => connectionReady && connectionError(design, connection.sourceHandle, connection.targetHandle, interfaces) === null}
            fitView={!Object.keys(layout.nodes).length} fitViewOptions={{ padding: 0.16, maxZoom: 1 }} defaultViewport={layout.viewport}
            onNodesChange={(changes) => setNodes((current) => applyNodeChanges(changes.filter((change) => change.type !== "remove"), current))}
            onNodeDragStop={(_, node) => mutate((next, nextLayout) => { nextLayout.nodes[node.id] = node.position; }, "画布位置已更新")}
            onNodeClick={(_, node) => { setSelection(node.type === "expression" ? { type: "net", id: node.data.net } : { type: "node", id: node.id }); setPendingPin(null); }}
            onNodeDoubleClick={(_, node) => { setSelection(node.type === "expression" ? { type: "net", id: node.data.net } : { type: "node", id: node.id }); setMobilePanel("inspector"); }}
            onEdgeClick={(_, edge) => { setSelection({ type: "net", id: edge.data.net, sink: edge.data.sink }); setPendingPin(null); }}
            onPaneClick={() => { setSelection(null); setPendingPin(null); setMobilePanel(null); }}
            onConnect={(connection) => connect(connection.sourceHandle, connection.targetHandle)}
            onConnectEnd={(event, state) => {
              const first = state.fromHandle?.id;
              const second = state.toHandle?.id ?? (event.target instanceof Element ? event.target.closest(".react-flow__handle")?.getAttribute("data-handleid") : undefined);
              if (first && second && first !== second && !state.isValid) {
                const error = connectionReady ? connectionError(design, first, second, interfaces) : "接口正在解析，请稍后连线";
                if (error) notify(error, true);
              }
              setPendingPin(null);
            }}
            onMoveEnd={(_, viewport) => setZoom(Math.round(viewport.zoom * 100))}>
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#cbd4dc" />
          </ReactFlow>
          <div className="canvas-stamp"><CircuitBoard size={13} />STRUCTURAL RTL</div>
          {pendingPin && <div className="connection-indicator"><span className="session-dot" /><code>{pendingPin}</code><IconButton icon={X} label="取消连线" onClick={() => setPendingPin(null)} /></div>}
          {!nodes.length && <div className="empty-canvas"><Blocks size={38} strokeWidth={1} /><span>空白设计</span><button className="button secondary" onClick={() => setMobilePanel("library")}><Plus size={15} />添加模块</button></div>}
          <div className="canvas-controls"><IconButton icon={ZoomOut} label="缩小" onClick={() => flow.zoomOut({ duration: 150 })} /><span>{zoom}%</span><IconButton icon={ZoomIn} label="放大" onClick={() => flow.zoomIn({ duration: 150 })} /><span className="toolbar-divider" /><IconButton icon={Maximize2} label="适应所有节点" onClick={() => flow.fitView({ padding: 0.16, duration: 250 })} /></div>
        </div>

        <OutputWindow open={panelOpen} onOpenChange={setPanelOpen} tab={tab}
          tabs={[ { id: "diagnostics", label: "诊断", Icon: ListTree }, { id: "bd", label: "BD Verilog", Icon: Code2 }, { id: "wrapper", label: "Wrapper", Icon: Blocks }, { id: "json", label: "设计 JSON", Icon: CircuitBoard } ].map(({ id, label, Icon }) => <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "active" : ""} onClick={() => { setTab(id); setPanelOpen(true); }}><Icon size={14} />{label}{id === "diagnostics" && inspection.diagnostics.length > 0 && <b>{inspection.diagnostics.length}</b>}</button>)}>
          {panelOpen && <div className="output-content" role="tabpanel">
            {tab === "diagnostics" ? <>
              <div className={`diagnostic-summary ${inspection.valid ? "success" : ""}`}>{checking ? <LoaderCircle size={18} className="spin" /> : inspection.valid ? <CircleCheck size={19} /> : <CircleAlert size={19} />}<div><strong>{checking ? "正在校验设计" : inspection.valid ? "所有连接检查通过" : "设计存在待修复项"}</strong><span>{inspection.valid ? `${totalPins} 个实例端口 · ${Object.keys(design.ports).length} 个外部端口 · ${Object.keys(design.nets).length} 条网络` : "DesignError"}</span></div>{inspection.valid && <span className="diagnostic-tag">VALID</span>}</div>
              {inspection.structuredDiagnostics?.length ? <Diagnostics items={inspection.structuredDiagnostics} disabled={checking || Boolean(busy) || fixing} onFocus={focusDiagnostic} onFix={applyDiagnosticFix} />
                : inspection.diagnostics.map((message) => <button className="diagnostic-error" key={message} onClick={() => focusDiagnostic(message)}><CircleAlert size={15} /><code>{message}</code><ArrowUpRight size={14} /></button>)}
              <div className="activity-line"><CheckCheck size={14} /><span>{activity}</span></div>
            </> : tab === "json" ? <div className="json-editor"><div className="code-toolbar"><code>{documentPath || `${design.name}.json`}</code><button className="small-command" onClick={applyJson}><Check size={13} />{t("semantic.applyJson")}</button></div><textarea spellCheck={false} aria-label={t("semantic.designJson")} value={jsonDraft} onChange={(event) => setJsonDraft(event.target.value)} /></div>
              : <div className="code-view"><div className="code-toolbar"><code>{filename}</code><div><IconButton icon={Copy} label="复制代码" disabled={!code} onClick={() => navigator.clipboard.writeText(code).then(() => notify("代码已复制")).catch((error) => notify(error.message, true))} /><IconButton icon={Download} label="下载 Verilog" disabled={!code} onClick={() => downloadFile(filename, code)} /></div></div>{code ? <pre><code>{code.split("\n").map((line, index) => <span className="code-line" key={index}><i>{index + 1}</i>{line}</span>)}</code></pre> : <div className="empty-small">{checking ? "正在生成预览" : "设计通过校验后可预览 HDL"}</div>}</div>}
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
              const connected = Object.values(design.nets).some((pins) => pins.includes(endpoint));
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
            <div className="inspector-object"><div className="inspector-symbol teal"><Workflow size={25} strokeWidth={1.5} /></div><span>BLOCK DESIGN</span><h2>{design.name}</h2><code>Verilog-2005</code></div>
            <section className="property-section"><h3>设计</h3><label className="field-label">模块名称<CommitInput label="设计名称" value={design.name} onCommit={(value) => mutate((next) => { checkName({ instances: {}, ports: {}, nets: {} }, value); next.name = value; })} /></label><div className="source-path"><span>Design file</span><code>{documentPath || "未保存"}</code><span>Source base</span><code>{baseDir}/</code></div></section>
            <section className="property-section"><h3>概览</h3><dl className="design-stats"><div><dt>模块实例</dt><dd>{Object.keys(design.instances).length}</dd></div><div><dt>信号网络</dt><dd>{Object.keys(design.nets).length}</dd></div><div><dt>外部端口</dt><dd>{Object.keys(design.ports).length}</dd></div><div><dt>输出文件</dt><dd>2</dd></div></dl></section>
            <section className="property-section"><h3>生成目标</h3><div className="output-file"><Code2 size={16} /><code>{design.name}.v</code></div><div className="output-file"><Blocks size={16} /><code>{design.name}_wrapper.v</code></div><span className="directory-label">build/gui/</span></section>
          </>}
        </div>
        <div className="inspector-footer"><ShieldCheck size={14} />{inspection.valid && !checking ? "Design validated" : "Draft design"}<span>v0.1</span></div>
      </aside>
    </main>
    <footer className="status-bar"><span><span className="session-dot" />{busy || "本地连接"}</span><span className="status-path">{documentPath || "Untitled"}</span><span>JSON <span className="status-divider">|</span> Verilog-2005</span></footer>

    <CopilotPanel open={copilotOpen} onClose={() => setCopilotOpen(false)} api={api} token={token} design={design} baseDir={baseDir} onDesignUpdate={applyCopilotDesign} />

    {toast && <div className={`toast ${toast.error ? "error" : ""}`} role={toast.error ? "alert" : "status"}>{toast.error ? <CircleAlert size={17} /> : <CircleCheck size={17} />}<span>{toast.message}</span><IconButton icon={X} label="关闭通知" onClick={() => setToast(null)} /></div>}

    {modal && <dialog ref={modalRef} className={`editor-dialog ${modal.kind === "module" ? "wide" : ""}`} onCancel={(event) => { event.preventDefault(); if (!busy) setModal(null); }} onClick={(event) => { if (event.target === event.currentTarget && !busy) setModal(null); }}>
      <form onSubmit={submitModal}><div className="dialog-heading"><h2>{{ save: "保存设计", open: "打开设计", external: "添加外部端口", module: "登记 RTL 模块" }[modal.kind]}</h2><IconButton icon={X} label="关闭对话框" disabled={Boolean(busy)} onClick={() => setModal(null)} /></div>
        <div className="dialog-body">
          {modal.kind === "save" && <label className="field-label">设计文件路径<input autoFocus required aria-label="保存路径" value={modal.path} onChange={(event) => setModal({ ...modal, path: event.target.value })} /></label>}
          {modal.kind === "open" && <><label className="field-label">工作区设计<select aria-label="工作区设计" value={modal.path} onChange={(event) => setModal({ ...modal, path: event.target.value })}>{modal.paths.map((path) => <option key={path}>{path}</option>)}</select></label><label className="field-label">文件路径<input required aria-label="打开路径" value={modal.path} onChange={(event) => setModal({ ...modal, path: event.target.value })} /></label></>}
          {modal.kind === "external" && <><label className="field-label">端口名称<input autoFocus required aria-label="新端口名称" value={modal.name} onChange={(event) => setModal({ ...modal, name: event.target.value })} /></label><label className="field-label">方向<select value={modal.direction} onChange={(event) => setModal({ ...modal, direction: event.target.value })}><option value="input">Input</option><option value="output">Output</option></select></label><label className="check-field"><input type="checkbox" checked={modal.vector} onChange={(event) => setModal({ ...modal, vector: event.target.checked })} />向量端口</label>{modal.vector && <div className="range-fields"><label>Left<input required value={modal.left} onChange={(event) => setModal({ ...modal, left: event.target.value })} /></label><span>:</span><label>Right<input required value={modal.right} onChange={(event) => setModal({ ...modal, right: event.target.value })} /></label></div>}<label className="check-field"><input type="checkbox" checked={modal.signed} onChange={(event) => setModal({ ...modal, signed: event.target.checked })} />Signed</label></>}
          {modal.kind === "module" && <><label className="field-label">模块名称<input autoFocus required aria-label="新模块名称" value={modal.name} onChange={(event) => setModal({ ...modal, name: event.target.value })} /></label><label className="field-label">模块元数据 JSON<textarea className="metadata-editor" spellCheck={false} required aria-label="模块元数据" value={modal.json} onChange={(event) => setModal({ ...modal, json: event.target.value })} /></label><div className="source-path"><span>Source base</span><code>{baseDir}/</code></div></>}
        </div><div className="dialog-actions"><button type="button" className="button secondary" disabled={Boolean(busy)} onClick={() => setModal(null)}>取消</button><button type="submit" className="button primary" disabled={Boolean(busy)}>{busy ? <LoaderCircle size={15} className="spin" /> : <Check size={15} />}{modal.kind === "save" ? "保存" : modal.kind === "open" ? "打开" : "添加"}</button></div>
      </form>
    </dialog>}
  </div>;
}