module bd_clock_divider #(parameter integer HALF_PERIOD = 2) (
    input wire clk,
    input wire rst,
    output reg out_clk,
    output reg tick
);
    localparam COUNT_WIDTH = HALF_PERIOD > 1 ? $clog2(HALF_PERIOD) : 1;
    reg [COUNT_WIDTH-1:0] counter;
    always @(posedge clk) begin
        if (rst) begin counter <= 0; out_clk <= 1'b0; tick <= 1'b0; end
        else begin
            tick <= 1'b0;
            if (counter == HALF_PERIOD - 1) begin
                counter <= 0;
                out_clk <= ~out_clk;
                tick <= ~out_clk;
            end else counter <= counter + 1'b1;
        end
    end
endmodule
