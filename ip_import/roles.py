from dataclasses import replace

from bdip import IpMetadata, IpPort, IpRole


def suggest_role(port: IpPort) -> IpRole | None:
    if port.role is not None and port.role.confirmed:
        return port.role
    name = port.name.lower()
    if name in {"clk", "clock"}:
        return IpRole("clock", 0.95, False)
    if name.endswith("_clk"):
        return IpRole("clock", 0.9, False)
    if name in {"rst", "reset", "rstn", "resetn"}:
        confidence = 0.95
    elif name.endswith(("_rst_n", "_reset_n", "_rst", "_reset")):
        confidence = 0.9
    elif name.endswith("_n"):
        confidence = 0.25
    else:
        return port.role
    return IpRole("reset", confidence, False, "low" if name.endswith("n") else "high", "unknown")


def suggest_roles(metadata: IpMetadata) -> IpMetadata:
    return replace(metadata, ports=tuple(replace(port, role=suggest_role(port)) for port in metadata.ports))