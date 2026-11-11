module bd_async_fifo #(parameter integer WIDTH = 8, parameter integer ADDR_WIDTH = 3) (
    input wire wr_clk,
    input wire wr_rst_n,
    input wire [WIDTH-1:0] s_data,
    input wire s_valid,
    output wire s_ready,
    input wire rd_clk,
    input wire rd_rst_n,
    output wire [WIDTH-1:0] m_data,
    output wire m_valid,
    input wire m_ready
);
    localparam DEPTH = 1 << ADDR_WIDTH;
    reg [WIDTH-1:0] storage [0:DEPTH-1];
    reg [ADDR_WIDTH:0] write_binary, write_gray, read_binary, read_gray;
    (* ASYNC_REG = "TRUE" *) reg [ADDR_WIDTH:0] read_sync_first, read_sync_second;
    (* ASYNC_REG = "TRUE" *) reg [ADDR_WIDTH:0] write_sync_first, write_sync_second;
    reg full, empty;
    wire write_fire = s_valid && s_ready;
    wire read_fire = m_valid && m_ready;
    wire [ADDR_WIDTH:0] write_next = write_binary + write_fire;
    wire [ADDR_WIDTH:0] read_next = read_binary + read_fire;
    wire [ADDR_WIDTH:0] write_gray_next = (write_next >> 1) ^ write_next;
    wire [ADDR_WIDTH:0] read_gray_next = (read_next >> 1) ^ read_next;
    wire [ADDR_WIDTH:0] full_target = read_sync_second ^ ((1 << ADDR_WIDTH) | (1 << (ADDR_WIDTH-1)));
    assign s_ready = wr_rst_n && !full;
    assign m_valid = rd_rst_n && !empty;
    assign m_data = storage[read_binary[ADDR_WIDTH-1:0]];
    always @(posedge wr_clk or negedge wr_rst_n) begin
        if (!wr_rst_n) begin
            write_binary <= 0; write_gray <= 0; full <= 0;
            read_sync_first <= 0; read_sync_second <= 0;
        end else begin
            read_sync_first <= read_gray; read_sync_second <= read_sync_first;
            write_binary <= write_next; write_gray <= write_gray_next;
            full <= write_gray_next == full_target;
            if (write_fire) storage[write_binary[ADDR_WIDTH-1:0]] <= s_data;
        end
    end
    always @(posedge rd_clk or negedge rd_rst_n) begin
        if (!rd_rst_n) begin
            read_binary <= 0; read_gray <= 0; empty <= 1;
            write_sync_first <= 0; write_sync_second <= 0;
        end else begin
            write_sync_first <= write_gray; write_sync_second <= write_sync_first;
            read_binary <= read_next; read_gray <= read_gray_next;
            empty <= read_gray_next == write_sync_second;
        end
    end
endmodule
