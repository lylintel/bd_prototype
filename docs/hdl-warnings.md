# HDL 警告处置与综合冒烟（B）

日期：2026-11-23。基线为 A 本地完整门禁生成的 24 对象、83 条警告记录；统计的是报告中的出现次数，不是去重后的源行。79 条来自 Verilator，4 条来自 Yosys。没有 IMPLICIT、LATCH、BLKANDNBLK 诊断；“没有诊断”不等于形式证明。

## 类别 x 来源

IP 源码列包含内置、固定上游源码和本地 adapter；示例设计列包含示例 RTL，以及由设计明确舍弃的端口位。生成 BD/wrapper 列只归生成器自身问题。所有保留项继续出现在 UI、日志和 JSON，未加类别屏蔽开关；原 `-Wno-fatal` 只让警告不直接终止 lint。

| 工具/类别 | IP 源码 | 生成 BD/wrapper | 示例设计 | 处置 |
|---|---:|---:|---:|---|
| Verilator WIDTHEXPAND | 13 | 0 | 1 | 豁免并保留可见提示，见下方逐项值域证明 |
| Verilator WIDTHTRUNC | 3 | 0 | 0 | UART RX 定时器赋值在合法参数范围内无有效位丢失；保留提示 |
| Verilator UNUSEDSIGNAL | 3 | 0 | 1 | AXI PROT 未使用、SPI 移位冗余位、示例明确舍弃高位；保留提示 |
| Verilator TIMESCALEMOD | 2 | 4 | 0 | 修复：工程化输出头统一 `1ns/1ps`，全部 6 条消除 |
| Verilator EOFNEWLINE | 2 | 0 | 0 | adapter 末尾换行的风格警告；为保持已冻结来源字节/哈希，豁免且可见 |
| Verilator PINCONNECTEMPTY | 10 | 0 | 0 | adapter 关闭的 AXIS 可选字段，显式空连接符合配置；豁免且可见 |
| Verilator GENUNNAMED | 10 | 0 | 0 | 固定上游 generate 无标签，影响层次命名稳定性而非本次功能；豁免且可见 |
| Verilator PROCASSINIT | 30 | 0 | 0 | 上游 FPGA 初始化与时序赋值，保留为 ASIC 可移植性提示，不承诺 ASIC 上电行为 |
| Yosys memory replacement | 4 | 0 | 0 | async FIFO/AXI 寄存器数组被展开为触发器；保留资源实现提示，不声称推断 BRAM |
| 合计 | 77 | 4 | 2 | 83 条基线；消除 6 条，剩余 77 条 |

## 位宽与其他 RTL 复核

这些是有意扩展或可证明在值域内的赋值，不通过截断常量来“消警告”；那可能改变越界阈值比较的行为。保留提示适用于下列参数约束与当前示例，不授权任意用户配置自动豁免。

| 来源 | 次数 | 核对与决定 |
|---|---:|---|
| examples/rtl/compare_eq.v:8 | 1 | 当前 WIDTH=8、THRESHOLD=9；无符号 value 扩展后比较整数阈值，无有效位丢失。保持历史源与 golden |
| vendor UART TX:95/104、RX:111/118/133 | 5 | prescale 是 16 位无符号，表达式在 32 位上下文运算；`prescale*8 <= 524280 < 2^19`，19 位定时器可表示。RX 半位采样值也可表示。运行时 prescale 必须 >=1；0 下溢不在有效波特率配置内，仍提示用户 |
| bd_clock_divider:13 | 1 | HALF_PERIOD=1..65536，计数宽 max(1,clog2(HALF_PERIOD)) 可表示 HALF_PERIOD-1；与正整数比较的零扩展不改变结果 |
| bd_debounce:17 | 1 | STABLE_CYCLES=2..65536；相同计数边界成立 |
| bd_shift_register:11 | 1 | WIDTH=1..128；serial_in 按无符号零扩展后 OR 到最低位，WIDTH=1 也有自检 |
| bd_spi_master:31 | 1 | CLOCK_DIV=1..65535；定时器可以表示 CLOCK_DIV-1 |
| bd_sync_fifo:20/28/30 | 3 | DEPTH=1..256；占用宽 clog2(DEPTH+1) 可表示 DEPTH，指针宽 max(1,clog2(DEPTH)) 可表示 DEPTH-1；显式回绕支持非二次幂深度 |
| bd_uart_tx:22 | 1 | CLKS_PER_BIT=2..65535；计数宽可表示 CLKS_PER_BIT-1 |
| bd_uart_rx:29/32/38 | 3 | CLKS_PER_BIT=4..65535；半位与整位 reload 均非负且小于 `2^TIMER_WIDTH`，32 位表达式裁到定时器宽度不丢失有效位 |

