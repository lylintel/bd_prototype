# Phase 2B：总线接口设计提案

状态：**AXI-Stream 范围已批准，实施中；未完成项不是当前能力**。日期：2026-11-23。评审修订以 D049 为准：先做 AXI-Stream；第二期 AXI-Lite/APB3 顺序待定，两者均不在本期。迁移契约集中在 [migration.md](migration.md)。不得新增时钟域规则 W020-W022，不调用或评测真实模型。

## 1. 范围与分期

目标是减少已知兼容接口的逐信号连线，同时保持可审计的端口级网表、错误定位、显式确认和旧 HDL 字节兼容。结构连接正确不等于协议行为、CDC、复位、时序或电气签核。

| 分期 | 内容 | 不包含 |
|---|---|---|
| 2B.1 | AXI-Stream 基础握手 profile；兼容性 golden 先行，再做元数据确认、接口连接、语义展开、确定性 HDL | APB3、AXI-Lite、任意总线推断、自动协议适配 |
| 2B.2 | 层次接口端口、UI 展开/折叠、信号级拆解、AI 接口提案与离线评测 | AI 修改共享子设计定义、跨层隐式寻址 |
| 第二期（顺序待定） | AXI4-Lite 或 APB3；须另行批准 | 本期不实现，AXI4 burst/ID、多 outstanding、互联仲裁、地址分配仍排除 |

全阶段不做：自动插入 CDC/FIFO/位宽转换、自动复位反相、AXI-Lite/APB bridge、IP-XACT、完整 SystemVerilog interface/modport 输出、组合环完整签核、厂商布局布线、真实 LLM 评测。复用现有信号端口和 Verilog/SystemVerilog 模板，不引入另一套 RTL 引擎。

当前事实：
- [../../ip.schema.json](../../ip.schema.json) 是 schema 1，interfaces 的 maxItems=0，不存在可直接填充的接口能力。
- [../../design.schema.json](../../design.schema.json) 支持 v2 普通端点、v3 slice/const/concat、v4 根定义表与 v3 子设计。
- [../../ops.schema.json](../../ops.schema.json) 与 [../../core/ops.py](../../core/ops.py) 是操作协议 v1，六类操作、四类端点，未知类型拒绝。
- [../../core/diagnostics.py](../../core/diagnostics.py) 提供 code/severity/location/message/params/fix；[../../core/generation.py](../../core/generation.py) 持有工程化输出和 source map。
- D046 的历史实现仅允许根层，与本次用户指定的“当前打开层”不一致。本期以后者为准：局部 ops 合回整根校验；共享子设计禁止 AI 修改，不隐式复制定义。

## 2. 接口定义与 IP 元数据

### 2.1 不可变协议定义

拟增加本地、版本化的接口定义注册表，定义文件 schema_version=1。定义具有 id、version、parameter constraints、signals、master_direction、required、width；不接受远程 URL、脚本或任意表达式求值器。宽度表达式只使用已有 Pratt 表达式子集和边界检查。

下例是单个规范定义的结构片段，并非完整 schema 或可直接导入的 IP：

```json
{
  "schema_version": 1,
  "id": "axi-stream",
  "version": "1.0.0",
  "profile": "ready-valid",
  "parameters": {"DATA_WIDTH": {"min": 8, "max": 1024, "multiple_of": 8}},
  "signals": {
    "tdata": {"master_direction": "out", "required": true, "width": "DATA_WIDTH"},
    "tvalid": {"master_direction": "out", "required": true, "width": "1"},
    "tready": {"master_direction": "in", "required": true, "width": "1"}
  }
}
```

此 ready-valid profile 比 AXI-Stream 规范的某些合法省略形式更严格：本产品第一版要求 TDATA/TVALID/TREADY 齐全，不将不支持的形式伪装成完整协议实现。信号方向以 master 为基准，slave 严格镜像；inout、同一物理端口映射到多个信号或多个接口暂不支持。

