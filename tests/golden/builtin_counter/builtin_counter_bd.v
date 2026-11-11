module builtin_counter_bd (
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

    wire clk_net;
    wire rst_net;
    wire enable_net;
    wire clear_net;
    wire [7:0] count_bus;
    wire [7:0] threshold_bus;
    wire overflow_net;
    wire equal_net;
    wire less_net;
    wire greater_net;

    assign clk_net = clk;
    assign rst_net = rst;
    assign enable_net = enable;
    assign clear_net = clear;
    assign count = count_bus;
    assign threshold_bus = threshold;
    assign overflow = overflow_net;
    assign equal = equal_net;
    assign less = less_net;
    assign greater = greater_net;

    bd_counter #(
        .WIDTH(8)
    ) counter_0 (
        .clk(clk_net),
        .rst(rst_net),
        .enable(enable_net),
        .clear(clear_net),
        .count(count_bus),
        .overflow(overflow_net)
    );

    bd_compare #(
        .WIDTH(8)
    ) compare_0 (
        .left_data(count_bus),
        .right_data(threshold_bus),
        .equal(equal_net),
        .less(less_net),
        .greater(greater_net)
    );
endmodule
