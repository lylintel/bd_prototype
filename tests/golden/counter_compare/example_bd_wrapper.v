module example_bd_wrapper (
    input wire clk,
    input wire rst,
    output wire match
);

    example_bd bd_i (
        .clk(clk),
        .rst(rst),
        .match(match)
    );
endmodule
