`timescale 1ns/1ps

module tb_uart_loopback;
    reg clk = 0;
    reg rst = 1;
    reg [15:0] prescale = 4;
    reg [7:0] in_data = 0;
    reg in_valid = 0;
    wire in_ready;
    wire [7:0] out_data;
    wire out_valid;
    reg out_ready = 0;
    wire tx_busy;
    wire rx_busy;
    wire overrun_error;
    wire frame_error;
    reg [7:0] expected [0:3];
    integer received = 0;
    integer cycle = 0;
    reg stalled = 0;
    reg [7:0] held_data = 0;

    uart_loopback_bd_wrapper dut (
        .clk(clk), .rst(rst), .prescale(prescale),
        .in_data(in_data), .in_valid(in_valid), .in_ready(in_ready),
        .out_data(out_data), .out_valid(out_valid), .out_ready(out_ready),
        .tx_busy(tx_busy), .rx_busy(rx_busy),
        .overrun_error(overrun_error), .frame_error(frame_error)
    );
    always #5 clk = ~clk;

    always @(negedge clk) begin
        if (rst) begin
            cycle = 0;
            out_ready = 0;
        end else begin
            cycle = cycle + 1;
            out_ready = (cycle % 7) < 3;
        end
    end

    always @(posedge clk) begin
        if (!rst) begin
            if (overrun_error || frame_error)
                $fatal(1, "UART reported an error");
            if (stalled && (!out_valid || out_data !== held_data))
                $fatal(1, "UART output changed while stalled");
            if (out_valid && out_ready) begin
                if (received >= 4 || out_data !== expected[received])
                    $fatal(1, "wrong UART word %0d: %02x", received, out_data);
                received = received + 1;
            end
            stalled = out_valid && !out_ready;
            held_data = out_data;
        end
    end

    task send_word;
        input [7:0] word;
        begin
            @(negedge clk);
            in_data = word;
            in_valid = 1;
            @(posedge clk);
            while (!in_ready) @(posedge clk);
            @(negedge clk);
            in_valid = 0;
        end
    endtask

    initial begin
        expected[0] = 8'h00;
        expected[1] = 8'hff;
        expected[2] = 8'h55;
        expected[3] = 8'ha6;
        repeat (4) @(negedge clk);
        if (out_valid || tx_busy || rx_busy)
            $fatal(1, "UART reset state is invalid");
        rst = 0;
        send_word(expected[0]);
        send_word(expected[1]);
        send_word(expected[2]);
        send_word(expected[3]);
        wait (received == 4);
        repeat (20) @(posedge clk);
        $display("PASS: buffered UART loopback, 4 words and backpressure");
        $finish;
    end

    initial begin
        #200000;
        $fatal(1, "UART loopback timed out");
    end
endmodule