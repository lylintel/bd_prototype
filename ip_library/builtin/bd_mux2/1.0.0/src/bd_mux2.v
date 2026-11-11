module bd_mux2 #(parameter integer WIDTH = 8) (
    input wire [WIDTH-1:0] input0,
    input wire [WIDTH-1:0] input1,
    input wire select,
    output wire [WIDTH-1:0] result
);
    assign result = select ? input1 : input0;
endmodule
