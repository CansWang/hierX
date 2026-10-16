mixed local/global nesting (ngspice lists r.xo.xm.xg.r.xl.r1 and r.xp.r1)
.subckt leaf a b
r1 a b 1k
.ends
.subckt g a b
.subckt loc a b
r1 a b 2k
.ends
xl a b loc
.ends
.subckt mid a b
xg a b g
.ends
.subckt outer a b
xm a b mid
.ends
xo n1 n2 outer
xp n2 n3 leaf
r0 n3 0 1k
.end
