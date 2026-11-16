# Phase 2A 实施报告

初版：2026-11-12；测量与兼容收尾更新：2026-11-16。范围：开工前补丁、P2.0、P2.1、P2.2、P2.3、P2.6。

## 2026-11-12 结论（历史）

P2.1/P2.2/P2.3 功能及兼容验收完成。P2.6 的纯校验接口、150ms 防抖、可复用基准与有限优化已提交独立分支，
但本地完整测试中的性能门禁仍失败，**不能宣布 Phase 2A 全部验收通过**。
按用户最后指示，已停止进一步优化；不减少设计规模、不放宽阈值、不跳过失败测试，增量实现留 Phase 4。
P2.4/P2.5（2B）、P1.8 与后续阶段没有实现。

## 提交记录

| 工作 | 提交 | 结果 |
| --- | --- | --- |
| 开工前补丁 | 18bfce4 | P1.7/CI 核实、三次浏览器 CI 重跑、Yosys 固定版本检测与安装说明 |
| P2.0 | 72da538 | 既有规则盘点、v2 格式迁移、独立新语义入口 |
| P2.1 | 936b0ae | 元数据参数/位宽/角色解析、版本化参数编辑 |
| P2.2 | 25ee86a | E001-E008/W010、定位、显式重新验证的修复 |
| P2.3 | b90fec4 | v3 切片/常量/拼接、UI、新 golden、Icarus 仿真 |
| P2.6 | f10d493 | phase2a-p26 分支，功能已实现，性能验收受阻 |
| P2.6 收尾 | 9c1b79d | 2026-11-16：新进程测量、批准的门禁策略、GUI 校验路径和历史往返验收 |

2026-11-12 时 main 保持 b90fec4；2026-11-16 按用户授权合入 P2.6 收尾。P1.7 与三次重跑证据沿用 [Phase 1 报告](phase-1.md)。
新旧规则边界见 [P2.0 基线](../phase2-baseline.md)，格式/API 见 [设计语义](../design-semantics.md)。

## 最终规则表

| 规则 | 原能力与本轮处理 | 最终状态 |
| --- | --- | --- |
| E001 | 复用位宽/范围/符号约束；参数传播、表达式最终形状、有限参数修复 | 已实现 |
| E002 | 复用单驱动/端点归属；增加切片接收区间重叠检查 | 已实现 |
| E003 | 复用必要输入连接检查；增加切片全位覆盖 | 已实现 |
| E004 | 包装 resolver 引用解析事实，递归检查表达式叶子 | 已实现 |
| E005 | 补齐 id/version 缺失/歧义、定义冲突及同名 RTL 多版本并用 | 已实现 |
| E006 | 有名数组保留并诊断重复实例/外部端口冲突 | 已实现 |
| E007 | 复用网络重名及命名空间冲突 | 已实现 |
| E008 | 复用 Verilog 标识符/关键字策略，覆盖表达式引用和生成名称冲突 | 已实现 |
| W010 | 新增无有效接收端的输出告警，不阻止 HDL 生成 | 已实现 |
| W020/W021/W022 | 时钟域、复位极性与同步/异步检查 | 2B，未实现 |

每条 E/W 规则独立文件、至少三组触发与三组不触发测试。新诊断字段为 code/severity/location/message/params，
可选 fix；UI 通过 code+params 资源化，message 仅后备。旧 /api/inspect 与原 P0.2 校验文本不变。

## 连接与兼容

- resolve 使用完整 IpMetadata，保留角色；来源读取、哈希及路径检查留服务边界，不使用 entries.definition 作为新规则输入。
- v2 普通端点及 v3 表达式端点并存；显式迁移返回副本，不猜歧义旧模块名，不有损降级或自动覆盖原文件。
- 只有实际使用表达式才切换 HDL 路径；无表达式 v3 和旧示例继续逐字节匹配原 golden。
- [新示例](../../examples/semantic/connections.json) 同时覆盖切片、拼接和定宽常量，独立 golden 固定 BD/wrapper/诊断。
  Icarus 编译及 [行为 testbench](../../examples/semantic/connections_tb.sv) 检查切片值、拼接顺序、传播和常量输出。
- GUI 的参数、诊断定位/修复、切片、常量、拼接使用真实后端 Playwright；覆盖取消、撤销、手机弹窗与桌面布局。
  显示节点不是硬件实例；保存、重开、生成保留权威 AST，普通参数/重命名操作不丢失表达式。

