import argparse
from http.client import HTTPConnection, HTTPException
import json
from pathlib import Path
import platform
from threading import Thread

from bdgui import EditorServer, Workspace


def rejection_matrix(workspace, *, samples=1):
    if type(samples) is not int or not 1 <= samples <= 10:
        raise ValueError("samples must be an integer between 1 and 10")
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
                    for sample in range(samples):
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
                        except (OSError, ValueError, HTTPException) as error:
                            result.update(error=type(error).__name__, errno=getattr(error, "errno", None),
                                          winerror=getattr(error, "winerror", None))
                            connection.close()
                        results.append(result)
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return {"platform": platform.platform(), "python": platform.python_version(), "fixed_samples": 24 * samples,
              "automatic_retries": 0, "http_version": "server HTTP/1.0; object reuse reconnects after close",
              "failures": sum(item.get("status") != 403 or not item.get("complete") for item in results), "results": results}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, choices=range(1, 11), default=10)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = rejection_matrix(Workspace(root, "examples/counter_compare.json"), samples=args.samples)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}))
    return int(report["failures"] != 0)


if __name__ == "__main__":
    raise SystemExit(main())