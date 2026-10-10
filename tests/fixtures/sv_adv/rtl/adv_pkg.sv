package adv_pkg;
  typedef struct packed {
    logic [7:0] len;
    logic       en;
  } req_t;
  typedef enum logic [1:0] { S_IDLE = 2'd0, S_RUN = 2'd1, S_DONE = 2'd2 } st_t;
  function automatic logic [8:0] bump(input logic [7:0] a);
    return {1'b0, a} + 9'd1;
  endfunction
endpackage
