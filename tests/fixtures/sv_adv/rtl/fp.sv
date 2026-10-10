// A parameterized module with a MODULE-SCOPED struct whose layout depends on the parameters:
// fp #(8,23) and fp #(11,52) are two different layouts under the same name (CVA6's fpnew_fma.fp_t case).
module fp #(parameter int E = 8, parameter int M = 23) (
  input  logic           clk,
  input  logic [E+M:0]   in_bits,
  output logic [E+M:0]   out_bits
);
  typedef struct packed {
    logic         sign;
    logic [E-1:0] exponent;
    logic [M-1:0] mantissa;
  } fp_t;
  fp_t a_q, y_d;
  assign a_q = fp_t'(in_bits);
  always_comb begin
    y_d = a_q;
    y_d.sign = ~a_q.sign;
  end
  assign out_bits = y_d;
endmodule
