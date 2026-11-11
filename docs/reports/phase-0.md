# Phase 0：基线与护栏

## 完成内容

- P0.1：核实 HTTP/NDJSON、设计/布局格式、IP 元数据、校验器、React 状态、Copilot 工具链与测试入口；实际运行启动、校验、生成、单测和构建。提交 243e826。
- P0.2：冻结两个现有示例的 BD、wrapper、校验结构；7 项 golden 测试覆盖真实 CLI 和单字符回归。先证明缺基准失败，再采集基准、证明正确输出通过。提交 946e0df。
- P0.3：添加固定开发依赖、Ruff/ESLint、应用 JS/JSX 类型检查、跨平台一键检查和 GitHub Actions。CI 覆盖 Python 3.10/3.14、Node 24，强制存在 Icarus。移除三个未使用导入，修复 DOM 类型和同义页签结构；原有包版本未升级。

## 验证证据

- Windows/Python 3.14.5：scripts/check.py 完整通过；56 项 Python 测试、57 个子测试、19 项前端单测；Ruff、ESLint、tsc 和 Vite 构建通过。
- 现有 RTL 生成器和示例数据未修改；golden 逐字节一致，无仿真跳过，无真实 LLM 调用。
- 浏览器冒烟：有效 example_bd、2 个实例、4 条连线和端口正常显示。独立启动命令使用 --port 0，不占用原服务端口。
- 远端记录：[GitHub Actions Checks](https://github.com/lylintel/bd_prototype/actions/workflows/ci.yml)。合入下一任务前，必须确认本次 P0.3 提交的两个矩阵任务都成功；本地通过本身不证明远端成功。

## 未完成及已知问题

- P1 至 P5 尚未实施；本阶段不宣称已有 Verilog 导入器、统一 IP schema、结构化诊断或 AI proposal 确认。
- Vite 仍提示 React Flow use-client 指令与大于 500 KB 的主包。性能/拆包属于后续阶段。
- 当前是完整应用 checkJs 的非 strict 基线，不等同于全部参数都有显式类型。第三方代码及声明不在本项目类型门禁中。
- ESLint 9 已提示停止支持，但当前 JSX 插件 peer 范围仍依赖这一代；后续应一起升级并验证。没有依赖漏洞报告，未用强制安装绕过 peer 限制。
- 原界面文案尚未整体迁移 i18n。P0 不新增交互文案，后续新界面必须先接入资源文件。

## 下一步

在 P0.3 远端 CI 通过后进入 P1.1：以独立版本化 IP 元数据兼容现有 modules，不直接更改旧设计格式；先增加有效/无效样例及迁移测试，并持续执行 golden。设计和决策依据见 [ARCHITECTURE_NOTES](../ARCHITECTURE_NOTES.md) 与 [DECISIONS](../DECISIONS.md)。