# 版本化设计与语义接口

## P5.1 规范保存与旧项目迁移

逻辑文件与 `.layout.json` 分离；保存时递归稳定 JSON 键顺序，根及子设计的 instances/nets 按 name 排序，project_ips 按 id/version 排序，UTF-8/LF、两空格缩进、末尾换行。
端点、参数声明、源码依赖数组和 concat 成员不重排。规范化返回副本，源数据不变；只有实际字节变化的文件进入原有暂存/替换写入，全部目标仍先做工作区和输入文件保护检查。
这只改变序列化顺序，没有新增逻辑字段，所以仍使用现有设计 v2/v3/v4 和布局 v1；不伪造新的结构版本。新保存文件的 HDL 排列可随规范顺序变化，原示例文件及旧 CLI golden 不变。

`migrations/` 兼容两种旧单文件入口：逻辑对象内嵌 layout，或 v1 项目容器包含 design/layout。内嵌逻辑可为无版本/v1 旧模块字典或 v2/v3/v4；检查来源后在内存升级为现有设计 v4，布局升级为 v1。普通非内嵌文件保持既有响应格式。
打开不会写回源文件，显式保存才拆分。独立布局文件与内嵌布局若规范化后不同，则报 migration_layout_conflict；null、重复键等损坏布局不会当作缺失处理。
测试覆盖历史示例副本、源路径重定位、层次与拼接保真、纯布局保存，以及两人修改不同实例后实际执行 git merge-file 的无冲突合并。

## 设计 v2

旧无版本文件及旧 CLI/API 保持兼容，不自动写回原文件。design.schema.json 支持普通端点 v2 和表达式端点 v3：

```json
{
  "schema_version": 2,
  "name": "demo",
  "ports": {"clk": {"direction": "input"}},
  "instances": [{"name": "counter_0", "ip": {"id": "counter", "version": "1.0.0"}, "params": {"WIDTH": "4 * 3"}}],
  "nets": [{"name": "clk_net", "endpoints": [{"ext": "clk"}, {"inst": "counter_0", "port": "clk"}]}]
}
```

此片段仅展示格式，未连接复位或完整系统。实例和网络用有名数组，保留重复名称以便定位；
外部端口继续使用 direction/range/signed，标量与单比特向量、升序与降序范围不混同。
project_ips 可携带独立 v1 元数据快照，供旧项目迁移与重新打开使用；源码路径相对于设计文件。
保存会重定位路径，来源哈希不匹配、路径越界或同 id/version 定义冲突不能静默接受。

core.design.migrate(design, library) 返回副本；旧模块名必须在传入集合中唯一，缺失或歧义返回 E005。
空画布也保留项目模块目录。旧 CLI 仍只处理旧格式；v2/v3 使用新语义 API、GUI 或 Python 接口。

## 参数与角色

core.resolve.resolve(design, library) 接收 v2/v3 文档及 IpMetadata 集合，不读取源码、解析 RTL或调用旧校验器。
参数使用 core.expr.evaluate，支持依赖默认值、实例覆盖和表达式；结果遵守 32 位整数及元数据 min/max。
未知参数、循环依赖、非法类型或求值失败为 D002。宽度限制 1–65536，保留范围和符号性，范围与 width 声明不一致为 D003。
相同 IP/覆盖组合在一次调用内复用解析结果；没有跨请求的参数/端口结果缓存。

解析后的端口带原始角色、置信度、确认标记和复位属性。角色不经过旧 definition 转换，不自动确认，
本阶段不提供时钟域传播或复位域检查。某个实例参数失败不会丢弃其他实例的已解析接口。

## 服务与界面

- POST /api/semantic/inspect：JSON design/base_dir，沿用 Host/Origin、X-BD-Token 和 2 MiB 请求上限。
- 返回 valid、结构化 diagnostics、files、interfaces、parameters，以及迁移后的 document、画布显示用 canvas 和 metadata。
- 每条新诊断含 code/severity/location/message/params，可选 fix；界面以 code+params 资源渲染，message 仅作后备。
- 服务边界 bdsemantic.prepare 读取并校验来源；纯核心只处理内存元数据。IpLibrary.metadata_snapshot 不依赖丢失角色的 entries.definition。
- 原 /api/inspect 的字符串诊断不变。/api/load、save、generate 按文档版本分派，旧设计仍使用旧路径。
- 参数编辑显式升级当前草稿到 v2，不改原文件；表达式、解析数值与恢复默认值均可编辑/查看，修改和版本化文档同属一个 undo 步骤。
- 画布仍使用现有显示结构，但保存/生成/语义检查使用 v2 文档，不能把显示转换层用作规则输入。

## 独立诊断规则

core.semantic.validate(design, library) 返回 Diagnostic 列表；先 resolve，再运行 core/rules 下的独立规则，不读盘、不修改输入。

