# 本地 BD 原型

用 JSON 描述已有 RTL 模块的实例、参数和连线。Python 校验器解析设计，生成一个结构性 Verilog 模块和一个顶层 wrapper。RTL 核心只依赖 Python 3.10 或更新版本的标准库；可选 Copilot 助手需要 Python 3.11+ 和单独安装的 SDK。

命令行和本地网页 GUI 共用校验与 Verilog 生成核心；画布采用 React Flow，静态资源本地打包。Copilot 不可用或未安装时，原有 RTL 编辑、校验、生成不受影响。

开源 IP 已整理到 `src/`：UART 发送/接收、简化流式寄存器、完整 AXI Stream 寄存器和 8 路优先编码器。来源、MIT 许可、固定配置、维护状态及使用方式见 [src/README.md](src/README.md)。GUI 可打开 [src/ip_catalog.json](src/ip_catalog.json) 使用模块库，或打开 [examples/uart_loopback.json](examples/uart_loopback.json) 查看完整回环设计。

| 文件 | 职责 |
| --- | --- |
| [bdtool.py](bdtool.py) | 设计模型、表达式求值、连接校验、两层生成器和 CLI |
| [bdip.py](bdip.py) | 独立 v1 IP 元数据数据类、schema 校验、加载保存与旧模块迁移 |
| [bdgui.py](bdgui.py) | Python 标准库 HTTP 服务、编辑器 API、设计与布局保存 |
| [bdcopilot.py](bdcopilot.py) | 可选 Copilot SDK 桥接、会话生命周期、流式事件和受限设计工具 |
| [bdworkflow.py](bdworkflow.py) | 可追踪需求、确定性连接计划、隔离生成及输入哈希保护 |
| [.github/skills/build-bd-design/SKILL.md](.github/skills/build-bd-design/SKILL.md) | 需求到 IP 组合、计划及 RTL 的项目工作流 skill |
| [requirements-copilot.txt](requirements-copilot.txt) | 固定 Copilot Python SDK 版本的可选依赖 |
| [web/src/CopilotPanel.jsx](web/src/CopilotPanel.jsx) | 模型选择、流式聊天、停止、新会话和上下文共享同意 |
| [web/src/App.jsx](web/src/App.jsx) | React Flow 画布、模块库、属性表、诊断和 HDL 预览 |
| [web/src/model.js](web/src/model.js) | 前端 JSON 编辑操作，不另写位宽表达式求值器 |
| [examples/counter_compare.json](examples/counter_compare.json) | 完整模块元数据及可编辑设计，基准阈值为 9 |
| [examples/rtl/counter.v](examples/rtl/counter.v) | 8 位参数化计数器，上升沿采样、同步高有效复位 |
| [examples/rtl/compare_eq.v](examples/rtl/compare_eq.v) | 参数化等值比较器 |
| [examples/rtl/tb.v](examples/rtl/tb.v) | 复位、逐周期匹配和计数回绕检查 |
| [tests/test_bdtool.py](tests/test_bdtool.py) | CLI、模型、生成结果和可选 HDL 仿真的验收测试 |
| [tests/test_bdgui.py](tests/test_bdgui.py) | GUI 后端、路径约束、草稿保存和 HTTP 访问检查 |
| [web/src/model.test.js](web/src/model.test.js) | 连线、扇出、重命名、外引端口和参数编辑回归 |

## IP 元数据

P1.1 新增 [ip.schema.json](ip.schema.json)，定义带版本、源码哈希、许可证、参数表达式和端口角色的独立 IP 格式。counter/compare_eq 可通过 API 自动迁移，保留原设计和 HDL 输出。现已提供跨平台 RTL 解析、角色建议、共享 CLI/HTTP 导入入口和 GUI 预览确认面板，使用方法和限制见 [docs/ip-import.md](docs/ip-import.md)。

仅使用 IP 元数据 API 时安装 `python -m pip install -r requirements-ip.txt`；开发安装已包含该依赖。字段、迁移示例和限制见 [docs/ip-metadata.md](docs/ip-metadata.md)。

位宽表达式已使用 P1.3 的安全 Pratt 求值器，支持 Verilog 整数、三目和 `$clog2`，限制见 [docs/expressions.md](docs/expressions.md)。旧设计与 HDL 输出保持兼容。

导入预览命令：`python -m bdstudio ip import path/to/rtl --recursive --dry-run`，移除 `--dry-run` 才写入本地版本库。源码变化需显式 `--version` 升版；用户导入源码默认不进入 Git。

## 开发检查

CI 与本地共用 [scripts/check.py](scripts/check.py)，依次执行 Ruff、全部 Python/golden 测试、ESLint、应用 JS/JSX 类型检查、前端单测、生产构建和隔离真实后端的 Playwright 验收。任一步失败立即返回非零状态。检查不请求真实 LLM，不需要登录或 SDK；只使用本机临时 HTTP 服务和 mock。

