`timescale 1ns/1ps
module tb;
    parameter CLKS_PER_BIT = 8;
    reg clk = 0, rst = 1, rx = 1, m_ready = 0;
    wire [7:0] m_data;
    wire m_valid, framing_error, overrun, busy;
    integer errors = 0, overruns = 0;
    always #5 clk = ~clk;
    always @(posedge clk) begin
        if (rst) begin errors = 0; overruns = 0; end
        else begin if (framing_error) errors = errors + 1; if (overrun) overruns = overruns + 1; end
    end
    bd_uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) dut(.clk(clk), .rst(rst), .rx(rx), .m_data(m_data), .m_valid(m_valid), .m_ready(m_ready), .framing_error(framing_error), .overrun(overrun), .busy(busy));
    task automatic send_byte(input [7:0] value, input stop_level);
        integer bit_index;
        begin
            rx = 0; repeat (CLKS_PER_BIT) @(negedge clk);
            for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1) begin
                rx = value[bit_index]; repeat (CLKS_PER_BIT) @(negedge clk);
            end
            rx = stop_level; repeat (CLKS_PER_BIT) @(negedge clk); rx = 1;
            repeat (4) @(negedge clk);
        end
    endtask
    initial begin
        repeat (3) @(negedge clk); rst = 0;
        rx = 0; @(negedge clk); rx = 1; repeat (CLKS_PER_BIT * 2) @(negedge clk);
        if (m_valid || errors) $fatal(1, "uart false start");
        send_byte(8'ha5, 1'b1);
        if (!m_valid || m_data !== 8'ha5 || errors) $fatal(1, "uart receive");
        send_byte(8'h5a, 1'b1);
        if (!m_valid || m_data !== 8'ha5 || overruns != 1) $fatal(1, "uart hold/drop newest");
        @(negedge clk); m_ready = 1; @(negedge clk); m_ready = 0;
        if (m_valid) $fatal(1, "uart consume");
        send_byte(8'h11, 1'b0);
        repeat (CLKS_PER_BIT + 4) @(negedge clk);
        if (errors != 1 || m_valid) $fatal(1, "uart framing");
        send_byte(8'h3c, 1'b1);
        if (!m_valid || m_data !== 8'h3c) $fatal(1, "uart recovery");
        $display("PASS bd_uart_rx"); $finish;
    end
    initial begin #1000000; $fatal(1, "uart rx timeout"); end
endmodule
