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

## P1.4 角色建议

`ip_import.roles.suggest_roles(metadata)` 返回副本；`suggest_role(port)` 提供单端口建议。只根据名称判断，不把建议当作硬件行为证据：

- clk/clock：clock，置信度 0.95；后缀 _clk：0.9。
- rst/reset/rstn/resetn：reset，0.95；_rst_n/_reset_n/_rst/_reset：0.9。
- 通用 _n：低置信度 0.25 的 reset 建议，可能只是低有效数据/片选，必须人工核对。
- 复位后缀 n 表示低有效，其余高有效；async 一律 unknown，confirmed 一律 false。
- 所有已确认角色原样保留；未匹配的名称保留原角色。不会仅因为运行建议而修改源码、设计或已有确认。

规则结果冻结在 tests/fixtures/roles.golden.json；无前端文案或自动连线副作用。

## 解析 Golden

tests/fixtures/verilog 中 13 个源文件包含人工定义的 interfaces.golden.json。投影锁定模块顺序、参数表达式、端口顺序、方向、原始范围/符号性和错误行号，比较原始 UTF-8 字节。源码 SHA-256 与原文件独立校验；完整元数据仍通过 P1.1 schema。

旧 examples 的 HDL golden 完全保留。CI 在 Windows/Linux、Python 3.10/3.14 四组合运行正式解析夹具和旧 golden；原 Linux 两组合仍执行完整 scripts/check.py。

## P1.5 导入与版本库

CLI 与 HTTP 共用 IpLibrary，不通过两套实现分别解释导入。示例：

```powershell
.\.venv\Scripts\python.exe -m bdstudio ip import examples/rtl/counter.v --dry-run
.\.venv\Scripts\python.exe -m bdstudio ip import tests/fixtures/import --recursive --license NOASSERTION
.\.venv\Scripts\python.exe -m bdstudio ip import path/to/changed.v --version 1.1.0
```

`--workspace` 指定目标工作区，默认当前目录。每个文件至多 1 MiB，一批最多 200 文件；目录可递归。单个读取、大小或解析错误不会中断其余文件，输出逐项 NDJSON 和 summary。退出码 0 表示没有失败/待升版项，1 表示部分失败或需要升版，2 表示请求/环境错误。

`--dry-run` 和 preview 不创建/修改 ip_library、索引或源文件；解析器仍使用自动清理的系统临时目录，WASM 引擎可能写工具缓存。不会声称整个系统零磁盘 I/O。

库使用新 schema_version=1 索引，保存到 `ip_library/<id>/<version>/ip.json` 和 `src/<file>`。源码哈希与接口签名相同则跳过；源码/接口变化必须给出更大的版本号，返回端口和参数的增删改差异。已有版本目录从不覆盖。

写入使用独占文件锁、临时目录、原子重命名和索引替换；索引失败会移除本次新版本，不改旧版本。异常退出遗留 .lock 时，先确认没有活动写入进程再清理，不能盲目删除正在使用的锁。

同一源文件的多个模块使用索引中的规范源码路径，避免重复编译。原始 AST 的模块依赖用于收集外部源码，包含文件内中间模块的间接依赖；缺少依赖、源码/接口记录被改动时条目不可用于生成。当前选用依赖模块的库内最新版本，复杂的跨版本工程约束尚未实现。

库条目可生成旧模型定义，参数默认表达式显式解析成 32 位整数绑定，端口 range 保留符号表达式。inout 可登记元数据，但旧 BD 连接模型尚不支持，因此标记不可拖入。多个版本的同名模块不能静默替换当前画布定义。

当前仓库公开，用户导入库和索引默认被 Git 忽略；只有后续原创 ip_library/builtin 参与版本管理。模块 id `builtin` 保留给该存储命名空间。

## HTTP 契约

- POST `/api/ip/import`：沿用 application/json、同源/Host 检查和 X-BD-Token；不使用 multipart。
- 请求字段：action 为 preview/commit，files 为 name/content_b64 数组，可选 license/version；commit 可传 metadata 对象（键为所选模块 id，值为编辑后的 v1 元数据）。带 metadata 时一次只处理一个源文件，空对象表示不选择模块。
- 单次 HTTP 正文仍受原 2 MiB 限制，源码解码后至多 1 MiB；浏览器按文件顺序请求，最多选择 200 个。无请求级更大正文例外。
- 响应为 application/x-ndjson：file 表示正在解析，ip 表示 preview/imported/skipped/needs_version/invalid，summary 给出计数。请求结构错误在流开始前返回 HTTP 错误。
- 确认时重新解析源码并校验编辑，不信任客户端哈希和接口。允许显示名、说明、标签、默认参数和角色调整；真实模块/端口名、方向、范围、符号性不能与源码矛盾，位宽编辑也必须与源接口一致。
- GET `/api/ip/library?base_dir=examples` 返回元数据、来源、可用性、诊断及重定位后的旧模型 definition。不安装可选导入依赖时旧 GUI/CLI 仍可使用，导入功能报告依赖缺失。

浏览器断开后不会回滚已经确认的单个模块；重试相同源码是幂等的。此接口不是远程多用户服务，不承诺跨版本 HDL 完整语义验证；仍需后续编译与仿真。

## P1.6 图形导入

模块库顶部的导入按钮打开独立预览对话框。可选择多个文件或文件夹，也可向对话框拖入文件/目录。目录只收集 .v/.sv，遍历限 32 层、5000 个条目、200 个 RTL 文件。目录能力依赖浏览器的文件系统入口 API；不支持时仍可多选文件。

预览可逐模块勾选，编辑显示名、标签、说明、版本、参数默认值、端口字段和角色。实际 RTL 模块名只读；错误的端口/位宽编辑会被源接口一致性检查拒绝，不重写 RTL 来迁就元数据。角色确认是独立勾选，不因点击“确认导入”自动确认所有角色。

预览取消不写库；坏文件保留错误，不阻断其余文件。确认后若部分失败则保留结果面板，已导入版本不会回滚。确认正在执行时禁用重复提交/关闭，断开浏览器的部分提交语义仍按 HTTP 契约处理。

IP 列表显示来源、版本和端口数量，搜索覆盖模块标识、显示名、标签和端口名。点击添加、双击或拖入画布时，在一次 undo 操作内加入定义和实例；同名不同定义拒绝覆盖。撤销画布操作不会删除已确认的库版本。旧设计格式不增加元数据字段，角色/版本完整信息保留在库中。

所有新界面文字来自 web/src/locales/zh-CN.json；旧文案未批量迁移。新组件和端到端代码均通过 lint，库刷新携带来源目录快照，防止异步结果用错源码相对路径。

Playwright 在独立临时工作区和随机端口启动真实 Python 服务，阻断浏览器外网请求，验证目录批量预览、参数编辑、确认、名称/标签/端口搜索、拖放、校验、撤销、手机布局/取消和部分失败。桌面/手机截图已实际查看；原生 OS 目录拖放的遍历由单测覆盖，E2E 使用真实目录选择与节点拖放。

```powershell
npm.cmd --prefix web run build
npm.cmd --prefix web run test:e2e
```

一键 scripts/check.py 会传入当前 Python 解释器；单独运行时默认使用项目 .venv，或显式设置 BD_PYTHON。测试截图在被 Git 忽略的 web/test-results 中。