准备 Python 3.10+、Node.js 24 和 Icarus Verilog（`iverilog`、`vvp` 必须在 PATH；Ubuntu 可用 `sudo apt-get install iverilog`），已有虚拟环境后安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
npm.cmd --prefix web ci
.\web\node_modules\.bin\playwright.cmd install chromium
```

一键运行与 CI 相同的检查：

```powershell
.\.venv\Scripts\python.exe scripts/check.py
```

Linux/macOS 首次在 web 目录执行 `npx playwright install --with-deps chromium`，随后使用 `.venv/bin/python scripts/check.py`。CI 测试 Python 3.10/3.14 与 Node 24，缺少 HDL 工具会失败，不接受跳过仿真的假绿；另有四组合解析矩阵。安装步骤需要网络，检查步骤不依赖外网。仅运行原有 Python 单测仍可用 `python -m unittest discover -s tests -v`；golden 必须使用 `python -m pytest tests/golden`，维护规则见 [tests/golden/README.md](tests/golden/README.md)。

## 网页 GUI

首次克隆后，在项目根目录创建虚拟环境并构建前端。需要 Python 3.10+（Copilot 助手需要 3.11+）及 Node.js 20.19+ 或 22.12+，推荐 Node.js 24。Windows PowerShell：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-parser.txt
npm.cmd --prefix web ci
npm.cmd --prefix web run build
.\.venv\Scripts\python.exe -m bdgui --open
```

Linux/macOS 使用 `python3 -m venv .venv`、`npm` 和 `.venv/bin/python` 执行对应命令。虚拟环境、依赖、前端编译产物、构建日志与个人设计不提交到 Git；仓库保留源码、锁文件、测试和演示设计。

已经完成构建后，后续只需启动服务：

```powershell
$Python = '.\.venv\Scripts\python.exe'
& $Python -m bdgui --open
```

默认地址为 <http://127.0.0.1:8765>。若端口被占用，服务会尝试后续端口，以终端打印地址为准。`--open` 打开浏览器，省略时只启动服务；终端按 Ctrl+C 停止。请保持服务终端运行。本机已有上述虚拟环境；其他机器可替换为其 Python 3.10+ 解释器。仅运行 RTL 功能无需额外 Python 包。

也可以启动时指定已保存设计：

```powershell
& $Python -m bdgui --design designs/web_demo.json --port 8765 --open
```

前端重建需要 Node.js 20.19+ 或 22.12+，推荐 Node.js 24。首次获取源码或修改前端后运行：

```powershell
npm.cmd --prefix web ci
npm.cmd --prefix web run build
```

Linux/macOS 将 `npm.cmd` 换成 `npm`。依赖由锁文件固定；构建结果写入 `web/dist/`，包含画布代码、图标及字体，运行时不访问 CDN，也不需要启动 Node 服务。修改前端后重建并刷新页面；修改 Python 服务后重启服务。

### 使用流程

1. 默认载入计数器与比较器示例。从左侧拖入模块，或用其加号、双击添加实例。新模块通过“登记 RTL 模块”填写已有源码的路径和手工接口元数据。
2. 从驱动端口拖线到接收端口，也可依次点击两个端口。已有驱动端的后续连线加入同一网络，形成扇出。Escape 取消连线。
3. 选择实例，在右侧修改整数参数；Enter 或移出输入框提交。名称编辑会同步更新网络端点引用。端口右侧按钮用于外引或断开连接。
4. 底部诊断使用核心原始错误信息；例如把比较器 `WIDTH` 改为 4，会得到 `nets.count_bus: width mismatch` 并禁用生成。未完成的设计仍可保存为草稿。
5. 保存时同时写出硬件 JSON 和独立的 `.layout.json`，后者保存坐标、缩放及偏移。再次打开会恢复布局。保存到新目录时自动重写 RTL 相对路径，文件仍可直接用于原 CLI。
6. “生成 HDL”将当前内存设计校验后写入 `build/gui/`，底部可查看 BD 和 wrapper、复制或下载代码。生成不等于保存设计；未保存标记会保持。

还支持撤销/重做、删除所选节点或网络支路、缩放、适应画布、整理布局、外部端口方向/范围/符号性编辑，以及可应用修改的设计 JSON 视图。窄屏通过顶部按钮打开模块和属性抽屉，画布支持缩放和平移。

### 代码窗口

- 拖动底部输出面板的上边界可调整高度；聚焦这条分隔线后也可用上下方向键调整。
- 点击“浮动代码窗口”后，拖动标题栏移动窗口，拖动边缘或右下角调整大小；“固定代码窗口到底部”恢复停靠。
- 使用“最大化代码窗口”与“还原代码窗口”切换大小，也可双击标题栏；还原后保留之前的浮动位置与尺寸。
- 标题栏的放大镜按钮调整 Verilog/JSON 字号，范围为 10 到 24 px，不修改代码内容。窗口仍支持文本选择、滚动、复制和下载。
- 窗口会限制在当前浏览器视口内。其位置、大小和字号是页面内的界面状态，不进入硬件 JSON，刷新后恢复默认；画布坐标仍按原方式单独保存。

窗口实现位于 [web/src/OutputWindow.jsx](web/src/OutputWindow.jsx)，使用 `react-rnd` 处理拖拽与缩放。