| 规则 | 检查 | 状态 |
| --- | --- | --- |
| E001 | 位宽、范围和符号性一致；可唯一推导的单参数修复 | 已实现 |
| E002 | 单驱动、接收端存在、端点重复归属 | 已实现 |
| E003 | 实例输入和外部输出连接完整 | 已实现 |
| E004 | 不存在或未解析的端点 | 已实现，包装 resolver 事实 |
| E005 | 缺失/歧义 IP 版本、同名 RTL 模块多版本冲突 | 已实现，包装 resolver 事实并检查版本并用 |
| E006 | 实例重复或与外部端口同名 | 已实现 |
| E007 | 网络重复或与实例/外部端口同名 | 已实现 |
| E008 | 标识符、关键字、端点引用名及生成模块冲突 | 已实现，复用原标识符规则 |
| W010 | 实例输出无接收端 | 已实现，不阻止生成 |

每条规则独立测试，至少三组触发和三组不触发用例；新增结构化诊断 golden 与原 P0 golden 分开。
点击诊断使用 location 选中节点或网络并缩放；非法网络仍以错误状态显示，避免无法定位。
重复名称草稿须先在 JSON 中明确修正，普通画布编辑不会将重复数组项静默合并。

POST /api/semantic/fix 接受 design/base_dir/diagnostic，只执行当前 validate 实际给出的 set_param 修复。
修复建议须匹配 code/location/params/fix，重新校验后必须严格减少错误集合且不增加其他错误，返回新草稿而不写盘。
客户端还核对编辑快照；用户请求期间的修改不会被覆盖。一次应用为一个 undo 步骤，过期/篡改/不安全修复返回 D006。
没有可证明的单参数修复时不显示修复按钮；不猜参数关系，也不提供任意 ops 执行入口。
W020/W021/W022 与协议接口属于 2B，本轮未实现。

## P2.3 连接表达式

首次应用连接设置升级草稿到 schema_version=3；也可使用
core.design.migrate(document, library, target_version=3) 显式升级，返回独立副本。
不提供有损降级；v2 拒绝表达式端点。已版本化文档默认保持原版本。

- 切片：`{"inst":"counter_0","port":"count","slice":[3,0]}`，外部端口可用 ext。
  必须在声明范围内、方向与原范围一致，索引为整数，不能把标量当向量。切片结果是无符号向量。
- 常量：`{"const":"8'd5"}`，仅接受显式宽度 1–256 位的 Verilog 数字字面量，不接受 X/Z、未定宽或任意代码。
- 拼接：`{"concat":[{"ext":"data","slice":[15,12]},{"const":"4'd5"}]}`，成员顺序即 HDL 高位到低位顺序。
  成员须全为驱动或全为接收端，常量只能作驱动；总宽度不超过 65536。
- 每个端点最多 256 个节点、16 层、每个拼接最多 128 个成员，非法表达式返回 D007。

E001 对表达式比较最终位宽和符号性，不要求切片规范化范围与声明范围相同，也不猜测参数修复。
表达式设计允许源端口扇出；E002 检查接收位区间重叠，E003 检查输入完整覆盖，允许互不重叠的分段赋值。
E004/E008 递归检查叶子引用，W010 使用实际源引用。无表达式时保留普通端点原有规则。

只有实际使用表达式才产生 assign 和避名冲突的临时端口网；普通 v2/v3 继续复用原渲染模板，HDL 字节不变。
实例端口可作切片接收端或拼接左值。示例 examples/semantic/connections.json 复用内置 bd_mux2，
新 tests/fixtures/semantic/connections.golden.json 固定 HDL、wrapper 和诊断；connections_tb.sv 验证实际输出。

连线属性提供端点编辑对话框，支持切片、常量及有序拼接成员。应用、取消、撤销均处理权威文档副本；
显示用常量/拼接节点不增加硬件实例。参数修改与实例/端口/网络重命名保留 AST；
不能用旧的整端口连线操作静默覆盖表达式，须经连接设置明确修改。保存、重开、生成均支持 v3。

## P4.3 层次设计 v4

v4 在根文档增加必需的 `subdesigns` 定义表，最多 200 个定义。每个值是无 `project_ips` 的 v3 子设计，名称须与键相同；所有叶级 IP 来源快照仍归根文档所有。
子设计通过原有 `ip: {id: 子设计名, version: "1.0.0"}` 引用，无隐式参数覆盖。定义可重复实例化，可引用其他定义，拒绝循环引用、超过 16 层、模块/生成文件命名冲突。
`migrate(..., target_version=4)` 返回独立副本，旧 v2/v3/无版本设计仍可打开；禁止有损降级。普通无层次设计的 HDL 字节不变。

