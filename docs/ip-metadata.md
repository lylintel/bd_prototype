# IP 元数据 v1

P1.1 提供独立 IP 描述，不替换已有设计 JSON 的 modules 字典，也不修改实例参数、连线或 HDL 生成。格式见 [ip.schema.json](../ip.schema.json)，Python API 见 [bdip.py](../bdip.py)。

## 安装和检查

IP 元数据模块需要 `jsonschema==4.25.1`；开发依赖已包含它。原 bdtool CLI 不依赖此包。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ip.txt
.\.venv\Scripts\python.exe -m pytest tests/test_bdip.py tests/golden -q
```

只安装 requirements-ip 不能运行 pytest；测试环境应安装 requirements-dev。JSON Schema 使用 Draft 2020-12，引用全部是文件内的 $defs，运行校验不联网。

## 数据契约

- 必填 schema_version 为整数 1；缺失或未知版本拒绝，不猜测、不原地升级。IP 的 version 是单独的三段发布号，如 1.0.0；v1 暂不接受预发布或构建后缀。
- id、参数名、端口名必须是普通 HDL 标识符，拒绝 Verilog 和 SystemVerilog 关键字，不支持转义标识符。Python 校验还拒绝参数/端口重名及 min 大于 max。
- parameters 的 type 当前为 int，default 是非空表达式字符串；min/max 是可选的 32 位整数约束。ports.dir 为 in/out/inout，width 是非空表达式字符串，不接受数值替代。
- 表达式仅作为数据保存。此阶段不求值、不确认位宽为正、不检查表达式引用和默认值是否满足约束；这些属于 P1.3/P2。支持 inout 元数据不代表旧生成器已经支持 inout 连接。
- 为无损迁移，port 可保留 range 原始左右索引和 signed；range 的有无区分标量和单比特向量。参数化 range 的迁移 width 使用两分支差值加一表达式，保留升序/降序语义，不用默认参数值冻结位宽。
- role 可选；若存在，kind/confidence/confirmed 必填，confidence 在 0 到 1 之间。reset 还须给出 polarity 和 async；不确定时使用 unknown。迁移不根据端口名猜角色，不标记任何自动确认。
- source 记录首个编译源文件；additional_sources 可保留其余有序文件，各自带 SHA-256 和 license。path 使用正斜线、相对于元数据文件目录，允许 ../，拒绝绝对路径、反斜线和控制字符。
- 迁移读取源码计算真实 SHA-256，授权范围由调用者必须提供的 workspace_root 限定。未提供许可证时记 NOASSERTION，不推断为 MIT。load/save 不读取源码、不重新计算哈希，也不证明源码自迁移后未变化。
- interfaces 在 v1 预留为空数组；不伪造尚未实现的协议分组。目录索引、版本去重、导入器和 GUI 接入不在本项范围。

## 加载与保存

`IpMetadata.from_dict(document, base_dir=...)` 验证并构造 frozen 数据类，嵌套的 IpSource、IpParameter、IpPort、IpRole 也是数据类。to_dict 返回独立的 JSON 对象，不暴露内部集合。

`load_ip(path)` 拒绝重复字段、非法 UTF-8、非有限 JSON 数值及超过 1 MiB 的文件。直接传入对象也受规范化 JSON 的 1 MiB 上限约束。错误是 IpMetadataError，含 code/location；中文消息集中在 [locales/zh-CN.json](../locales/zh-CN.json)。

`save_ip(metadata, path)` 在写入前重新校验，保持 UTF-8/LF/尾换行，并通过同目录临时文件原子替换。拒绝覆盖已登记源码；失败时不替换原文件。它不是带确认的版本库导入命令，调用者需明确选择输出路径。

load_ip 和迁移返回的对象记录非序列化的 base_dir。另存时自动重写源码相对路径，以保持源码指向；不修改传入对象。手工 from_dict 时若省略 base_dir，源码路径将相对于首次保存目录解释。Windows 跨盘不能生成相对路径时拒绝另存。

## 迁移已有模块

在仓库根目录运行以下 Python 代码，即可一次转换 counter 和 compare_eq。相同函数也适用于 uart_loopback；不需要修改原设计。

```python
import json
from pathlib import Path

from bdip import load_ip, migrate_legacy_modules, save_ip

root = Path.cwd()
example = root / "examples" / "counter_compare.json"
design = json.loads(example.read_text(encoding="utf-8"))
modules = migrate_legacy_modules(design, example.parent, workspace_root=root)
for module_name, metadata in modules.items():
    destination = root / "build" / "ip-metadata-v1" / module_name / "ip.json"
    save_ip(metadata, destination)
    assert load_ip(destination).source.sha256 == metadata.source.sha256
```

迁移只读取旧 modules 的合法定义，不要求草稿连线已经完成；使用原 bdtool 检查模块默认参数与端口范围。保留模块顺序、多源码顺序、参数默认值/约束、原始范围和符号性。源文件不存在、元数据无效、源码越出授权根目录时返回领域错误，不输出半成品。迁移本身不写文件，上例中的保存由调用者显式执行。

## 回归边界

现有设计仍由原 load_design/validate_design 加载；P0 golden 不重采集。旧设计格式没有变化，因此仍不添加 schema_version。新 IP 文件从 v1 起版本化；未来不兼容修改需要新的 schema_version 和迁移入口。