module bd_debounce #(parameter integer STABLE_CYCLES = 4) (
    input wire clk,
    input wire rst,
    input wire raw_in,
    output reg level,
    output reg changed
);
    localparam COUNT_WIDTH = STABLE_CYCLES > 1 ? $clog2(STABLE_CYCLES) : 1;
    (* ASYNC_REG = "TRUE" *) reg first_sample, second_sample;
    reg [COUNT_WIDTH-1:0] stable_count;
    always @(posedge clk) begin
        if (rst) begin
            first_sample <= 0; second_sample <= 0; stable_count <= 0; level <= 0; changed <= 0;
        end else begin
            first_sample <= raw_in; second_sample <= first_sample; changed <= 0;
            if (second_sample == level) stable_count <= 0;
            else if (stable_count == STABLE_CYCLES - 1) begin
                level <= second_sample; changed <= 1; stable_count <= 0;
            end else stable_count <= stable_count + 1'b1;
        end
    end
endmodule
