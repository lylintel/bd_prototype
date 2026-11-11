`timescale 1ns/1ps
module tb;
    parameter STABLE_CYCLES = 4;
    reg clk = 0, rst = 1, raw_in = 0;
    wire level, changed;
    integer pulses = 0;
    always #5 clk = ~clk;
    always @(posedge clk) if (rst) pulses = 0; else if (changed) pulses = pulses + 1;
    bd_debounce #(.STABLE_CYCLES(STABLE_CYCLES)) dut(.clk(clk), .rst(rst), .raw_in(raw_in), .level(level), .changed(changed));
    initial begin
        repeat (3) @(negedge clk); rst = 0;
        raw_in = 1; @(negedge clk); raw_in = 0;
        repeat (STABLE_CYCLES + 6) @(negedge clk);
        if (level || pulses != 0) $fatal(1, "debounce glitch");
        raw_in = 1; repeat (STABLE_CYCLES + 6) @(negedge clk);
        if (!level || pulses != 1) $fatal(1, "debounce rising");
        repeat (5) @(negedge clk);
        if (pulses != 1) $fatal(1, "debounce repeated pulse");
        raw_in = 0; @(negedge clk); raw_in = 1; @(negedge clk); raw_in = 0;
        repeat (STABLE_CYCLES + 6) @(negedge clk);
        if (level || pulses != 2) $fatal(1, "debounce falling");
        $display("PASS bd_debounce"); $finish;
    end
endmodule
