module bd_spi_master #(parameter integer CLOCK_DIV = 2) (
    input wire clk,
    input wire rst,
    input wire start,
    input wire [7:0] tx_data,
    input wire miso,
    output wire ready,
    output reg busy,
    output reg sclk,
    output reg mosi,
    output reg cs_n,
    output reg [7:0] rx_data,
    output reg done
);
    localparam TIMER_WIDTH = CLOCK_DIV > 1 ? $clog2(CLOCK_DIV) : 1;
    reg [TIMER_WIDTH-1:0] timer;
    reg [7:0] transmit, receive;
    reg [2:0] bit_index;
    assign ready = !rst && !busy;
    always @(posedge clk) begin
        if (rst) begin
            busy <= 0; sclk <= 0; mosi <= 0; cs_n <= 1; rx_data <= 0; done <= 0;
            timer <= 0; transmit <= 0; receive <= 0; bit_index <= 0;
        end else begin
            done <= 0;
            if (!busy) begin
                if (start) begin
                    busy <= 1; cs_n <= 0; sclk <= 0; timer <= 0; bit_index <= 0;
                    transmit <= tx_data; receive <= 0; mosi <= tx_data[7];
                end
            end else if (timer == CLOCK_DIV - 1) begin
                timer <= 0;
                if (!sclk) begin sclk <= 1; receive <= {receive[6:0], miso}; end
                else begin
                    sclk <= 0;
                    if (bit_index == 7) begin busy <= 0; cs_n <= 1; rx_data <= receive; done <= 1; end
                    else begin bit_index <= bit_index + 1'b1; transmit <= {transmit[6:0], 1'b0}; mosi <= transmit[6]; end
                end
            end else timer <= timer + 1'b1;
        end
    end
endmodule
