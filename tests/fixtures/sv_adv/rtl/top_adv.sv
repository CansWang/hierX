import adv_pkg::*;

module top_adv #(
  parameter logic [16383:0] CFG    = {16384{1'b1}},     // wider than Python's int<->str limit allows in decimal
  parameter int             NLANES = cfg_pkg::NLANES_CFG
) (
  input  logic        clk,
  input  logic        rst_n,
  input  struct packed { logic [7:0] a; logic [3:0] b; } cfg_i,   // anonymous inline struct port
  input  req_t        req_i,
  input  logic [31:0] f32_i,
  input  logic [63:0] f64_i,
  output logic [31:0] f32_o,
  output logic [63:0] f64_o,
  output logic [7:0]  q_o,
  output st_t         st_o
);
  logic [7:0] d_i;
  logic [7:0] lane_q [NLANES];
  logic [7:0] tbl [4];

  assign d_i = req_i.len + cfg_i.a;
  always_comb for (int k = 0; k < 4; k++) tbl[k] = d_i + 8'(k);
  assign q_o = tbl[6] ^ {4'd0, cfg_i.b};  // constant index out of range: Verilator warns SELRANGE (outside the lint group)

  fp #(.E(8),  .M(23)) u_fp32 (.clk(clk), .in_bits(f32_i), .out_bits(f32_o));
  fp #(.E(11), .M(52)) u_fp64 (.clk(clk), .in_bits(f64_i), .out_bits(f64_o));

  generate
    if (NLANES > 1) begin : gen_multi
      lane u_lane_star (.*);                                     // wildcard connections
    end
  endgenerate

  for (genvar i = 0; i < NLANES; i++) begin : gen_lane
    lane u_lane (
      .clk,                                                      // shorthand `.name`
      .rst_n,
      .d_i  (d_i + 8'(i)),
      .q_o  (lane_q[i])
    );
  end

  always_comb st_o = (bump(req_i.len) > 9'd8) ? S_RUN : S_IDLE;
endmodule
