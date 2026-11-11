module bd_sync_2ff (
    input wire clk,
    input wire rstn,
    input wire async_in,
    output wire sync_out
);
    (* ASYNC_REG = "TRUE" *) reg first_stage, second_stage;
    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin first_stage <= 1'b0; second_stage <= 1'b0; end
        else begin first_stage <= async_in; second_stage <= first_stage; end
    end
    assign sync_out = second_stage;
endmodule
