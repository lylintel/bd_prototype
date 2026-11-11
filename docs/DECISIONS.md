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