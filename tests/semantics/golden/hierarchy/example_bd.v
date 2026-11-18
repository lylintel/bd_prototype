module example_bd (
    input wire clk,
    input wire rst,
    output wire match
);

    wire clk_net;
    wire rst_net;
    wire match_net;

    assign clk_net = clk;
    assign rst_net = rst;
    assign match = match_net;

    counter_group counter_group (
        .boundary_clk_net(clk_net),
        .boundary_rst_net(rst_net),
        .boundary_match_net(match_net)
    );
endmodule
