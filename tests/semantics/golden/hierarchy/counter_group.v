module counter_group (
    input wire boundary_clk_net,
    input wire boundary_rst_net,
    output wire boundary_match_net
);

    wire clk_net;
    wire rst_net;
    wire [31:0] count_bus;
    wire match_net;

    assign clk_net = boundary_clk_net;
    assign rst_net = boundary_rst_net;
    assign boundary_match_net = match_net;

    counter #(
        .WIDTH(32)
    ) counter_0 (
        .clk(clk_net),
        .rst(rst_net),
        .count(count_bus)
    );

    compare_eq #(
        .WIDTH(32),
        .THRESHOLD(9)
    ) compare_0 (
        .value(count_bus),
        .match(match_net)
    );
endmodule
