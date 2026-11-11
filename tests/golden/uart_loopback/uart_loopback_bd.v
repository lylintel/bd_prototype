module uart_loopback_bd (
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

    wire clk_net;
    wire rst_net;
    wire [15:0] prescale_net;
    wire [7:0] input_data_net;
    wire input_valid_net;
    wire input_ready_net;
    wire [7:0] buffer_data_net;
    wire buffer_valid_net;
    wire buffer_ready_net;
    wire serial_net;
    wire [7:0] output_data_net;
    wire output_valid_net;
    wire output_ready_net;
    wire tx_busy_net;
    wire rx_busy_net;
    wire overrun_net;
    wire frame_net;

    assign clk_net = clk;
    assign rst_net = rst;
    assign prescale_net = prescale;
    assign input_data_net = in_data;
    assign input_valid_net = in_valid;
    assign in_ready = input_ready_net;
    assign out_data = output_data_net;
    assign out_valid = output_valid_net;
    assign output_ready_net = out_ready;
    assign tx_busy = tx_busy_net;
    assign rx_busy = rx_busy_net;
    assign overrun_error = overrun_net;
    assign frame_error = frame_net;

    bd_stream_register #(
        .DATA_WIDTH(8),
        .REG_TYPE(2)
    ) buffer_0 (
        .clk(clk_net),
        .rst(rst_net),
        .in_data(input_data_net),
        .in_valid(input_valid_net),
        .in_ready(input_ready_net),
        .out_data(buffer_data_net),
        .out_valid(buffer_valid_net),
        .out_ready(buffer_ready_net)
    );

    uart_tx #(
        .DATA_WIDTH(8)
    ) tx_0 (
        .clk(clk_net),
        .rst(rst_net),
        .s_axis_tdata(buffer_data_net),
        .s_axis_tvalid(buffer_valid_net),
        .s_axis_tready(buffer_ready_net),
        .txd(serial_net),
        .busy(tx_busy_net),
        .prescale(prescale_net)
    );

    uart_rx #(
        .DATA_WIDTH(8)
    ) rx_0 (
        .clk(clk_net),
        .rst(rst_net),
        .m_axis_tdata(output_data_net),
        .m_axis_tvalid(output_valid_net),
        .m_axis_tready(output_ready_net),
        .rxd(serial_net),
        .busy(rx_busy_net),
        .overrun_error(overrun_net),
        .frame_error(frame_net),
        .prescale(prescale_net)
    );
endmodule
