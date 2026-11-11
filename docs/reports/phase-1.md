# Phase 1：进行中

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

## 未完成与限制

- 本阶段整体尚未完成。P1.3–P1.7 未实施，P1.8 按用户要求暂不做；不宣称已有 GUI 导入器或扩充后的内置库。
- width/default 是表达式字符串，但尚不求值；原生成器仍不支持 inout 或新增的协议接口。v1 interfaces 必须为空。
- 许可证缺失记 NOASSERTION；不猜时钟/复位角色。load/save 不重新读取源码校验哈希。版本目录、去重和升版流程留待 P1.5。
- 安装依赖需要网络，测试不需要外网或真实 LLM。旧 RTL CLI 继续不依赖额外 Python 包。

## 下一项

P1.3：安全 Pratt 表达式求值器。P1.1 用法见 [IP 元数据说明](../ip-metadata.md)，P1.2 用法和限制见 [RTL 接口解析](../ip-import.md)。