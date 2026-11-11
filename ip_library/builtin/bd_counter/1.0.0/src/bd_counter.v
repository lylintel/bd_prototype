module bd_counter #(parameter integer WIDTH = 8) (
    input wire clk,
    input wire rst,
    input wire enable,
    input wire clear,
    output reg [WIDTH-1:0] count,
    output reg overflow
);
    always @(posedge clk) begin
        if (rst) begin
            count <= {WIDTH{1'b0}};
            overflow <= 1'b0;
        end else begin
            overflow <= 1'b0;
            if (clear) count <= {WIDTH{1'b0}};
            else if (enable) begin
                count <= count + 1'b1;
                overflow <= &count;
            end
        end
    end
endmodule
