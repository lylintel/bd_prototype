module spike_ansi #(parameter WIDTH = 8) (
    input logic clk,
    input logic [WIDTH-1:0] data,
    output logic [WIDTH-1:0] result
);
    localparam TOTAL = WIDTH + 1;
    assign result = data;
endmodule

module spike_legacy(left, right, result);
    input [3:0] left, right;
    output reg [3:0] result;
    always @* result = left ^ right;
endmodule
