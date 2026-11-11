`timescale 1ns/1ps
module tb;
    parameter WIDTH = 8;
    reg clk = 0, rst = 1, enable = 0, serial_in = 0;
    reg [WIDTH-1:0] expected = 0;
    wire [WIDTH-1:0] parallel_out;
    wire serial_out;
    integer cycle_index;
    always #5 clk = ~clk;
    bd_shift_register #(.WIDTH(WIDTH)) dut(.clk(clk), .rst(rst), .enable(enable), .serial_in(serial_in), .parallel_out(parallel_out), .serial_out(serial_out));
    initial begin
        repeat (2) @(negedge clk); rst = 0;
        for (cycle_index = 0; cycle_index < 80; cycle_index = cycle_index + 1) begin
            @(negedge clk); enable = cycle_index % 3 != 0; serial_in = cycle_index % 5 < 2;
            @(posedge clk); if (enable) expected = expected * 2 + serial_in;
            #1; if (parallel_out !== expected || serial_out !== expected[WIDTH-1]) $fatal(1, "shift state");
        end
        $display("PASS bd_shift_register"); $finish;
    end
endmodule
