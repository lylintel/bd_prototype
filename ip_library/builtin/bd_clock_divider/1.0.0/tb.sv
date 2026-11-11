`timescale 1ns/1ps
module tb;
    parameter HALF_PERIOD = 3;
    reg clk = 0, rst = 1;
    wire out_clk, tick;
    integer cycle_index, expected_clock;
    reg expected_tick;
    always #5 clk = ~clk;
    bd_clock_divider #(.HALF_PERIOD(HALF_PERIOD)) dut(.clk(clk), .rst(rst), .out_clk(out_clk), .tick(tick));
    initial begin
        repeat (2) @(negedge clk); rst = 0;
        for (cycle_index = 1; cycle_index <= HALF_PERIOD * 12; cycle_index = cycle_index + 1) begin
            @(posedge clk); expected_clock = (cycle_index / HALF_PERIOD) % 2;
            expected_tick = cycle_index % HALF_PERIOD == 0 && expected_clock;
            #1; if (out_clk !== (expected_clock != 0) || tick !== expected_tick) $fatal(1, "divider period");
        end
        $display("PASS bd_clock_divider"); $finish;
    end
endmodule
