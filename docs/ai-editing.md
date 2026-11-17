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

## P3.2 元数据检索

[ai/retrieval.py](../ai/retrieval.py) 的 SearchIndex(library).search_ip(query,k=8) 使用 BM25Plus，
索引名称、描述、标签、端口及参数名。中文字符/双字片段与标识符下划线拆分并用；明确 id 优先，不匹配任何词项则不返回候选。
相同分数按 id/version 排序，版本始终显式保留。目录上限 10000，查询最长 8000 字符，k 为 1–32；embedding 未实现。

返回卡片只包含 id/version/parameters/ports，描述和源码不进入卡片。旧 SDK 的 bd_catalog 已采用同一 top-8 边界。
安装依赖使用 `python -m pip install -r requirements-ai.txt`，开发/Copilot 安装已包含它。

共用 20 条查询种子中，19 个有目标 IP 的查询均在 top-8 命中全部目标；缺失 IP 案例不计分母。
500 IP 查询 11 次，中位数 1.331ms、最大 2.146ms，包含分词、评分、排序及卡片生成，不含索引构建。
这些是检索回归指标，不是真实模型生成质量指标；20 条用例的完整期望与回放仍待 P3.7。

P3.2 完整门禁：498 项 Python、68 子测试、40 项前端单测、12 条浏览器流程，lint/typecheck/build 全通过。
日志 build/phase3-p32-check.log；本机独立校验性能中位数 265.503ms、最大 383.646ms。

## P3.3 LLM 客户端与设置

[ai/client.py](../ai/client.py) 提供可替换 LLMClient、OpenAIClient 和离线 ReplayClient。
OpenAI 兼容客户端支持 base_url/model/api_key/temperature、JSON schema 或工具输出；结果仍经本地 JSON/schema 检查。
非法结构重试一次；限流、超时、认证、拒绝、重定向或超限直接返回稳定错误，不自动重试。
单请求最多 32 条消息/256 KiB，响应最多 1 MiB。连接测试只访问 /models，不执行推理。

顶栏 AI 设置可编辑服务、模型及结构化模式，也可测试未保存的配置。配置保存在 .bdstudio/ai.json，Git 已忽略该目录。
密钥只保留本次服务进程，重启后可重新输入或通过 BD_AI_API_KEY 提供；不会回显或写入配置。
更换服务 origin 会清除旧密钥，除非同时明确输入新密钥。输入框为空表示保留同服务现有密钥，清除选项明确删除它。

请求日志默认关闭；开启后 .bdstudio/ai-requests.jsonl 只含脱敏的结果元数据，不含提示词、响应或 headers。
配置 API 为 GET/POST /api/ai/settings，连接测试为 POST /api/ai/test，继续使用现有本地访问保护。
底层客户端已可供 P3.4 调用；完整自然语言生成回路与画布 diff 在后续任务完成，不能把连接成功当成模型生成或硬件验证通过。

P3.3 完整门禁：520 项 Python、68 子测试、40 项前端单测、13 条浏览器流程，lint/typecheck/build 全通过。
日志 build/phase3-p33-check.log；本机独立性能中位数 268.716ms、最大 301.270ms。配置页桌面和手机截图已检查。