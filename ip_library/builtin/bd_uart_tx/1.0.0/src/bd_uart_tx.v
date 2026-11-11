module bd_uart_tx #(parameter integer CLKS_PER_BIT = 8) (
    input wire clk,
    input wire rst,
    input wire [7:0] s_data,
    input wire s_valid,
    output wire s_ready,
    output reg tx,
    output reg busy
);
    localparam TIMER_WIDTH = CLKS_PER_BIT > 1 ? $clog2(CLKS_PER_BIT) : 1;
    reg [TIMER_WIDTH-1:0] timer;
    reg [9:0] frame;
    reg [3:0] bit_index;
    assign s_ready = !rst && !busy;
    always @(posedge clk) begin
        if (rst) begin tx <= 1; busy <= 0; timer <= 0; frame <= 0; bit_index <= 0; end
        else if (!busy) begin
            tx <= 1;
            if (s_valid) begin
                frame <= {1'b1, s_data, 1'b0}; bit_index <= 0; timer <= 0; tx <= 0; busy <= 1;
            end
        end else if (timer == CLKS_PER_BIT - 1) begin
            timer <= 0;
            if (bit_index == 9) begin tx <= 1; busy <= 0; end
            else begin bit_index <= bit_index + 1'b1; tx <= frame[bit_index + 1'b1]; end
        end else timer <= timer + 1'b1;
    end
endmodule
