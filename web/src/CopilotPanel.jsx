import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Bot, CircleAlert, Copy, LoaderCircle, Plug, Plus, Send, ShieldCheck, Square, Wrench, X } from "lucide-react";
import { readCopilotEvents, updateCopilotMessages } from "./copilot.js";
import { t } from "./i18n.js";
import Proposal from "./ai/Proposal.jsx";

const toolLabels = { bd_design: "读取已共享设计", bd_validate: "校验设计", bd_preview: "预览 HDL",
  bd_workflow: "读取设计工作流", bd_catalog: "查询授权 IP 目录", bd_read_source: t("ai.readMetadata"),
  bd_requirements: "记录可追踪需求", bd_plan: "预检查连接计划", bd_generate: t("ai.legacyProposal"), bd_propose: t("ai.proposeTool") };
const toolStates = { running: "执行中", complete: "完成", failed: "未完成" };

function Action({ icon: Icon, label, ...props }) {
  return <button type="button" className="icon-button" title={label} aria-label={label} {...props}><Icon size={16} strokeWidth={1.7} /></button>;
}

export default function CopilotPanel({ open, onClose, api, token, design, baseDir, onAcceptProposal, onAuthorize }) {
  const [status, setStatus] = useState(null);
  const [connecting, setConnecting] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [model, setModel] = useState("");
  const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [turns, setTurns] = useState(0);
  const [error, setError] = useState("");
  const [proposal, setProposal] = useState(null);
  const controller = useRef(null);
  const requestId = useRef(null);
  const apiRef = useRef(api);
  const feed = useRef(null);
  const followOutput = useRef(true);

  useEffect(() => { apiRef.current = api; }, [api]);
  useEffect(() => {
    if (open) apiRef.current("/api/copilot/status").then(setStatus).catch((failure) => setError(failure.message));
    else if (controller.current) {
      const activeId = requestId.current;
      controller.current.abort();
      if (activeId) apiRef.current("/api/copilot/cancel", { request_id: activeId }).catch(() => {});
    }
  }, [open]);
  useEffect(() => () => {
    controller.current?.abort();
    if (requestId.current) apiRef.current("/api/copilot/cancel", { request_id: requestId.current }).catch(() => {});
  }, []);
  useEffect(() => {
    if (followOutput.current && feed.current) feed.current.scrollTop = feed.current.scrollHeight;
  }, [messages, open]);

  async function connect() {
    setConnecting(true);
    setError("");
    try { setStatus(await api("/api/copilot/connect", {})); }
    catch (failure) { setError(failure.message); }
    finally { setConnecting(false); }
  }

  async function newConversation() {
    setError("");
    try {
      if (proposal) await discardProposal(proposal);
      if (conversationId) await api("/api/copilot/clear", { conversation_id: conversationId });
      setConversationId(null);
      setMessages([]);
      setTurns(0);
    } catch (failure) { setError(failure.message); }
  }

  async function stop() {
    const activeController = controller.current;
    const activeId = requestId.current;
    try { if (activeId) await api("/api/copilot/cancel", { request_id: activeId }); }
    catch (failure) { setError(failure.message); }
    finally { activeController?.abort(); }
  }

  async function send(event) {
    event.preventDefault();
    const text = prompt.trim();
    if (!text || proposal || generating || connecting || !status?.authenticated) return;
    try { await onAuthorize("copilot"); }
    catch (failure) { setError(failure.message); return; }
    const activeController = new AbortController();
    controller.current = activeController;
    requestId.current = null;
    let activeId = `pending-${Date.now()}`;
    let settled = false;
    setError("");
    setGenerating(true);
    setPrompt("");
    followOutput.current = true;
    setMessages((previous) => [...previous, { id: `user-${Date.now()}`, role: "user", content: text, design: design.name }]);
    const payload = { prompt: text, model: model || null, conversation_id: conversationId, confirm_usage: true, share_context: true, allow_design_changes: true, design, base_dir: baseDir };
    try {
      const response = await fetch("/api/copilot/chat", { method: "POST", headers: { "Content-Type": "application/json", "X-BD-Token": token }, body: JSON.stringify(payload), signal: activeController.signal });
      await readCopilotEvents(response, (received) => {
        if (received.type === "start") {
          activeId = received.request_id;
          requestId.current = received.request_id;
          setConversationId(received.conversation_id);
          setTurns(received.turns);
        }
        if (received.type === "done") settled = true;
        if (received.type === "proposal") setProposal(received.proposal);
        if (received.type === "design_update") {
          setMessages((previous) => [...previous, { id: `${activeId}:design-update`, role: "error", content: t("ai.legacyBlocked") }]);
        }
        setMessages((previous) => updateCopilotMessages(previous, received, activeId));
      });
    } catch (failure) {
      if (failure.name === "AbortError") {
        if (!settled) setMessages((previous) => [...previous, { id: `${activeId}:stopped`, role: "status", content: "已停止生成" }]);
      } else setError(failure.message);
    } finally {
      if (!settled && requestId.current) api("/api/copilot/cancel", { request_id: requestId.current }).catch(() => {});
      controller.current = null;
      requestId.current = null;
      setGenerating(false);
    }
  }

  async function acceptProposal(value, selected) {
    if (!await onAcceptProposal(value, selected)) throw new Error(t("ai.acceptFailed"));
    setProposal((current) => current?.id === value.id ? null : current);
    setMessages((previous) => [...previous, { id: `${value.id}:accepted`, role: "status", content: t("ai.accepted") }]);
  }

  async function discardProposal(value) {
    await api("/api/ops/discard", { proposal_id: value.id });
    setProposal((current) => current?.id === value.id ? null : current);
    setMessages((previous) => [...previous, { id: `${value.id}:discarded`, role: "status", content: t("ai.discarded") }]);
  }

  if (!open) return null;
  const ready = Boolean(status?.connected && status?.authenticated);
  return createPortal(<aside className="copilot-panel" aria-label="Copilot 助手">
    <header className="copilot-heading"><Bot size={20} /><strong>Copilot</strong><span>RTL Assistant</span><Action icon={Plus} label="新 Copilot 会话" disabled={generating || connecting || !messages.length} onClick={newConversation} /><Action icon={X} label="关闭 Copilot" onClick={onClose} /></header>
    <div className="copilot-connection"><span className={`copilot-indicator ${ready ? "ready" : ""}`} /><span>{connecting ? "正在连接" : ready ? "已连接" : status?.connected ? "需要登录" : "未连接"}</span><button className="small-command" onClick={connect} disabled={connecting || generating || !status?.compatible}>{connecting ? <LoaderCircle size={13} className="spin" /> : <Plug size={13} />}{ready ? "检查连接" : "连接 Copilot"}</button></div>
    {!status?.compatible && status && <div className="copilot-notice" role="status"><CircleAlert size={15} /><span>需要安装项目的可选 Copilot SDK 依赖。</span></div>}
    {status?.message && <div className="copilot-notice"><span>{status.message}</span></div>}
    <label className="copilot-model"><span>模型</span><select aria-label="Copilot 模型" value={model} disabled={!ready || generating || Boolean(conversationId)} onChange={(event) => setModel(event.target.value)}><option value="">账户默认模型</option>{status?.models?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
    <div className="copilot-messages" ref={feed} role="log" aria-label="Copilot 消息" aria-live="polite" onScroll={() => { const element = feed.current; followOutput.current = element.scrollHeight - element.scrollTop - element.clientHeight < 60; }}>
      {!messages.length && <div className="copilot-empty"><Bot size={30} strokeWidth={1.2} /><span>暂无消息</span></div>}
      {messages.map((message) => message.role === "tool" ? <div className="copilot-tool" key={message.id}>{message.status === "running" ? <LoaderCircle size={13} className="spin" /> : <Wrench size={13} />}<span>{toolLabels[message.name] || message.name}</span><small>{toolStates[message.status] || message.status}</small></div>
        : <article className={`copilot-message ${message.role}`} key={message.id}>
          {(message.role === "user" || message.role === "assistant") && <div className="copilot-message-heading"><span>{message.role === "user" ? "你" : "Copilot"}</span>{message.design && <code title={message.design}>{message.design}</code>}{message.role === "assistant" && <Action icon={Copy} label="复制 Copilot 回复" onClick={() => navigator.clipboard.writeText(message.content).catch((failure) => setError(failure.message))} />}</div>}
          <pre>{message.content}</pre>
          {message.runDir && <code className="copilot-artifact">{message.runDir}</code>}
          {message.diff && <details className="copilot-diff"><summary>设计差异</summary><pre>{message.diff}</pre></details>}
        </article>)}
      {generating && <div className="copilot-working"><LoaderCircle size={14} className="spin" />正在回复</div>}
    </div>
    {proposal && <Proposal key={proposal.id} proposal={proposal} busy={generating} onAccept={acceptProposal} onDiscard={discardProposal} />}
    {error && <div className="copilot-notice error" role="alert"><CircleAlert size={15} /><span>{error}</span><Action icon={X} label="关闭 Copilot 错误" onClick={() => setError("")} /></div>}
    <form className="copilot-composer" onSubmit={send}>
      <textarea aria-label="Copilot 消息输入" placeholder="输入消息" rows={3} maxLength={8000} value={prompt} disabled={generating || Boolean(proposal)} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form.requestSubmit(); } }} />
      <div className="copilot-compose-actions"><span>{turns}/{status?.max_turns || 20} 条用户消息</span>{generating ? <button className="button secondary" type="button" onClick={stop}><Square size={13} />停止</button> : <button className="button primary" type="submit" disabled={!ready || !prompt.trim() || connecting || Boolean(proposal)}><Send size={14} />发送</button>}</div>
      <footer className="copilot-policy"><ShieldCheck size={12} />{t("ai.policy")}<span>{t("ai.manualSend")}</span></footer>
    </form>
  </aside>, document.body);
}