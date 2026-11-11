# 原创内置 IP

本目录的 17 个 RTL 实现和 testbench 为本项目新编写，不复制 src/vendor 中的上游 IP。适用许可见 [LICENSE](LICENSE)，每个生成的 ip.json 都记录 MIT、源码 SHA-256、参数约束、说明和标签。

| IP 源码 | 自检 | 主要契约 |
| --- | --- | --- |
| [bd_sync_fifo](bd_sync_fifo/1.0.0/src/bd_sync_fifo.v) | [tb](bd_sync_fifo/1.0.0/tb.sv) | 任意正深度，同域 ready/valid，同时读写，满空保护 |
| [bd_async_fifo](bd_async_fifo/1.0.0/src/bd_async_fifo.v) | [tb](bd_async_fifo/1.0.0/tb.sv) | Gray 指针，深度 2 的 ADDR_WIDTH 次方，独立读写时钟 |
| [bd_sync_2ff](bd_sync_2ff/1.0.0/src/bd_sync_2ff.v) | [tb](bd_sync_2ff/1.0.0/tb.sv) | 单比特两级同步，低有效异步复位 |
| [bd_edge_detect](bd_edge_detect/1.0.0/src/bd_edge_detect.v) | [tb](bd_edge_detect/1.0.0/tb.sv) | 同域信号上升/下降沿单周期脉冲 |
| [bd_clock_divider](bd_clock_divider/1.0.0/src/bd_clock_divider.v) | [tb](bd_clock_divider/1.0.0/tb.sv) | 周期为 2×HALF_PERIOD，输出上升沿 tick |
| [bd_debounce](bd_debounce/1.0.0/src/bd_debounce.v) | [tb](bd_debounce/1.0.0/tb.sv) | 两级采样后连续稳定计数，变化脉冲 |
| [bd_shift_register](bd_shift_register/1.0.0/src/bd_shift_register.v) | [tb](bd_shift_register/1.0.0/tb.sv) | 串入并出，左移，使能保持 |
| [bd_stream_slice](bd_stream_slice/1.0.0/src/bd_stream_slice.v) | [tb](bd_stream_slice/1.0.0/tb.sv) | 一级弹性缓存，ready 组合返回，背压保持 |
| [bd_mux2](bd_mux2/1.0.0/src/bd_mux2.v) | [tb](bd_mux2/1.0.0/tb.sv) | 2 路组合选择 |
| [bd_mux4](bd_mux4/1.0.0/src/bd_mux4.v) | [tb](bd_mux4/1.0.0/tb.sv) | 4 路组合选择 |
| [bd_counter](bd_counter/1.0.0/src/bd_counter.v) | [tb](bd_counter/1.0.0/tb.sv) | 清零优先于使能，回绕脉冲 |
| [bd_compare](bd_compare/1.0.0/src/bd_compare.v) | [tb](bd_compare/1.0.0/tb.sv) | 无符号相等/小于/大于 |
| [bd_uart_tx](bd_uart_tx/1.0.0/src/bd_uart_tx.v) | [tb](bd_uart_tx/1.0.0/tb.sv) | 8N1，LSB 优先，ready/valid 输入 |
| [bd_uart_rx](bd_uart_rx/1.0.0/src/bd_uart_rx.v) | [tb](bd_uart_rx/1.0.0/tb.sv) | 8N1，中心采样，帧错/溢出，单字节缓存 |
| [bd_spi_master](bd_spi_master/1.0.0/src/bd_spi_master.v) | [tb](bd_spi_master/1.0.0/tb.sv) | 模式 0，8 位，MSB 优先，单片选，全双工 |
| [bd_simple_dual_port_ram](bd_simple_dual_port_ram/1.0.0/src/bd_simple_dual_port_ram.v) | [tb](bd_simple_dual_port_ram/1.0.0/tb.sv) | 一写一读，独立时钟，同步读和有效标志 |
| [bd_axil_regs](bd_axil_regs/1.0.0/src/bd_axil_regs.v) | [tb](bd_axil_regs/1.0.0/tb.sv) | 32 位四寄存器，独立 AW/W、WSTRB、B/R 背压 |

## 使用边界

- 单时钟模块通常使用高有效同步 rst；单比特同步器使用 rstn，异步 FIFO 使用两个低有效异步复位，AXI-Lite 使用低有效 resetn。以各模块声明为准。
- 异步 FIFO 的复位必须协调，两域复位应同步释放；不支持一侧独立复位后保留队列数据。Gray 同步仍需要目标器件的 CDC、布局和时序约束，ASYNC_REG 不是签核证明。
- 两级同步器仅用于单比特控制；不能直接保证多位总线一致性。边沿检测输入必须已处于目标时钟域。
- FIFO 复位清指针/标志，不擦除存储阵列。只在 valid 时消费数据。RAM 读复位只清输出，不初始化存储器；同地址跨时钟读写冲突不保证行为。
- 分频器输出为逻辑产生的时钟，使用它需要生成时钟约束；优先使用 tick 作为原时钟域的使能。
- UART 固定 8N1，无奇偶校验、自适应波特率或流控。RX 无法反压串行线，输出满时丢弃新字节并给出 overrun，旧字节保持。CLKS_PER_BIT 需要满足清单约束。
- SPI 仅支持模式 0、8 位和单片选，不是全模式通用控制器。busy 时忽略 start，done 为单周期脉冲，rx_data 保持到下一次完成。
- AXI-Lite 仅 32 位、四个寄存器，地址偏移 0/4/8/12；未对齐或越界返回 SLVERR。每个方向最多一个待处理响应，有吞吐气泡。PROT 被接受但不实施权限控制，不可作为安全边界。
- 本目录通过数字仿真和结构编译，不代表目标器件综合、时序、CDC、功耗或真实硬件验证已完成。

## 清单与重建

[manifest.json](manifest.json) 是描述、约束和测试变体的源数据。每个版本目录包含原创 src、tb.sv 和生成的 ip.json。[index.json](index.json) 是只读发布索引，GUI 自动读取；用户导入只写外层私有 index.json，不覆盖本目录。

重建通过同一个 IpLibrary 预览/提交入口，不另写一套元数据解析。源码或接口变化必须提高版本并保留版本化路径；不能靠重建覆盖同版本来掩盖变化。

```powershell
.\.venv\Scripts\python.exe -m ip_import.builtin
.\.venv\Scripts\python.exe -m ip_import.builtin --update
.\.venv\Scripts\python.exe -m tests.golden.test_examples --update builtin_counter
.\.venv\Scripts\python.exe -m pytest tests/test_builtin_ip.py tests/golden -q
```

命令从仓库根目录运行。正常测试只比较，不更新文件。每个 IP 的自检必须实际编译、仿真并输出 PASS；另有全部生成 wrapper 的编译、源哈希/接口快照、私有库隔离和版本保护测试。

新示例 [builtin_counter.json](../../examples/builtin_counter.json) 连接原创计数器与比较器，并有 [集成自检](examples/counter_tb.sv)。所有生成 HDL 在 tests/fixtures/builtin-hdl.golden.json 中冻结；原有两个示例 golden 保持不变。