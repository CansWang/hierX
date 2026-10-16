globals, ground spellings, three-level bindings, a cross-scope controlling reference
.global vdd
.subckt inner a b
r1 a vdd 1k
r2 b gnd 1k
.ends
.subckt middle p q
x_in p q inner
c1 p 0 1p
.ends
.subckt outer m n
x_mid m n middle
.ends
x_top in out outer
vs in 0 1
f1 out 0 vs 2
vdd vdd 0 1.8
.end