### 连线规则

- 网络只允许一个驱动端，可连接多个接收端。外部输入和实例输出是驱动端，实例输入和外部输出是接收端；首版不支持 `inout`。
- 点击与拖拽共用同一预检。范围尚未解析时不会跳过校验；位宽、索引顺序、标量/向量形状、符号性须一致，否则应使用显式 RTL 适配模块。
- 可以从输入端反向起拖，但保存的网络仍按真实驱动方向建立。已连接的输入不能再接第二个驱动，必须先断开旧连接。
- 选中一条线后按 Delete，只删除该接收端支路；断开驱动端则删除整个网络、释放所有接收端，不留下只有接收端的无驱动网络。
- 走线采用正交避障路由，模块移动后会重算，不再让长线直接穿过中间模块。若节点重叠或通道不足而无法路由，会显示警示色虚线，应移动节点腾出空间。
- 画面中的交叉不自动建立电气连接；连接关系以 JSON 中的 `nets` 为准。合法时序反馈继续允许，组合环路分析仍是独立的后续能力。

交互规则在 [web/src/model.js](web/src/model.js) 中统一维护；[web/src/CircuitEdge.jsx](web/src/CircuitEdge.jsx) 使用 `@tisoap/react-flow-smart-edge` 的同步正交路由接口，适合当前小规模原型。布局路径不参与 Verilog 生成。

### 文件与范围

- 硬件设计保存到 `designs/`；布局单独保存，不进入 HDL 生成模型。原始示例不会被保存操作覆盖。
- GUI 的 HDL 产物固定在 `build/gui/`，不覆盖 CLI 在 `build/` 下的基准产物。
- [designs/web_demo.json](designs/web_demo.json) 和 [designs/web_demo.layout.json](designs/web_demo.layout.json) 是本次浏览器操作实际保存的示例，阈值为 19。
- 源文件路径相对于当前设计目录，右侧显示 `Source base`。新源码须先放入工作区，再登记元数据；不提供任意 HDL 解析或上传编译执行功能。
- 服务仅绑定本机回环地址；API 检查 Host、Origin 和会话请求令牌，限制请求大小，所有源路径和保存路径必须留在工作区。它是单用户本地工具，不是可暴露到公网的多用户服务。
- 页面刷新默认重新读取服务启动时的设计；要继续某个已保存设计，可使用“打开设计”或启动参数 `--design`。未保存修改有离开页面提示。

### GUI 验证

```powershell
& $Python -m unittest discover -s tests -v
npm.cmd --prefix web test
npm.cmd --prefix web run build
```

2026-11-04 实际结果：15 项 Python 测试通过、无跳过，12 项前端模型与走线测试通过，Vite 生产构建通过。浏览器验证了模块拖入、节点移动、点击与拖动连线、单网络扇出、参数错误诊断及生成禁用、撤销恢复、外部端口创建、删除、保存重开、布局视口恢复，以及桌面与手机窄屏布局。构建中 React Flow 的 `use client` 被忽略提示不影响本地客户端构建。

本轮修复另行实测了代码窗口的高度调整、浮动移动与缩放、最大化还原、字号调整、手机视口边界，以及非法方向/位宽连接拒绝、反向起拖、独立支路删除、驱动端释放所有接收端。长连线对中间模块的路径采样交点为 0，模块移动后仍会重新避让。窗口调整未改变代码内容或设计的保存状态。

网页实际生成的阈值 19 产物另行编译仿真通过，输出 `PASS: threshold=19 and counter wraparound`。本机仿真工具绝对路径如下，可避免终端命令查找差异：

```powershell
& "$env:LOCALAPPDATA/Programs/iverilog-11.0/bin/iverilog.exe" -g2012 -s tb -o build/gui/sim examples/rtl/counter.v examples/rtl/compare_eq.v build/gui/example_bd.v build/gui/example_bd_wrapper.v examples/rtl/tb.v
& "$env:LOCALAPPDATA/Programs/iverilog-11.0/bin/vvp.exe" build/gui/sim +threshold=19
```

这两条命令对应网页生成的阈值 19 配置；改变参数后应使用对应阈值。没有 Icarus 的机器仍可运行 GUI，测试会明确跳过 HDL 仿真。

## Copilot 助手

采用“网页 -> 本地 Python 服务 -> 官方 Copilot SDK -> Copilot 运行时”的架构。SDK 负责模型会话、流式事件和工具执行编排；本项目只处理传输、权限、取消和资源边界，不自建模型编排循环。

### 安装与登录

