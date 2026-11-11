import json
from pathlib import Path
import random
import shutil
import subprocess
import sys

import pytest

import bdtool
from core.expr import ExpressionError, evaluate
from ip_import.parser import parse_file


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "fixtures" / "expressions.golden.json"
CASES = json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.mark.parametrize("expression,expected", CASES)
def test_expression_value(expression, expected):
    assert evaluate(expression, {"WIDTH": 8, "DEPTH": 16}) == expected


def test_expression_corpus_golden():
    actual = [[expression, evaluate(expression, {"WIDTH": 8, "DEPTH": 16})] for expression, _ in CASES]
    assert (json.dumps(actual, indent=2) + "\n").encode() == GOLDEN.read_bytes()


@pytest.mark.parametrize("expression", [
    "", " ", "1/0", "1%0", "MISSING+1", "abs(3)", "__import__('os')", "WIDTH.real",
    "[1]", "1;2", "1//2", "1?2", "1?2:", "(1", "1)", "8'b2", "8'hxz", "'h", "8'd",
    "$clog2(-1)", "$clog2()", "$clog2(1,2)", "2**1000000", "2**-1", "1<<1000000", "1<<-1",
    "9" * 4097, "(" * 200 + "1" + ")" * 200, "+".join(["1"] * 3000),
])
def test_invalid_or_excessive_expression_is_rejected(expression):
    with pytest.raises(ExpressionError) as error:
        evaluate(expression, {"WIDTH": 8})
    assert error.value.code
    assert error.value.offset >= 0


def test_parameter_values_must_be_integers():
    for value in (True, 1.5, "8", None):
        with pytest.raises(ExpressionError):
            evaluate("WIDTH", {"WIDTH": value})


def test_core_uses_extended_range_language_without_changing_hdl():
    path = ROOT / "examples" / "counter_compare.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["modules"]["counter"]["ports"]["count"]["range"] = ["$clog2(2 ** WIDTH) - 1", 0]
    document["modules"]["compare_eq"]["ports"]["value"]["range"] = ["$clog2(2 ** WIDTH) - 1", 0]
    assert bdtool.render_verilog(bdtool.validate_design(document, path.parent)) == bdtool.render_verilog(bdtool.load_design(path))


def test_parser_localparam_width_uses_parameter_override():
    metadata = parse_file(ROOT / "tests" / "fixtures" / "verilog" / "local.v").modules[0]
    assert evaluate(metadata.ports[0].width, {"WIDTH": 16}) == 32


def test_verilog_operator_semantics_with_icarus(tmp_path):
    cases = [("2 ** 3 ** 2", 64), ("-2 ** 2", 4), ("-7 / 3", -2), ("-7 % 3", -1), ("$clog2(0)", 0)]
    checks = "\n".join(f'if (({expression}) !== {expected}) $fatal(1, "operator mismatch");' for expression, expected in cases)
    source = tmp_path / "operators.sv"
    source.write_bytes(f"module tb; initial begin\n{checks}\n$finish; end endmodule\n".encode())
    executable = tmp_path / "simulation"
    subprocess.run([shutil.which("iverilog"), "-g2012", "-s", "tb", "-o", str(executable), str(source)], check=True, capture_output=True, timeout=30)
    subprocess.run([shutil.which("vvp"), str(executable)], check=True, capture_output=True, timeout=30)


def exercise_fuzz():
    randomizer = random.Random(1729)
    alphabet = "0123456789abcdefWIDTH+-*/%()?:<>=!&|^~_'$.,[] "
    for _ in range(5000):
        text = "".join(randomizer.choices(alphabet, k=randomizer.randrange(0, 160)))
        try:
            assert type(evaluate(text, {"WIDTH": 8})) is int
        except ExpressionError:
            pass


def test_random_strings_have_process_time_budget():
    subprocess.run([sys.executable, "-m", "tests.test_expr", "--fuzz"], cwd=ROOT,
                   check=True, capture_output=True, timeout=15)


if __name__ == "__main__":
    exercise_fuzz()