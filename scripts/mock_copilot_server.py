import argparse
from pathlib import Path
import sys
from types import SimpleNamespace

from bdcopilot import CopilotBridge
from bdgui import EditorServer, Workspace


def main(argv=None):
    parser = argparse.ArgumentParser(description="Test-only real HTTP server with the shared fake SDK")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from test_bdcopilot import FakeClient, FakeResult

    sdk = SimpleNamespace(Client=FakeClient, Connection=SimpleNamespace(for_stdio=lambda **kwargs: kwargs),
                          Tool=lambda **kwargs: SimpleNamespace(**kwargs), Result=FakeResult,
                          Reject=lambda **kwargs: SimpleNamespace(kind="reject", **kwargs))
    workspace = Workspace(args.workspace, "examples/counter_compare.json")
    server = EditorServer(("127.0.0.1", args.port), workspace)
    server.copilot.close()
    server.copilot = CopilotBridge(workspace, sdk_loader=lambda: sdk)
    print(f"BD Studio: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()