PARAMS: on definitions and instances, // comments, an include whose line 1 is .subckt
.include "inc_first_subckt.inc"
.subckt outer_b in out PARAMS: rv=3k // trailing comment
xh in out leaf
r2 in out {rv}
.ends outer_b
xb n2 n3 outer_b PARAMS: rv=5k
xl n3 0 leaf
.end
