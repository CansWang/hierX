.subckt fake a b
r1 n1 0 1k
.subckt real a b
r2 a b 2k
.ends
x1 n1 0 real
.end
