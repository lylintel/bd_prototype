`timescale 1ns/1ps

module tb_priority_encoder;
    reg [7:0] requests = 0;
    wire high_valid;
    wire low_valid;
    wire [2:0] high_index;
    wire [2:0] low_index;
    wire [7:0] high_onehot;
    wire [7:0] low_onehot;
    integer pattern;
    integer bit_index;
    integer expected_high;
    integer expected_low;

    priority_encoder #(.WIDTH(8), .LSB_HIGH_PRIORITY(0)) high_first (
        .input_unencoded(requests), .output_valid(high_valid),
        .output_encoded(high_index), .output_unencoded(high_onehot)
    );
    priority_encoder #(.WIDTH(8), .LSB_HIGH_PRIORITY(1)) low_first (
        .input_unencoded(requests), .output_valid(low_valid),
        .output_encoded(low_index), .output_unencoded(low_onehot)
    );

    initial begin
        for (pattern = 0; pattern < 256; pattern = pattern + 1) begin
            requests = pattern[7:0];
            #1;
            if (high_valid !== (pattern != 0) || low_valid !== (pattern != 0))
                $fatal(1, "priority valid flag mismatch for %02x", pattern);
            if (pattern != 0) begin
                expected_high = 0;
                expected_low = -1;
                for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1) begin
                    if (requests[bit_index]) begin
                        expected_high = bit_index;
                        if (expected_low == -1)
                            expected_low = bit_index;
                    end
                end
                if (high_index !== expected_high[2:0] || low_index !== expected_low[2:0])
                    $fatal(1, "priority index mismatch for %02x", pattern);
                if (high_onehot !== (8'b1 << expected_high) || low_onehot !== (8'b1 << expected_low))
                    $fatal(1, "priority onehot mismatch for %02x", pattern);
            end
        end
        $display("PASS: priority encoder, 256 patterns in both priority modes");
        $finish;
    end
endmodule