import { endpointPins } from "./model.js";
import { t } from "../i18n.js";

export function interfaceHandle(endpoint) {
  return endpoint.ext_interface ? `~if:@:${endpoint.ext_interface}` : `~if:${endpoint.inst}:${endpoint.interface}`;
}

export function parseInterfaceHandle(value) {
  if (typeof value !== "string" || !value.startsWith("~if:")) return null;
  const parts = value.split(":");
  if (parts.length !== 3 || !parts[1] || !parts[2]) return null;
  return parts[1] === "@" ? { ext_interface: parts[2] } : { inst: parts[1], interface: parts[2] };
}

export function interfaceNodeId(endpoint) {
  return endpoint.ext_interface ? `@interface:${endpoint.ext_interface}` : endpoint.inst;
}

export function interfaceDescriptor(info, endpoint) {
  const items = endpoint.ext_interface ? info?.external : info?.instances?.[endpoint.inst];
  const name = endpoint.ext_interface ?? endpoint.interface;
  return items && Object.hasOwn(items, name) ? items[name] : null;
}

export function interfaceMode(info, endpoint) {
  const mode = interfaceDescriptor(info, endpoint)?.mode;
  return endpoint.ext_interface ? mode === "master" ? "slave" : "master" : mode;
}

const pinKey = (endpoint) => endpoint.ext !== undefined ? `@${endpoint.ext}` : `${endpoint.inst}.${endpoint.port}`;

export function projectInterfaceGraph(document, info, expanded = []) {
  const result = { ports: {}, externals: [], edges: [], hiddenPins: new Set(), ownedPins: new Set(), hiddenExternals: new Set() };
  if (document?.schema_version !== 5 || !info) return result;
  const rawPins = new Set(document.nets.flatMap((net) => net.endpoints.flatMap((endpoint) => endpointPins(endpoint))));
  const occupied = new Set(), summaries = new Map((info.connections ?? []).map((item) => [item.name, item]));
  const members = (endpoint) => {
    const declaration = interfaceDescriptor(info, endpoint);
    return (declaration?.physical_ports ?? Object.values(declaration?.signals ?? {}).map((signal) => signal.port))
      .map((port) => endpoint.ext_interface ? `@${port}` : `${endpoint.inst}.${port}`);
  };
  for (const connection of document.interface_connections) {
    const summary = summaries.get(connection.name);
    const endpoints = [connection.from, connection.to];
    for (const endpoint of endpoints) {
      occupied.add(interfaceHandle(endpoint));
      for (const pin of members(endpoint)) {
        result.ownedPins.add(pin);
        if (!expanded.includes(connection.name) && !rawPins.has(pin)) {
          result.hiddenPins.add(pin);
          if (pin.startsWith("@")) result.hiddenExternals.add(pin);
        }
      }
    }
    if (expanded.includes(connection.name) && summary) {
      for (const [signal, member] of Object.entries(summary.signals)) {
        const source = pinKey(member.source), target = pinKey(member.sink);
        result.edges.push({ id: `interface:${connection.name}:${signal}`, source: member.source.inst ?? source, target: member.sink.inst ?? target,
          sourceHandle: source, targetHandle: target, type: "circuit", label: signal.toUpperCase(),
          data: { interfaceConnection: connection.name, signal, net: member.net, width: member.width, readOnly: true } });
      }
    } else if (endpoints.every((endpoint) => interfaceDescriptor(info, endpoint))) {
      const forward = interfaceMode(info, endpoints[0]) === "master" ? endpoints : [...endpoints].reverse();
      result.edges.push({ id: `interface:${connection.name}`, source: interfaceNodeId(forward[0]), target: interfaceNodeId(forward[1]),
        sourceHandle: interfaceHandle(forward[0]), targetHandle: interfaceHandle(forward[1]), type: "circuit", label: connection.name,
        data: { interfaceConnection: connection.name, coarse: true, width: summary?.signals?.tdata?.width ?? 1, invalid: !summary?.valid } });
    }
  }
  const makePin = (endpoint, declaration) => {
    const width = declaration.parameters?.DATA_WIDTH ?? 1;
    const drives = interfaceMode(info, endpoint) === "master";
    const key = interfaceHandle(endpoint);
    return { endpoint: key, name: declaration.name, interface: true, interfaceMode: declaration.mode, width,
      range: width > 1 ? [width - 1, 0] : null, direction: drives ? "output" : "input", drives,
      label: t("interfaces.pin", { endpoint: endpoint.ext_interface ? `@${declaration.name}` : `${endpoint.inst}.${declaration.name}` }),
      connectable: declaration.valid && !occupied.has(key) && !members(endpoint).some((pin) => rawPins.has(pin)) };
  };
  result.ports = Object.fromEntries(Object.entries(info.instances ?? {}).map(([name, declarations]) => [name,
    Object.entries(declarations).map(([identifier, declaration]) => makePin({ inst: name, interface: identifier }, declaration))]));
  result.externals = Object.entries(info.external ?? {}).map(([name, declaration]) => ({ id: interfaceNodeId({ ext_interface: name }),
    name, port: makePin({ ext_interface: name }, declaration), anchor: declaration.signals?.tdata?.port,
    declaredMode: declaration.mode }));
  return result;
}