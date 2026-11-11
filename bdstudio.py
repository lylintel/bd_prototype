import argparse
import json
from pathlib import Path

from core.expr import MESSAGES


def main(argv=None):
    parser = argparse.ArgumentParser(prog="bdstudio", description=MESSAGES["IP_CLI_DESCRIPTION"])
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
    args = parser.parse_args(argv)
    try:
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


if __name__ == "__main__":
    raise SystemExit(main())