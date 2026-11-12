# 实施决策

## D001：分任务执行并保留原格式

- 背景：实施计划覆盖多阶段，要求一次一个任务、逐任务验收/提交，且路径和模块名为示意。
- 选项：立即重构目录和格式；或先记录真实实现并锁定 golden。
- 决定：P0.1 仅文档和基线，P0.2 固定逐字节输出，后续增量映射。不改原示例，也不提前引入 schema_version。
- 理由：当前顶层校验拒绝未知字段，直接增加版本字段会破坏旧文件。

## D002：实际路径映射

| 计划中的概念 | 当前实现 | 后续处理原则 |
| --- | --- | --- |
| core/expr.py | bdtool._range_bound | P1.3 新解析器按测试驱动接入，不直接使用 eval |
| core/ops.py / apply_ops | bdworkflow.apply_operations | P3.1 保留兼容层并提供受版本约束的操作格式 |
| validate(design, library) | bdtool.validate_design(data, base_dir) | P2 分离文件解析与结构化诊断，不伪装成已存在 |
| instances[].params | instances 字典及 parameters | P2.1 迁移前保持当前格式，不同时维护无说明的两个真相 |
| ip_library | src/ip_catalog.json 加设计内联 modules | P1.1 兼容读取，P1.5 再落版本化存储 |
| LLMClient | CopilotBridge.sdk_loader + FakeClient | P3.3 再统一接口，当前测试不请求真实 LLM |
| 布局拆分 | 已有独立 .layout.json | P5.1 复用，排序/版本改动受 golden 和迁移约束 |

## D003：确认流程与数据保密的新旧要求

- 背景：此前用户明确启用自动应用与默认共享；新计划 P3.5 明确要求 proposal 确认，跨阶段项要求默认不发送完整 RTL。
- 决定：以新计划为后续目标，但 P0 不改变现有工作流；在 P3 任务中明确实施、测试、更新 skill 和说明。
- 理由：避免“摸底”提交夹带行为变化。最终不得用旧授权说明绕过新的确认要求。

## D004：无既有 lint 门禁的启动阶段

- 背景：仓库初始没有 lint/typecheck 配置，P0.1 只读运行时代码，P0.3 才建立 CI。
- 决定：P0.1/P0.2 如实记录缺失门禁，执行已有测试和 git diff --check；P0.3 配置真实 lint/typecheck 并补齐对应门禁。不得将编辑器“无诊断”冒充全仓 lint。
- 理由：不在前序任务中隐含实现 P0.3，也不为追求全绿而关闭将要增加的检查。

## D005：新文案和已有代码基线

- 背景：计划要求用户可见文案走 i18n，但现有组件及诊断大量硬编码。
- 决定：P0 文档和测试不引入新 UI。后续涉及新 UI 时先建 i18n 资源并迁移对应触及范围；不要在基线任务中全面改写现有界面。
- 理由：减少与当前任务无关的格式变更，维持测试可归因性。

## D006：P0.3 质量门禁与兼容性

- 决定：Python 使用固定版本 pytest/Ruff；前端保持 JavaScript，使用 TypeScript checkJs/noEmit 检查全部应用 JS/JSX，并使用 ESLint 检查应用及单测。未开启 strict/noImplicitAny，后续可逐步补类型；没有 ts-ignore/ts-nocheck 或排除应用文件。
- 依赖边界：maxNodeModuleJsDepth=0、skipLibCheck=true 只跳过第三方实现/声明检查。测试文件由 Node 实际执行和 ESLint 检查，不把故意无效输入当成应用类型错误。
- 局部修复：DOM EventTarget 经 Element 检查后访问 closest；页签使用同义对象替代混合数组；CSS 变量只允许 -- 前缀键。React Flow 同名 Handle 类型/值导出通过命名空间取值，不改第三方源码。
- lint：Ruff E9/F 与 ESLint recommended/JSX 使用规则，不混入全库格式化。ESLint 9 与当前 react 插件兼容，但安装器已提示版本停止支持，后续升级需一起验证 JSX 插件，不以强制忽略 peer 冲突解决。
- CI：GitHub Actions 在 Ubuntu、Python 3.10/3.14、Node 24 执行与本地相同的 scripts/check.py，依赖安装后检查离线运行。强制要求 Icarus，不把缺工具跳过 HDL 当通过。真实 CI 状态须单独核实，不等同于本地检查。

