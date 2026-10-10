module lane (
  input  logic       clk,
  input  logic       rst_n,
  input  logic [7:0] d_i,
  output logic [7:0] q_o
);
  always_ff @(posedge clk or negedge rst_n)
    if (!rst_n) q_o <= '0; else q_o <= d_i + 8'd1;
endmodule
