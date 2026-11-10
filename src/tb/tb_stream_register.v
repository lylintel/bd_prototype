`timescale 1ns/1ps

module tb_stream_register;
    parameter integer REG_TYPE = 2;
    reg clk = 0;
    reg rst = 1;
    reg [15:0] in_data = 0;
    reg in_valid = 0;
    wire in_ready;
    wire [15:0] out_data;
    wire out_valid;
    reg out_ready = 0;
    reg input_accepted = 0;
    reg stalled = 0;
    reg [15:0] held_data = 0;
    integer sent = 0;
    integer received = 0;
    integer cycle;

    bd_stream_register #(.DATA_WIDTH(16), .REG_TYPE(REG_TYPE)) dut (
        .clk(clk), .rst(rst), .in_data(in_data), .in_valid(in_valid),
        .in_ready(in_ready), .out_data(out_data), .out_valid(out_valid), .out_ready(out_ready)
    );
    always #5 clk = ~clk;

    initial begin
        repeat (4) @(negedge clk);
        rst = 0;
        for (cycle = 0; cycle < 1000; cycle = cycle + 1) begin
            @(negedge clk);
            if (!in_valid || input_accepted) begin
                in_valid = sent < 64 && (cycle % 5) != 0;
                in_data = 16'h1200 + sent;
            end
            out_ready = (cycle % 9) >= 4;
            @(posedge clk);
            if (stalled && (!out_valid || out_data !== held_data))
                $fatal(1, "stream output changed while stalled");
            input_accepted = in_valid && in_ready;
            if (input_accepted)
                sent = sent + 1;
            if (out_valid && out_ready) begin
                if (received >= sent || out_data !== (16'h1200 + received))
                    $fatal(1, "stream data lost, duplicated or reordered at word %0d", received);
                received = received + 1;
            end
            stalled = out_valid && !out_ready;
            held_data = out_data;
            if (received == 64) begin
                if (sent != 64)
                    $fatal(1, "stream transaction count mismatch");
                $display("PASS: stream mode=%0d, 64 words with backpressure", REG_TYPE);
                $finish;
            end
        end
        $fatal(1, "stream register timed out");
    end
endmodule