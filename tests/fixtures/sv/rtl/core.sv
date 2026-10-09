import dma_pkg::*;

module core #(parameter int W = 8, parameter int DEPTH = 4) (
  input  logic        clk,
  input  logic        rst_n,
  input  desc_t       desc,
  input  logic        start,
  output state_t      state,
  output logic [W-1:0] result,
  inout  wire         sda
);
  logic [W-1:0] acc;
  logic         zero;
  logic         pl;

  function automatic logic [W-1:0] saturate(input logic [W:0] v);
    return v[W] ? '1 : v[W-1:0];
  endfunction

  task automatic pulse(output logic p);
    p = 1'b1;
  endtask

  alu #(.W(W)) u_alu (
    .clk  (clk),
    .a    (acc),
    .b    (desc.cfg.len[W-1:0]),
    .op   (desc.cfg.irq_en),
    .lut  ('{default: '0}),
    .y    (result),
    .zero (zero)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= IDLE;
      acc   <= '0;
    end else begin
      acc <= saturate({1'b0, acc} + add_len(desc.cfg.len, 8'd1));
      case (state)
        IDLE: if (start) begin state <= BUSY; pulse(pl); end
        BUSY: state <= zero ? DONE : BUSY;
        default: state <= IDLE;
      endcase
    end
  end
endmodule