UNUSEDSIGNAL 三条 IP 提示：`bd_axil_regs` 的 awprot/arprot 不参与访问权限判定，适用于无保护属性区分的寄存器区，不能作为安全访问控制器；`bd_spi_master.transmit[7]` 的首位由 tx_data[7] 直接驱动 mosi，其后只读 transmit[6:0]，属于冗余存储位。

adapter 的 m_axis_tkeep/tlast/tid/tdest/tuser 对应 enable=0，各出现两次，共 10 条显式空输出；不是漏接必选协议字段。上游 axis_register/priority_encoder 的未命名 generate 共 10 次，上游 UART/axis_register 的声明初始化共 30 次，均不静默修改上游源码。

未发现需要修改内置 IP 功能的证据，故本轮**没有改内置 IP、没有升其版本、没有更新或弱化 testbench、没有更新任何历史 golden**。现有 35 组 Icarus 行为变体及 wrapper/集成自检仍作为完整门禁执行。将来如需改内置源码，仍必须新版本目录、显式 golden 更新及原强度行为测试；本轮豁免不解除这一要求。

## 生成物零警告

工程化生成器添加 `timescale 1ns/1ps`；旧 `bdtool` 模板未变。source map 根据实际新行号生成，旧示例/历史 golden 字节不变。默认输出无延时行为，该声明明确与上游模块的仿真时间单位兼容。

`scripts/check_hdl.py` 对生成文件中的任何警告执行门禁，唯一精确豁免是 `examples/semantic/connections.json` 的 `connections_bd.v` 中 UNUSEDSIGNAL：`Bits of signal are not used: 'data'[11:8]`。这是示例 slice 明确不用的外部输入高位，与用户故意悬空的 W010 类情况同属设计意图提示，但当前语义层不会对该高位发 W010，不谎称二者诊断完全等同。豁免按 case、文件、类别、完整 detail 匹配；不放过其他 UNUSEDSIGNAL 或位宽警告。运行时用户设计中的 W010/空输出仍可见，不一概升级成错误。

## Lint 与综合

工具在临时工作目录执行，参数固定、无 shell、stdin 关闭、每次工具调用 30 秒上限，工具日志最多读取 1 MiB；综合 JSON 最大 64 MiB。执行：

1. Verilator `--lint-only -Wall -Wno-fatal --top-module <top>`。
2. Yosys `read_verilog [-sv] ...; hierarchy -check -top <top>; synth -top <top> -flatten; check -assert; write_json synthesis.json`。
3. 结构化解析综合网表；统计硬件单元，排除 `$scopeinfo` 并另报该调试对象数量。缺少/损坏统计文件为失败。

UI“运行 HDL 检查”与完整门禁/CI 共用此流程，分别显示 lint、综合、版本及单元数。真实回归特意构造 Verilator 接受但 Yosys 拒绝的多事件时序过程，证明 lint 通过不等于可综合。精确文件行号经 source map 回到实例/网络；工具没给源行时标记 `location_precision=top_level_fallback`，定位顶层而不是捏造源行。

五个既有对象的明确清单是以下前五行，额外覆盖层次和 SV；另有 17 个内置 IP standalone 共 24 对象。统计为本机固定工具下的通用单元，不是 LUT/BRAM 利用率、ASIC 面积或 PPA 结果。

| 对象 | 综合单元数（排除 scopeinfo） |
|---|---:|
| examples/builtin_counter.json | 73 |
| examples/counter_compare.json | 29 |
| examples/semantic/connections.json | 8 |
| examples/uart_loopback.json | 699 |
| src/ip_catalog.json | 0 |
| examples/hierarchy/counter.json | 125 |
| examples/sv/register.json | 8 |

`src/ip_catalog.json` 是空顶层目录示例，0 是优化后的真实结果，只证明可解析/处理空顶层，不证明每个目录 IP 的动态行为；UART 示例实际实例化相应上游链路。内置 IP 单元数：async_fifo 297、axil_regs 551、clock_divider 7、compare 41、counter 31、debounce 14、edge_detect 5、mux2 8、mux4 60、shift_register 8、simple_dual_port_ram 290、spi_master 90、stream_slice 11、sync_2ff 2、sync_fifo 346、uart_rx 156、uart_tx 68。

