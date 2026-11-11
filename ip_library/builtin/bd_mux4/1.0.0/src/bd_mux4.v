module bd_mux4 #(parameter integer WIDTH = 8) (
    input wire [WIDTH-1:0] input0,
    input wire [WIDTH-1:0] input1,
    input wire [WIDTH-1:0] input2,
    input wire [WIDTH-1:0] input3,
    input wire [1:0] select,
    output reg [WIDTH-1:0] result
);
    always @* begin
        case (select)
            2'd0: result = input0;
            2'd1: result = input1;
            2'd2: result = input2;
            2'd3: result = input3;
            default: result = {WIDTH{1'b0}};
        endcase
    end
endmodule
