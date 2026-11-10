# 可用开源 RTL IP

本目录整理了 4 个 MIT 许可的上游模块，以及 1 个本项目新增的接口适配层。选择标准是：单向数字端口、无器件专用原语、无需额外 HDL 包、可用现有整数参数/位宽规则表达，并能由本机 Icarus Verilog 编译。

上游项目为 [alexforencich/verilog-uart](https://github.com/alexforencich/verilog-uart) 与 [alexforencich/verilog-axis](https://github.com/alexforencich/verilog-axis)。两者 README 均声明已被 [fpganinja/taxi](https://github.com/fpganinja/taxi) 取代，不再接收维护。此处是方便当前 Verilog 原型使用的历史快照，不代表持续维护的生产 IP 推荐；生产使用需另行评估替代项目、许可、CDC、约束和验证范围。

## 模块清单

| GUI 模块名 | 用途 | 本地配置范围 | 注意事项 |
| --- | --- | --- | --- |
| `uart_tx` | ready/valid 数据转 UART 串行发送 | `DATA_WIDTH=5..9`，默认 8 | 无奇偶校验、1 个停止位；`prescale` 是 16 位输入，不是参数 |
| `uart_rx` | UART 串行接收转 ready/valid 数据 | `DATA_WIDTH=5..9`，默认 8 | 有 `busy`、`overrun_error`、`frame_error` 输出 |
| `bd_stream_register` | 简化的数据/valid/ready 流式寄存器 | `DATA_WIDTH=1..1024`，`REG_TYPE=0..2` | 推荐首选；内部使用未修改的 `axis_register` |
| `axis_register` | 带 keep/last/id/dest/user 的 AXI4-Stream 寄存器 | 本地目录固定 `DATA_WIDTH=8`、`KEEP_WIDTH=1`；侧带使能和宽度可配置 | 按普通端口连接，不提供 AXI 接口分组 |
| `priority_encoder` | 8 路请求优先编码，带 valid/index/one-hot | 本地目录固定 `WIDTH=8`；可选高位或低位优先 | 输出只有在 `output_valid=1` 时才有意义 |

上表的固定配置是本地元数据 profile 的限制，不是上游 RTL 本身的全部能力。`axis_register` 固定数据/keep 宽度，避免在当前模型中隐式计算除法和参数联动；`priority_encoder` 固定 8 路，避免引入 `$clog2`。需要更多位宽时，应同时调整元数据和测试，不能仅改变实例参数来绕过限制。

## 目录与许可证

```text
src/
  ip_catalog.json                  可直接打开的空白设计，含全部 5 个模块定义
  UPSTREAM.json                    来源、维护状态、版本说明、逐文件 SHA-256
  vendor/verilog-uart/rtl/          原始 uart_tx.v、uart_rx.v
  vendor/verilog-axis/rtl/          原始 axis_register.v、priority_encoder.v
  adapters/bd_stream_register.v     本地新增的简化接口适配层
  tb/                              本地编译/行为验收用测试台
```

原始 RTL 未改写，完整保留文件开头的版权和 MIT 许可声明。复制或再分发时须继续保留这些声明。适配层和测试台单独放置，不冒充上游源文件；本次未更改整个项目的许可。

下载日期为 2026-11-05。由于公开 GitHub API 当时触发限流，未核实默认分支的提交 SHA，故 [UPSTREAM.json](UPSTREAM.json) 将 `resolved_commit` 明确记为 `null`。版本以已下载文件及 SHA-256 锁定，不宣称等于未来的 `master`。更新源码时应重新核实许可、记录版本/校验值并重跑测试，不能只覆盖文件后沿用旧验证结论。

## GUI 中使用

1. 重启更新后的本地服务，在“打开设计”列表中选择 `src/ip_catalog.json`；旧服务仍可通过文件路径输入框手动打开该路径。
2. 左侧会出现全部 5 个模块。拖入实例，编辑参数，按驱动方向连接端口。库文件本身是空白设计，尚未实例化 IP。
3. 将实际设计另存到 `designs/`，不要把工作设计写回上游库。保存时会自动调整 RTL 相对路径。
4. 若要查看已接好的设计，打开 `examples/uart_loopback.json`。

也可在项目根目录直接启动模块库：

```powershell
.\.venv\Scripts\python.exe -m bdgui --design src/ip_catalog.json --open
```

若原服务占用默认端口，新服务会选择后续端口，以终端打印的 URL 为准。仅添加库文件不会改变已有设计中的 `modules`，打开模块库或示例后才会显示对应模块。

## 连接规则与时序

所有时序模块均使用 `clk` 上升沿和同步高有效 `rst`。这是单时钟域的普通 RTL 集成，`bd_stream_register` 不是异步 FIFO，不能用来跨时钟域。

ready/valid 数据只有在同一上升沿 `valid && ready` 时传输。发送端一旦拉高 valid，在接收端 ready 到来前必须保持 valid 和数据；ready 的方向与数据相反。不能把两个 ready 输出直接短接，也不能把一个 ready/valid 源简单扇出成多个独立消费者并期待自动广播握手。

`REG_TYPE=2` 是 skid buffer，推荐默认使用；`1` 是有气泡的简单缓冲；`0` 是组合旁路，不能用来切断组合时序路径。简化适配层关闭 keep/last/id/dest/user，只传输 data/valid/ready；不提供分帧或字节有效信息。

完整 `axis_register` 即使关闭某些侧带，也仍有对应的物理输入端口，必须显式连接。其 `tkeep` 是 `[0:0]` 向量，不能在当前严格模型下直接接标量；valid/ready/last 则是标量。

UART 的配置关系为 `baud = Fclk / (8 * prescale)`，`prescale` 应取非零 16 位整数，且不得在发送或接收过程中改变。例如 50 MHz 时钟、115200 目标波特率可取 54，但须核对实际误差。串行线本身不会接受 ready 背压：接收数据必须在下一帧到来前取走，否则会出现溢出、丢数据。真实外部 RX 引脚还需要按器件和时钟要求处理输入同步、IO 电平及约束；本例没有板级 CDC 或物理接口验证。

`priority_encoder` 无时钟，是组合逻辑。`LSB_HIGH_PRIORITY=0` 选择最高置位位，`1` 选择最低置位位。零请求时只应看 `output_valid=0`，不要假设 index 或 one-hot 也必定为零。

## 回环示例

`examples/uart_loopback.json` 的链路是：

```text
外部 data/valid/ready -> skid buffer -> UART TX -> serial_net -> UART RX -> 外部 data/valid/ready
```

例如 `serial_net` 连接 `tx_0.txd` 与 `rx_0.rxd`，生成一个标量 wire；`buffer_data_net` 则是 8 位数据网，而 `buffer_ready_net` 从发送器的 ready 输出返回缓冲器输入。时钟和复位分别是一个驱动、多接收端网络。

在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m bdtool validate src/ip_catalog.json
.\.venv\Scripts\python.exe -m bdtool generate examples/uart_loopback.json -o build/ip_demo
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_ip_catalog.py -v
```

手动仿真回环产物：

```powershell
& "$env:LOCALAPPDATA/Programs/iverilog-11.0/bin/iverilog.exe" -g2012 -s tb_uart_loopback -o build/ip_demo/sim src/vendor/verilog-uart/rtl/uart_tx.v src/vendor/verilog-uart/rtl/uart_rx.v src/vendor/verilog-axis/rtl/axis_register.v src/adapters/bd_stream_register.v build/ip_demo/uart_loopback_bd.v build/ip_demo/uart_loopback_bd_wrapper.v src/tb/tb_uart_loopback.v
& "$env:LOCALAPPDATA/Programs/iverilog-11.0/bin/vvp.exe" build/ip_demo/sim
```

## 已验证范围

2026-11-05 全量 Python 回归为 23 项全部通过、无跳过，其中本目录新增 8 项 IP 验收测试。完整结果保存在项目根目录的 `build/ip_validation.log`。

- 5 个模块的元数据通过原有模型校验，20 组参数配置的生成封装与原始 RTL 在 Verilog-2005 模式编译通过，未发现端口绑定警告。
- 缓冲 UART 回环通过 4 个数据字和短周期接收背压测试，无帧错误/溢出。
- 16 位流式寄存器的 3 种模式分别通过 64 字传输、停顿保持与不丢不重检查。
- 8 路优先编码器在两种优先方向下穷举 256 个输入组合通过。
- 4 个上游文件的 SHA-256 和 MIT 许可声明检查通过。

这不是上游完整回归、形式验证或 FPGA/ASIC 时序签核。尚未验证完整 AXI 侧带的所有行为、UART 噪声/波特率误差极限、板级收发、综合资源或 PPA。没有 Icarus 的机器仍可打开模块库，但 HDL 测试会明确跳过。