本机固定使用 `github-copilot-sdk==1.0.28`，SDK 所需最低版本为 Python 3.11。选择同一个项目虚拟环境安装并启动服务：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-copilot.txt
.\.venv\Scripts\python.exe -m copilot download-runtime
copilot --version
copilot login
.\.venv\Scripts\python.exe -m bdgui --open
```

当前 SDK 会下载并校验与包配套的运行时，支持 stdio JSON-RPC，不必把某个系统 CLI 版本当成唯一运行时。独立 CLI 用于本机登录；本次实际安装的 CLI 为 1.0.106，SDK 配套运行时为 1.0.105。此 CLI 的登录命令是 `copilot login`，不是 `copilot auth login`。

登录应由用户在本机终端/浏览器中完成，不要把密码、PAT 或设备凭据粘贴到本 GUI 或聊天消息。登录成功后，在助手面板点击“连接 Copilot”。VS Code 扩展已登录不代表这个 CLI 已登录。SDK 会重建尚未登录的运行时，以读取更新后的 CLI 状态。

默认明确使用用户的 `~/.copilot` 状态目录，或环境变量 `COPILOT_HOME` 指定的位置；CLI 登录与 GUI 必须使用相同用户和状态目录。运行时工作目录另外隔离在系统临时区，禁用工程配置发现、文件 hooks、不受控的 skills 扫描、MCP 和主机 Git 操作。项目内的指定 skill 由应用显式加载，不依赖自动发现。会话记录可能由 SDK/CLI 保存在用户状态目录，不写入硬件 JSON；清空本页会话不代表已发送内容能从远端撤回。

本工具是本机单用户应用，SDK 使用 `mode="copilot-cli"` 和 `use_logged_in_user=True` 读取 CLI 已保存的登录信息。不要改回 `mode="empty"`：SDK 1.0.28 在该模式下会主动设置 `COPILOT_DISABLE_KEYTAR=1`，禁用系统凭据库，导致 Windows 上 CLI 已登录但 GUI 仍显示“需要登录”。工具权限仍由会话级白名单、拒绝权限处理器及显式禁用配置发现/自动化来限制，不因读取登录信息而开放文件或终端工具。

通常使用 SDK 配套运行时即可。需要指定兼容 CLI 时，可在启动服务的终端设置 `COPILOT_CLI_PATH` 为可信可执行文件路径。不要指向会询问安装的启动器；本机曾遇到 VS Code 启动器触发 MSI 错误 1618，后续安装已成功，不应为此终止其他 Windows 安装程序。

### 使用与用量

点击右上角“Copilot 助手”图标打开面板。打开面板只读取本地状态，不启动模型请求；“连接 Copilot”只检查运行时、身份与可用模型，不发送提示词。原有拖拽、参数修改、设计校验及 HDL 生成不会自动调用 Copilot。

按本机用户的设置，用量确认默认开启，页面不再显示确认复选框；仍须主动点击发送或在输入框按 Enter 才提交请求。具体用量取决于账号方案、模型和服务端规则；本页统计的是用户消息数，不是账单余额，也不承诺“一条消息固定扣一次高级请求”。工具续轮也可能带来额外用量，停止已经开始的请求不保证免计费。额度及组织策略以 GitHub 官方账单和管理设置为准。

按本机用户的设置，“共享当前设计 JSON”和用量确认默认开启且不显示复选框。现在每次手动发送还会携带 `allow_design_changes=true`，授权本轮使用受限设计工作流。设计快照随请求发送；需要功能证据时，Copilot 可另外读取目录中已登记的 RTL 文本，不会自动上传整个项目。仅打开面板、拖动节点或修改参数不会向 Copilot 发送消息。后端仍逐回合检查共享和设计修改授权，不允许旧会话沿用已撤销的权限。需要隔离历史上下文时，使用“新 Copilot 会话”。

当前开放下列专用工具，但不开放任意内置文件、终端、网络或硬件操作：

| 工具 | 能力 |
| --- | --- |
| `bd_design` | 读取用户本轮显式共享的 JSON 快照 |
| `bd_validate` | 复用本地核心进行连接/参数检查，返回诊断与已解析接口 |
| `bd_preview` | 返回校验通过后的 BD/wrapper 文本，不落盘、不编译 |
| `bd_workflow` | 返回指定 skill、数据契约、当前基准哈希和实际用户消息证据 ID |
| `bd_catalog` | 查询当前设计及本地 IP 库的真实定义、来源、哈希和冲突 |
| `bd_read_source` | 只读取指定已登记模块的 RTL 文件，检查路径、类型、大小及哈希 |
| `bd_requirements` | 保存有原话证据的结构化需求、验收方法和开放问题 |
| `bd_plan` | 在设计副本上执行明确操作并预检查，要求需求覆盖和审查义务 |
| `bd_generate` | 在独立目录生成设计、BD、wrapper、差异和报告，并发出画布更新事件 |

### 自动设计与 Skill

可直接向 Copilot 提出设计修改要求，例如“将 compare_0 的阈值改为 19，保留其他模块和连线”，或指定输入、输出、协议和参数，请它从已有 IP 库构建电路。只说明功能却缺少会改变实现的信息时，它应一次集中询问最重要的 1-3 项，而不是默认补齐算法、精度或溢出策略。

工作流由 [.github/skills/build-bd-design/SKILL.md](.github/skills/build-bd-design/SKILL.md) 和 [数据契约](.github/skills/build-bd-design/references/contracts.md) 定义。SDK 会话会显式加载该文件，`bd_workflow` 返回同一套契约；用户提供的外部 Vivado skill 保持未修改。本版适配当前 `bdtool` JSON/Verilog 后端，不声称实现 Vivado IP Integrator、IP-XACT 导入、Tcl、地址自动化或器件烧写。

本次新版服务使用 <http://127.0.0.1:8768>，旧服务未被强行中断。请在新版页面开启新会话；修改 skill 后也需开启新会话，修改 Python 后端后需重启服务。

1. 读取真实目录及必要源码，获得模块名、接口、定义和源码哈希。相同名称但不同定义会记录为冲突，不按名称升级或替换。
2. 用需求 ID 和用户原文建立规格，覆盖输入输出、算法、精度、速率、帧、背压、时延、控制、地址、中断、平台和验收。区分硬约束与优化目标，性能数字必须有单位、类型和条件。
3. 保存未知项、影响、候选解释、阻塞阶段和开放问题。原话必须逐字出现在引用的用户消息中；缺失硬要求或 build/plan 阻塞项不能生成。
4. 提交关联需求 ID 的显式操作计划。支持添加实例/外部端口、改参数、连接、断开、移除指定对象及重命名设计，不支持任意改写模块定义或上游源码。保留未涉及的对象，原子校验失败不会污染共享快照。
5. 通过计划预检查后直接生成，不再弹全局批准框。结果自动同步到当前画布，并进入撤销历史；如果你在推理期间改变了硬件设计或源码基准目录，则拒绝覆盖并保留隔离产物。只移动节点不会阻止更新，原有布局会保留。

每个用户回合使用独立的 `build/copilot/<run-id>/`，不覆盖原设计、已保存设计或其他运行产物：

```text
catalog/ip_catalog.json
requirements/user_evidence.json
requirements/specification.json
requirements/open_questions.json
requirements/traceability.json
plans/base_design.json
plans/plan.json
plans/candidate.json
plans/design.diff
generated/design.json
generated/<design>.v
generated/<design>_wrapper.v
verification/preflight.json
verification/results.json
run_state.json
```

生成的硬件 JSON 会重定位源码相对路径，可在 GUI 的文件路径框或原 CLI 中重新打开。聊天区显示实际产物目录、计划状态、差异和画布应用结果。`run_state.json` 记录输入哈希、最后通过阶段和依赖；源码或目录在预检查后变化会拒绝过期生成。后续回合从当前快照和已有消息证据重新规划，不自动跳过变更影响的检查。

规划审查的 `pass` 不是硬件验证通过。当前工具实际执行的是结构/参数校验与 Verilog 文本生成，仿真、Vivado、综合、CDC、时序及硬件检查会明确记录为 `not_run`。缺少合法 IP 组合时应报告冲突和缺失能力，不降低要求来制造“成功”。

### 会话与停止

- 支持当前页面中的多轮会话和逐段输出；最终消息替换流式草稿，不重复拼接内容。不展示模型内部 reasoning 事件。
- 模型列表来自当前已登录账号；改变模型需新建会话。会话不自动跨页面恢复。
- 一次只允许一个生成请求。每个会话最多 20 条用户消息，每轮最多执行 24 次受限工具，响应等待超时为 180 秒；一份计划每回合最多尝试 3 次，并限制输入、上下文与输出大小。
- “停止”、关闭助手面板或连接断开都会触发 SDK 中止；中止未得到确认时会进一步强制断开自有运行时。已提交的远端请求仍可能计费。不自动重试失败的模型请求、发送新用户消息或后台压缩；同一回合允许在三次上限内修正计划。
- “新 Copilot 会话”清空本页面消息，并请求 SDK 断开和删除对应会话。关闭 GUI 服务也会清理运行时。

本地接口为 `GET /api/copilot/status`，以及受现有 Host/Origin/请求令牌保护的 `POST /api/copilot/connect`、`chat`、`cancel`、`clear`。聊天响应采用 NDJSON 流，认证凭据不传入浏览器。

### 验证边界

2026-11-06 已验证：SDK 安装、配套运行时下载、真实 JSON-RPC 连接与登录状态；修复系统凭据库读取后，本机返回 `connected=true`、`authenticated=true`，列出 13 个可用模型。真实 SDK 已接受包含 9 个专用工具和项目 skill 的会话配置，该测试会话已关闭，未发送提示词。注册检查记录位于 `build/workflow_sdk_probe.log`。

当前全量回归为 49 项 Python 测试、19 项前端测试全部通过，无跳过，生产构建通过。Python 汇总保存在 `build/workflow_validation.log`。包含原有 RTL/IP 仿真、权限与取消测试，以及原话证据、未知项阻塞、三次计划上限、输入变化、防覆盖、目录隔离和自动画布冲突检测。

新增确定性验收从真实目录选用 8 路优先编码器，配置实例、连接外部端口、生成两层 RTL 并用 Icarus Verilog 编译通过，保留原有电路。浏览器替身验收确认：自动应用阈值 19、撤销恢复 9；生成期间手动改为 23 后，旧结果不会覆盖，也不增加全局确认弹窗。

初版浏览器验证覆盖了用量/共享开关、流式展示、工具状态、停止和新会话，以及 390 px 窄屏布局；现按用户要求将用量确认、设计共享和受限设计修改固定为默认授权，并不显示额外复选框。模型回复与工具调用在回归/界面测试中使用替身，未发送真实收费模型请求。确定性计划执行、生成与示例编译是真实运行；自然语言选型质量、真实模型的完整自动流程、Vivado/功能时序签核和实际扣费尚未验收。

默认设置调整后已重新构建并做浏览器请求拦截验证：打开面板不发送消息，相关复选框和占位说明均不存在；一次手动发送携带两个 `true` 标志、当前设计 JSON 和源码基准目录。测试响应来自本地替身，不消耗真实模型用量。

官方资料：[GA 公告](https://github.blog/changelog/2026-06-02-copilot-sdk-is-now-generally-available/)、[Python SDK 文档](https://github.com/github/copilot-sdk/tree/main/python)。上游 `main` 文档可能继续变化，本项目以固定版本及实际接口为准。

## 运行

解压后进入 `bd_prototype` 目录。以下命令使用 `python3`，可按本机解释器名称改为 `python` 或 Windows 上的 `py -3`。

```sh
python3 -m bdtool validate examples/counter_compare.json
python3 -m bdtool generate examples/counter_compare.json -o build
python3 -m unittest discover -s tests -v
```

本机是 Windows，`python3` 指向不可用的 Microsoft Store 别名。本次实际使用已安装的 Python 3.14.5；在工作区根目录的 PowerShell 中可运行：

```powershell
$Python = '.\.venv\Scripts\python.exe'
& $Python -m bdtool validate examples/counter_compare.json
& $Python -m bdtool generate examples/counter_compare.json -o build
& $Python -m unittest discover -s tests -v
```

先按上面的首次运行步骤创建虚拟环境；也可替换为其他 Python 3.10+ 解释器。RTL 核心无需 `pip install`。

[build/example_bd.v](build/example_bd.v) 实例化计数器和比较器。[build/example_bd_wrapper.v](build/example_bd_wrapper.v) 只根据 BD 的外部端口实例化 `example_bd`。重新运行生成命令会更新输出目录里的同名产物。

校验失败时 CLI 返回状态码 1，并向标准错误输出定位信息；成功返回 0。生成前会完成整个设计的校验，非法设计不会覆盖现有产物。输出也不能覆盖设计 JSON 或已登记的 RTL 源文件。生成器保留 JSON 声明顺序、使用 LF 换行且不加入时间戳，相同输入重复生成得到相同字节内容。

## 从一条连线看数据模型

完整示例的外部端口为 `clk`、`rst` 和 `match`。`counter_0` 与 `compare_0` 是实例名，分别引用 `counter` 和 `compare_eq` 模块定义；两者的 `WIDTH` 为 8，比较阈值为 9。

```json
"count_bus": ["counter_0.count", "compare_0.value"]
```

这是 `nets` 下的一项。`counter_0` 和 `compare_0` 分别引用两个模块定义。它们的 `WIDTH` 均为 8。校验器根据元数据将 `counter_0.count` 认作驱动端，将 `compare_0.value` 认作接收端，解析二者的范围为 `[7:0]`。生成结果是一根 `wire [7:0] count_bus;`，两处端口绑定分别是 `.count(count_bus)` 和 `.value(count_bus)`。

结构模块中的对应片段如下，完整产物见上面的文件链接：

```verilog
wire [7:0] count_bus;

