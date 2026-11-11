`timescale 1ns/1ps
module tb;
    parameter ADDR_WIDTH = 2;
    reg wr_clk = 0, rd_clk = 0, wr_rst_n = 0, rd_rst_n = 0;
    reg [7:0] s_data = 0, held_data;
    reg s_valid = 0, m_ready = 0;
    wire [7:0] m_data;
    wire s_ready, m_valid;
    integer sent = 0, received = 0, write_cycles = 0, read_cycles = 0;
    reg stalled = 0, saw_full = 0;
    always #3 wr_clk = ~wr_clk;
    always #5 rd_clk = ~rd_clk;
    bd_async_fifo #(.WIDTH(8), .ADDR_WIDTH(ADDR_WIDTH)) dut(.wr_clk(wr_clk), .wr_rst_n(wr_rst_n), .s_data(s_data), .s_valid(s_valid), .s_ready(s_ready), .rd_clk(rd_clk), .rd_rst_n(rd_rst_n), .m_data(m_data), .m_valid(m_valid), .m_ready(m_ready));
    always @(posedge wr_clk) begin
        if (!wr_rst_n) sent = 0;
        else begin
            if (s_valid && s_ready) sent = sent + 1;
            if (!s_ready && s_valid) saw_full = 1;
        end
    end
    always @(posedge rd_clk) begin
        if (!rd_rst_n) begin received = 0; stalled = 0; end
        else begin
            if (stalled && (!m_valid || m_data !== held_data)) $fatal(1, "async fifo stall");
            if (m_valid && m_ready) begin
                if (m_data !== received[7:0]) $fatal(1, "async fifo ordering");
                received = received + 1;
            end
            stalled = m_valid && !m_ready; held_data = m_data;
        end
    end
    initial begin
        repeat (4) @(negedge wr_clk); wr_rst_n = 1;
        @(negedge rd_clk); rd_rst_n = 1;
        fork
            begin
                while (sent < 80) begin
                    @(negedge wr_clk); s_valid = sent < 80 && write_cycles % 7 != 0; s_data = sent; write_cycles = write_cycles + 1;
                end
                @(negedge wr_clk); s_valid = 0;
            end
            begin
                while (received < 80) begin
                    @(negedge rd_clk); m_ready = received < 80 && read_cycles % 4 < 2; read_cycles = read_cycles + 1;
                end
                @(negedge rd_clk); m_ready = 0;
            end
        join
        repeat (8) @(negedge rd_clk);
        if (sent != 80 || received != 80 || !saw_full || m_valid) $fatal(1, "async fifo coverage");
        $display("PASS bd_async_fifo"); $finish;
    end
    initial begin #1000000; $fatal(1, "async fifo timeout"); end
endmodule
