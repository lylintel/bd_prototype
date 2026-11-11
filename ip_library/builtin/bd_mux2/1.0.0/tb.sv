`timescale 1ns/1ps
module tb;
    parameter WIDTH = 8;
    reg [WIDTH-1:0] input0, input1;
    reg select;
    wire [WIDTH-1:0] result;
    integer sample_index;
    bd_mux2 #(.WIDTH(WIDTH)) dut(.input0(input0), .input1(input1), .select(select), .result(result));
    initial begin
        for (sample_index = 0; sample_index < 64; sample_index = sample_index + 1) begin
            input0 = sample_index; input1 = ~sample_index; select = 0;
            #1; if (result !== input0) $fatal(1, "mux2 input0");
            select = 1;
            #1; if (result !== input1) $fatal(1, "mux2 input1");
        end
        $display("PASS bd_mux2"); $finish;
    end
endmodule
