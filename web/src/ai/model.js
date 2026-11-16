import { formatEndpoint } from "../semantic/model.js";

export function operationText(operation) {
  switch (operation.op) {
    case "set_param": return `${operation.inst}.${operation.name} = ${operation.value}`;
    case "add_instance": return `${operation.name}: ${operation.ip}@${operation.version} ${JSON.stringify(operation.params ?? {})}`;
    case "remove_instance": return operation.name;
    case "add_external_port": return `${operation.name}: ${JSON.stringify({ dir: operation.dir, width: operation.width, range: operation.range })}`;
    case "connect":
    case "disconnect": return `${formatEndpoint(operation.from)} -> ${formatEndpoint(operation.to)}${operation.net ? ` (${operation.net})` : ""}`;
    default: return JSON.stringify(operation);
  }
}