| 协议/profile | master 发往 slave | slave 返回 master | 可选信号及约束 |
|---|---|---|---|
| AXI-Stream ready-valid | TDATA、TVALID | TREADY | TKEEP/TSTRB 宽 DATA_WIDTH/8；TLAST 宽 1；TID/TDEST/TUSER 使用明确的正整数宽度参数 |
| APB3 | PADDR、PSEL、PENABLE、PWRITE、PWDATA | PRDATA、PREADY | PSLVERR 可选；地址宽 1..32，数据宽建议 8/16/32，首期以 32 位为必测配置；不含 APB4 PSTRB/PPROT |
| AXI4-Lite（后期） | AWADDR/AWPROT/AWVALID、WDATA/WSTRB/WVALID、BREADY、ARADDR/ARPROT/ARVALID、RREADY | AWREADY/WREADY、BRESP/BVALID、ARREADY、RDATA/RRESP/RVALID | 首个 profile 要求五通道所有列出信号；DATA_WIDTH=32/64，ADDR_WIDTH=1..64；不自动猜测 AWPROT/ARPROT tie-off |

必选列表由 profile 决定，不允许单个 IP 把必选字段改成可选。可选项两端均存在时要求方向/宽度一致；两端均不存在时不展开；仅一端存在时报适配诊断，**不自动悬空输入或静默补常量**。诊断必须提供需用户确认的一键 fix：预览显式展开及建议的成员绑定/常量，展示 TLAST 等字段的行为影响，确认后原子执行；拒绝确认不修改任何对象。信号级修改必须先显式物化，不能通过 fix 留下总线与信号两份事实来源。

时钟/复位不塞进数据总线束：接口通过 association 指向已有物理端口。本期仅验证引用存在，不实现时钟域诊断（包括 W020-W022）。未来检查只能依据已确认 role，不依据名字猜测时钟域，宁漏报不误报，文案不得称 CDC 签核。共享 clock/reset association 不视为多个数据 signal 映射。

### 2.2 IP schema v2

v1 继续原样验证；v2 保留原字段及物理 ports，interfaces 允许有界数组（建议每 IP 最多 64 个、每接口最多 64 个信号）。每项只允许 name/protocol/definition_version/profile/mode/parameters/signals/clock/reset/confirmed 字段；additionalProperties=false。name、信号和端口名复用现有标识符规则；同一 IP 的接口名唯一。

拟议接口片段，物理端口必须已经由 RTL 解析得到，不能仅凭映射创建不存在的引脚：

```json
{
  "name": "m_axis",
  "protocol": "axi-stream",
  "definition_version": "1.0.0",
  "profile": "ready-valid",
  "mode": "master",
  "parameters": {"DATA_WIDTH": "WIDTH"},
  "signals": {"tdata": "m_data", "tvalid": "m_valid", "tready": "m_ready"},
  "clock": "clk",
  "reset": "rst",
  "confirmed": true
}
```

parameters 表达式只引用该 IP 已有参数，解析实例覆盖值后再与物理端口宽度核对。可选宽度参数仅在相应信号出现时要求存在，不能用宽度 0 表示缺失。DATA_WIDTH 与物理范围的宽度匹配仍不能忽略 signed、升/降序索引；沿用现有范围语义，不自动反转位序。

v1 -> v2 的空接口内存迁移无信息损失；只读打开和普通保存不自动改 v1 文件。用户确认并登记非空接口时才写 schema 2，同时按现有库规则升 IP 版本（建议元数据能力变化用 minor 版本）。旧 id/version 和源 SHA 继续可读，新版本不覆盖旧目录。interface_hash 的 v2 计算须包含接口映射、定义版本及约束；v1 hash 算法保持不变，不能批量重写旧 hash/golden。

### 2.3 自动归组只是建议

优先按分词后的 `m_axis_`/`s_axis_`、`apb_`、`m_axi_`/`s_axi_` 前缀和规范后缀识别，不使用任意 substring 匹配。保留原名，只提供映射建议；`tx_valid` 等不规范名称提供用户手选映射。多个相同后缀候选不择一猜测。

建议评分规则应固定并可解释：完整规范前缀且方向/宽度成立为 0.95；去前缀后一一对应但角色靠端口方向推断为 0.80；通用 data/valid/ready 别名最多 0.60。缺少必选、冲突或非法宽度的候选不能确认，评分不是协议正确性的概率。clock/reset 未确认不得自动标 confirmed=true。

候选及 confidence/evidence 只在导入预览草稿中保存，不直接成为激活接口；用户确认后才写完整元数据。部分缺失逐项列出 missing_signals，允许放弃接口建议而保留原信号导入。重导入不覆盖已确认映射；源端口/参数变化使确认失效，并显示版本差异供重新确认。

## 3. 设计文件、所有权与迁移

