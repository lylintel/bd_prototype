module bd_simple_dual_port_ram #(parameter integer WIDTH = 8, parameter integer ADDR_WIDTH = 4) (
    input wire wr_clk,
    input wire wr_enable,
    input wire [ADDR_WIDTH-1:0] wr_address,
    input wire [WIDTH-1:0] wr_data,
    input wire rd_clk,
    input wire rd_rst,
    input wire rd_enable,
    input wire [ADDR_WIDTH-1:0] rd_address,
    output reg [WIDTH-1:0] rd_data,
    output reg rd_valid
);
    localparam DEPTH = 1 << ADDR_WIDTH;
    reg [WIDTH-1:0] storage [0:DEPTH-1];
    always @(posedge wr_clk) begin
        if (wr_enable) storage[wr_address] <= wr_data;
    end
    always @(posedge rd_clk) begin
        if (rd_rst) begin rd_data <= 0; rd_valid <= 0; end
        else begin
            rd_valid <= rd_enable;
            if (rd_enable) rd_data <= storage[rd_address];
        end
    end
endmodule
