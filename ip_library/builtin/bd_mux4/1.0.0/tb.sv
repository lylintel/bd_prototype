`timescale 1ns/1ps
module tb;
    parameter WIDTH = 8;
    reg [WIDTH-1:0] input0, input1, input2, input3, expected;
    reg [4*WIDTH-1:0] packed_inputs;
    reg [1:0] select;
    wire [WIDTH-1:0] result;
    integer sample_index, choice;
    bd_mux4 #(.WIDTH(WIDTH)) dut(.input0(input0), .input1(input1), .input2(input2), .input3(input3), .select(select), .result(result));
    initial begin
        for (sample_index = 0; sample_index < 64; sample_index = sample_index + 1) begin
            input0 = sample_index; input1 = ~sample_index; input2 = sample_index ^ 8'h55; input3 = sample_index + 1;
            packed_inputs = {input3, input2, input1, input0};
            for (choice = 0; choice < 4; choice = choice + 1) begin
                select = choice; expected = packed_inputs >> (choice * WIDTH);
                #1; if (result !== expected) $fatal(1, "mux4 selection");
            end
        end
        $display("PASS bd_mux4"); $finish;
    end
endmodule
