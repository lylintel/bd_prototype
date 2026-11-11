module example_bd (
    input wire clk,
    input wire rst,
    output wire match
);

    wire clk_net;
    wire rst_net;
    wire [7:0] count_bus;
    wire match_net;

    assign clk_net = clk;
    assign rst_net = rst;
    assign match = match_net;

    counter #(
        .WIDTH(8)
    ) counter_0 (
        .clk(clk_net),
        .rst(rst_net),
        .count(count_bus)
    );

    compare_eq #(
        .WIDTH(8),
        .THRESHOLD(9)
    ) compare_0 (
        .value(count_bus),
        .match(match_net)
    );
endmodule