## P2.6 数据

[生成器](../../scripts/synthetic_design.py) 可调整实例数、每实例连接数和固定 seed，返回文档和元数据，供测试与后续基准复用。
本轮使用 2000 实例、8000 网络、每实例 4 条连接、8 位端口、seed=20261112。
只测完整 validate（含一次 resolve 和全部规则），不含生成器、文件 I/O、HTTP、HDL 渲染；不剔除首样本。
这是结构基准，不是可执行 RTL 仿真设计。

```powershell
.\.venv\Scripts\python.exe -m scripts.synthetic_design --instances 2000 --connections 4 --seed 20261112 --samples 11
```

用户最终确认门槛：至少 10 次，中位数 <300ms 且最大值 <600ms。

| 最后一轮后检查 | 样本数 | 中位数 ms | 最大 ms | 结果 |
| --- | --- | --- | --- | --- |
| 聚焦语义/golden pytest | 11 | 495.550 | 809.706 | 失败，其余 126 项通过 |
| 完整 scripts/check.py 的 pytest | 11 | 447.293 | 762.031 | 失败，其余 442 项 +57 子测试通过 |
| 独立基准 CLI | 11 | 283.791 | 341.119 | 通过，不替代完整门禁 |

独立原始样本（ms）：218.159、336.725、341.119、274.413、294.283、245.874、299.894、250.501、335.472、283.791、192.734。
环境：Python 3.14.5 / Windows 11 build 26200 / Intel Family 6 Model 154 Stepping 3。
本地日志：build/phase2-p26-check.log、build/phase2-p26-benchmark.json。不同运行状态的波动原因尚未证实。

cProfile、已核实的组合缓存/索引、唯一追加优化轮次和预算建议全部记录在 [DECISIONS D022](../DECISIONS.md)。
没有在验证循环里进行 deepcopy、正则编译或 schema 重验；相同组合复用位宽和角色，所有规则共享同次解析。
`ValidationChanges` 预留实例/网络/外部端口/库变化提示，当前仍全量，不能声称已实现增量。

## 验证证据