拟议 design schema 5 增加 `interfaces`（根/子设计外部接口描述）与 `interface_connections`（当前 scope 的接口连接）。它们与原始 ports/instances/nets 并存，但**派生信号 net 不重复持久化**。一个 interface connection 是两个端点的点对点连接，不支持 multicast/fanout、部分通道连接或跨层路径。

```json
{
  "name": "samples",
  "from": {"inst": "producer_0", "interface": "m_axis"},
  "to": {"inst": "consumer_0", "interface": "s_axis"}
}
```

该片段放入 interface_connections 数组，不可放进现有 nets.endpoints。连接 name 与其他对象统一查重，建议最多 128 字符以给派生 net 名预留空间。接口外部端点用 `{"ext_interface":"stream_in"}`，不复用物理端口的 ext 字段，避免歧义。

根 schema 5 保留扁平 subdesigns 定义表；v5 子设计是独立 scope schema：有 ports/instances/nets/interfaces/interface_connections，但不含 project_ips 或嵌套 subdesigns。继续根统一元数据和最大 200 定义/16 深度/2 MiB 限制，不能通过接口展开绕过既有 100000 nets 等上限。新增接口连接建议最多 10000 条，且展开后的每项旧限制也必须满足。

迁移与保存的唯一对外契约见 [migration.md](migration.md)。迁移显式单向、旧文件不自动重写；无接口设计在同一生成模式下必须与 v4 输出逐字节一致，包括头部。首个实施任务先冻结该 golden 与迁移后保存/重开的往返测试，不先实现接口行为。

接口端口的物理 ports 仍是 RTL 事实；interface_connections 独占它实际展开的物理端点/位范围。普通 nets、slice 或 concat 若占用相同位，报 E205；不能同时有“总线连接”和另一份部分 signal 连接，哪怕驱动值看起来一样。分析时使用范围相交，不仅比较端口名。

“展开查看”只改变布局显示；“拆为信号连接”才是语义操作：删除一条 interface_connection，插入其全部派生 nets，一次原子历史。之后用户可编辑 slice/const/concat；接口元数据保留但不再拥有该连接。反向“归组成接口连接”只在全量成员一一对应且无额外使用时提供预览，确认后删除原 signal nets 再添加接口连接。不支持半条接口同时存在两种权威表示。

历史 golden 不变的证明门禁：原示例文件和全部旧 golden 的 SHA 清单前后相等；v2/v3/v4 的生成路径保持原算法；新版本差异必须进入独立 v5 golden。对每个旧夹具运行 open/save/reopen/undo，确认未升级且生成 HDL 字节相同。不得靠整体重录基线让测试通过。

## 4. 校验与 P2.2 诊断

拟议保留 E201-E211 与 W201；尚未加入代码或 locale。新的 location 在现有 design/instance/net/endpoint 上补 interface/connection/signal，跨层只使用已存在的 scope 定位，不向物理标识符塞入 `parent.child`。

| 代码 | 条件 | 必要 params |
|---|---|---|
| E201 | 协议/profile/定义版本不一致 | source_protocol, target_protocol, source_profile, target_profile, source_version, target_version |
| E202 | master-master、slave-slave 或非法角色组合 | source_mode, target_mode, effective_source_mode, effective_target_mode |
| E203 | 必选信号缺失或映射到不存在端口 | endpoint, missing_signals, unresolved_ports |
| E204 | 位宽参数或实际 signal 宽度不一致 | parameter, source_value, target_value, source_expression, target_expression, signal, source_width, target_width |
| E205 | 普通/部分展开连接与接口所有权冲突 | connection, signal, endpoint, overlap_range, conflicting_nets |
| E206 | 物理端口方向、signed/范围与协议声明不符 | signal, expected_direction, actual_direction, expected_range, actual_range, reason |
| E207 | 可选成员只出现在一端，缺少显式适配 | signal, present_endpoint, missing_endpoint, required_action |
| E208 | 派生名冲突或展开规模超限 | generated_name, conflicting_object, expanded_nets, limit |
| E209 | 未确认接口或非法参数/关联 | interface, reason, parameter, value, allowed_values |
| E210 | interface 与 scalar 混接/接口作为表达式成员 | source_type, target_type, expression_path |
| E211（本期不实施） | 未来依据已确认 role 的时钟域检查，另行评审 | source_clock_net, target_clock_net, source_reset, target_reset |
| W201（本期不实施） | 未来时钟关联提示，不能绕过本期 W020-W022 禁令 | endpoint, unresolved_associations, reason |

