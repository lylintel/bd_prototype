`timescale 1ns/1ps
module tb;
    parameter CLOCK_DIV = 3;
    reg clk = 0, rst = 1, start = 0, miso = 0;
    reg [7:0] tx_data = 0, reply = 0, captured = 0;
    wire ready, busy, sclk, mosi, cs_n, done;
    wire [7:0] rx_data;
    integer slave_bit, edges;
    always #5 clk = ~clk;
    bd_spi_master #(.CLOCK_DIV(CLOCK_DIV)) dut(.clk(clk), .rst(rst), .start(start), .tx_data(tx_data), .miso(miso), .ready(ready), .busy(busy), .sclk(sclk), .mosi(mosi), .cs_n(cs_n), .rx_data(rx_data), .done(done));
    always @(negedge cs_n) begin slave_bit = 7; edges = 0; captured = 0; miso = reply[7]; end
    always @(posedge sclk) if (!cs_n) begin captured = {captured[6:0], mosi}; edges = edges + 1; end
    always @(negedge sclk) if (!cs_n && slave_bit > 0) begin slave_bit = slave_bit - 1; miso = reply[slave_bit]; end
    task automatic transfer(input [7:0] value, input [7:0] response);
        begin
            wait (ready); @(negedge clk); tx_data = value; reply = response; start = 1;
            @(negedge clk); start = 0;
            repeat (2) @(negedge clk); start = 1; tx_data = ~value;
            @(negedge clk); start = 0;
            wait (done); #1;
            if (rx_data !== response || captured !== value || edges != 8 || !cs_n || sclk || busy) $fatal(1, "spi transaction");
            @(negedge clk);
        end
    endtask
    initial begin
        repeat (3) @(negedge clk); rst = 0;
        transfer(8'ha6, 8'h3c); transfer(8'h39, 8'hc3);
        @(negedge clk); start = 1; @(negedge clk); start = 0;
        repeat (3) @(negedge clk); rst = 1;
        @(posedge clk); #1; if (busy || !cs_n || sclk || done) $fatal(1, "spi reset");
        $display("PASS bd_spi_master"); $finish;
    end
    initial begin #1000000; $fatal(1, "spi timeout"); end
endmodule
