module compare_eq #(
    parameter integer WIDTH = 8,
    parameter integer THRESHOLD = 9
) (
    input  wire [WIDTH-1:0] value,
    output wire             match
);
    assign match = (value == THRESHOLD);
endmodule
