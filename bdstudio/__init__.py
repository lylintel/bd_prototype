import argparse
import json
from pathlib import Path

from core.expr import MESSAGES


def main(argv=None):
    parser = argparse.ArgumentParser(prog="bdstudio", description=MESSAGES["PROJECT_CLI_DESCRIPTION"])
    commands = parser.add_subparsers(dest="command", required=True)
    ip = commands.add_parser("ip")
    actions = ip.add_subparsers(dest="action", required=True)
    importer = actions.add_parser("import")
    importer.add_argument("paths", type=Path, nargs="+")
    importer.add_argument("--workspace", type=Path, default=Path.cwd())
    importer.add_argument("--recursive", action="store_true")
    importer.add_argument("--license", default="NOASSERTION")
    importer.add_argument("--version")
    importer.add_argument("--dry-run", action="store_true")
    generator = commands.add_parser("generate", help=MESSAGES["PROJECT_GENERATE_HELP"])
    generator.add_argument("design", type=Path)
    generator.add_argument("--workspace", type=Path, default=Path.cwd())
    generator.add_argument("--out-dir", "-o", type=Path, default=Path("build/gui"))
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            from bdgui import Workspace
            workspace = Workspace(args.workspace, str(args.design))
            loaded = workspace.load(str(args.design))
            result = workspace.generate({"design": loaded["design"], "base_dir": loaded["base_dir"], "design_path": loaded["path"], "quality": True, "out_dir": str(args.out_dir)})
            print(json.dumps({"type": "generated", "paths": result["paths"]}, ensure_ascii=False))
            return 0
        from ip_import.library import IpLibrary
        failed = False
        for event in IpLibrary(args.workspace).import_paths(args.paths, recursive=args.recursive, dry_run=args.dry_run,
                                                         license_name=args.license, version=args.version):
            print(json.dumps(event, ensure_ascii=False), flush=True)
            if event["type"] == "summary":
                failed = bool(event["counts"]["invalid"] or event["counts"]["needs_version"])
        return 1 if failed else 0
    except (ImportError, OSError, ValueError) as error:
        print(json.dumps({"type": "error", "message": str(error)}, ensure_ascii=False))
        return 2