`core.hierarchy.collapse_design(document, library, selection, name)` 自动将内部网络移入子设计，对跨边界网络建立保留方向、宽度、范围及符号性的端口。折叠前后均检查，失败不改变输入。
当前明确拒绝一个拼接端点同时引用分组内外的情况；须先显式拆分连接，不猜位序或静默改变 AST。域传播、协议校验和组合回路分析没有因此新增。

`POST /api/hierarchy/collapse` 接受 design/base_dir/selection/name，只返回候选文档和检查结果，不写文件。
`POST /api/hierarchy/inspect` 接受完整根文档和 scope 定义名，返回当前层接口/画布，但 valid、diagnostics、files 始终覆盖整个根设计。
子层诊断携带 `location.design`；任意层错误均阻止生成。点击诊断可跨层导航。子层视图不提供作用域不匹配的自动参数修复。
生成只为根设计输出 wrapper；每个子设计定义单独输出一次 `.v`。派生接口不作为真实源码加入 project_ips 或来源校验。

层次布局使用 `schema_version: 1`，根 nodes/viewport 之外增加扁平 scopes 表，各值是普通 nodes/viewport。旧无版本布局继续兼容。
导航不增加历史步骤；折叠、子层编辑分别是独立撤销步骤，保存和生成始终针对完整根设计。
超过 32 个端口的层次块默认摘要显示，两个代理锚点仅用于绘图，展开恢复真实端口。紧凑块间网络束保留原始网络列表，可逐条选择，不是电气合并。

格式成功结果最多缓存 16 个内容 SHA-256；内容变化重新检查，电气规则和来源完整性每次检查。一次检查内共享层次接口和已解析子设计，不跨请求缓存语义结论。
新示例和 golden 位于 examples/hierarchy 和 tests/semantics/golden/hierarchy；严格 Verilator lint 使用 32 位参数配置，避免原比较器的 8/32 位比较警告，未修改原 RTL 或关闭警告。

## 历史兼容验证

三个既有示例通过新语义接口生成的 HDL 均与原 golden 字节一致。参数测试禁止 resolver 文件访问，
禁止新核心调用 bdtool.validate_design。真实 HTTP 测试覆盖令牌、来源篡改、v2 保存/重开/生成和角色保留；
真实浏览器覆盖参数表达式、宽度标签、失配后修正、v2 引用、撤销和桌面/手机布局。

P2.1 完整验收：340 项 Python 测试、57 个子测试、34 项前端单测、5 项浏览器流程通过，
Ruff/ESLint/typecheck/build 通过，scripts/check.py 退出码 0。日志为本地 build/phase2-p21-recheck.log。

P2.2 完整验收：410 项 Python 测试、57 个子测试、34 项前端单测、7 项真实浏览器流程全绿，
日志为 build/phase2-p22-check.log。原 HDL/校验 golden 不变，新诊断 golden 严格按 UTF-8/LF 字节比较。
随后显式声明原有 strict=false 基线及 CSS 模块类型，项目 typecheck 与编辑器诊断均通过。

P2.3 完整验收（2026-11-12）：433 项 Python 测试、57 个子测试、36 项前端单测、10 条真实浏览器流程全绿，
Ruff/ESLint/typecheck/build 通过，scripts/check.py 退出码 0，日志 build/phase2-p23-check.log。
新示例 strict golden、Icarus 编译与行为仿真通过；原 golden 未修改。手机常量与桌面拼接截图已人工检查。

## P2.6 服务、防抖与基准

自动检查固定防抖 150ms，重复修改取消旧定时器和请求；迟到结果/异常不会覆盖当前检查状态。
validate 保持纯函数，每次只有一次 resolve，所有规则共享结果。参数/端口缓存与网络索引均限定单次调用。
ValidationChanges 提供 instances/nets/external_ports/library_changed 提示字段；当前不使用提示缩小范围，仍返回完整结果，增量实现留 Phase 4。

可复用基准（生成开销、源码 I/O、HTTP 和前端渲染不计入校验时间）：

```powershell
.\.venv\Scripts\python.exe -m scripts.synthetic_design --instances 2000 --connections 4 --seed 20261112 --samples 11
```

门槛按用户评审改为至少 10 次的中位数 <300ms 且最大值 <600ms；默认 11 次，不剔除首样本。
生成器返回独立文档和完整 IpMetadata，可调整实例数、每实例连接数和 seed；源路径故意不对应文件，纯校验不读取它。
这不是可执行硬件仿真设计。范围与原始数据详见 DECISIONS D022。

2026-11-12 最终完整 Python 门禁 442 项 +57 子测试通过，仅性能失败（中位数 447.293ms、最大 762.031ms）。
独立 CLI 为 283.791/341.119ms，不能代替完整门禁。前端 38 项单测、10 条浏览器流程及 lint/typecheck/build 通过。
按用户限制停止进一步优化，P2.6 留在独立分支，性能验收尚未稳定通过；未实现 Phase 4 增量或 2B 域/协议功能。