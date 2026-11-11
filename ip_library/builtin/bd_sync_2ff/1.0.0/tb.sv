`timescale 1ns/1ps
module tb;
    reg clk = 0, rstn = 0, async_in = 0;
    reg expected_first = 0, expected_second = 0;
    wire sync_out;
    integer cycle_index;
    always #5 clk = ~clk;
    bd_sync_2ff dut(.clk(clk), .rstn(rstn), .async_in(async_in), .sync_out(sync_out));
    initial begin
        repeat (2) @(negedge clk); rstn = 1;
        for (cycle_index = 0; cycle_index < 40; cycle_index = cycle_index + 1) begin
            @(negedge clk); async_in = cycle_index % 5 < 2;
            @(posedge clk); expected_second = expected_first; expected_first = async_in;
            #1; if (sync_out !== expected_second) $fatal(1, "sync latency");
        end
        @(negedge clk); rstn = 0;
        #1; if (sync_out !== 0) $fatal(1, "sync reset");
        $display("PASS bd_sync_2ff"); $finish;
    end
endmodule
