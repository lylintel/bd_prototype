module bd_uart_rx #(parameter integer CLKS_PER_BIT = 8) (
    input wire clk,
    input wire rst,
    input wire rx,
    output reg [7:0] m_data,
    output reg m_valid,
    input wire m_ready,
    output reg framing_error,
    output reg overrun,
    output wire busy
);
    localparam TIMER_WIDTH = CLKS_PER_BIT > 1 ? $clog2(CLKS_PER_BIT) : 1;
    localparam IDLE = 0, START = 1, DATA = 2, STOP = 3;
    (* ASYNC_REG = "TRUE" *) reg first_sample, second_sample;
    reg [1:0] state;
    reg [TIMER_WIDTH-1:0] timer;
    reg [2:0] bit_index;
    reg [7:0] received;
    assign busy = state != IDLE;
    always @(posedge clk) begin
        if (rst) begin
            first_sample <= 1; second_sample <= 1; state <= IDLE; timer <= 0; bit_index <= 0;
            received <= 0; m_data <= 0; m_valid <= 0; framing_error <= 0; overrun <= 0;
        end else begin
            first_sample <= rx; second_sample <= first_sample;
            framing_error <= 0; overrun <= 0;
            if (m_valid && m_ready) m_valid <= 0;
            case (state)
                IDLE: if (!second_sample) begin state <= START; timer <= CLKS_PER_BIT/2 - 1; end
                START: begin
                    if (timer != 0) timer <= timer - 1'b1;
                    else if (!second_sample) begin state <= DATA; bit_index <= 0; timer <= CLKS_PER_BIT - 1; end
                    else state <= IDLE;
                end
                DATA: begin
                    if (timer != 0) timer <= timer - 1'b1;
                    else begin
                        received[bit_index] <= second_sample; timer <= CLKS_PER_BIT - 1;
                        if (bit_index == 7) state <= STOP;
                        else bit_index <= bit_index + 1'b1;
                    end
                end
                STOP: begin
                    if (timer != 0) timer <= timer - 1'b1;
                    else begin
                        state <= IDLE;
                        if (!second_sample) framing_error <= 1;
                        else if (m_valid && !m_ready) overrun <= 1;
                        else begin m_data <= received; m_valid <= 1; end
                    end
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
