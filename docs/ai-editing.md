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

## P3.4 生成与修复回路

POST /api/ai/propose 接受 design/base_dir/prompt 和可选 allow_removals，使用已配置的客户端。
回路最多三轮，每轮替换完整 ops 批次、始终从原始快照重算；不会累积失败修改。
响应包括 ops、summary、assumptions、missing_ip、questions、validation、attempts 及机器反馈 trace。
只有提供卡片中的 IP 可以新增，端点仍须通过实际元数据与 P2.2/P2.3 校验。

模型上下文不含 RTL/坐标；反馈仅 code+params/location 和受影响端口的解析摘要，不回传后端 message。
缺失 IP、待澄清问题、达到失败上限或传输失败都返回不可接受提案。成功仍需用户选择并确认，生成不等于应用。
调用期间源码或库变化会拒绝过期结果；同一服务一次只有一个活动 AI 生成请求。
回路与提案服务已有离线回放/真实服务契约测试；自然语言界面和颜色 diff 在 P3.5 接入。

P3.4 完整门禁：530 项 Python、68 子测试、40 前端单测、13 浏览器流程，lint/typecheck/build 全通过。
日志 build/phase3-p34-check.log；本机独立性能中位数 290.169ms、最大 419.883ms。

## P3.5 预览与确认

工具栏 AI 提案入口提供需求输入、删除实例授权和生成状态。提案显示摘要、假设、问题、缺失 IP、尝试次数及可逐条选择的操作。
选择变更通过 /api/ops/select 重新计算和校验子集，绿色新增、红色删除、琥珀修改只显示在独立只读图层。
原设计 JSON、参数面板和校验徽标仍对应真实设计，不把候选当成已应用结果。预览期间文件操作与历史修改被禁用。
接受前再次校验并核对原设计/IP 库快照，整批只产生一个撤销步骤；放弃/关闭不修改设计或 HDL。
无效或未决的原提案即使取消部分操作也不能接受；有效提案的非法子集同样不能接受。

真实后端加 mock LLM 的三条新增流程覆盖逐条取消、所选操作接受、已有历史下单次撤销、删除预览放弃和三轮无效结果禁用接受。
完整门禁记录在 build/phase3-p35-check.log，包含桌面/手机截图和历史 golden 检查。没有调用真实模型。

## P3.6 安全边界

AI 请求限制为 256KiB、每 60 秒 10 次，新旧入口共用额度；超限返回结构化 AI_RATE_LIMIT 或 AI_LLM_LIMIT。
元数据/工具数据不是指令，描述不进入模型卡片；SDK 数据工具也使用 BEGIN_BD_DATA/END_BD_DATA 定界。
所有模型输出必须经过 typed ops 白名单、标识符校验、新语义校验与人工确认。未知操作/接口端点、路径和关键字名称被拒绝，不执行 shell 或文本代码。
remove_instance 在共享提案服务默认禁止。新面板可逐轮显式授权；旧 SDK 入口不支持扩大删除权限，应改用新面板。
恶意描述夹具、越权 SDK、非法 ops、限流恢复、密钥不落盘及协议大小测试均离线执行。限流为本地单进程保护，不是公网服务安全认证。

## P3.7 离线评测

```powershell
.\.venv\Scripts\python.exe -m bdstudio.ai_eval --client mock --report build/ai-eval
.\.venv\Scripts\python.exe -m bdstudio.ai_eval --client mock --report build/ai-eval-next --compare build/ai-eval/report.json
```

tests/ai_eval/cases.yaml 是 20 条独立期望，replays.json 是固定完整响应。评测不会自动修改二者。
scripts/ai_eval_fixtures.py --write 只用于维护回放；改完仍需对照独立期望和失败变异测试，不能以重建回放替代审查。
每次实际执行检索、生成修复回路、typed ops 和新语义校验。未连接端口按实例名_端口名引出，实例名等于 IP ID；已存在的基线名称保留。
实例/连线 F1 忽略集合顺序，连接忽略 net 名但保留方向、切片及拼接顺序。完全匹配还检查参数与外部接口，缺失 IP 和待澄清为预期拒绝，不计为“校验通过”。
报告包含逐例差异、诊断、尝试次数、机器反馈 trace 和哈希，--compare 提供指标变化及回归案例。所有 20 例必须执行，不能跳过不支持的用例。

