`timescale 1ns/1ps
module tb;
    reg clk = 0;
    reg rst = 1;
    reg [7:0] in_data = 0;
    reg in_valid = 0;
    wire in_ready;
    wire [7:0] out_data;
    wire out_valid;
    reg out_ready = 0;
    reg [15:0] random_state = 16'h5a37;
    reg accepted_input = 0;
    reg stalled = 0;
    reg [7:0] held_data = 0;
    integer sent = 0;
    integer received = 0;
    integer total_received = 0;
    integer stalled_cycles = 0;
    integer cycle;

    axis_pair_wrapper dut(.clk(clk), .rst(rst), .in_data(in_data), .in_valid(in_valid),
        .in_ready(in_ready), .out_data(out_data), .out_valid(out_valid), .out_ready(out_ready));
    always #5 clk = ~clk;

    always @(posedge clk) begin
        if (rst) begin
            sent = 0;
            received = 0;
            accepted_input = 0;
            stalled = 0;
        end else begin
            if (stalled && (!out_valid || out_data !== held_data)) $fatal(1, "Payload or VALID changed under backpressure");
            if (out_valid && out_ready) begin
                if (received >= sent) $fatal(1, "Unexpected or duplicated transfer");
                if (out_data !== received[7:0]) $fatal(1, "Transfer reordered or corrupted");
                received = received + 1;
                total_received = total_received + 1;
            end
            accepted_input = in_valid && in_ready;
            if (accepted_input) sent = sent + 1;
            if (sent - received > 2) $fatal(1, "Pipeline lost a transfer");
            stalled = out_valid && !out_ready;
            held_data = out_data;
            if (stalled) stalled_cycles = stalled_cycles + 1;
        end
    end

    initial begin
        repeat (3) @(negedge clk);
        rst = 0;
        for (cycle = 0; cycle < 1024; cycle = cycle + 1) begin
            @(negedge clk);
            random_state = {random_state[14:0], random_state[15] ^ random_state[13] ^ random_state[12] ^ random_state[10]};
            if (cycle == 200) begin
                rst = 1;
                in_valid = 0;
                out_ready = 0;
            end else if (cycle == 203) rst = 0;
            else if (!rst) begin
                if (accepted_input || !in_valid) begin
                    in_valid = random_state[0] || random_state[2];
                    in_data = sent[7:0];
                end
                out_ready = random_state[1] || random_state[3];
            end
        end
        repeat (20) begin
            @(negedge clk);
            if (accepted_input || !in_valid) in_valid = 0;
            out_ready = 1;
        end
        @(negedge clk);
        if (received != sent || out_valid) $fatal(1, "Pipeline did not drain exactly");
        if (received < 256 || total_received < 300 || stalled_cycles < 20) $fatal(1, "Insufficient handshake coverage");
        $display("PASS AXIS received=%0d total=%0d stalled=%0d", received, total_received, stalled_cycles);
        $finish;
    end

    initial begin
        #200000;
        $fatal(1, "Handshake test timed out");
    end
endmodule