module bd_stream_slice #(parameter integer WIDTH = 8) (
    input wire clk,
    input wire rst,
    input wire [WIDTH-1:0] s_data,
    input wire s_valid,
    output wire s_ready,
    output reg [WIDTH-1:0] m_data,
    output reg m_valid,
    input wire m_ready
);
    assign s_ready = !m_valid || m_ready;
    always @(posedge clk) begin
        if (rst) begin m_valid <= 0; m_data <= 0; end
        else if (s_ready) begin
            m_valid <= s_valid;
            if (s_valid) m_data <= s_data;
        end
    end
endmodule
