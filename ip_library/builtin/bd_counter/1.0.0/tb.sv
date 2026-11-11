`timescale 1ns/1ps
module tb;
    parameter WIDTH = 4;
    reg clk = 0, rst = 1, enable = 0, clear = 0;
    reg [WIDTH-1:0] expected = 0;
    reg expected_overflow;
    wire [WIDTH-1:0] count;
    wire overflow;
    integer cycle_index;
    always #5 clk = ~clk;
    bd_counter #(.WIDTH(WIDTH)) dut(.clk(clk), .rst(rst), .enable(enable), .clear(clear), .count(count), .overflow(overflow));
    initial begin
        repeat (2) @(negedge clk); rst = 0;
        for (cycle_index = 0; cycle_index < (1 << WIDTH) * 3 + 40; cycle_index = cycle_index + 1) begin
            @(negedge clk); enable = cycle_index % 3 != 0; clear = cycle_index == 23;
            @(posedge clk);
            expected_overflow = enable && !clear && (&expected);
            if (clear) expected = 0;
            else if (enable) expected = expected + 1'b1;
            #1; if (count !== expected || overflow !== expected_overflow) $fatal(1, "counter state");
        end
        $display("PASS bd_counter"); $finish;
    end
    initial begin #1000000; $fatal(1, "counter timeout"); end
endmodule