返回仍是 `code/severity/location/message/params/fix?`。诊断文案在后端与前端现有 i18n 路径中本地化；params 用稳定机器字段，数组规范排序。E201-E210 先于逐信号展开检查；阻断错误不继续产生几十条 E003 噪声。已展开且合法的成员继续走 E001-E008/W010，同一根因按 connection+signal+code 去重，并保留 provenance 供 UI 展开查看。

错误 fix 只作建议，必须经现有显式确认及重新校验。类型/角色/位宽不同不自动交换角色、截断数据、改参数、加常量或插入转换器。未确认接口可定位导入映射面板；冲突可定位现有 nets，并提供“拆为信号连接”预览，不直接破坏用户连线。

## 5. 信号展开、HDL 与层次

处理路径：schema 检查 -> 实例参数解析 -> 接口定义解析及确认 -> 连接/所有权检查 -> 派生信号网 -> 现有信号 resolve/semantic -> HDL 与 source map。GUI、CLI、AI 使用同一个后端规范化过程，前端不得维护独立电气展开算法。

每个连接按定义中规范信号顺序展开。TDATA/TVALID 等按 master -> slave 生成，TREADY 反向；APB 和 AXI-Lite 也按每信号方向决定驱动，不因用户拖拽 from/to 顺序倒转所有信号。整个接口不具有单一“所有位都是输出”的方向。

建议派生名 `__bd_if_<connection>__<signal>`，连接名限制 128 字符、signal 使用规范名，最终仍验合法性及 256 字符上限。冲突报 E208 并让用户显式更名；不使用随机数、时间戳或运行序号，输入对象重排不改变生成字节。原始 net 名保持不变。

source map 拟升 schema 2：保留 schema 1 的 files/hash/ranges 字段读取兼容，ranges.location 可新增 interface_connection、interface、signal、endpoint；同时保存派生 net -> 原连接/双方物理端口映射。HDL error 落在派生 wire/assign 时可定位粗线并展开具体成员；落在实例行仍定位实例。原始 IP 源行延用现有唯一实例映射，无精确工具位置时显式顶层回退。

根/子设计 interfaces 描述模块向外的角色。例如一个声明为 slave 的模块边界，其物理输入在模块内部充当驱动；连接校验对 ext_interface 使用**镜像后的内部有效角色**，对普通 IP 实例使用原角色。因此内部 slave 接到根上同样声明为 slave 的外部接口合法，而两个内部 master 不合法。该规则必须单独有方向表测试，避免对外部输入“双重反转”。

折叠选择时，只有完整、无冲突的接口连接穿过边界，且所有成员都可映射，才建议导出接口端口；用户确认后创建边界描述和标量 ports。部分跨边界、混合 concat、多个外部接收方继续采用当前标量边界，不猜测残缺总线。复用子设计时派生接口保持各实例独立端点，修改共享定义必须整根重验全部引用者。A 的子层 AI 限制不解除。

Verilog-2005 和 SV 输出均展开为普通 ports/wires/logic/assign，不输出 SV interface。结构相同的“接口连接版”和“物化信号版”应具有相同端口/连接拓扑与仿真行为；派生 net 命名不同的 HDL 用独立 golden 比较，不谎称一定逐字节相同。

## 6. UI、表达式与手机

- 复用现有 React Flow 节点、代理锚点、密集图轻量边和虚拟化。节点显示接口名称、角色图标、协议/profile、DATA/ADDR 参数；一个稳定几何的接口句柄，不为全部隐藏成员创建 DOM handle。
- 接口连线用粗线并给出规范名称；正向/反向握手由接口图标区分，不使用单向箭头暗示整束同向。选中可在属性面板看完整方向表、绑定物理端口、参数及诊断。颜色不是唯一状态信号。
- 展开/折叠使用 chevron 图标、aria-expanded 和 tooltip，语义拆解使用独立明确命令与确认对话框；单纯展开不改变设计或撤销栈，布局记录单独存放。断开整束一次撤销。
- slice/const/concat 继续只接受信号端点。用户必须先物化连接，不能对粗线使用切片或把 interface 拖进 concat。映射可通过真实端口表定位，但不因展开查看就释放所有权。
- 候选接口、未确认、缺失成员、参数不一致和部分信号占用有独立状态；不可连接目标仍给出原因，不靠禁用按钮隐藏错误。鼠标、键盘和触摸均可选择接口并进入诊断定位。
- 所有新文本/aria-label/tooltip/错误说明进入现有 i18n，测试缺失 key 与参数；界面保持现有工程工具风格，不增加教程型大面板。
- 手机以现有单面板切换为基础，详细成员在抽屉中纵向滚动；句柄触摸区域不少于 44px，节点宽度/行高稳定，长名称换行或省略并可查看完整值。390px 与 360px 验证无页面横向溢出，面板不遮住必须点击的确认/撤销按钮。

