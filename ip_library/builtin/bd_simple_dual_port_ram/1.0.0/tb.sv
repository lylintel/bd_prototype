`timescale 1ns/1ps
module tb;
    parameter ADDR_WIDTH = 4;
    reg wr_clk = 0, rd_clk = 0, wr_enable = 0, rd_enable = 0, rd_rst = 1;
    reg [ADDR_WIDTH-1:0] wr_address = 0, rd_address = 0;
    reg [7:0] wr_data = 0, expected, held_data;
    wire [7:0] rd_data;
    wire rd_valid;
    integer address_index;
    always #3 wr_clk = ~wr_clk;
    always #5 rd_clk = ~rd_clk;
    bd_simple_dual_port_ram #(.WIDTH(8), .ADDR_WIDTH(ADDR_WIDTH)) dut(.wr_clk(wr_clk), .wr_enable(wr_enable), .wr_address(wr_address), .wr_data(wr_data), .rd_clk(rd_clk), .rd_rst(rd_rst), .rd_enable(rd_enable), .rd_address(rd_address), .rd_data(rd_data), .rd_valid(rd_valid));
    initial begin
        repeat (3) @(negedge rd_clk); rd_rst = 0;
        for (address_index = 0; address_index < (1 << ADDR_WIDTH); address_index = address_index + 1) begin
            @(negedge wr_clk); wr_enable = 1; wr_address = address_index; wr_data = address_index * 3 + 7;
        end
        @(negedge wr_clk); wr_enable = 0;
        for (address_index = 0; address_index < (1 << ADDR_WIDTH); address_index = address_index + 1) begin
            @(negedge rd_clk); rd_enable = 1; rd_address = address_index; expected = address_index * 3 + 7;
            @(posedge rd_clk); #1; if (!rd_valid || rd_data !== expected) $fatal(1, "ram read latency/data");
        end
        @(negedge rd_clk); held_data = rd_data; rd_enable = 0; rd_address = 0;
        repeat (3) begin @(posedge rd_clk); #1; if (rd_valid || rd_data !== held_data) $fatal(1, "ram read hold"); end
        @(negedge rd_clk); rd_rst = 1;
        @(posedge rd_clk); #1; if (rd_valid || rd_data !== 0) $fatal(1, "ram output reset");
        @(negedge rd_clk); rd_rst = 0; rd_enable = 1; rd_address = 0;
        @(posedge rd_clk); #1; if (rd_data !== 8'd7) $fatal(1, "ram contents preserved");
        $display("PASS bd_simple_dual_port_ram"); $finish;
    end
    initial begin #1000000; $fatal(1, "ram timeout"); end
endmodule
