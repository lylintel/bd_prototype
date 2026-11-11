# 安全整数表达式

P1.3 在 core/expr.py 提供 `evaluate(expression, parameters=None) -> int`。词法扫描、Pratt 解析和整数求值全部在本地完成，不调用 eval/exec、Python AST 执行或外部解释器。

## 支持范围

- 十进制与下划线；Verilog 定宽/非定宽 b/o/d/h 常量，如 8'd5、8'shff、'h1F。定宽常量先截断到指定宽度，s 常量按补码解释。X/Z 和不完整常量拒绝。
- 保留旧入口可接受的 0x/0b/0o 整数字面量。
- 参数名、括号、正负号、+ - * / % **、关系/相等比较、三目、$clog2；另支持逻辑/位运算与有界移位。
- 二元运算按 Verilog 优先级，幂运算左结合，一元操作高于幂。三目右结合。相关边界已由 Icarus 实际核对，不套用 Python 的幂优先级。
- 除法向零截断，余数与被除数同号；比较和逻辑结果为 0/1。三目和逻辑运算短路，但所有分支仍必须语法合法。
- $clog2 使用整数 bit_length，不依赖浮点精度；0/1 返回 0，负数拒绝。

这是元数据/位宽的有界数学整数求值，不是完整 SystemVerilog 四态、向量上下文宽度传播或自动有符号转换引擎。除字面量截断外不会模拟任意向量溢出。右移是数学整数算术右移；负数的向量逻辑右移不属于本 API。

## 安全限制

- 最多 4096 字符、2048 token、64 层解析/求值嵌套；最多 256 位整数，指数和移位量在 0–256 范围。
- 未知名称、非整数参数、任意函数调用、属性/下标、非法 token、除零、负指数及超限输入均返回 ExpressionError，携带 code/offset。
- 新消息位于 locales/zh-CN.json；旧核心的 unknown-parameter/unsupported-expression 英文识别前缀保留，避免破坏原诊断测试。

bdtool._range_bound 委托此求值器，再经过原有 32 位有符号索引检查。旧设计结构、参数存储格式和 HDL 输出不改变。IP 元数据加载仍只验证结构，不会偷偷求值所有字段。

## 验证

tests/fixtures/expressions.golden.json 冻结 52 组表达式结果，逐字节对比。还覆盖非法/超限输入、Icarus 操作符核对、旧核心集成、localparam 参数覆盖，以及独立进程中 5000 组固定种子随机字符串（15 秒上限）。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_expr.py tests/golden -q
```