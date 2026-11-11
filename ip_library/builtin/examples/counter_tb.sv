`timescale 1ns/1ps
module tb;
    reg clk = 0, rst = 1, enable = 0, clear = 0;
    reg [7:0] threshold = 3, expected = 0;
    reg expected_overflow;
    wire [7:0] count;
    wire overflow, equal, less, greater;
    integer cycle_index;
    always #5 clk = ~clk;
    builtin_counter_bd_wrapper dut(.clk(clk), .rst(rst), .enable(enable), .clear(clear), .threshold(threshold),
        .count(count), .overflow(overflow), .equal(equal), .less(less), .greater(greater));
    initial begin
        repeat (3) @(negedge clk); rst = 0;
        for (cycle_index = 0; cycle_index < 400; cycle_index = cycle_index + 1) begin
            @(negedge clk); enable = cycle_index % 4 != 1; clear = cycle_index == 10; threshold = cycle_index % 23;
            @(posedge clk);
            expected_overflow = enable && !clear && expected == 8'hff;
            if (clear) expected = 0; else if (enable) expected = expected + 1'b1;
            #1;
            if (count !== expected || overflow !== expected_overflow) $fatal(1, "example counter");
            if (equal !== (expected == threshold) || less !== (expected < threshold) || greater !== (expected > threshold)) $fatal(1, "example comparison");
        end
        $display("PASS builtin_counter_bd"); $finish;
    end
    initial begin #1000000; $fatal(1, "example timeout"); end
endmodule