## 固定版本与隔离

- Verilator：OSS CAD Suite 2026-11-17，`5.055 devel rev v5.054-302-g2d6aba6ed`，允许发行包自带 `(mod)` 后缀，不接受其他修订。
- Yosys：`yowasp-yosys==0.70.0.0.post1259`、运行时 `1.96`、wasmtime `47.0.1`，实际 `Yosys 0.70 / 28ba3cb92`。CI 显式 BD_YOSYS 指向此可执行文件，不能被套件里的其他 Yosys 抢占。
- 每次处理 RTL 前查询并核对版本，报告保留 expected_version/version；错配给 HDL_TOOL_VERSION，且测试断言不执行 lint/synth。CI 使用固定日期发布包并打印工具版本，不再依赖 apt 的滚动 Verilator。
- 字面量 include 先解析真实路径，须在传入项目根内；绝对路径、相对路径、符号链接均受 resolve 后边界限制。越界在工具发现/执行前拒绝，不打开目标文件，诊断仅给原因和包含指令的文件/行。
- 合法 include 依赖递归复制到临时目录并改写其路径，原文件不改。递归深度 16、路径索引 200 项、每源文件 2 MiB；宏 include、token 拼接、反斜线续行/转义等复杂形式保守拒绝。检查也可能拒绝注释中的 include 文本，这是保守扫描限制，不宣称完整预处理器兼容。
- 测试覆盖工作区外绝对路径且无 sentinel 内容回显、工作区内真实 include、临时目录最终移除、固定参数和无 shell。临时目录不是操作系统沙箱，不保证阻止 RTL 中所有文件系统系统任务；任意不可信 RTL 仍应在独立 OS 沙箱审阅运行。

## 验证记录

聚焦测试：检查器 16 项、真实综合失败 source map、版本错配、内外 include 与原生成器回归通过。完整 `scripts/check.py` 通过：644 Python、90 子测试、65 Node、31 浏览器流程，Ruff/ESLint/typecheck/build 全绿；24 对象 lint/综合零 error、77 警告，生成物仅一条精确设计豁免。日志 `build/phase4b-hdl-check.log`，语义性能 451.091/678.380ms 按既定政策保留非阻塞告警。另行两条浏览器截图流程通过，桌面/390px 手机可视检查通过。Pylance 核对 11 个调用点兼容，旧 golden/内置/上游 RTL 的 Git 差异为空。工具原始记录位于 `build/hdl-checks.json`，采用报告 schema 2，旧报告不覆盖解释为新语义。

A 已独立提交 `b8d2cbd`；[A CI 45120062098](https://github.com/lylintel/bd_prototype/actions/runs/45120062098) 七项成功，500 三样本预算均通过。详见 [Phase 4B 报告](reports/phase-4b.md)。B 完成后才写 C 设计文档，不实现接口功能。

### B 远端可移植性修复

B 初始提交 `daaa95d` 的 [CI 45124319354](https://github.com/lylintel/bd_prototype/actions/runs/45124319354) 四项解析矩阵及性能收集成功，两项主门禁失败。固定版本校验、全部 24 对象 lint/综合均通过；唯一失败是合法 include 用例：Linux YoWASP 无法打开写入 RTL 的宿主 `/tmp/...` 绝对路径。不是版本错配，也没有通过重跑掩盖。

补充跨平台契约断言后在 Windows 稳定复现“写入绝对路径”缺陷。修复只将已验证和复制的 include 改为临时 cwd 下的 `includes/...` 相对引用；仍先检查原始解析路径的工作区边界，未向 WASI 开放项目外目录。相对路径、真实工具读取、外部 sentinel 不回显三项聚焦测试通过。补充修复完整门禁通过：644 Python +90 子测试、65 Node、31 E2E，24 对象 lint/综合通过；日志 `build/phase4b-hdl-portable-check.log`，语义性能 417.549/620.703ms 保留非阻塞告警。原失败 CI 保留，不将其重写为通过。

修复提交 `d54fe06` 的 [CI 45129258459](https://github.com/lylintel/bd_prototype/actions/runs/45129258459) 七项任务全部成功，包含 Linux Python 3.10/3.14 的真实 include 回归与固定版本综合。该远端结果在 C 的文档提交中补记；B 的实现仍为 `daaa95d` + `d54fe06` 两个可追溯提交。