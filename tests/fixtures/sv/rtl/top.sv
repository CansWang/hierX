import dma_pkg::*;

module top (
  input  logic        clk,
  input  logic        rst_n,
  input  logic [31:0] src_addr,
  input  logic [31:0] dst_addr,
  input  cfg_t        cfg,
  input  logic        start,
  output logic [7:0]  result_a,
  output logic [15:0] result_b,
  output logic        done,
  inout  wire         sda
);
  desc_t  desc;
  state_t st_a, st_b;

  assign desc = '{src: src_addr, dst: dst_addr, cfg: cfg};

  core #(.W(8))  u_core_a (.clk(clk), .rst_n(rst_n), .desc(desc), .start(start), .state(st_a), .result(result_a), .sda(sda));
  core #(.W(16)) u_core_b (.clk(clk), .rst_n(rst_n), .desc(desc), .start(start), .state(st_b), .result(result_b), .sda(sda));

  assign done = (st_a == DONE) && (st_b == DONE);
endmodule
