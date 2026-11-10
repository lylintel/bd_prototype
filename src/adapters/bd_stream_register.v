module bd_stream_register #(
    parameter integer DATA_WIDTH = 8,
    parameter integer REG_TYPE = 2
) (
    input  wire                  clk,
    input  wire                  rst,
    input  wire [DATA_WIDTH-1:0] in_data,
    input  wire                  in_valid,
    output wire                  in_ready,
    output wire [DATA_WIDTH-1:0] out_data,
    output wire                  out_valid,
    input  wire                  out_ready
);
    axis_register #(
        .DATA_WIDTH(DATA_WIDTH),
        .KEEP_ENABLE(0),
        .KEEP_WIDTH(1),
        .LAST_ENABLE(0),
        .ID_ENABLE(0),
        .ID_WIDTH(1),
        .DEST_ENABLE(0),
        .DEST_WIDTH(1),
        .USER_ENABLE(0),
        .USER_WIDTH(1),
        .REG_TYPE(REG_TYPE)
    ) register_inst (
        .clk(clk),
        .rst(rst),
        .s_axis_tdata(in_data),
        .s_axis_tkeep(1'b1),
        .s_axis_tvalid(in_valid),
        .s_axis_tready(in_ready),
        .s_axis_tlast(1'b1),
        .s_axis_tid(1'b0),
        .s_axis_tdest(1'b0),
        .s_axis_tuser(1'b0),
        .m_axis_tdata(out_data),
        .m_axis_tkeep(),
        .m_axis_tvalid(out_valid),
        .m_axis_tready(out_ready),
        .m_axis_tlast(),
        .m_axis_tid(),
        .m_axis_tdest(),
        .m_axis_tuser()
    );
endmodule