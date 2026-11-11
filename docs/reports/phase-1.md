# Phase 1：P1.1-P1.7 实现完成

本地最终验收通过，P1.8 按要求不做。远端门禁以本次提交的 [Checks](https://github.com/lylintel/bd_prototype/actions/workflows/ci.yml) 为准，不将本地结果冒充远端成功。

Phase 2A 开工前复核（2026-11-11）：9c928e9 的 [原始运行](https://github.com/lylintel/bd_prototype/actions/runs/42988783259/attempts/1)
六项任务成功；另行完整复跑三次：[attempt 2](https://github.com/lylintel/bd_prototype/actions/runs/42988783259/attempts/2)、
[attempt 3](https://github.com/lylintel/bd_prototype/actions/runs/42988783259/attempts/3)、
[attempt 4](https://github.com/lylintel/bd_prototype/actions/runs/42988783259/attempts/4)。
每轮均含 Python 3.10/3.14 的完整门禁（各四条真实浏览器流程）和四项解析矩阵。
三轮全部成功，未修改测试或开启重试以掩盖不稳定；这是有限次稳定性证据，不是无故障保证。

| 内容 | 提交 |
| --- | --- |
| P0 开工前核验 | 0f54c92 |
| 解析器 spike 及兼容性调整 | 06c3847、14c9430、aa8c4b4 |
| P1.1 | bae64c2 |
| P1.2 | fcde8c5 |
| P1.3 | c7a4114 |
| P1.4 | 3044b6f |
| P1.5 | 7803092 |
| 独立 i18n 基础 | 98cc60f |
| P1.6 与浏览器 CI 镜像修复 | 4de8962、fe3858a |
| P1.7 | 9c928e962f43d12b9a45ede25dbaf5a28d7980cd |

## P1.1 交付范围

- 新增独立 ip.schema.json v1，Python 嵌套 frozen 数据类与 load_ip/save_ip/migrate_legacy_modules API。
- 自动转换现有 counter/compare_eq，也覆盖 uart_loopback；保留源码顺序、SHA-256、参数约束、符号性和升序/降序范围。原有设计格式及 RTL 生成器不变。
- 使用独立 jsonschema 依赖、离线本地 schema 引用与中文错误资源。源码哈希读取限于调用者指定的工作区；保存前校验并原子替换，不覆盖源码。

## 验证记录

- 测试先行：先确认缺少模块导致红灯，再实现；追加边界用例后，确实捕获末尾换行、NaN 和直接对象体积检查缺口，再修复。
- 54 项新测试覆盖 7 组合法 schema、25 组非法 schema，以及迁移、数据类往返、路径重定位、哈希、输入隔离、文件大小和写入失败保护。
- 7 项 P0 golden 保持逐字节一致；定向检查共 61 项通过。
- 2026-11-11 Windows/Python 3.14.5 完整执行 scripts/check.py：110 项 Python 测试、57 个子测试、19 项前端测试全部通过；Ruff、ESLint、应用类型检查和构建通过。原有 Vite use-client/包体积提示仍存在。
- 禁用 site-packages 后，`python -S bdtool.py validate examples/counter_compare.json` 仍通过，验证原 CLI 不依赖新增包。新增文件无编辑器诊断。
- 远端运行见 [Checks](https://github.com/lylintel/bd_prototype/actions/workflows/ci.yml)，以本任务提交的 Python 3.10/3.14 矩阵结果为准；本地测试不替代远端结果。

## P1.2 交付范围

- 开工前检查独立提交 0f54c92，补齐 P0.3 SHA/远端成功证据、明确 LF 和严格字节比较。
- spike 实际发现 pyslang 12.1.0 需要 Python 3.11+，Python 3.10 的两个组合安装失败。现改为可选依赖，并固定便携 Yosys。aa8c4b4 的四组合解析及两项完整 CI 均成功，记录见 DECISIONS D009。
- 正式解析器读取 Yosys 未简化 AST，提取 ANSI/非 ANSI、多模块、参数、localparam、inout、符号性和范围方向。localparam 保留为展开后的参数表达式，不固化位宽。
- 13 个夹具及人工 JSON golden；语法错误行号、路径、大小、工具缺失、超时和 warning 有测试。原 HDL golden 不变。解析 API 不写 IP 库。
- P1.2 本地 scripts/check.py 通过：124 项 Python 测试、57 个子测试、19 项前端测试，lint/typecheck/build 全绿。定向解析/golden 检查 18 项通过；四组合 CI 已接入正式夹具。

## P1.3 交付范围

- 安全 Pratt 求值器支持 Verilog 整数、参数、算术、比较、三目、$clog2 和受限逻辑/移位，无 eval/exec。
- 52 组合法表达式纳入独立字节 golden；覆盖超限、除零、未知参数、5000 组限时随机字符串及 Icarus 语义核对。
- 旧位宽入口已复用新求值器，保持最终 32 位约束；旧 HDL golden 不变。解析器 localparam 的参数覆盖与旧核心扩展语法有集成测试。
- P1.3 本地 scripts/check.py 全绿：211 项 Python 测试、57 个子测试、19 项前端测试，lint/typecheck/build 通过；表达式与旧 golden 定向检查 96 项通过。

## P1.4 交付范围

- 纯函数时钟/复位建议，包含置信度、极性和 unknown 时序；所有自动建议均未确认。
- 通用 _n 低置信度建议与明确名称区分；已确认角色不覆盖，原元数据不修改。
- 16 组名称规则纳入字节 golden，另有确认保护与批量不变性测试；四组合 CI 也执行角色测试。
- P1.4 完整本地门禁通过：234 项 Python 测试、57 个子测试、19 项前端测试，lint/typecheck/build 全绿；角色及旧 golden 定向检查 32 项通过。

## P1.5 交付范围

- CLI 与受保护 HTTP/NDJSON 共用版本库；支持文件/目录、递归、预览、许可声明、显式升版和逐项汇总。
- 源码哈希/接口签名幂等，旧版本不覆盖；原子发布/索引和独占锁，失败回滚本次新版本。
- 24 模块加损坏文件的批次纳入 golden，覆盖损坏/超限文件不中断其余项、请求边界、真实 HTTP token、跨文件依赖、源码/元数据完整性和 CLI 无库存储预览。
- 默认忽略用户导入库，保留原创 builtin 为受版本管理目录；导入面板尚未实现。
- P1.5 本地 scripts/check.py 全绿：256 项 Python 测试、57 个子测试、19 项前端测试，lint/typecheck/build 通过；库与旧 golden 定向检查 31 项通过。

## 独立 i18n 基础

- P1.6 前单独建立前端中文资源、插值、缺失键检查和原型隔离测试。
- 不迁移旧文案、不改变现有页面；后续新导入组件的文本受 ESLint 资源化规则约束。
- 独立基础设施完整门禁通过：256 项 Python 测试、57 个子测试、23 项前端测试，lint/typecheck/build 全绿；硬编码与资源调用的 lint 正负样例也已实际验证。

## P1.6 交付范围

- 资源化导入对话框：多文件/文件夹选择和有界目录拖放，逐模块选择、参数/端口/角色预览编辑、确认与部分失败状态。
- 库列表显示来源/版本/端口数，搜索名称/标签/端口；安全引用式拖放和单步 undo，同名不同定义不替换。
- 三条真实后端 Playwright 流程通过，覆盖目录批量导入、参数编辑、搜索、拖入、校验、撤销、手机取消与错误恢复、坏文件不阻断其他文件。桌面/手机截图已查看，无整体越界或确认按钮遮挡。
- 原有设计/HDL golden 不变，测试使用临时工作区和随机端口，浏览器外网请求被阻断；新的浏览器检查已加入 scripts/check.py 和 CI。
- P1.6 最终完整门禁通过：256 项 Python 测试、57 个子测试、31 项前端单测、3 项 Playwright 流程，lint/typecheck/build 全绿。新增文件无编辑器诊断，已有依赖版本未升级。

## P1.7 交付范围

- 17 个原创 RTL、17 个独立自检 testbench 和 MIT 许可，覆盖计划中的全部基础类别；不使用 src/vendor 文件充数。
- 35 组参数变体的 Icarus 自检通过，全部单实例生成 wrapper 编译通过；新增计数器比较示例也通过实际仿真。
- 同一导入流水线生成版本化 ip.json、只读内置索引、完整 HDL golden 与新示例；私有导入索引不覆盖内置目录，源码/接口变化要求升版。
- 浏览器验收已扩展为四项，全部内置 IP 自动显示且可添加，不创建私有索引；原有三个用户导入流程也通过。
- 最终 scripts/check.py 退出码 0：303 项 Python 测试、57 个子测试、31 项前端单测、4 项真实浏览器流程，Ruff/ESLint/typecheck/build 全绿。本轮日志位于本地 build/phase1-final-check.log。
- 与 P0.2 提交 946e0df 直接比较，原 counter_compare、uart_loopback、examples/rtl、src/vendor 和两个原 golden 目录无差异。新增示例独立建立 golden，不重采集旧基准。

## 未完成与限制

- P1.8 按用户要求暂不做；Phase 2 及后续阶段未提前实施。
- width/default 在元数据中仍是字符串；可显式使用新求值器，但加载不会自动修改表达式。原生成器仍不支持 inout 或新增的协议接口，v1 interfaces 必须为空。
- 许可证缺失记 NOASSERTION；角色只能作为未确认建议。单独 load_ip/save_ip 不重新读取源码校验哈希，版本库会在生成旧模型定义时核对来源；复杂依赖版本约束仍未实现。
- 安装依赖需要网络，测试不需要外网或真实 LLM。旧 RTL CLI 继续不依赖额外 Python 包。
- 原创 IP 仅完成数字仿真与结构编译，未完成目标器件综合、CDC、时序、功耗或硬件签核。UART、SPI、RAM、AXI-Lite 的具体范围和复位限制见原创 IP 清单。

## 下一项

下一阶段为 Phase 2 的结构化语义诊断与接口能力，本轮未提前实施。已有功能见 [IP 元数据](../ip-metadata.md)、[RTL 解析与导入](../ip-import.md)、[安全表达式](../expressions.md)、[i18n 基础](../i18n.md) 和 [原创 IP 清单](../../ip_library/builtin/README.md)。