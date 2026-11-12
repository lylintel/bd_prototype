# 版本化设计与语义接口

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
相同 IP/覆盖组合在一次调用内复用解析结果；没有跨请求可变全局缓存。

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

## 兼容验证

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