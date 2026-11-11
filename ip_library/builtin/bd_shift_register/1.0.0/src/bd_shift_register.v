module bd_shift_register #(parameter integer WIDTH = 8) (
    input wire clk,
    input wire rst,
    input wire enable,
    input wire serial_in,
    output reg [WIDTH-1:0] parallel_out,
    output wire serial_out
);
    always @(posedge clk) begin
        if (rst) parallel_out <= {WIDTH{1'b0}};
        else if (enable) parallel_out <= (parallel_out << 1) | serial_in;
    end
    assign serial_out = parallel_out[WIDTH-1];
endmodule
