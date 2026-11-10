export const clone = (value) => structuredClone(value);
export const externalId = (name) => `@${name}`;

export function allNames(design) {
  return new Set([...Object.keys(design.instances), ...Object.keys(design.ports), ...Object.keys(design.nets)]);
}

export function uniqueName(design, base) {
  const taken = allNames(design);
  let name = base;
  let index = 0;
  while (taken.has(name)) name = `${base}_${index++}`;
  return name;
}

export function checkName(design, name, previous) {
  if (!/^[A-Za-z_][A-Za-z0-9_$]*$/.test(name)) throw new Error("名称须为合法的 Verilog 标识符");
  if (name !== previous && allNames(design).has(name)) throw new Error(`名称 ${name} 已被使用`);
}

export function endpointInfo(design, endpoint, interfaces = {}) {
  if (typeof endpoint !== "string") return null;
  const match = /^(?:@([A-Za-z_][A-Za-z0-9_$]*)|([A-Za-z_][A-Za-z0-9_$]*)\.([A-Za-z_][A-Za-z0-9_$]*))$/.exec(endpoint);
  if (!match) return null;
  const external = Boolean(match[1]);
  const instance = match[2];
  const name = match[1] ?? match[3];
  const raw = external ? design.ports[name] : design.modules[design.instances[instance]?.module]?.ports?.[name];
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const literal = raw.range === undefined || (Array.isArray(raw.range) && raw.range.length === 2 && raw.range.every((bound) => Number.isInteger(bound) && bound >= -(2 ** 31) && bound < 2 ** 31));
  const resolved = literal ? { range: raw.range ?? null, signed: raw.signed ?? false } : external ? interfaces.ports?.[name] : interfaces.instances?.[instance]?.[name];
  const range = resolved?.range ?? raw.range ?? null;
  const validShape = Boolean(resolved) && typeof resolved.signed === "boolean" && (range === null || (Array.isArray(range) && range.length === 2 && range.every(Number.isInteger)));
  return { ...raw, ...resolved, direction: raw.direction, range, endpoint, name, instance,
    width: validShape ? range === null ? 1 : Math.abs(range[0] - range[1]) + 1 : undefined,
    drives: external ? raw.direction === "input" : raw.direction === "output", resolved: validShape };
}

function connectionPlan(design, first, second, interfaces) {
  const start = endpointInfo(design, first, interfaces);
  const end = endpointInfo(design, second, interfaces);
  if (!start || !end) throw new Error("连接端点不存在");
  if (![start.direction, end.direction].every((direction) => ["input", "output"].includes(direction))) throw new Error("端口方向只支持 input 或 output");
  if (first === second || start.drives === end.drives) throw new Error("连线必须包含一个驱动端和一个接收端");
  const driver = start.drives ? start : end;
  const sink = start.drives ? end : start;
  const driverNets = Object.entries(design.nets).filter(([, pins]) => pins.includes(driver.endpoint));
  const sinkNets = Object.entries(design.nets).filter(([, pins]) => pins.includes(sink.endpoint));
  if (driverNets.length > 1 || sinkNets.length > 1) throw new Error("端点属于多条网络，请先修复重复连接");
  const driverNet = driverNets[0];
  const sinkNet = sinkNets[0];
  if (sinkNet && sinkNet[0] !== driverNet?.[0]) throw new Error(`${sink.endpoint} 已连接到 ${sinkNet[0]}，请先断开原驱动`);

  function checkShape(receiver) {
    if (!driver.resolved || !receiver.resolved) throw new Error("端口范围尚未解析，请等待参数校验完成或先修复参数");
    if (driver.width !== receiver.width) throw new Error(`位宽不匹配：${driver.endpoint} (${driver.width}) -> ${receiver.endpoint} (${receiver.width})`);
    if (JSON.stringify(driver.range) !== JSON.stringify(receiver.range) || driver.signed !== receiver.signed) throw new Error("端口索引或符号性不匹配；位序转换须使用显式适配模块");
  }
  checkShape(sink);
  if (driverNet) {
    const peers = driverNet[1].map((pin) => endpointInfo(design, pin, interfaces));
    if (new Set(driverNet[1]).size !== driverNet[1].length || peers.some((port) => !port || !["input", "output"].includes(port.direction))) throw new Error(`网络 ${driverNet[0]} 包含非法或重复端点`);
    if (peers.filter((port) => port.drives).length !== 1) throw new Error(`网络 ${driverNet[0]} 必须有且只有一个驱动端`);
    peers.filter((port) => !port.drives).forEach(checkShape);
  }
  return { driver, sink, driverNet, sinkNet };
}

export function connectionError(design, first, second, interfaces = {}) {
  try { connectionPlan(design, first, second, interfaces); return null; }
  catch (error) { return error.message; }
}

export function connectPorts(design, first, second, interfaces = {}) {
  const { driver, sink, driverNet, sinkNet } = connectionPlan(design, first, second, interfaces);
  if (driverNet) {
    if (!sinkNet) driverNet[1].push(sink.endpoint);
    return driverNet[0];
  }
  const name = uniqueName(design, `${driver.name}_net`);
  design.nets[name] = [driver.endpoint, sink.endpoint];
  return name;
}

