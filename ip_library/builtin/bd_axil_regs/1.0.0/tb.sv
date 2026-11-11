`timescale 1ns/1ps
module tb;
    parameter ADDR_WIDTH = 6;
    reg clk = 0, resetn = 0;
    reg [ADDR_WIDTH-1:0] awaddr = 0, araddr = 0;
    reg awvalid = 0, wvalid = 0, bready = 0, arvalid = 0, rready = 0;
    reg [31:0] wdata = 0;
    reg [3:0] wstrb = 0;
    wire awready, wready, bvalid, arready, rvalid;
    wire [1:0] bresp, rresp;
    wire [31:0] rdata, reg0, reg1, reg2, reg3;
    always #5 clk = ~clk;
    bd_axil_regs #(.ADDR_WIDTH(ADDR_WIDTH)) dut(.clk(clk), .resetn(resetn), .awaddr(awaddr), .awprot(3'b101), .awvalid(awvalid), .awready(awready),
        .wdata(wdata), .wstrb(wstrb), .wvalid(wvalid), .wready(wready), .bresp(bresp), .bvalid(bvalid), .bready(bready),
        .araddr(araddr), .arprot(3'b111), .arvalid(arvalid), .arready(arready), .rdata(rdata), .rresp(rresp), .rvalid(rvalid), .rready(rready),
        .reg0(reg0), .reg1(reg1), .reg2(reg2), .reg3(reg3));
    task automatic write_word(input [ADDR_WIDTH-1:0] address, input [31:0] value, input [3:0] strobes,
                              input integer aw_delay, input integer w_delay, input [1:0] response);
        begin
            fork
                begin
                    @(negedge clk); repeat (aw_delay) @(negedge clk); awaddr = address; awvalid = 1;
                    @(posedge clk); while (!awready) @(posedge clk);
                    @(negedge clk); awvalid = 0;
                end
                begin
                    @(negedge clk); repeat (w_delay) @(negedge clk); wdata = value; wstrb = strobes; wvalid = 1;
                    @(posedge clk); while (!wready) @(posedge clk);
                    @(negedge clk); wvalid = 0;
                end
            join
            wait (bvalid); #1;
            if (bresp !== response) $fatal(1, "axil write response");
            repeat (3) begin @(posedge clk); #1; if (!bvalid || bresp !== response) $fatal(1, "axil B stall"); end
            @(negedge clk); bready = 1;
            @(posedge clk); #1; if (bvalid) $fatal(1, "axil B consume");
            @(negedge clk); bready = 0;
        end
    endtask
    task automatic read_word(input [ADDR_WIDTH-1:0] address, input [31:0] value, input [1:0] response, input integer stall_cycles);
        begin
            @(negedge clk); araddr = address; arvalid = 1;
            @(posedge clk); while (!arready) @(posedge clk);
            @(negedge clk); arvalid = 0;
            wait (rvalid); #1;
            if (rdata !== value || rresp !== response) $fatal(1, "axil read response");
            repeat (stall_cycles) begin @(posedge clk); #1; if (!rvalid || rdata !== value || rresp !== response) $fatal(1, "axil R stall"); end
            @(negedge clk); rready = 1;
            @(posedge clk); #1; if (rvalid) $fatal(1, "axil R consume");
            @(negedge clk); rready = 0;
        end
    endtask
    initial begin
        repeat (3) @(negedge clk); resetn = 1;
        read_word(0, 0, 0, 2);
        write_word(0, 32'h11223344, 4'b1111, 0, 3, 0);
        write_word(0, 32'haabbccdd, 4'b0101, 4, 0, 0);
        read_word(0, 32'h11bb33dd, 0, 3);
        write_word(4, 32'hf0f00f0f, 4'b1111, 1, 1, 0);
        write_word(8, 32'hcafebabe, 4'b1111, 0, 1, 0);
        write_word(12, 32'hdeadbeef, 4'b1111, 1, 0, 0);
        write_word(4, 0, 4'b0000, 0, 0, 0);
        if (reg0 !== 32'h11bb33dd || reg1 !== 32'hf0f00f0f || reg2 !== 32'hcafebabe || reg3 !== 32'hdeadbeef) $fatal(1, "axil bank");
        if (ADDR_WIDTH > 4) begin write_word(16, 32'hffffffff, 4'b1111, 0, 0, 2); read_word(16, 0, 2, 1); end
        write_word(2, 32'hffffffff, 4'b1111, 0, 0, 2);
        read_word(3, 0, 2, 2);
        fork
            begin read_word(0, 32'h11bb33dd, 0, 12); end
            begin wait (rvalid); write_word(0, 32'h87654321, 4'b1111, 0, 1, 0); end
        join
        read_word(0, 32'h87654321, 0, 1);
        @(negedge clk); awaddr = 0; awvalid = 1;
        @(posedge clk); @(negedge clk); awvalid = 0; resetn = 0;
        #1; if (bvalid || rvalid || reg0 !== 0 || reg1 !== 0 || reg2 !== 0 || reg3 !== 0) $fatal(1, "axil reset");
        repeat (2) @(negedge clk); resetn = 1;
        read_word(0, 0, 0, 1);
        $display("PASS bd_axil_regs"); $finish;
    end
    initial begin #1000000; $fatal(1, "axil timeout"); end
endmodule
