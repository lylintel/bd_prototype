module builtin_counter_bd_wrapper (
    input wire clk,
    input wire rst,
    input wire enable,
    input wire clear,
    output wire [7:0] count,
    output wire overflow,
    input wire [7:0] threshold,
    output wire equal,
    output wire less,
    output wire greater
);

    builtin_counter_bd bd_i (
        .clk(clk),
        .rst(rst),
        .enable(enable),
        .clear(clear),
        .count(count),
        .overflow(overflow),
        .threshold(threshold),
        .equal(equal),
        .less(less),
        .greater(greater)
    );
endmodule
