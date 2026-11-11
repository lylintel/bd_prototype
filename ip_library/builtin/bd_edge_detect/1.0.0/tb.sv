`timescale 1ns/1ps
module tb;
    reg clk = 0, rst = 1, signal_in = 0, previous = 0;
    reg expected_rising, expected_falling;
    wire rising, falling;
    integer cycle_index;
    always #5 clk = ~clk;
    bd_edge_detect dut(.clk(clk), .rst(rst), .signal_in(signal_in), .rising(rising), .falling(falling));
    initial begin
        repeat (2) @(negedge clk); rst = 0;
        for (cycle_index = 0; cycle_index < 40; cycle_index = cycle_index + 1) begin
            @(negedge clk); signal_in = cycle_index % 7 < 3;
            @(posedge clk); expected_rising = signal_in && !previous; expected_falling = !signal_in && previous; previous = signal_in;
            #1; if (rising !== expected_rising || falling !== expected_falling) $fatal(1, "edge pulse");
        end
        @(negedge clk); rst = 1;
        @(posedge clk); #1; if (rising || falling) $fatal(1, "edge reset");
        $display("PASS bd_edge_detect"); $finish;
    end
endmodule