## 7. AI 操作与离线评测

拟议 ops schema 2 继续保留六个现有操作，connect/disconnect 的 endpoint union 增加 interface 分支；操作信封必须明确 schema_version=2，模型响应 schema 同步升版。v1 回放及调用仍按 v1 验证，不通过宽松 oneOf 猜测版本。

```typescript
type ScalarEndpoint = PortEndpoint | SliceEndpoint | ConstEndpoint | ConcatEndpoint;
type InterfaceEndpoint =
  | { type: "interface"; inst: string; interface: string }
  | { type: "interface"; ext_interface: string };
type Endpoint = ScalarEndpoint | InterfaceEndpoint;
```

这是设计伪类型，不是新增 TypeScript 文件。ConcatEndpoint 的成员仍只允许旧标量递归联合，绝不包含 InterfaceEndpoint。interface-interface 的 connect/disconnect 进入接口连接集合；混接在 ops 层拒绝后映射 E210。未知额外属性、元数据中缺失或未知的定义版本、假造接口与越层 inst 路径仍拒绝。端点通过固定 IP id/version 的元数据解析定义版本，不另外接收模型指定版本。操作上限 200 不变，接口展开后还需受总信号/网数限制；建议每提案新增展开信号最多 4096，超过时要求拆分明确任务，而非隐藏截断。

首期 AI 不新增接口定义、不确认候选、不修改 role/协议，也不自动物化接口。使用当前打开层的已确认接口及导出边界，禁止越层名称；共享子设计只读。局部候选必须合回整根并重新解析，不能只校验模型上下文子图；接受时也核对 scope 与根快照。预览以一条接口操作为原子选择项，不能只接受 VALID 而漏掉 READY；diff 可展开完整信号修改。

紧凑网表增加已解析的 interface 名称、协议/定义版本/profile、有效角色、已求值宽度、存在/缺失的可选信号、当前连接/占用摘要与 clock/reset 关联。IP 卡片增加相同已确认信息及物理映射，不发送 RTL、任意注册表文件或共享子设计内部定义。保持现有 8 张检索卡片、32k token 默认上下文、128 KiB 编码限制及选中子图策略；超限明确报错，不能截断一半接口。新增索引字段可以匹配中文“流接口/APB 主端”等，但不得用 held-out 结果调排名。

重试反馈只给 code/location/params，新增 affected_interfaces：解析参数、有效角色、缺失成员、可连接现有接口、冲突 net/位范围、需要的用户确认。不给可执行修复代码、shell 或外部路径内容。仍最多 3 次，每次基于原始快照替换整个 batch；transport 错误不转为语义重试。接受时核对文档/元数据/接口定义指纹和权限，一次 history commit，过期或已消费提案拒绝。

拟议新离线集合（保持现有 dev20/held-out12 及 A 三条回归不变）：

| 集合 | 数量建议 | 类别 |
|---|---:|---|
| 新 dev | 12 | AXIS/APB 合法连接、READY 反向、外部接口镜像、位宽修复、可选成员不对称、局部占用、不存在接口、拒绝确认/删除、子设计导出边界、metadata 注入 |
| 新 held-out | 8 | 不规范命名/歧义前缀、相同协议不同 profile、共享定义复用、跨层陷阱、参数联动、partial concat 冲突、长中文需求、相互矛盾角色要求 |

先冻结独立 expected document/diagnostic，再编 replay；不能从实现或模型输出生成答案。held-out 隔离，不用于 prompt/检索调优。报告按新旧 cohort、协议和错误类型分组，分别给 schema 合法率、首轮/最终结构正确率、连接 F1、missing-interface 判定、确认边界、重试次数及 token；确定性 mock 一致率不等于真实模型质量。本阶段不新增真实网络调用。

## 8. 验证与性能门禁

