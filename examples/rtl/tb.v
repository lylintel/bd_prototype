`timescale 1ns/1ps

module tb;
    reg clk = 0;
    reg rst = 1;
    wire match;
    integer threshold;
    integer cycle;

    example_bd_wrapper dut (.clk(clk), .rst(rst), .match(match));
    always #5 clk = ~clk;

    initial begin
        if (!$value$plusargs("threshold=%d", threshold))
            threshold = 9;

        repeat (2) @(negedge clk);
        if (match !== (threshold == 0))
            $fatal(1, "unexpected match after reset");
        rst = 0;

        // Check the first match and one counter wraparound.
        for (cycle = 1; cycle <= 256 + threshold + 1; cycle = cycle + 1) begin
            @(posedge clk);
            #1;
            if (match !== ((cycle % 256) == threshold))
                $fatal(1, "wrong match at cycle %0d", cycle);
        end

        $display("PASS: threshold=%0d and counter wraparound", threshold);
        $finish;
    end
endmodule
