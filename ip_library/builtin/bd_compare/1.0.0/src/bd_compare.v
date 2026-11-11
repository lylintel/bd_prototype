module bd_compare #(parameter integer WIDTH = 8) (
    input wire [WIDTH-1:0] left_data,
    input wire [WIDTH-1:0] right_data,
    output wire equal,
    output wire less,
    output wire greater
);
    assign equal = left_data == right_data;
    assign less = left_data < right_data;
    assign greater = left_data > right_data;
endmodule
