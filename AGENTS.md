# BD Studio Agent Instructions

本文件是仓库内执行入口。先读本文件，再读对应阶段报告与 docs/DECISIONS.md；不得从编辑器聊天记录寻找执行规则。以下第 0 节逐字保留 IMPLEMENTATION_PLAN.md 的原文，后续明确授权与本文件补充约束同时适用。

## 0. 执行规则（必须遵守）

1. **先摸清仓库再动手。** Phase 0 的产出（`docs/ARCHITECTURE_NOTES.md`）是后续所有任务的依据。本文件中出现的路径、模块名都是**示意**，以真实仓库结构为准；对不上时在 `docs/DECISIONS.md` 记录你的映射，不要停下来等人。
2. **不允许破坏现有行为。** `examples/counter_compare.json` 生成的 Verilog 必须保持逐字节不变（Phase 0 建立 golden 测试），除非任务明确要求改变，并同步更新 golden 与迁移。
3. **每个任务一个提交**，提交信息格式：`P1.2: <一句话>`。每个任务结束时必须：测试全绿、lint 通过、更新相关文档。
4. **校验器、`apply_ops`、表达式求值器、Verilog 解析器先写测试再写实现。**
5. **测试不得依赖网络或真实 LLM。** LLM 调用一律通过可替换的 `LLMClient` 接口，CI 中使用录制回放（cassette）或 mock。
6. **文件格式有改动就升 `schema_version` 并提供迁移**，旧示例文件必须仍能打开。
7. **所有用户可见文案走 i18n 资源文件**（现有界面是中文，不要硬编码字符串）。
8. **安全底线**：绝不 `eval`/`exec` 用户或 AI 提供的任何字符串；所有标识符经过 Verilog 合法性与关键字检查；上传文件限制大小与数量。
9. 不确定的设计决策：选保守方案，写入 `docs/DECISIONS.md`（背景/选项/决定/理由），继续推进。**唯一需要停下来的情况**：必须做不兼容的数据破坏且无法迁移。
10. 每个 Phase 结束输出 `docs/reports/phase-N.md`：完成了什么、没完成什么、已知问题、下一步建议。

### 任务格式
每个任务包含：**目标 / 改动 / 验收**。验收条件全部满足才算完成。

## 当前约束

- 当前工作在 perf/2b-paired；只推送该分支，不合入 main。D050 已关闭，不以重复到绿替代稳定性度量。
- 每次稳定性与性能运行预先固定数量，保留全部结果、排除理由、trace 与状态附件；不调大超时，不加固定 sleep，不弱化/删除断言，不跳过用例。
- 性能目标仍为 <=10%。当前授权方法是 2000 实例、至少九对交错 A/B、配对比值中位数和四分位；负载硬界限与剔除规则先写 DECISIONS，剔除超过三分之一为无法验收。历史三对结果不是新方法验收。
- 不终止用户进程，不使用 sudo，不关闭 TLS 校验，不修改/提交/还原来源未确认的工作区改动。
- examples/sv/rtl/sv_register.sv 的 M 标记待用户确认；目前与 HEAD 原始字节一致，不能猜测未提交改动作者。
- 本期仅 AXI-Stream；不做第二期接口、W020-W022、真实模型调用或真实模型评测。AI/SDK 用 mock，测试不得发送 RTL 正文。
- 旧 golden 与原 RTL 逐字节保留；不得用换行/路径归一化掩盖 HDL 差异。独立期望的冻结哈希规则见 D050 前置记录，不重录预期。

## 报告入口

| 阶段 | 文件 |
|---|---|
| 架构依据 | [docs/ARCHITECTURE_NOTES.md](docs/ARCHITECTURE_NOTES.md) |
| 原始计划 | [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) |
| 设计决定 | [docs/DECISIONS.md](docs/DECISIONS.md) |
| Phase 0 / 1 | [docs/reports/phase-0.md](docs/reports/phase-0.md)、[docs/reports/phase-1.md](docs/reports/phase-1.md) |
| Phase 2A / 2B.1 | [docs/reports/phase-2a.md](docs/reports/phase-2a.md)、[docs/reports/phase-2b-1.md](docs/reports/phase-2b-1.md) |
| Phase 3 / 3.5 | [docs/reports/phase-3.md](docs/reports/phase-3.md)、[docs/reports/phase-3.5.md](docs/reports/phase-3.5.md) |
| Phase 4 / 4B / 5 | [docs/reports/phase-4.md](docs/reports/phase-4.md)、[docs/reports/phase-4b.md](docs/reports/phase-4b.md)、[docs/reports/phase-5.md](docs/reports/phase-5.md) |
| 本地 Linux 复现 | [docs/local-linux-ci.md](docs/local-linux-ci.md) |

## 验证命令与工具

完整门禁为 `python scripts/check.py`，包括 Ruff、Python/golden/语义、固定 HDL 工具、离线 AI、前端 lint/typecheck/单测/build、两个顺序浏览器分片和旧语义基准。进程 300 秒、Playwright 单条 120 秒/断言 20 秒、HDL 工具 30 秒不变。

```text
python -m pytest -q tests/golden tests/semantics
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web run test
npm --prefix web run build
node web/node_modules/playwright/cli.js test --config web/playwright.config.js --grep "AXI-Stream hierarchy confirms" --repeat-each 10 --workers 1
python -m bdstudio.ai_eval --client mock --suite interfaces --report build/ai-eval-interfaces
```

Windows 使用已配置的 Python 完整路径及 npm.cmd；Linux 使用外部固定工具目录，不混用 Windows 可执行文件。原语义绝对预算的非阻塞政策不代替本期相对性能验收。

| 工具 | 固定版本 |
|---|---|
| Linux Node | 24.22.3 |
| Playwright / Chromium | 1.58.2 / 145.0.7632.6，revision 1208 |
| 从零 Linux CPython | 3.14.10，python-build-standalone 20261124，正常 GIL |
| OSS CAD Suite | 2026-11-17 |
| Verilator | 5.055 devel，v5.054-302-g2d6aba6ed；允许包自带 `(mod)` |
| YoWASP / Yosys | 0.70.0.0.post1259 / 0.70，git 28ba3cb92 |
| YoWASP runtime / wasmtime | 1.96 / 47.0.1 |

Linux 便携套件使用官方 bin 包装器，不把 OSS CAD Suite 的 libc 注入全局 LD_LIBRARY_PATH。版本、归档哈希及外置安装步骤集中维护在 Linux 复现入口；规则有变化时同时更新本文件和 DECISIONS。