import importlib.metadata
import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sysconfig
import tempfile


FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "verilog"
BACKENDS = ("yosys", "pyslang") if importlib.util.find_spec("pyslang") else ("yosys",)


def capture_pyslang():
    from pyslang.ast import Compilation
    from pyslang.syntax import SyntaxTree

    tree = SyntaxTree.fromFile(str(FIXTURES / "spike.sv"))
    assert not [diagnostic for diagnostic in tree.diagnostics if diagnostic.isError()], "Fixture has syntax errors"
    compilation = Compilation()
    compilation.addSyntaxTree(tree)
    result = {instance.body.definition.name: [[port.name, str(port.direction), str(port.type)]
              for port in instance.body.portList] for instance in compilation.getRoot().topInstances}
    assert not [diagnostic for diagnostic in compilation.getAllDiagnostics() if diagnostic.isError()], "Fixture does not elaborate"
    return (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")


def capture_yosys():
    executable = Path(sysconfig.get_path("scripts")) / ("yowasp-yosys.exe" if platform.system() == "Windows" else "yowasp-yosys")
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory)
        (workspace / "input.sv").write_bytes((FIXTURES / "spike.sv").read_bytes())
        subprocess.run([str(executable), "-Q", "-T", "-p", "read_verilog -sv input.sv; hierarchy -check; proc; write_json result.json"],
                       cwd=workspace, capture_output=True, check=True, timeout=180)
        document = json.loads((workspace / "result.json").read_text(encoding="utf-8"))
    result = {name: [[port_name, port["direction"], len(port["bits"])] for port_name, port in module["ports"].items()]
              for name, module in document["modules"].items()}
    return (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main():
    for backend in BACKENDS:
        actual = capture_pyslang() if backend == "pyslang" else capture_yosys()
        golden = "spike.syntax.golden.json" if backend == "pyslang" else "spike.yosys.golden.json"
        assert actual == (FIXTURES / golden).read_bytes(), "Parser golden mismatch"
        package = "pyslang" if backend == "pyslang" else "yowasp-yosys"
        print(json.dumps({"os": platform.system(), "python": platform.python_version(), "backend": backend,
                          "version": importlib.metadata.version(package), "fixture": "spike.sv", "result": "pass"}))


if __name__ == "__main__":
    main()