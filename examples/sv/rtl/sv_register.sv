module sv_register #(parameter int WIDTH = 8) (
    input logic clk,
    input logic [WIDTH-1:0] data,
    output logic [WIDTH-1:0] result
);
    always_ff @(posedge clk) begin
        result <= data;
    end
endmodule
