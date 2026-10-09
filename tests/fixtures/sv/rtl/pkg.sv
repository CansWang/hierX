package dma_pkg;
  typedef enum logic [1:0] { IDLE = 2'd0, BUSY = 2'd1, DONE = 2'd2, ERR = 2'd3 } state_t;

  typedef struct packed {
    logic [7:0]  len;
    logic [3:0]  chan;
    logic        irq_en;
    logic [2:0]  prio;
  } cfg_t;

  typedef struct packed {
    logic [31:0] src;
    logic [31:0] dst;
    cfg_t        cfg;
  } desc_t;

  function automatic logic [8:0] add_len(input logic [7:0] a, input logic [7:0] b);
    return {1'b0, a} + {1'b0, b};
  endfunction
endpackage
