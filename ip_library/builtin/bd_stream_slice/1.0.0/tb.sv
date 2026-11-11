`timescale 1ns/1ps
module tb;
    parameter WIDTH = 8;
    reg clk = 0, rst = 1, s_valid = 0, m_ready = 0;
    reg [WIDTH-1:0] s_data = 0, held_data;
    reg [WIDTH-1:0] expected [0:255];
    wire [WIDTH-1:0] m_data;
    wire s_ready, m_valid;
    integer writes = 0, reads = 0, cycle_index;
    reg stalled = 0, saw_stall = 0;
    always #5 clk = ~clk;
    bd_stream_slice #(.WIDTH(WIDTH)) dut(.clk(clk), .rst(rst), .s_data(s_data), .s_valid(s_valid), .s_ready(s_ready), .m_data(m_data), .m_valid(m_valid), .m_ready(m_ready));
    always @(posedge clk) begin
        if (rst) begin writes = 0; reads = 0; stalled = 0; end
        else begin
            if (stalled && (!m_valid || m_data !== held_data)) $fatal(1, "slice stall stability");
            if (m_valid && m_ready) begin
                if (reads >= writes || m_data !== expected[reads]) $fatal(1, "slice ordering");
                reads = reads + 1;
            end
            if (s_valid && s_ready) begin expected[writes] = s_data; writes = writes + 1; end
            stalled = m_valid && !m_ready; held_data = m_data;
            if (stalled) saw_stall = 1;
        end
    end
    initial begin
        repeat (2) @(negedge clk); rst = 0;
        for (cycle_index = 0; cycle_index < 100; cycle_index = cycle_index + 1) begin
            @(negedge clk); s_valid = cycle_index % 3 != 0; m_ready = cycle_index % 5 < 2; s_data = cycle_index;
        end
        @(negedge clk); s_valid = 0; m_ready = 1;
        repeat (4) @(negedge clk);
        if (writes < 10 || reads != writes || !saw_stall) $fatal(1, "slice coverage");
        $display("PASS bd_stream_slice"); $finish;
    end
    initial begin #1000000; $fatal(1, "slice timeout"); end
endmodule
