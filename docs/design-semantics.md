# 版本化设计与语义接口

## 设计 v2

旧无版本文件及旧 CLI/API 保持兼容，不自动写回原文件。新的 design.schema.json 使用 schema_version=2：

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
空画布也保留项目模块目录。旧 CLI 仍只处理旧格式；v2 使用新语义 API、GUI 或 Python 接口。

## 参数与角色

core.resolve.resolve(design, library) 接收 v2 文档及 IpMetadata 集合，不读取源码、解析 RTL或调用旧校验器。
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

P2.1 提供 E001 和 resolver 的定位错误；生成前仍有完整连接/名称保护。独立规则、精确定位和修复按钮在 P2.2 完成，切片/拼接/常量在 P2.3 完成。

## 兼容验证

三个既有示例通过新语义接口生成的 HDL 均与原 golden 字节一致。参数测试禁止 resolver 文件访问，
禁止新核心调用 bdtool.validate_design。真实 HTTP 测试覆盖令牌、来源篡改、v2 保存/重开/生成和角色保留；
真实浏览器覆盖参数表达式、宽度标签、失配后修正、v2 引用、撤销和桌面/手机布局。

P2.1 完整验收：340 项 Python 测试、57 个子测试、34 项前端单测、5 项浏览器流程通过，
Ruff/ESLint/typecheck/build 通过，scripts/check.py 退出码 0。日志为本地 build/phase2-p21-recheck.log。