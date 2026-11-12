def check(resolved):
    return [item for item in resolved.diagnostics if item.code == "E004"]