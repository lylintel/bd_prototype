import argparse
from http.client import HTTPConnection
import json
from pathlib import Path
import platform
from threading import Thread

from bdgui import EditorServer, Workspace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    workspace = Workspace(root, "examples/counter_compare.json")
    server = EditorServer(("127.0.0.1", 0), workspace)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    results = []
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    try:
        connection.request("GET", "/api/state")
        token = json.loads(connection.getresponse().read())["token"]
        for reuse in (False, True):
            for padding in (0, 4096, 65536):
                payload = json.dumps({"padding": "x" * padding})
                for rejection in ("missing_token", "bad_token", "origin", "host"):
                    for sample in range(10):
                        if not reuse:
                            connection.close()
                        headers = {"Content-Type": "application/json", "X-BD-Token": token}
                        if rejection == "missing_token":
                            del headers["X-BD-Token"]
                        elif rejection == "bad_token":
                            headers["X-BD-Token"] = "invalid"
                        elif rejection == "origin":
                            headers["Origin"] = "https://invalid.example"
                        else:
                            headers["Host"] = "invalid.example"
                        result = {"reuse_connection_object": reuse, "body_bytes": len(payload),
                                  "rejection": rejection, "sample": sample + 1}
                        try:
                            connection.request("POST", "/api/inspect", payload, headers)
                            response = connection.getresponse()
                            data = response.read()
                            result.update(status=response.status, complete=len(data) == int(response.getheader("Content-Length")))
                        except (OSError, ValueError) as error:
                            result.update(error=type(error).__name__, errno=getattr(error, "errno", None),
                                          winerror=getattr(error, "winerror", None))
                            connection.close()
                        results.append(result)
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    report = {"platform": platform.platform(), "python": platform.python_version(), "fixed_samples": 240,
              "automatic_retries": 0, "http_version": "server HTTP/1.0; object reuse reconnects after close",
              "failures": sum(item.get("status") != 403 or not item.get("complete") for item in results), "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}))


if __name__ == "__main__":
    main()