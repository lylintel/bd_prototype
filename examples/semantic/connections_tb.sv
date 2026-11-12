module tb;
    reg [15:0] data;
    reg select;
    wire [7:0] result;
    wire [7:0] fixed;

    connections_bd_wrapper dut (.data(data), .select(select), .result(result), .fixed(fixed));

    initial begin
        data = 16'h3ca6;
        select = 0;
        #1;
        if (result !== 8'ha6 || fixed !== 8'd5) $fatal(1, "slice or constant mismatch");
        select = 1;
        #1;
        if (result !== 8'h35) $fatal(1, "concat order mismatch");
        data = 16'hf080;
        #1;
        if (result !== 8'hf5 || fixed !== 8'd5) $fatal(1, "concat propagation mismatch");
        $display("PASS connections_bd");
        $finish;
    end
endmodule