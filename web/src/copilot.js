import { clone, validateDocumentShape } from "./model.js";

function canonicalDesign(value) {
  return JSON.stringify(value, (key, item) => item && typeof item === "object" && !Array.isArray(item)
    ? Object.fromEntries(Object.keys(item).sort().map((name) => [name, item[name]])) : item);
}

export function resolveDesignUpdate(current, baseDir, event) {
  if (baseDir !== event.base_dir || canonicalDesign(current) !== canonicalDesign(event.base_design)) {
    throw new Error("当前设计已变化，未覆盖画布；生成结果保留在隔离目录。");
  }
  return clone(validateDocumentShape(event.design));
}

export async function readCopilotEvents(response, onEvent) {
  if (!response.ok) {
    const result = await response.json();
    throw new Error(result.error || `HTTP ${response.status}`);
  }
  if (!response.body) throw new Error("浏览器不支持流式响应");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;
  const consume = (line) => {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (typeof event.type !== "string") throw new Error("无效的 Copilot 响应");
    onEvent(event);
    if (event.type === "done") completed = true;
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      if (buffer.length > 1000000) throw new Error("Copilot 响应超过大小限制");
      let end;
      while ((end = buffer.indexOf("\n")) !== -1) {
        consume(buffer.slice(0, end));
        buffer = buffer.slice(end + 1);
      }
      if (done) {
        consume(buffer);
        break;
      }
    }
    if (!completed) throw new Error("连接中断，回复可能不完整；未自动重试");
  } finally {
    reader.releaseLock();
  }
}

export function updateCopilotMessages(messages, event, requestId) {
  if (event.type === "delta" || event.type === "message") {
    if (typeof event.content !== "string") return messages;
    const id = `${requestId}:${event.id || "answer"}`;
    const previous = messages.find((message) => message.id === id);
    const content = event.type === "message" ? event.content : (previous?.content || "") + event.content;
    const next = { id, role: "assistant", content };
    return previous ? messages.map((message) => message.id === id ? next : message) : [...messages, next];
  }
  if (event.type === "tool") {
    const id = `${requestId}:tool:${event.name}`;
    const next = { id, role: "tool", name: event.name, status: event.status };
    return messages.some((message) => message.id === id) ? messages.map((message) => message.id === id ? next : message) : [...messages, next];
  }
  if (event.type === "error") return [...messages, { id: `${requestId}:error:${messages.length}`, role: "error", content: event.message }];
  if (event.type === "workflow") {
    const stages = { bd_requirements: "需求已记录", bd_plan: "连接计划已通过预检查", bd_generate: "隔离 RTL 产物已生成" };
    return [...messages, { id: `${requestId}:workflow:${messages.length}`, role: "status",
      content: `${stages[event.stage] || event.stage}${event.status === "blocked" ? "，存在阻塞问题" : ""}`,
      runDir: event.run_dir }];
  }
  if (event.type === "done" && event.status === "cancelled") return [...messages, { id: `${requestId}:stopped`, role: "status", content: "已停止生成" }];
  return messages;
}