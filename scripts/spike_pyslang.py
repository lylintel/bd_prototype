import importlib.metadata
import json
from pathlib import Path
import platform

from pyslang.ast import Compilation
from pyslang.syntax import SyntaxTree


FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "verilog"


def capture():
    tree = SyntaxTree.fromFile(str(FIXTURES / "spike.sv"))
    assert not [diagnostic for diagnostic in tree.diagnostics if diagnostic.isError()], "Fixture has syntax errors"
    compilation = Compilation()
    compilation.addSyntaxTree(tree)
    result = {instance.body.definition.name: [[port.name, str(port.direction), str(port.type)]
              for port in instance.body.portList] for instance in compilation.getRoot().topInstances}
    assert not [diagnostic for diagnostic in compilation.getAllDiagnostics() if diagnostic.isError()], "Fixture does not elaborate"
    return (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main():
    assert capture() == (FIXTURES / "spike.syntax.golden.json").read_bytes(), "Parser golden mismatch"
    print(json.dumps({"os": platform.system(), "python": platform.python_version(),
                      "pyslang": importlib.metadata.version("pyslang"), "fixture": "spike.sv", "result": "pass"}))


if __name__ == "__main__":
    main()