## D007：P1.1 独立 IP schema 与兼容迁移

- 背景：现有模块直接内联于设计 modules，使用 sources 数组、range 原始索引、signed 与参数 min/max；计划示例的 source/width 不足以保留这些信息。
- 选项：直接替换旧格式；或新增独立元数据 API 并显式迁移。
- 决定：新增根目录 ip.schema.json 和 bdip.py，采用 Draft 2020-12/jsonschema，不改旧 load_design、GUI 或生成器。schema_version=1 只属于新 IP 文件；旧设计不强行添加未知字段。requirements-ip.txt 单独声明依赖，开发依赖和 CI 包含它。
- 无损字段：额外有序源码放 additional_sources；port 保留可选 range/signed，parameter 保留 min/max。符号范围的 width 是比较/三目表达式，不按默认参数数值固化。原有源码、设计、golden 不改写。
- 来源边界：迁移要求显式 workspace_root，只哈希范围内的已登记源文件；未知许可证用 NOASSERTION，角色不猜测/不确认。load/save 仅处理元数据，不验证源码新鲜度。另存通过非序列化 base_dir 重写相对源码路径；失败不替换原文件。
- 有意推迟：表达式求值/默认值约束检查到 P1.3，角色建议到 P1.4，版本库和导入命令到 P1.5，协议接口到 P2.5。v1 interfaces 仅允许空数组，版本号仅三段发布号。具体字段、限制和 API 见 docs/ip-metadata.md。
- 安全与本地化：文件/对象上限 1 MiB，拒绝重复 JSON 字段、NaN/Infinity、非法标识符、关键字和正则结尾换行绕过。新领域错误统一 code/location，中文消息放 locales/zh-CN.json；不新增硬编码 UI 文案。

## D008：Phase 1 后续执行补充约束

- 2026-11-11 用户要求继续 P1.1–P1.7，P1.1 已通过并保留，P1.8 暂不执行。
- 开工前独立提交核验 P0.3 SHA/远端矩阵、LF 和 golden 严格字节比较；不改变既有 golden 内容。
- P1.2 前独立 spike，验证 Windows/Linux 与 Python 3.10/3.14 四组合的 pyslang 安装和真实解析；不支持的组合使用可选 pyslang 或 Yosys 主路径，不隐藏失败。
- P1.5 沿用现有受保护 HTTP/NDJSON 约定，不强制 multipart；P1.6 前先独立提交前端 i18n 基础，不迁移旧文案，所有新界面文案使用资源。
- P1.7 全部原创 RTL，每个附 testbench 并在 Icarus/CI 运行，不复制现有 vendor IP 充数。每项结束完整 scripts/check.py，通过后单独提交；新增夹具/示例也冻结预期输出。
- 开工前本地完整检查最终通过 112 项 Python 测试、57 个子测试和 19 项前端测试。首次遇到原 HTTP 测试 WinError 10053；该用例单独复跑与完整复跑均通过，未跳过测试、未修改 HTTP 代码，原因未确定。

## D009：P1.2 前 pyslang 跨平台 spike