| 层次 | 必须验证的内容 |
|---|---|
| Schema/迁移 | v1 IP/v2-v4 设计/v1 ops 不变；v2 IP/v5 设计/v2 ops 正反例；strict unknown-field；无损迁移、取消/撤销、来源哈希与版本 |
| resolve/semantic | master/slave 与外部镜像；所有新增诊断 params；物理宽度/方向；可选缺失；slice/concat 位区间冲突；参数改变；共享子设计全部实例 |
| golden/source map | 新 v5 AXIS/APB 独立 golden；信号展开顺序/输入重排稳定；schema2 source map 正反定位；全部旧 golden SHA 零变化 |
| HDL | 固定 Verilator/Yosys 版本；各合法 profile lint 与 synth 通过；生成 BD/wrapper 无非豁免 warning；记录 cells 与文件哈希，禁止把 lint 结果标成综合 |
| Icarus AXIS | 真实源/汇，reset、空闲、持续传输、随机但固定种子背压；只在 TVALID && TREADY 时计数；停顿时 VALID 及 payload/sideband 保持；scoreboard 检查不丢、不重、不乱序；覆盖 TREADY 反向及连续替换 |
| Icarus APB | SETUP/ACCESS、等待周期、读写、PREADY 延迟、PSLVERR；PSEL/PENABLE/地址/控制稳定性，接口版与物化版相同交易结果 |
| Icarus AXI-Lite 后期 | AW/W 独立乱序到达、B/R 背压、WSTRB、地址/错误响应、复位；不把通道整体同时握手作为前提 |
| 浏览器 | 导入建议/明确确认、接口连线/拒绝、展开只读、物化/撤销、诊断定位、保存重开、子设计复用、AI 预览接受/丢弃/stale、桌面及手机 |
| 安全 | 伪造定义版本、名称/路径注入、超限展开、非法表达式、未知 endpoint、include 越界、不可信元数据确认绕过、离线 mock 无网络 |

2000 实例性能使用两类配对夹具：原信号级夹具完全不变，另增电气拓扑等价的接口表达夹具（记录原始 net 数、展开后 net 数和接口数，不能借粗线降低业务规模）。固定种子、机器、工具/浏览器版本，按 A 的负载前后检采集三样本，拒测不算通过。

本功能验收只使用同机同次运行的有/无接口同规模配对开销 <=10%，不使用绝对毫秒/FPS 数字。旧性能预算属于旧功能历史门禁，不替代本期相对验收，也不把旧超限归因于接口功能。分别记录解析/生成/浏览器交互的配对原值与比值、派生网内存和请求字节；拒测及失败不计为通过。

已批准目标：同次配对的额外开销 <=10%，每提案最多展开 4096 信号；隐藏成员不挂 DOM，request-local 索引避免每条粗线遍历全图。旧 2000 绝对预算联合复验与本期配对验收分开报告。若夹具超过原 2 MiB 限制，明确报告容量边界，不偷偷升上限。

## 9. 风险、替代方案与任务拆分

| 风险/方案 | 处理或取舍 |
|---|---|
| 接口与标量网双重权威 | 只持久化接口声明，派生网只在规范化阶段存在；物化为显式事务 |
| 仅 UI 前缀分组 | 实现轻，但不保证必选/方向/参数；保留作为不激活的预览替代，不用于自动连线 |
| 永远保存展开 nets，加分组标签 | 旧工具兼容好，但参数变化/删除容易留下残片；暂不选为权威格式 |
| 直接输出 SV interface | 仿真/综合工具支持和旧 Verilog 兼容风险高；首期不选 |
| 可选字段自动 tie-off | 容易改变包边界/路由/访问属性；首期报 E207，交用户明确处理 |
| 自动名推断误配 | 置信度只建议，必须显式确认；接口定义版本固定、重复端口拒绝 |
| 共享层次定义变化扩大影响 | 全根解析、依赖者全部校验、一次历史事务；AI 仍根层限定 |
| 性能/模型上下文膨胀 | 展开量双重限额、索引复用、虚拟化、预算报错；不以删信号提高性能 |
| 协议签核误解 | 界面分开结构/HDL/行为结果；握手 scoreboard 只是覆盖声明的场景 |

建议按以下顺序执行，每项测试先行、独立提交并跑完整既定门禁，任一步未验收不跳步：

