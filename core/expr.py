from __future__ import annotations

from dataclasses import dataclass
import json
import operator
from pathlib import Path
import re
from typing import Mapping


MAX_LENGTH = 4096
MAX_TOKENS = 2048
MAX_DEPTH = 64
MAX_BITS = 256
MESSAGES = json.loads((Path(__file__).resolve().parents[1] / "locales" / "zh-CN.json").read_text(encoding="utf-8"))
TOKEN = re.compile(r"\s+|(?:[0-9][0-9_]*)?'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+|0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|[0-9][0-9_]*|\$clog2|[A-Za-z_][A-Za-z0-9_$]*|\*\*|<<|>>|<=|>=|==|!=|&&|\|\||[+\-*/%()?:<>&|^~!]")
PRECEDENCE = {"||": 2, "&&": 3, "|": 4, "^": 5, "&": 6, "==": 7, "!=": 7,
              "<": 8, "<=": 8, ">": 8, ">=": 8, "<<": 9, ">>": 9,
              "+": 10, "-": 10, "*": 11, "/": 11, "%": 11, "**": 12}
OPERATORS = {"+": operator.add, "-": operator.sub, "*": operator.mul,
             "&": operator.and_, "|": operator.or_, "^": operator.xor,
             "==": operator.eq, "!=": operator.ne, "<": operator.lt, "<=": operator.le,
             ">": operator.gt, ">=": operator.ge}


class ExpressionError(ValueError):
    def __init__(self, code: str, offset: int = 0, **values: object):
        self.code, self.offset = code, offset
        super().__init__(MESSAGES[code].format(offset=offset, **values))


@dataclass(frozen=True)
class Expr:
    kind: str
    operands: tuple[Expr, ...] = ()
    value: int | str | None = None
    offset: int = 0


def _checked(value: int, offset: int) -> int:
    if type(value) is not int or value.bit_length() > MAX_BITS:
        raise ExpressionError("EXPR_RANGE", offset)
    return value


def _literal(text: str, offset: int) -> int:
    clean = text.replace("_", "")
    try:
        if "'" in clean:
            size, digits = clean.split("'", 1)
            signed = digits[:1].lower() == "s"
            if signed:
                digits = digits[1:]
            base = {"b": 2, "o": 8, "d": 10, "h": 16}[digits[0].lower()]
            value = int(digits[1:], base)
            width = int(size) if size else max(32, value.bit_length())
            if not 1 <= width <= MAX_BITS:
                raise ExpressionError("EXPR_RANGE", offset)
            value &= (1 << width) - 1
            if signed and value & (1 << (width - 1)):
                value -= 1 << width
        else:
            value = int(clean, 0) if clean.lower().startswith(("0x", "0b", "0o")) else int(clean, 10)
        return _checked(value, offset)
    except ExpressionError:
        raise
    except (ValueError, KeyError):
        raise ExpressionError("EXPR_LITERAL", offset) from None


class Parser:
    def __init__(self, expression: str):
        if not isinstance(expression, str) or not expression.strip():
            raise ExpressionError("EXPR_SYNTAX")
        if len(expression) > MAX_LENGTH:
            raise ExpressionError("EXPR_LIMIT", MAX_LENGTH)
        self.tokens = []
        offset = 0
        while offset < len(expression):
            match = TOKEN.match(expression, offset)
            if match is None:
                raise ExpressionError("EXPR_SYNTAX", offset)
            if not match[0].isspace():
                self.tokens.append((match[0], offset))
                if len(self.tokens) > MAX_TOKENS:
                    raise ExpressionError("EXPR_LIMIT", offset)
            offset = match.end()
        self.tokens.append(("", offset))
        self.position = 0

    def take(self) -> tuple[str, int]:
        token = self.tokens[self.position]
        if token[0]:
            self.position += 1
        return token

    def expect(self, expected: str) -> None:
        token, offset = self.take()
        if token != expected:
            raise ExpressionError("EXPR_SYNTAX", offset)

    def expression(self, minimum: int = 0, depth: int = 0) -> Expr:
        if depth > MAX_DEPTH:
            raise ExpressionError("EXPR_LIMIT", self.tokens[self.position][1])
        token, offset = self.take()
        if token in ("+", "-", "!", "~"):
            left = Expr("unary" + token, (self.expression(13, depth + 1),), offset=offset)
        elif token == "(":
            left = self.expression(0, depth + 1)
            self.expect(")")
        elif token == "$clog2":
            self.expect("(")
            left = Expr("clog2", (self.expression(0, depth + 1),), offset=offset)
            self.expect(")")
        elif token and (token[0].isdigit() or token[0] == "'"):
            left = Expr("literal", value=_literal(token, offset), offset=offset)
        elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", token):
            left = Expr("name", value=token, offset=offset)
        else:
            raise ExpressionError("EXPR_SYNTAX", offset)
        while True:
            operation, offset = self.tokens[self.position]
            if operation == "?" and minimum <= 1:
                self.take()
                yes = self.expression(0, depth + 1)
                self.expect(":")
                no = self.expression(1, depth + 1)
                left = Expr("?", (left, yes, no), offset=offset)
            elif operation in PRECEDENCE and PRECEDENCE[operation] >= minimum:
                self.take()
                right = self.expression(PRECEDENCE[operation] + 1, depth + 1)
                left = Expr(operation, (left, right), offset=offset)
            else:
                return left


def _value(node: Expr, parameters: Mapping[str, int], depth: int = 0) -> int:
    if depth > MAX_DEPTH:
        raise ExpressionError("EXPR_LIMIT", node.offset)
    if node.kind == "literal":
        return node.value
    if node.kind == "name":
        if node.value not in parameters:
            raise ExpressionError("EXPR_UNKNOWN", node.offset, name=node.value)
        return _checked(parameters[node.value], node.offset)
    left = _value(node.operands[0], parameters, depth + 1)
    if node.kind == "?":
        return _value(node.operands[1 if left else 2], parameters, depth + 1)
    if node.kind == "&&" and not left:
        return 0
    if node.kind == "||" and left:
        return 1
    if node.kind == "clog2":
        if left < 0:
            raise ExpressionError("EXPR_DOMAIN", node.offset)
        return (left - 1).bit_length() if left > 1 else 0
    if node.kind.startswith("unary"):
        return _checked({"unary+": operator.pos, "unary-": operator.neg,
                         "unary~": operator.invert, "unary!": lambda value: int(not value)}[node.kind](left), node.offset)
    right = _value(node.operands[1], parameters, depth + 1)
    if node.kind in {"&&", "||"}:
        return int(bool(right))
    if node.kind in {"/", "%"}:
        if right == 0:
            raise ExpressionError("EXPR_ZERO", node.offset)
        quotient = abs(left) // abs(right) * (-1 if (left < 0) != (right < 0) else 1)
        return quotient if node.kind == "/" else left - quotient * right
    if node.kind in {"**", "<<", ">>"}:
        if not 0 <= right <= MAX_BITS:
            raise ExpressionError("EXPR_RANGE", node.offset)
        return _checked({"**": operator.pow, "<<": operator.lshift, ">>": operator.rshift}[node.kind](left, right), node.offset)
    return _checked(int(OPERATORS[node.kind](left, right)), node.offset)


def evaluate(expression: str, parameters: Mapping[str, int] | None = None) -> int:
    parser = Parser(expression)
    tree = parser.expression()
    if parser.tokens[parser.position][0]:
        raise ExpressionError("EXPR_SYNTAX", parser.tokens[parser.position][1])
    return _value(tree, parameters or {})