from copy import deepcopy

from core.resolve import resolve


def compact_design(document, library):
    resolved = resolve(document, library)
    return {"name": document["name"], "ports": {name: shape.to_dict() for name, shape in resolved.ports.items()},
            "instances": [{"name": item["name"], "ip": item["ip"], "params": item.get("params", {}),
                           "resolved_params": resolved.instances[item["name"]].parameters if item["name"] in resolved.instances else {},
                           "ports": {name: shape.to_dict() for name, shape in resolved.instances[item["name"]].ports.items()}
                           if item["name"] in resolved.instances else {}} for item in document["instances"]],
            "nets": deepcopy(document["nets"])}


def metadata_card(metadata):
    return {"id": metadata.id, "version": metadata.version,
            "parameters": [parameter.to_dict() for parameter in metadata.parameters],
            "ports": [port.to_dict() for port in metadata.ports]}