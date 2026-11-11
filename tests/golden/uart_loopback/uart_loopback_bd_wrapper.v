module uart_loopback_bd_wrapper (
    input wire clk,
    input wire rst,
    input wire [15:0] prescale,
    input wire [7:0] in_data,
    input wire in_valid,
    output wire in_ready,
    output wire [7:0] out_data,
    output wire out_valid,
    input wire out_ready,
    output wire tx_busy,
    output wire rx_busy,
    output wire overrun_error,
    output wire frame_error
);

    uart_loopback_bd bd_i (
        .clk(clk),
        .rst(rst),
        .prescale(prescale),
        .in_data(in_data),
        .in_valid(in_valid),
        .in_ready(in_ready),
        .out_data(out_data),
        .out_valid(out_valid),
        .out_ready(out_ready),
        .tx_busy(tx_busy),
        .rx_busy(rx_busy),
        .overrun_error(overrun_error),
        .frame_error(frame_error)
    );
endmodule
