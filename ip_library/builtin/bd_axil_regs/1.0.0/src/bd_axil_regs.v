module bd_axil_regs #(parameter integer ADDR_WIDTH = 6) (
    input wire clk,
    input wire resetn,
    input wire [ADDR_WIDTH-1:0] awaddr,
    input wire [2:0] awprot,
    input wire awvalid,
    output wire awready,
    input wire [31:0] wdata,
    input wire [3:0] wstrb,
    input wire wvalid,
    output wire wready,
    output reg [1:0] bresp,
    output reg bvalid,
    input wire bready,
    input wire [ADDR_WIDTH-1:0] araddr,
    input wire [2:0] arprot,
    input wire arvalid,
    output wire arready,
    output reg [31:0] rdata,
    output reg [1:0] rresp,
    output reg rvalid,
    input wire rready,
    output wire [31:0] reg0,
    output wire [31:0] reg1,
    output wire [31:0] reg2,
    output wire [31:0] reg3
);
    reg [31:0] bank [0:3];
    reg aw_pending, w_pending;
    reg [ADDR_WIDTH-1:0] saved_awaddr;
    reg [31:0] saved_wdata;
    reg [3:0] saved_wstrb;
    integer register_index, byte_index;
    assign awready = resetn && !aw_pending && !bvalid;
    assign wready = resetn && !w_pending && !bvalid;
    assign arready = resetn && !rvalid;
    assign reg0 = bank[0];
    assign reg1 = bank[1];
    assign reg2 = bank[2];
    assign reg3 = bank[3];
    always @(posedge clk or negedge resetn) begin
        if (!resetn) begin
            aw_pending <= 0; w_pending <= 0; saved_awaddr <= 0; saved_wdata <= 0; saved_wstrb <= 0;
            bvalid <= 0; bresp <= 0; rvalid <= 0; rresp <= 0; rdata <= 0;
            for (register_index = 0; register_index < 4; register_index = register_index + 1) bank[register_index] <= 0;
        end else begin
            if (bvalid && bready) bvalid <= 0;
            if (rvalid && rready) rvalid <= 0;
            if (awvalid && awready) begin saved_awaddr <= awaddr; aw_pending <= 1; end
            if (wvalid && wready) begin saved_wdata <= wdata; saved_wstrb <= wstrb; w_pending <= 1; end
            if (aw_pending && w_pending && !bvalid) begin
                aw_pending <= 0; w_pending <= 0; bvalid <= 1;
                if (saved_awaddr >= 16 || saved_awaddr[1:0] != 0) bresp <= 2'b10;
                else begin
                    bresp <= 2'b00;
                    for (byte_index = 0; byte_index < 4; byte_index = byte_index + 1)
                        if (saved_wstrb[byte_index]) bank[saved_awaddr[3:2]][byte_index*8 +: 8] <= saved_wdata[byte_index*8 +: 8];
                end
            end
            if (arvalid && arready) begin
                rvalid <= 1;
                if (araddr >= 16 || araddr[1:0] != 0) begin rresp <= 2'b10; rdata <= 0; end
                else begin rresp <= 2'b00; rdata <= bank[araddr[3:2]]; end
            end
        end
    end
endmodule
