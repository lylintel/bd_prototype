# AI 编辑与确认边界

## P3.1 Typed Ops

[ops.schema.json](../ops.schema.json) 是独立的 schema_version=1 格式；
[core/ops.py](../core/ops.py) 提供纯函数 apply_ops(design, library, operations)，返回候选文档和 error 诊断列表。
输入是明确版本的 v2/v3 设计和完整 IpMetadata 集合；旧设计在服务边界先显式迁移，不猜 IP 版本。

支持 add_instance、remove_instance、set_param、add_external_port、connect、disconnect。
批次最多 200 项、2 MiB；参数为受限整数或 P1.3 表达式，不执行代码。标识符复用原 Verilog 策略。
结构/实体错误返回原文档副本并整批回滚；操作合法但电气规则失败时返回未被接受的候选和新语义错误，供后续修复。
同参数设置和重复相同连接幂等；重复添加、重复删除/断开等返回明确 OP 错误，不静默覆盖。

```json
{
  "schema_version": 1,
  "ops": [
    {"op": "set_param", "inst": "compare_0", "name": "THRESHOLD", "value": 19},
    {"op": "disconnect", "from": {"type": "port", "inst": "counter_0", "port": "count"}, "to": {"type": "port", "inst": "compare_0", "port": "value"}},
    {"op": "connect", "from": {"type": "const", "const": "8'd5"}, "to": {"type": "port", "inst": "compare_0", "port": "value"}, "net": "count_bus"}
  ]
}
```

该片段演示格式，不是功能设计建议。端点 type=port/slice/const/concat：地址沿用 inst/port 或 ext；
slice 增加 slice:[hi,lo]；const 使用显式位宽字符串；concat 包含有序 typed 成员。
应用时移除操作层 type，并只在使用表达式时把设计升级为 v3。未知 type 返回 OP_ENDPOINT_TYPE，接口端点留 2B。
端点最多 16 层、256 节点、每拼接 128 成员；实际位宽、方向、接收覆盖等由 P2.2/P2.3 规则判断。

## 预览和接受

[bdai.py](../bdai.py) 是 I/O 边界，读取校验过的版本化元数据及当前项目目录，再调用纯 ops/语义核心。
提案只保存在本机服务内存，最多 32 个、10 分钟有效；不写硬件设计或 HDL。

| API | 行为 |
| --- | --- |
| POST /api/ops/preview | design/base_dir/ops，可选 summary；返回 id、候选、诊断和 requires_confirmation |
| POST /api/ops/accept | proposal_id、当前 design/base_dir、selected 索引、confirmed=true；重新检查设计/库指纹及所选操作 |
| POST /api/ops/discard | 丢弃提案，不改设计 |

沿用本地 Host/Origin/token 和请求大小限制。模型工具没有接受接口，也不能通过操作字段声明用户已经确认。
错误提案、过期/已消费 ID、无效索引、变化的设计或库会被拒绝。取消勾选后的剩余操作也必须重新验证。
接受只消耗一次提案，前端再核对当前快照，一次 mutate 形成一个撤销步骤；保存/生成仍是用户单独动作。

## 旧 Copilot 兼容

旧 status/connect/chat/cancel/clear 和 SDK 连接保留，不在本轮下线。
新增 bd_propose 直接提交 typed ops。旧 bd_generate 只转换已审计计划并发出 proposal，不能生成 HDL 或发 design_update；
旧操作无法安全转换时明确报错，不回退旧自动执行。旧需求/计划可保留审计日志，但不是接受或硬件验证证据。
前端阻止旧 design_update 自动应用；旧计划提案与原生 typed ops 使用相同确认 API。

共享上下文支持 v2/v3，保留表达式。bd_design 返回无坐标的紧凑网表，含参数和解析端口宽度。
bd_catalog 和兼容名称 bd_read_source 只返回端口/参数元数据，RTL 正文不发送给模型；bd_preview 也不向模型返回 HDL。
SDK 仅允许专用工具，不开放任意文件、shell、网络或 MCP。每次发送仍需本轮共享和编辑授权。

## 验证边界

tests/semantics/test_ops.py 对六类操作各至少四条契约测试，并覆盖事务性、幂等/明确重复错误、类型扩展拒绝、表达式及纯函数边界。
服务测试覆盖无落盘、确认、重验、过期、单次消费；SDK mock 覆盖旧入口不再自动更新和 v3/隐私保留。
真实后端 + 共享 Fake SDK 的 Playwright 流程验证：接受前设计不变、三项操作一起接受、一次撤销全部恢复，原文件不变。
该测试使用 scripts/mock_copilot_server.py，仅用于测试，不连接真实模型；无需安装或登录 SDK。

检索、可替换 LLMClient、自动修复回路、完整 diff 预览、安全评测和 20 例评测分别在 P3.2-P3.7 完成，不能用本节测试宣称真实模型质量已经验证。

P3.1 完整门禁：493 项 Python、68 子测试、40 项前端单测、12 条真实浏览器流程通过，Ruff/ESLint/typecheck/build 通过。
日志 build/phase3-p31-check.log；本机独立性能中位数 371.766ms、最大 428.906ms，按用户批准策略告警，门禁退出 0，并不宣称该样本低于中位数预算。
桌面与 390px 手机提案截图已检查。服务端 ops 与返回视图独立复制，回归测试防止返回对象修改待确认内容。