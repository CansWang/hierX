module alu #(parameter int W = 8) (
  input  logic         clk,
  input  logic [W-1:0] a,
  input  logic [W-1:0] b,
  input  logic         op,
  input  logic [W-1:0] lut [4],
  output logic [W-1:0] y,
  output logic         zero
);
  always_ff @(posedge clk) begin
    y <= op ? a - b : a + b + lut[op];
  end
  assign zero = (y == '0);
endmodule
