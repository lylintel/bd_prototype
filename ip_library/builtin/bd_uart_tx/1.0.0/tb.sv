`timescale 1ns/1ps
module tb;
    parameter CLKS_PER_BIT = 8;
    reg clk = 0, rst = 1, s_valid = 0;
    reg [7:0] s_data = 0, sampled;
    reg [7:0] expected [0:2];
    wire s_ready, tx, busy;
    integer frame_index, bit_index;
    always #5 clk = ~clk;
    bd_uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) dut(.clk(clk), .rst(rst), .s_data(s_data), .s_valid(s_valid), .s_ready(s_ready), .tx(tx), .busy(busy));
    task automatic send_byte(input [7:0] value);
        begin
            @(negedge clk); while (!s_ready) @(negedge clk);
            s_data = value; s_valid = 1;
            @(negedge clk); s_valid = 0;
        end
    endtask
    initial begin
        expected[0] = 8'h00; expected[1] = 8'ha5; expected[2] = 8'hff;
        repeat (3) @(negedge clk); rst = 0;
        fork
            begin send_byte(expected[0]); send_byte(expected[1]); send_byte(expected[2]); end
            begin
                for (frame_index = 0; frame_index < 3; frame_index = frame_index + 1) begin
                    @(negedge tx); repeat (CLKS_PER_BIT / 2) @(posedge clk);
                    #1; if (tx !== 0 || !busy) $fatal(1, "uart start");
                    for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1) begin
                        repeat (CLKS_PER_BIT) @(posedge clk); #1; sampled[bit_index] = tx;
                    end
                    repeat (CLKS_PER_BIT) @(posedge clk);
                    #1; if (tx !== 1 || sampled !== expected[frame_index]) $fatal(1, "uart payload/stop");
                end
            end
        join
        wait (s_ready);
        send_byte(8'h55); repeat (CLKS_PER_BIT + 2) @(negedge clk); rst = 1;
        @(posedge clk); #1; if (tx !== 1 || busy) $fatal(1, "uart reset abort");
        $display("PASS bd_uart_tx"); $finish;
    end
    initial begin #1000000; $fatal(1, "uart tx timeout"); end
endmodule
