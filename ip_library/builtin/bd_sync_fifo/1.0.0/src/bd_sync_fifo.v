module bd_sync_fifo #(parameter integer WIDTH = 8, parameter integer DEPTH = 16) (
    input wire clk,
    input wire rst,
    input wire [WIDTH-1:0] s_data,
    input wire s_valid,
    output wire s_ready,
    output wire [WIDTH-1:0] m_data,
    output wire m_valid,
    input wire m_ready,
    output wire [$clog2(DEPTH+1)-1:0] level
);
    localparam PTR_WIDTH = DEPTH > 1 ? $clog2(DEPTH) : 1;
    localparam COUNT_WIDTH = $clog2(DEPTH+1);
    reg [WIDTH-1:0] storage [0:DEPTH-1];
    reg [PTR_WIDTH-1:0] write_pointer, read_pointer;
    reg [COUNT_WIDTH-1:0] occupancy;
    wire push = s_valid && s_ready;
    wire pop = m_valid && m_ready;
    assign m_valid = !rst && occupancy != 0;
    assign s_ready = !rst && (occupancy < DEPTH || pop);
    assign m_data = storage[read_pointer];
    assign level = occupancy;
    always @(posedge clk) begin
        if (rst) begin write_pointer <= 0; read_pointer <= 0; occupancy <= 0; end
        else begin
            if (push) begin
                storage[write_pointer] <= s_data;
                write_pointer <= write_pointer == DEPTH-1 ? 0 : write_pointer + 1'b1;
            end
            if (pop) read_pointer <= read_pointer == DEPTH-1 ? 0 : read_pointer + 1'b1;
            case ({push, pop})
                2'b10: occupancy <= occupancy + 1'b1;
                2'b01: occupancy <= occupancy - 1'b1;
                default: occupancy <= occupancy;
            endcase
        end
    end
endmodule