counter #(.WIDTH(8)) counter_0 (
	.clk(clk_net), .rst(rst_net), .count(count_bus)
);
compare_eq #(.WIDTH(8), .THRESHOLD(9)) compare_0 (
	.value(count_bus), .match(match_net)
);
```

`count` 和 `value` 是两个模块各自的端口名，`count_bus` 是 BD 内的网络名，不要求同名。时钟、复位分别通过 `assign clk_net = clk;`、`assign rst_net = rst;` 进入 BD；比较器的输出通过 `assign match = match_net;` 导出。

`@clk` 表示 BD 的外部端口，`counter_0.clk` 表示实例端口。外部输入与实例输出可以驱动网络。外部输出与实例输入接收网络信号。一个网络接收端可有多个，每个端点属于一个网络。生成器用 `assign` 将外部端口与内部网络连接。必接项是实例输入和 BD 外部输出。未使用的实例输出可以悬空。

| JSON 字段 | 内容 |
| --- | --- |
| `name` | 结构模块名，封装名自动加上 `_wrapper` |
| `modules` | 按 RTL 模块名索引的定义，每项包含 `sources` 和 `ports`，可选 `parameters` |
| `ports` | BD 外部端口，按端口名索引 |
| `instances` | 按实例名索引，每项指定 `module`，可用 `parameters` 覆盖默认值 |
| `nets` | 按网络名索引，每项列出端点。顺序用于稳定输出，驱动方向根据端口推导 |

端口包含 `direction`，可选 `range` 和 `signed`。省略 `range` 表示标量，`[0, 0]` 表示单比特向量。`[0, 7]` 和 `[7, 0]` 保留各自的顺序。网络两端须有相同的范围和符号约定。需要改变位序、宽度或符号时，可以接入显式转换模块。

模块参数是带 `default` 的有符号 32 位整数，可选 `min` 和 `max`。范围两端可以是整数或表达式，如 `["WIDTH - 1", 0]`。表达式支持整数、参数名、括号、加减乘。求值使用 AST 白名单，超出范围或参数未定义会报错。源文件路径相对于 JSON 文件目录。

实例参数取模块默认值，再应用该实例的覆盖值；两个实例可以复用同一模块定义而有不同参数。参数值本身必须是整数，不支持参数间引用或 Verilog 常量字符串。范围表达式不允许函数调用、属性访问、除法、移位或任意代码执行。外部端口没有模块参数作用域，应填写具体范围或不引用参数的表达式。

校验还会拒绝非法标识符、重复 JSON 键、未知字段、未知参数、端点重复连接、无驱动或多驱动网络、端口/实例/网络之间的名称冲突，以及模块参数与端口同名。错误带有 `modules.*.ports.*`、`instances.*.parameters.*` 或 `nets.*` 等定位信息。

原型以手工元数据作为 RTL 模块接口描述，只检查源文件存在性，不自动解析 HDL。元数据与实际源码的端口、参数是否一致，由 HDL 编译进一步验证。设计图允许时序反馈：例如寄存器输出同时连接自身数据输入与外部输出。这里不做图的拓扑排序，也不把图中有环等同于非法电路；组合环路分析需要独立的 RTL 分析能力。

## 两层生成与核心入口

| 层次 | 所需输入 | 生成内容 |
| --- | --- | --- |
| BD 结构模块 | 模块元数据及源文件位置、实例及已解析参数、外部端口、已校验网络 | 外部端口声明、内部 `wire`、外部端口 `assign`、参数绑定和 IP 实例 |
| 顶层 wrapper | BD 模块名，以及已解析的外部端口名称、方向、范围和符号性 | 同形状的顶层端口，以及整个 BD 的一个实例 |

wrapper 不需要知道计数器、比较器或内部网络的细节，也不需要读取 RTL 源码。MVP 将实例参数具体化在 BD 内，wrapper 没有额外的参数透传。其内部实例名默认是 `bd_i`，若与外部端口冲突则追加下划线避让。两层都不自动插入 IOBUF 或做位宽转换。

现有可复用入口均位于 [bdtool.py](bdtool.py)：

- `validate_design(data, base_dir) -> Design`：接受可编辑的 JSON 字典及源路径基准目录，返回解析后的设计快照；失败抛出 `DesignError`，不写文件。
- `load_design(path) -> Design`：读取磁盘 JSON、拒绝重复键，并以 JSON 所在目录调用校验。
- `render_verilog(design) -> dict[str, str]`：纯文本生成，返回两个文件名到内容的映射，不写文件。
- `main(argv) -> int`：CLI 入口，串联加载、校验、生成和输出保护。GUI 保存设计后可以在工作进程中调用同一条 `generate` 命令。

## 修改参数并仿真

默认阈值为 9。将 `instances.compare_0.parameters.THRESHOLD` 改为 19，再运行生成命令，结构模块中的 `.THRESHOLD(19)` 随之更新。

只修改设计 JSON，不编辑生成代码。验收测试会在临时目录中完成 9 到 19 的修改与重新生成，断言 BD 文件只有对应参数绑定发生变化、wrapper 字节不变，并分别编译仿真。工作区中的基准示例仍保留阈值 9。

若本机有 Icarus Verilog，测试套件自动验证复位后的输出、每个周期的比较结果、首次匹配以及 8 位计数器回绕后的匹配。若没有 `iverilog` 或 `vvp`，只跳过 HDL 测试并明确显示原因，Python 测试仍运行。

先检查原始 RTL 加生成模块能够按 Verilog-2005 编译：

```sh
iverilog -g2005 -s example_bd_wrapper -o build/sim examples/rtl/counter.v examples/rtl/compare_eq.v build/example_bd.v build/example_bd_wrapper.v
```

再编译带行为检查的测试台并运行基准示例：

```sh
iverilog -g2012 -s tb -o build/sim examples/rtl/counter.v examples/rtl/compare_eq.v build/example_bd.v build/example_bd_wrapper.v examples/rtl/tb.v
vvp build/sim +threshold=9
```

这里的 `-g2012` 让测试台使用 `$fatal`。阈值改为 19 后，重新生成并编译，再传入 `+threshold=19`。生成代码本身采用 Verilog-2005 的结构写法。

## GUI 模型与核心接口

已实现的界面由左侧模块列表、中间实例画布、右侧参数/端口属性表和诊断区组成，提供保存、校验和生成操作。画布和命令行使用同一个硬件设计 JSON，不维护另一套网表或 Verilog 模板。

| 界面操作 | 设计模型更新 |
| --- | --- |
| 注册已有 RTL 模块 | 在 `modules` 添加源路径、参数默认值和手工端口元数据；MVP 不自动解析 HDL |
| 从模块列表拖入节点 | 选择模块定义，以不冲突的名称创建 `instances` 项，坐标写入独立布局数据 |
| 编辑实例参数 | 修改实例的 `parameters`，调用核心重新解析端口并校验整个设计，不在前端另写位宽求值器 |
| 从驱动端拖线到接收端 | 新建一项 `nets`，或把接收端加入该驱动端已有的网络，避免把扇出误建为两个驱动网络 |
| 将端口设为外部 | 新建 `ports` 项并将 `@端口名` 加入网络；实例输入对应外部输入，实例输出对应外部输出，范围和符号性保持一致 |
| 删除连线或实例 | 同一编辑事务中移除关联端点；删除空网络，暂时不完整的网络由诊断区标记 |
| 重命名实例或外部端口 | 同时更新相应字典键和所有网络端点引用；实例重命名还更新布局键 |
| 拖动节点、缩放画布 | 只修改布局数据，不修改硬件 JSON，也不改变生成 HDL |
| 预览或导出 HDL | 前端调用本地 API，由服务端调用 `validate_design`、`render_verilog`；导出复用核心的输出保护函数 |

独立布局 JSON 的最小示例为：

```json
{
	"design": "example_bd",
	"nodes": {
		"counter_0": {"x": 120, "y": 100},
		"compare_0": {"x": 420, "y": 100}
	},
	"viewport": {"x": 0, "y": 0, "zoom": 1}
}
```

这份布局数据不传给校验器。可编辑硬件字典是保存和撤销/重做的对象；`Design` 是每次校验得到的解析快照，不能用它覆盖原始模块元数据。GUI 允许保存尚未连完线的草稿，但有校验错误时禁用 HDL 导出，保留最后一次成功产物。

已实现的 HTTP 接口位于 [bdgui.py](bdgui.py)：

| 接口 | 行为 |
| --- | --- |
| `GET /api/state` | 读取启动设计、布局、诊断与当前会话请求令牌 |
| `GET /api/designs` | 列出示例与已保存设计 |
| `GET /api/load?path=...` | 读取工作区内的指定设计，路径基准随设计一起返回 |
| `POST /api/inspect` | 接受 `design`、`base_dir`，返回 `valid`、诊断、已解析接口和 HDL 预览；草稿中可独立解析的接口仍可显示 |
| `POST /api/save` | 接受硬件设计、布局、源路径基准和目标路径，保存并返回可重新打开的设计 |
| `POST /api/generate` | 严格校验当前设计后生成两层 HDL，返回代码及实际输出路径 |

前端编辑操作集中在 [web/src/model.js](web/src/model.js)，通过浅层交互检查提供即时反馈。位宽、参数、端点、名称及连接合法性最终都由 Python 核心裁定；前端没有实现第二套 Verilog 模板或表达式解释器。

诊断区显示 `DesignError` 的原始文本，并利用其中的实例、端口或网络路径定位画布对象。当前核心返回首个错误，不提供多错误聚合。拖线、改参数、保存和生成共用这些校验规则。

## MVP 边界

只支持普通单向端口和整端口直接连接。截断、补位、拼接、位序或符号性变换应通过显式 RTL 适配模块表达，不能靠修改网络名称或隐式 Verilog 转换完成。AXI 接口分组、IP-XACT 导入、任意 HDL 自动解析、复杂层次、组合环路分析和器件专用 IOBUF 均为后续扩展。本次未运行 Vivado 综合或实现，不宣称具有 Vivado IP Integrator 的完整能力。

## CLI 核心验证记录

以下是 GUI 扩展前的核心验收记录；当前包含 GUI 的全量结果见上面的“GUI 验证”。

2026-11-04 在本机 Windows、Python 3.14.5、Icarus Verilog 11.0 环境实际执行：

| 检查 | 结果 |
| --- | --- |
| CLI `validate` | `Valid: example_bd (2 instances, 4 nets)` |
| CLI `generate` | 生成并核对 BD 与 wrapper，参数为 `WIDTH=8`、`THRESHOLD=9` |
| Verilog-2005 编译 | 原始 RTL 与两份生成代码编译通过 |
| 带测试台的基准仿真 | `PASS: threshold=9 and counter wraparound` |
| `unittest discover -s tests -v` | 9 项测试全部通过，无跳过；包含阈值 9 和 19 的 HDL 编译及行为仿真 |

18 个无效设计子用例覆盖不存在的端点、位宽不匹配、多驱动、零驱动、未解析参数、未连接输入和外部输出、重复连接、参数类型/范围、未知参数、非法标识符、名称冲突和表达式白名单。另外检查了默认参数、可悬空输出、重复 JSON 键、源文件覆盖保护、wrapper 实例名避让、标量与单比特向量区别、升序范围、符号性、扇出和合法时序反馈。

先前测试在工作区内清理临时目录时出现过 `WinError 32`。本次将测试临时目录移到系统临时区，独立 HDL 用例和完整测试均通过；没有忽略清理错误，也未确定当时具体的占用进程。测试中的 CLI、编译和仿真子进程均设置了 30 秒超时。