| 任务 | 交付 | 验收条件 |
|---|---|---|
| 2B.0 | 首先冻结无接口兼容 golden 与显式迁移往返 | 同模式 v4/v5 HDL 字节一致；旧文件不改写，迁移后保存/重开一致，撤销恢复原文档 |
| 2B.1a | 本地协议定义、IP v2 schema/解析、版本指纹 | 必选/可选/方向/参数全部正反例；v1 及旧来源/golden 不变 |
| 2B.1b | 前缀候选与导入确认 | 候选不写激活元数据，歧义/缺失可纠正，明确确认后新 IP 版本 |
| 2B.1c | 设计 v5/迁移、接口解析、所有权与诊断 | 本文 E201-E211 可复现；老版本保存不升级；整批原子撤销 |
| 2B.1d | 确定性信号展开、HDL/source map | 新 golden、固定 lint/synth、旧 golden SHA 零变化、Icarus AXIS/APB |
| 2B.2a | UI 句柄/粗线、查看与物化分离 | 桌面/手机/键盘全流程、错误定位与保存重开，无半条连接状态 |
| 2B.2b | 层次导出与共享定义引用 | 内外角色镜像、完整/部分边界、复用全部重验、禁止穿层 |
| 2B.2c | ops v2/AI 卡片与紧凑网表 | v1 回放不变，新 dev/held-out 独立、三次重试/确认/stale 安全约束 |
| 2B.2d | 2000 实例配对性能与收尾报告 | 三个合格样本、绝对预算与新增开销分开，失败和拒测完整保留 |
| 2B.3 | AXI4-Lite profile 与行为覆盖 | AW/W 独立握手等全清单通过；未完成时不标称 AXI-Lite 支持 |

## 10. 已批准约束与第二期待定项

以下原评审问题已由 D049 取代：本期只做 AXI-Stream；采用三种新版 schema、单向显式迁移与总线唯一事实来源；可选绑定需确认 fix；AI 当前打开层且共享定义只读；性能仅同次配对 <=10%，4096 展开信号上限。警告指定六类的计数和逐条证据见 [../hdl-warnings.md](../hdl-warnings.md)。第二期 AXI-Lite/APB3 顺序仍待定，不影响本期。

以下清单保留为原评审记录，不再作为当前待办授权：

1. 是否接受首期只做 AXI-Stream ready-valid 和 APB3，AXI4-Lite 后置？AXIS 要求 TREADY、APB 要求 PREADY，超出 profile 的合法省略形式首期不支持。
2. 是否接受 IP schema 2 / design 5 / ops 2，以及“首次接口操作才迁移、只存接口连接、物化后才允许信号编辑”的策略？
3. 是否接受可选信号不对称一律显式报适配需求，不自动 tie-off；未知 clock/reset 给提示、明确跨时钟直连报错？
4. 是否接受继续限制 AI 在根层已确认接口及导出边界，不授权其确认元数据、物化连接或修改共享定义？
5. 是否采用新增 <=10% 配对语义开销目标和每提案最多 4096 展开信号？既有绝对预算/时限及本机未完成的三样本复验不放宽。
6. B 的 77 条可见警告豁免是否认可？如要求对已证明值域安全的内置 IP 仍做显式位宽清理，需另开版本升级、旧版本兼容、testbench/golden 工作，不混入本次接口文档提交。

本轮完成 AXI-Stream 片区及 phase-2b-1 报告后停止，不进入第二期。以下第 11 节是上轮纯文档交付的历史验证，不代表本轮接口实现已完成。

## 11. 本轮文档交付验证

在 B 最终代码 `d54fe06` 上独立执行完整 `scripts/check.py`，644 Python、90 子测试、65 Node、31 浏览器流程及 lint/typecheck/build 全部通过，24 HDL 对象完成 lint/综合。日志 `build/phase2b-design-final-check.log`；语义性能 median=382.810ms、max=425.852ms，按既定政策保留中位数非阻塞告警。六个本地代码链接全部解析成功。

本次门禁证明既有系统未因文档交付受到影响，**不代表本文提出的接口功能已通过测试**。A 的 [CI 45120062098](https://github.com/lylintel/bd_prototype/actions/runs/45120062098)、B 最终修复的 [CI 45129258459](https://github.com/lylintel/bd_prototype/actions/runs/45129258459) 均七项成功；B 初始失败仍保留在 [警告与综合报告](../hdl-warnings.md)。