- 固定 pyslang 12.1.0；当前 Windows/Python 3.14.5 已成功安装并解析原 counter。API 位于 pyslang.syntax.SyntaxTree 与 pyslang.ast.Compilation，不使用已移走的顶层旧 API。
- scripts/spike_pyslang.py 真实解析 ANSI/非 ANSI、多模块、参数、localparam、wire/reg/logic 夹具，比较端口名/方向/类型的 UTF-8 golden 字节，输出实际系统/Python/包版本。
- CI 增加 Windows/Linux 与 Python 3.10/3.14 四组合，明确要求可安装的二进制 wheel，任何安装/解析/字节差异都会失败；不允许 continue-on-error。原 Linux 完整检查同时保留。
- 决定：只有本 spike 提交的四项实际 CI 全通过，才采用固定 pyslang 为主解析器并开始 P1.2；否则将 pyslang 降为可选、用 Yosys 主路径并重新验证全矩阵。实时证据为该提交的 Checks，不用单机结果代替四组合证据。
- 新夹具 tests/fixtures/verilog/spike.sv 已有独立 golden；原有 HDL golden 不变。此 spike 只确认依赖/API/平台能力，尚不是正式导入器。
- 首次远端运行 42958799473 在 YAML 校验阶段失败，未启动任何 job：未引用的命令中冒号后接空格被解释为映射。改为 run 块文本，并新增本地 BaseLoader 语法检查；这不是 pyslang 安装失败证据。使用额外的 CI 修复提交保留已发布失败记录，不强制改写远端历史。
- 实际安装矩阵 [42959289371](https://github.com/lylintel/bd_prototype/actions/runs/42959289371)：Windows/Linux 的 Python 3.14 安装/解析均成功，两边 Python 3.10 安装失败。包元数据确认 pyslang 12.1.0 Requires-Python >=3.11。
- 最终策略调整：pyslang 单列 requirements-pyslang.txt 为可选后端，旧 Python 不强装；requirements-parser.txt 固定跨平台 yowasp-yosys 0.70.0.0.post1259、runtime 1.96、wasmtime 47.0.1（均支持 Python 3.9+）。Python 3.10 必须实际通过 Yosys，3.14 同时验证 Yosys/pyslang；不跳过解析、不删除组合。真实四组合转绿前仍不得进入 P1.2。
- Yosys 与 pyslang 产物分别有字节 golden；Yosys 原生 JSON 的端口范围已求值，正式解析器必须保留这个限制并拒绝或明确诊断无法无损导入的参数关系，不将求值后的范围伪装成原表达式。
- 最终验收：[42960020833](https://github.com/lylintel/bd_prototype/actions/runs/42960020833)，对应 aa8c4b4；Windows/Linux × Python 3.10/3.14 四项解析全部成功，两项完整检查也成功。Windows 3.10 实际执行 Yosys 用时 1m39s，不是安装后跳过。

## D010：P1.2 使用未简化 Yosys AST

- 经本机实际探测，read_verilog -defer -dump_ast1 保留参数表达式、localparam、端口顺序和源码行号，解决 write_json 求值后丢失范围关系的问题。
- 为保证 Python 3.10 与 3.14 输出相同，正式解析以固定 Yosys 为主，pyslang 保持可选，避免两个 AST 路径生成不一致的元数据。读取结构化节点记录，不自写 Verilog 语法解析器；不运行 elaboration/proc。
- localparam 展开为原参数表达式，不新增元数据字段，因此继续使用 P1.1 schema v1；不修改旧设计/HDL golden。无法表达的多维接口、数组或特殊类型必须给诊断，不退化成错误位宽。
- 拒绝预处理指令、限 1 MiB 源码/32 MiB AST/180 秒；暂存文件名和命令固定，源路径须在显式授权根目录内。错误位置回映输入 basename/行号，新消息走已有中文资源。
- 正式夹具 13 个，人工预期接口投影冻结在 interfaces.golden.json；四平台解析矩阵也运行正式夹具和原 HDL golden。
- P1.2 远端 [42964301456](https://github.com/lylintel/bd_prototype/actions/runs/42964301456) 对应 fcde8c5：六项任务全部成功，包括 Windows/Python 3.10 的正式夹具和旧 golden。

## D011：P1.3 有界整数语义

- Pratt 求值器位于 core/expr.py，旧 bdtool._range_bound 委托它，仍由原 _integer 检查最终 32 位索引；参数/设计 JSON 格式不变，不更新旧 golden。
- 使用有界数学整数而非完整 SV 四态位向量解释器。定宽数字截断并按 s 标志解释补码；幂左结合、一元高于幂、除法向零取整、余数跟随被除数，经 Icarus 核对。
- 长度 4096、token 2048、深度 64、整数 256 位，指数/移位 0–256；短路仅跳过求值，不跳过语法检查。固定种子模糊测试在独立进程限时执行。
- 表达式结果单列 golden，52 条合法值，非法输入与集成测试另行覆盖。IP schema 加载不自动解析默认值，P1.5 导入准备阶段再显式解析参数依赖。
- P1.3 远端 [42965496513](https://github.com/lylintel/bd_prototype/actions/runs/42965496513) 对应 c7a4114，状态 success。

## D012：P1.4 角色建议的置信边界

- 建议采用独立纯函数，不在解析时自动把角色确认为事实；后续导入预览显式调用。命中规则也始终 confirmed=false，同步/异步保持 unknown。
- 通用 _n 按计划给低有效复位建议，但仅 0.25 置信度，避免把数据/片选当成确定复位。确切名称/后缀分别为 0.95/0.9。
- 已确认角色完全保留，包括与名称不一致的用户判断；未知名称也不清除已有未确认角色。规则及保护行为都有测试和字节 golden。

## D013：P1.5 版本库与 HTTP/NDJSON

- 采用 JSON + base64 单文件上传、NDJSON 分项响应；沿用原 2 MiB 正文上限和同源/token 安全约定，不引入 multipart。浏览器批次按文件请求，解码后每文件 1 MiB、最多 200 个。
- preview/dry-run 不改变库和源文件；临时解析目录/引擎缓存不算业务产物，文档明确其磁盘 I/O。commit 再次解析并核对元数据，不将客户端预览当成可信源码。
- IpLibrary 为 CLI/HTTP 共用实现。新 index.json schema_version=1，版本目录不可覆盖；同哈希/签名跳过，变化要求显式递增版本。独占 .lock、目录原子发布、索引原子替换与失败回滚保留旧版本。
- 源码文件可含多个模块，索引保留规范路径，防止生成时重复编译；AST 模块引用和文件内依赖闭包带入所需源码。缺失依赖、已篡改源码/接口条目标记不可用。依赖暂取最新库版本，复杂版本约束留后续工程化。
- 编辑允许默认参数/角色/显示信息，禁止伪造实际模块或端口声明；参数表达式转为旧模型显式整数绑定。inout 元数据可入库，但不能绕过旧 BD 连接限制。
- 公开仓库默认忽略用户 IP 库和索引，仅原创 builtin 例外，避免意外发布用户源码。builtin 为保留存储名；库文件不通过新外部网络服务上传。
- 24 模块与一个损坏文件的持久夹具纳入 batch.golden.json；测试覆盖部分成功、递归、幂等、升版、参数确认、事务失败、源码完整性与真实 HTTP/CLI。
- P1.5 远端 [42969908142](https://github.com/lylintel/bd_prototype/actions/runs/42969908142) 对应 7803092，状态 success。

## D014：P1.6 前独立前端 i18n 基础

- 先单独提交资源/API/单测，不迁移旧界面，不改变现有页面显示。新资源使用 web/src/locales/zh-CN.json，t/hasMessage 提供命名插值与显式缺失检测。
- 不增加只能翻译半个页面的语言切换 UI；未知语言回退中文。前后端资源暂分开，避免让 UI 基础设施重写已有领域诊断。
- 后续导入组件放 src/ip，新增 JSX 文本和可见标签属性受资源化 lint 规则约束。真实模块名/端口名/版本是数据，不翻译；错误状态和命令标签必须用资源。

## D015：P1.6 界面与真实后端验收

- 复用现有模块侧栏、图标按钮、原生 dialog 和单步 undo；导入只写版本库，添加/拖放才修改当前画布。对话框打开时暂停画布快捷键，避免背景设计被误操作。
- 目录选择/拖放有深度和条目上限，坏文件按项显示且继续。源码标识只读，显示信息/参数/角色可编辑；端口编辑必须通过后端真实接口一致性检查。
- 拖放只传 id/version 引用，必须匹配当前目录快照和库条目，不能携带任意定义。同名不同定义拒绝覆盖，来源角标也须匹配实际定义。
- Playwright 固定 1.58.2，测试启动隔离工作区和随机端口的真实服务；通过 BD_PYTHON 继承一键检查解释器，只访问回环地址，无真实 LLM。浏览器安装属于准备步骤，运行测试不依赖外网。
- E2E 包含目录批量导入/参数编辑/搜索/拖放/校验/撤销、手机错误与取消、坏文件不压制有效文件。生成截图与报告忽略，不发布用户数据。现有模块/HDL golden 不改。
- P1.6 首次远端运行 42977037763 的浏览器安装失败：实际镜像已为 Ubuntu 26.04.1，Playwright 明确报告不支持 ubuntu26.04-x64；四项解析检查成功。将完整浏览器检查固定在受支持的 ubuntu-24.04，解析矩阵继续保留 ubuntu-latest/windows-latest。新增本地 CI 镜像约束测试，不跳过浏览器测试，也不强制绕过依赖检查。
- 修复提交 fe3858a 的 [42978722216](https://github.com/lylintel/bd_prototype/actions/runs/42978722216) 全部六项任务成功，含真实浏览器测试；耗时 1m56s。

## D016：P1.7 原创内置库

- 新写 17 个独立 RTL 和各自 testbench，2/4 路 mux 分列，不复制 vendor 实现。统一 MIT 许可，每份 IP 元数据带实际源码哈希、说明、标签、参数约束。
- 采用 builtin/id/version/src 与 tb.sv 的版本化布局。manifest 为配置源，ip_import.builtin 经过同一 IpLibrary 预览/确认流程生成 ip.json、只读 index、全部单实例 HDL 快照和新计数器比较示例。
- 库读取合并只读内置索引与私有索引，写入仅更新私有索引；不复制或覆盖发布索引。重复源码继续使用规范路径，保持原有用户数据优先。
- 内置更新需显式版本提升：源码哈希或接口签名变化时不能覆盖同版本。角色/说明是数据，SPI 的 cs_n 明确指定为未确认控制角色，不能因后缀就当成已确认复位。
- 35 组参数化 IP 自检、所有 wrapper 编译、新示例仿真、元数据/HDL 字节重建、版本保护和 GUI 全目录可用性共同验收。新增示例只单独生成其 golden，不重写原有两个基准。
- 范围约束：UART 为 8N1，SPI 为模式 0/8 位，AXI-Lite 为 32 位四寄存器且不实现 PROT 权限；异步 FIFO 协调复位，RAM 同址跨时钟冲突不保证。数字测试不等于器件 CDC/时序/硬件签核。

## D017：Phase 2A 开工前运行时保护

- 固定 AST 解码格式不能仅依赖安装文件。parse_file 每次核对当前解释器的 yowasp-yosys、yowasp-runtime、wasmtime 实际分发包版本；偏离返回 IP_PARSE_VERSION，缺包返回 IP_PARSE_TOOL，不静默降级。执行文件仍固定在同一解释器的 scripts 目录，不从 PATH 选择其他 Yosys。
- 版本契约为 0.70.0.0.post1259 / 1.96 / 47.0.1，安装方式见 ip-import.md。测试先复现三个偏离版本被错误接受，再修复并确认解析/旧 golden 25 项通过。
- P1.7 提交为 9c928e962f43d12b9a45ede25dbaf5a28d7980cd。远端运行 42988783259 原始及三次重跑 attempts 2/3/4 均成功，每轮两项完整检查包含浏览器，四项解析矩阵保留。链接见 phase-1 报告。
- 本地开工前 scripts/check.py 全绿：307 项 Python、57 个子测试、31 项前端单测、4 项浏览器流程。旧输出未修改。P2A 仅包含 P2.0、P2.1、P2.2、P2.3、P2.6，域图/协议接口留 P2B。

## D018：P2.0 新设计契约与解析边界

- 选择独立 design.schema.json v2，旧无版本格式作为 v1 兼容入口，不在打开时写回。实例使用有名数组及 ip:{id,version}/params；网络使用 name/endpoints 数组，端点为 inst/port 或 ext 对象。数组保留重复项，便于 E006/E007 诊断，而非解析字典时丢失。
- core.design.migrate 接受显式 IpMetadata 集合，无文件访问、不修改输入。旧 module 只有唯一候选才能迁移；无候选或多版本/重复候选返回带位置的 E005，不按最新版本或列表顺序猜。保留顺序、范围、符号性与参数覆盖。
- 可选 project_ips 携带项目作用域的 v1 IP 元数据快照，使从旧内联模块迁移的文件可重新打开；元数据独立校验。服务边界负责将来源路径重定位、检查哈希并合并版本库，冲突必须报错，不能覆盖角色。设计不再内联旧 modules 真相。
- 新 resolve(design, library) 与 validate(design, library) 只接受内存新元数据；旧转换只用于兼容加载或画布适配，不用于规则输入。解析一次后规则共享参数/位宽/角色，便于后续 2B。未确认角色原样保留。
- P0.2 校验字符串、旧 bdtool.validate_design/render_verilog/inspect 契约保持不变。新函数及新 API 返回 code/severity/location/message/params/可选 fix。诊断基础类型提前在 P2.0 提供，以便迁移错误从第一天就遵守同一契约；具体规则在 P2.2 实施。
- P2.3 使用连接表达式时才引入额外 HDL assign/临时网；纯端口新设计可复用旧渲染器的已解析数据结构，不经旧校验器。这不是将角色丢给旧模型后再校验。

## D019：P2.1 元数据解析与画布兼容

- core.resolve 是纯内存解析层，保留 IpRole，按实例解析参数与端口；同 IP/参数组合只在本次调用内缓存。32 位参数/索引约束沿用旧行为，端口宽度安全上限 65536。
- bdsemantic 与 IpLibrary.metadata_snapshot 负责来源文件、哈希、路径和版本库完整性；新规则不得调用旧 entries.definition 或 validate_design。旧内联模块的兼容加载仍可使用 P1.1 迁移工具。
- 新 /api/semantic/inspect 返回结构化结果；旧 /api/inspect 和原 golden 不变。生成只复用旧已解析数据结构与格式模板，测试用禁止旧校验器调用的桩核实边界。
- 现有画布显示快照和 v2 逻辑文档放入同一个历史状态。旧设计未编辑新功能前继续原格式；参数编辑或应用 JSON 后使用明确引用的 v2 草稿。服务保存/重新打开保留 project_ips 路径与角色，原文件不自动覆盖。
- E001 为参数联动验收的必要前置，在 P2.1 提供独立规则文件；其余规则及精确修复在 P2.2。当前生成保护不把未完成连接误报为可生成。新增界面全部采用 i18n，并扩展既有资源化 lint 范围。
- P2.1 首次完整运行出现一项失败标记，之后 pytest 触及 300 秒上限，未产生失败堆栈；缓存也未记录失败项。按进度附近单独执行内置 IP 42 项全通过，再启用首错即停/耗时统计完整重跑，340 项 Python、57 个子测试、34 项前端、5 项浏览器全通过。未改测试范围、未放宽时限；不能据此宣称首次问题原因已查明。

## D021：P2.3 版本化连接表达式

- 端点扩展另升 design schema v3，v2 保持普通端点限制；提供显式迁移副本，不在打开时写回、不允许有损降级。
- 复用 P1.3 求值器检查定宽常量，使用结构化 AST 处理切片/拼接，不解析任意 HDL 文本、不使用 eval/exec。
- 解析端点保留叶子引用与位区间；E002/E003 据此检查重叠与完整覆盖，允许合法源扇出及分段接收。角色不丢弃，域传播仍留 2B。
- 有表达式才启用临时端口网和 assign 渲染；没有表达式的 v3 也必须保持原模板字节。新示例/golden 独立，不更新 P0 基线。
- 显示投影可以扁平化叶子，权威文档不能。常量/拼接显示节点没有硬件实例身份；旧整端口操作不兼容时明确拒绝。
- 重启后重新执行核心、模型、类型检查和真实浏览器流程。最初浏览器测试点击了禁用指针事件的 SVG 文字；改为实际标签区域后切片/常量/拼接流程全绿，没有通过 force 点击绕过界面。

## D020：P2.2 独立规则与有限修复

- E001-E008/W010 分文件实现和测试，复用解析事实/原标识符规则；E004/E005 不重新解析 IP。参数、格式、来源等前置诊断使用 D 码，与电气规则分开。每条诊断均含 params，前端以 code+params 资源化，message 只作后备。
- 同一 RTL 模块的两个版本不能在同一设计中同时实例化：当前没有模块重命名/库命名空间链接，明确 E005，不偷偷选择一个版本。时钟域、复位域和协议规则仍留 2B。
- E001 仅在一个参数候选能够匹配目标形状、约束合法且不改变其他端口形状时提供修复。apply_fix 与 HTTP 修复入口只接受当前诊断中的实际建议，复制文档后再验证错误集合严格减少；不提前引入 P3 任意操作执行器。
- 前端诊断按 location 定位，不用消息字符串推断新诊断位置。客户端快照比较阻止异步修复覆盖并发编辑，一次应用一个撤销步骤。错误网络仍可见并可选中；重复实例/网络数组不能被显示字典静默合并。
- 完整门禁 410 项 Python、57 个子测试、34 项前端、7 项浏览器通过。新增诊断 golden 的 CRLF/尾换行差异被原始字节比较捕获，只格式化该新文件为 UTF-8/LF，未更改比较器或旧 golden。
- 期间编辑器对 App.jsx 报告 290 条严格模式/资源导入错误，而固定 TypeScript 5.9.3 的项目 tsc 通过。showConfig 确认原配置未启用 strict；显式设 strict=false 并补 CSS 类型声明后，两边均无错误。保持 D006 的既有非严格基线，没有降低已有门禁或升级依赖。