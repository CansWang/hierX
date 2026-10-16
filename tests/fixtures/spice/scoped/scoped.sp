scoped declarations (the ngspice probe: a local leaf and a local model shadow the global ones)
.subckt leaf a b
r1 a b 1k
.ends leaf
.subckt outer_a in out
.subckt leaf a b
c1 a b 1p
.ends leaf
.model dmod d is=2e-14
xh in out leaf
d1 in out dmod
.ends outer_a
.subckt outer_b in out
xh in out leaf
r2 in out 3k
.ends outer_b
.model dmod d is=1e-14
xa n1 n2 outer_a
xb n2 n3 outer_b
d0 n1 n3 dmod
.end