- P2.3 完整本地门禁：433 项 Python、57 子测试、36 项前端单测、10 条浏览器流程全绿，lint/typecheck/build 通过。
- P2.3 main CI：[43150593745](https://github.com/lylintel/bd_prototype/actions/runs/43150593745)，b90fec4，成功。
- P2.6 本地完整门禁退出码 1，仅性能失败；Ruff 通过，新旧 golden 与功能测试通过。
- 被 Python 失败阻断的前端门禁已单独补跑：38 项单测、10 条浏览器流程及 ESLint/typecheck/build 全通过，相关编辑器诊断为空。
- P2.6 分支 CI：[43157754125](https://github.com/lylintel/bd_prototype/actions/runs/43157754125)，f10d493，六项作业全部成功：
  Python 3.10/3.14 的完整检查（含性能门禁和浏览器），以及 Linux/Windows × Python 3.10/3.14 的解析器检查。
  远端通过没有消除本地完整门禁的失败证据，不以此宣称本机预算已稳定满足；未进一步优化或合并 main。

## 限制与后续

1. 性能预算尚未稳定通过，不继续本轮调优。Phase 4 可基于变更提示、参数组合和端口/网络索引维护失效闭包；
   全局名称/IP 唯一性规则需全局索引或全量回退。先在固定规格 runner 独立记录分布，再评审预算，不能静默提高阈值。
2. 2B 优先基于已保留且未自动确认的 role 构建时钟/复位域，再实现 W020/W021/W022；不以命名猜测冒充 CDC 签核。
3. 2B 接口分组建议先 AXI-Stream/APB，再 AXI-Lite；本轮没有新增协议级连接或自动归组。
4. 仍不支持 inout 集成、任意 HDL 表达式端点、同名模块多版本链接；不是时序、综合、CDC 或板级签核工具。
5. 现有 Vite use-client/较大 chunk 提示仍在，未通过修改构建警告阈值掩盖；渲染性能属于后续工作。

## 2026-11-16 收尾

本机完整 scripts/check.py 已通过：453 项 Python、68 子测试、38 项前端单测、11 条真实浏览器流程，
Ruff/ESLint/typecheck/build 全绿；新进程性能中位数 298.538ms、最大 522.127ms。本次收尾相对已评审分支的 core 差异为空。
日志 build/phase2-p26-close-check.log，性能 JSON 为 build/performance.json。
收尾 CI [43813514485](https://github.com/lylintel/bd_prototype/actions/runs/43813514485) 六项全部成功。
Python 3.10.22/3.14.10 分别进行五次独立测量，十批全部在 300/600ms 预算内，维持阻塞而未降级；逐次表与实际机器信息见 D022 补充。
合入 main 的工作树再次运行完整本地门禁，仍为 453 Python +68 子测试、38 前端单测、11 浏览器全绿，
新进程基准中位数 288.602ms、最大 396.402ms，日志 build/phase2-main-merge-check.log。

用户批准调整测量/门禁，不再优化校验器：正式测量在新子进程中执行独立 CLI，每样本前 GC 收集，至少 11 次，
不删除首样本，预算仍为 300/600ms。本机超限告警，--strict-perf 可失败；CI 五次测量逐次写 summary，
任一次超限则仅预算步骤非阻塞，功能测试/测量异常不降级。归因原始数据与因果判断见 DECISIONS D022 补充。

### 校验路径对照

| 入口或显示 | 驱动路径 | 旧校验是否参与 GUI 状态 |
| --- | --- | --- |
| 首次 /api/state、打开 /api/load | Workspace.load → semantic_inspect → prepare → core.semantic.inspect_design | 否 |
| 保存后刷新状态 | save → load → semantic_inspect | 否 |
| 150ms 自动检查 | /api/semantic/inspect → 同一新语义路径 | 否 |
| 顶栏手动校验 | validateNow → /api/semantic/inspect | 否 |
| 顶栏通过/待修复、诊断面板 | 同一个 inspection 的 valid 与结构化 diagnostics，检查中有独立状态 | 否 |
| 参数、JSON、连接编辑和显式修复 | 新语义检查/修复后更新同一 inspection | 否 |
| /api/inspect、原 CLI 和 P0.2 基线 | 原 bdtool.validate_design/Workspace.inspect | 仅兼容，不用于 GUI 状态 |

真实后端 Playwright 新增同名 IP 冲突用例，证明旧接口通过并不导致 GUI 通过；首次加载即 E005，
顶栏待修复、诊断面板非 success、生成禁用，手动检查也不调用旧接口。未使用伪造校验响应。

### 历史夹具清单

这里的 v1 指无 schema_version 的旧设计，IP 元数据自身的 schema_version=1 不是设计 v1。

| 历史设计文件/夹具族 | 输入格式 | 已测试的往返 |
| --- | --- | --- |
| examples/counter_compare.json | v1 | 加载→显式迁移 v2/v3→保存→再加载→再次保存至更深目录 |
| examples/uart_loopback.json | v1 | 同上，包含 vendor 依赖路径 |
| examples/builtin_counter.json | v1 | 同上，包含内置 IP 版本与角色 |
| src/ip_catalog.json | v1 | 同上，保留空画布中未实例化的完整项目 IP 目录 |
| designs/web_demo.json + .layout.json | v1 | 同上，保留非默认 THRESHOLD=19 及独立布局 |
| examples/semantic/connections.json | v3 | 加载→同版本迁移→保存→再加载→深目录保存，保留全部表达式 |
| 上述 v1 的 v2 派生历史格式、参数表达式用例 | v2 | 完整文档/metadata/角色/参数/布局/诊断/HDL 对比 |
| tests/semantics/test_connections.py 五种历史场景 | v3 | slice、constant、concat、partial_sink、concat_sink 均加载→保存→再加载并保持 HDL |
| 非法 JSON/重复键/NaN/未知版本/非法形状 | 拒绝夹具 | 原拒绝测试留在 CI；不宣称非法输入可以成功无损保存 |

往返由 tests/test_bdgui.py 的历史夹具测试和既有参数/表达式测试执行，普通 pytest 即包含，因此随 CI 运行。
完整文档比较仅将源码相对路径解析为实际同一文件，并按 id/version 比较项目快照集合；实例、网络和表达式顺序不被归一化。
同时比较角色、参数、布局、诊断、解析接口及 HDL 字节，并验证原文件没有被写回。