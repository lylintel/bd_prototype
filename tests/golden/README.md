# HDL Golden 基线

P0.2 锁定 examples 下每个 JSON 设计的 BD、wrapper 和规范化校验结果。比较 UTF-8 字节，包括空白、LF 换行、尾换行、实例/参数/网络顺序；源路径仅转成仓库相对路径，避免绝对机器路径进入快照。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests/golden -v
```

测试没有网络/LLM 依赖，不调用 HDL 工具。CLI 使用临时输出目录；测试不会更新 golden。单字符回归测试临时替换生成器返回的第一个 `module` 字符，确认相同比较器确实失败，随后恢复，不改源码。

只有任务明确允许改变输出并完成迁移时，才在仓库根目录执行下面的维护命令，并逐项审查 Git 差异：

```powershell
.\.venv\Scripts\python.exe -m tests.golden.test_examples --update
```

不可以用重新采集 golden 掩盖意外回归。当前初始基线来自未修改的 bdtool 生成器；完整示例集合缺少任何 golden 都会导致测试失败。

新增示例可仅更新指定项：`python -m tests.golden.test_examples --update builtin_counter`。这不会触碰 counter_compare 或 uart_loopback 的基准。比较器本身始终比较字节，不转换换行或路径分隔符。