初始 mock 结果：简单/中等 17/17，通过各自期望 20/20，实例/连线 F1=1，完全匹配率=1，missing_ip 正确率=1，检索命中 19/19。
校验通过率为 18/20；缺失 ADC 和含糊时序两例按设计拒绝。固定回放用于回归，不衡量真实模型的生成能力。

真实服务仅人工执行，需预先在本地环境设置 BD_AI_BASE_URL、BD_AI_MODEL、BD_AI_API_KEY（不要写进命令行或提交）。
然后明确执行 --client real --allow-network --report build/ai-eval-real；这会发送提示及精简元数据，可能产生服务费用。
本轮没有调用真实模型，没有进行模型质量、硬件 CDC、时序或功能签核。

P3.7 最终本机完整门禁：543 项 Python、68 子测试、42 前端单测、17 条浏览器流程，加 20 条独立回路评测；lint/typecheck/build 全部通过。
日志 build/phase3-p37-check.log；11 样本独立性能中位数 299.800ms、最大 446.511ms。四 IP 计数/比较/边沿/同步链已验证预览、接受、校验及单次撤销。
与 Phase 3 前的 5cc18aa 比较，examples 与历史 golden 没有改动。报告比较命令已实际运行，同一输入无回归。

## Phase 3.5 三次评测协议

本节替代上节单次 CLI 协议；旧 20 例仍为 dev，新增 12 例 held-out，默认全部执行三次。原评分函数和历史数据保留。

```powershell
.\.venv\Scripts\python.exe -m bdstudio.ai_eval --client mock --report build/ai-eval-mock --max-calls 400 --max-cost 0
.\.venv\Scripts\python.exe -m bdstudio.ai_eval --client real --allow-network --dry-run --report build/ai-eval-real --mock-report build/ai-eval-mock/report.json --max-calls 400 --max-cost 0
```

真实运行必须先由用户配置私有端点/模型或 BD_AI_BASE_URL、BD_AI_MODEL；密钥使用 BD_AI_API_KEY。CLI 不读取 GUI 进程内会话密钥，也不猜测缺失端点。
用户另行提供 BD_AI_INPUT_PRICE、BD_AI_OUTPUT_PRICE（美元/百万 token 的价格上界），并自行设置 BD_AI_MAX_COST。也可通过 --input-price/--output-price 指定非敏感价格。

```powershell
.\.venv\Scripts\python.exe -m bdstudio.ai_eval --client real --allow-network --report build/ai-eval-real --mock-report build/ai-eval-mock/report.json --max-calls 400 --max-cost $env:BD_AI_MAX_COST
```

没有配置时只生成 waiting_configuration 报告，不发送请求；本轮已验证此路径。不要把密钥放进命令行、设计文件或版本控制。
--suite dev/held-out/all 可选择数据集；--compare 上次 report.json 仅对同数据集、同三次协议和完整结果做差值。
退出码：0 为完整合格的 mock/真实结果或 dry-run；1 为完成但验收不合格；2 为等待/配置错误；3 为预算中断且已保存部分报告。

--max-calls 包含每次实际 POST 和 JSON 修复，最多三轮语义尝试，每轮 JSON 最多再试一次。--max-cost 默认 0，不能为跑完用例自动增加。
--max-output-tokens 默认 8192，--input-overhead 默认 1024；预留成本使用字节上界，缺少 usage 不释放预留。提供商必须支持并遵守输出限制；若不支持会明确失败，不会移除限制继续调用。
预算依赖用户给出的保守价格/开销上界，不是账单签核；供应商侧费用限额仍是最终保障。

报告分别列出首次通过、首个语义候选通过、最终通过、修复收益、三次一致率、实际/估算 token、延迟、尝试次数、失败分类及最多五份脱敏完整对话。
初始 mock 只有三个出现首次或最终失败的案例，所以只生成三份对话，不虚构另外两份。真实未运行时没有真实失败对话或指标。
基线报告先提交；只能依据 dev 的真实失败分类提出调整，held-out 不用于逐条修补提示。真实 dev 简单/中等首次低于 70% 时必须先提交分析和方案，不自动调参。