export function disconnectPort(design, endpoint) {
  const driver = endpointInfo(design, endpoint)?.drives;
  for (const [name, pins] of Object.entries(design.nets)) {
    if (!pins.includes(endpoint)) continue;
    const remaining = pins.filter((pin) => pin !== endpoint);
    if (driver || remaining.length < 2) delete design.nets[name];
    else design.nets[name] = remaining;
  }
}

export function addInstance(design, module) {
  if (!design.modules[module]) throw new Error("模块不存在");
  const name = uniqueName(design, `${module}_0`);
  design.instances[name] = { module, parameters: {} };
  return name;
}

export function deleteNode(design, id) {
  const external = id.startsWith("@");
  const endpoints = external ? [id] : Object.keys(design.modules[design.instances[id]?.module]?.ports ?? {}).map((name) => `${id}.${name}`);
  for (const endpoint of endpoints) disconnectPort(design, endpoint);
  if (external) delete design.ports[id.slice(1)];
  else delete design.instances[id];
}

export function renameNode(design, layout, id, name) {
  const external = id.startsWith("@");
  const previous = external ? id.slice(1) : id;
  checkName(design, name, previous);
  const section = external ? "ports" : "instances";
  design[section] = Object.fromEntries(Object.entries(design[section]).map(([key, value]) => [key === previous ? name : key, value]));
  const newId = external ? externalId(name) : name;
  for (const [net, pins] of Object.entries(design.nets)) {
    design.nets[net] = pins.map((pin) => external ? (pin === id ? newId : pin) : (pin.startsWith(`${id}.`) ? `${name}${pin.slice(id.length)}` : pin));
  }
  if (layout.nodes[id]) {
    layout.nodes[newId] = layout.nodes[id];
    delete layout.nodes[id];
  }
  return newId;
}

export function makeExternal(design, endpoint, interfaces) {
  const port = endpointInfo(design, endpoint, interfaces);
  if (!port?.instance) throw new Error("请选择实例端口");
  if (port.range && !port.resolved) throw new Error("端口范围尚未解析，请先检查参数");
  const name = uniqueName(design, port.name);
  const spec = { direction: port.direction };
  if (port.range) spec.range = [...port.range];
  if (port.signed) spec.signed = true;
  design.ports[name] = spec;
  try {
    connectPorts(design, endpoint, externalId(name), interfaces);
  } catch (error) {
    delete design.ports[name];
    throw error;
  }
  return externalId(name);
}

export function renameNet(design, previous, name) {
  checkName(design, name, previous);
  design.nets = Object.fromEntries(Object.entries(design.nets).map(([key, value]) => [key === previous ? name : key, value]));
}

export function rangeLabel(port) {
  if (!port) return "?";
  if (port.range) return `[${port.range[0]}:${port.range[1]}]`;
  return "1";
}

export function parseInteger(text) {
  if (!/^-?\d+$/.test(String(text).trim())) throw new Error("参数必须为整数");
  const value = Number(text);
  if (!Number.isSafeInteger(value) || value < -(2 ** 31) || value >= 2 ** 31) throw new Error("参数必须为 32 位有符号整数");
  return value;
}

export function validateDocumentShape(value) {
  const isRecord = (item) => item !== null && typeof item === "object" && !Array.isArray(item);
  const checkPorts = (ports, location) => {
    if (!isRecord(ports)) throw new Error(`${location} 必须是端口对象`);
    for (const [name, port] of Object.entries(ports)) {
      if (!isRecord(port) || typeof port.direction !== "string") throw new Error(`${location}.${name} 缺少端口方向`);
      if (port.range !== undefined && (!Array.isArray(port.range) || port.range.length !== 2 || port.range.some((bound) => !["number", "string"].includes(typeof bound)))) throw new Error(`${location}.${name}.range 必须为两个索引`);
    }
  };
  if (!isRecord(value)) throw new Error("设计必须是 JSON 对象");
  if (typeof value.name !== "string") throw new Error("缺少设计名称");
  for (const field of ["modules", "instances", "ports", "nets"]) {
    if (!isRecord(value[field])) throw new Error(`缺少 ${field} 对象`);
  }
  checkPorts(value.ports, "ports");
  for (const [name, module] of Object.entries(value.modules)) {
    if (!isRecord(module) || !Array.isArray(module.sources) || module.sources.some((source) => typeof source !== "string")) throw new Error(`模块 ${name} 缺少源码路径数组`);
    checkPorts(module.ports, `modules.${name}.ports`);
    if (module.parameters !== undefined) {
      if (!isRecord(module.parameters)) throw new Error(`模块 ${name} 参数必须是对象`);
      for (const [parameter, spec] of Object.entries(module.parameters)) {
        if (!isRecord(spec) || !["number", "string", "boolean"].includes(typeof spec.default)) throw new Error(`模块 ${name} 参数 ${parameter} 缺少标量默认值`);
      }
    }
  }
  for (const [name, instance] of Object.entries(value.instances)) {
    if (!isRecord(instance) || typeof instance.module !== "string") throw new Error(`实例 ${name} 缺少 module`);
    if (instance.parameters !== undefined && (!isRecord(instance.parameters) || Object.values(instance.parameters).some((parameter) => !["number", "string", "boolean"].includes(typeof parameter)))) throw new Error(`实例 ${name} 参数必须是标量值对象`);
  }
  for (const pins of Object.values(value.nets)) {
    if (!Array.isArray(pins) || pins.some((pin) => typeof pin !== "string")) throw new Error("网络必须是端点字符串数组");
  }
  return value;
}