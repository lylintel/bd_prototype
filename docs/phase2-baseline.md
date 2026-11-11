# Phase 2A 能力基线

基准：P1.7 9c928e9，开工前保护 18bfce4。P0 架构文档描述历史状态，不作为当前能力缺失的推断依据。

## 规则对照

| 规则 | 当前状态 | 已有实现证据 | 2A 处理 |
| --- | --- | --- | --- |
| E001 位宽不匹配 | 已存在 | bdtool.validate_design 对每个 sink 比较 width，另拒绝范围/符号性差异 | 在元数据解析结果上包装等价规则；明确转换才允许改变形状 |
| E002 多驱动/输出互接 | 已存在 | validate_design 要求一个 driver，_resolve_endpoint 决定方向 | 复用驱动方向语义；补结构化多诊断 |
| E003 输入未连接 | 已存在 | validate_design 检查所有实例 input 和外部 output | 保持严格输入检查 |
| E004 不存在的端口 | 已存在 | _resolve_endpoint 校验端点存在性 | 提供精确 instance/port/net 位置 |
| E005 不存在 IP/版本 | 部分存在 | validate_design 拒绝未知 module，但没有版本引用 | 显式 id/version，缺失/歧义均拒绝 |
| E006 实例名重复 | 部分存在 | JSON _unique_keys 拒绝重复键；claim_name 检查外部端口冲突 | v2 有名数组保留重复项以便规则诊断 |
| E007 net 重复/冲突 | 已存在 | JSON 重复键保护及共享 used_names | v2 同样检查 net 数组重复及外部/实例冲突 |
| E008 非法标识符 | 已存在 | _name + IDENTIFIER.fullmatch + KEYWORDS | 复用原 Verilog-2005 规则，不用字符串拼接绕过 |
| W010 输出悬空 | 缺失 | 未连接 output 允许，render_verilog 输出空绑定 | 增加 warning，不变成 error |

已有实例 parameters 覆盖、min/max/32 位约束与端口 range 求值。P1.3 已接入安全表达式求值器；
不是重新实现参数覆盖。旧输出是首个 DesignError 字符串，缺少 code/location/params/fix；
P0.2 冻结输出与两份原 HDL 不变，新诊断使用独立函数和 HTTP 接口。

## 元数据与设计契约

- 新格式及迁移决策见 DECISIONS D018。无版本旧设计继续原路径；显式迁移不原地写文件。
- IP 元数据为 bdip.IpMetadata，包括原始范围、符号性、参数约束及 role。旧 IpLibrary.entries 的 definition 不含 role，不能作为新校验器输入。
- 服务边界准备库快照并检查来源；resolve(design, library) 只处理内存元数据，得到每实例的参数、端口宽度/范围/角色；规则只读该结果，不读取源文件、不调用旧 validate_design。
- 元数据中的未确认角色必须保持未确认；本轮不传播时钟域，不实现 W020/W021/W022 或协议接口。
- 旧项目内联模块可在 I/O 边界借助 P1.1 的 migrate_legacy_modules 得到项目 IP；那只是旧文件兼容加载，不参与新语义校验。与库发生歧义时不得按最新版本猜测。

## 分任务验收

P2.0：格式迁移、唯一引用及边界测试。P2.1：新元数据 resolver、参数界面、旧 HDL 精确复用。
P2.2：每规则独立文件/测试，至少三正三反、i18n 诊断定位和修复。
P2.3：有界切片/常量/拼接语法、新 HDL golden + Icarus、界面流程。
P2.6：纯函数、150ms 防抖、可复用固定种子设计生成器与 2000 实例全量测量。

P2.0 验收：16 项迁移/格式测试与原 golden 定向共 28 项通过；完整 scripts/check.py 退出码 0，
323 项 Python、57 个子测试、31 项前端单测、4 项浏览器流程及 lint/typecheck/build 通过。
捕获并修复空画布迁移丢失项目目录、同名接口被静默替换两个缺口；未修改原 golden。