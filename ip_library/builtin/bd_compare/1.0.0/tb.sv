`timescale 1ns/1ps
module tb;
    parameter WIDTH = 4;
    reg [WIDTH-1:0] left_data, right_data;
    wire equal, less, greater;
    integer left_index, right_index;
    bd_compare #(.WIDTH(WIDTH)) dut(.left_data(left_data), .right_data(right_data), .equal(equal), .less(less), .greater(greater));
    initial begin
        for (left_index = 0; left_index < 32; left_index = left_index + 1)
            for (right_index = 0; right_index < 32; right_index = right_index + 1) begin
                left_data = left_index; right_data = right_index;
                #1;
                if (equal !== (left_data == right_data) || less !== (left_data < right_data) || greater !== (left_data > right_data)) $fatal(1, "compare relation");
                if ((equal + less + greater) != 1) $fatal(1, "compare one hot");
            end
        left_data = {WIDTH{1'b1}}; right_data = 0;
        #1; if (!greater || less || equal) $fatal(1, "compare unsigned");
        $display("PASS bd_compare"); $finish;
    end
endmodule
