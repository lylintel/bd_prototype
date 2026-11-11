# RTL 接口解析

## P1.2 范围

[ip_import/parser.py](../ip_import/parser.py) 提供 `parse_file(path, workspace_root=..., license_name="NOASSERTION")`，返回 ParseResult。结果包含 IpMetadata 列表、code/severity/path/line/message 诊断和 backend 标识，不写库、不修改设计、不执行 HDL。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-parser.txt
.\.venv\Scripts\python.exe -m pytest tests/test_ip_parser.py tests/golden -q
```

pytest 属于开发依赖；运行测试需安装 requirements-dev。pyslang 是单独的可选依赖，不是解析 API 的前提。跨平台安装 spike 证明 pyslang 12.1.0 不支持 Python 3.10，因此正式解析统一使用固定 YoWASP Yosys。

```python
from pathlib import Path
from ip_import.parser import parse_file

root = Path.cwd()
result = parse_file(root / "examples/rtl/counter.v", workspace_root=root)
for metadata in result.modules:
    print(metadata.to_dict())
for diagnostic in result.diagnostics:
    print(diagnostic.code, diagnostic.path, diagnostic.line, diagnostic.message)
```

## 语义与限制

- 使用 Yosys `read_verilog -defer -dump_ast1` 的未简化 AST。不是用正则解析 Verilog：正则仅解码固定版本 Yosys 的节点记录，HDL 语法由 Yosys 解析。
- 提取 ANSI/非 ANSI 端口、头部/模块体参数、wire/reg/logic、同行声明、多模块、inout、符号性与范围方向。localparam 作为表达式依赖展开，不冒充可覆盖参数，不将端口范围固化为默认参数值。
- 不进行 elaboration/proc/synthesis，不执行 initial 或读取存储器初始化文件。AST 不等同于完整 HDL 编译和行为验证。
- 尚不支持接口类型、结构体、数组端口、多维 packed 范围、字符串参数或所有 SystemVerilog 表达式；不能无损表达的模块返回错误诊断，不删掉字段后假装成功。表达式数值求解在 P1.3。
- 当前保守拒绝含反引号的预处理源码，包括宏和 include；这也会拒绝注释中的反引号。调用者应提供无预处理指令的输入；不尝试跨目录自动读取 include。未来放开需显式授权文件集及预处理策略。
- 源文件上限 1 MiB；AST 输出上限 32 MiB；子进程超时 180 秒，初次 WASM 编译可能较慢。工具参数和临时文件名固定，不将用户路径拼入 Yosys 命令文本。工作区路径以 resolve 后检查，诊断不泄露临时绝对路径。
- Yosys 语法错误返回原输入的行号；无法取得位置的工具错误使用第 1 行。非致命 warning 提供通用警告，不阻止有效模块返回；原始编译器输出不直接进入 UI。
- 同一文件中某个接口不受支持时，其余可提取模块可返回；调用者仍须检查 diagnostics，不能把部分结果当作整个文件成功。

## Golden

tests/fixtures/verilog 中 13 个源文件包含人工定义的 interfaces.golden.json。投影锁定模块顺序、参数表达式、端口顺序、方向、原始范围/符号性和错误行号，比较原始 UTF-8 字节。源码 SHA-256 与原文件独立校验；完整元数据仍通过 P1.1 schema。

旧 examples 的 HDL golden 完全保留。CI 在 Windows/Linux、Python 3.10/3.14 四组合运行正式解析夹具和旧 golden；原 Linux 两组合仍执行完整 scripts/check.py。