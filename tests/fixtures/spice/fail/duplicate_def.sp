two definitions in ONE scope
.subckt dup a b
r1 a b 1k
.ends
.subckt dup a b
r1 a b 2k
.ends
x1 n1 0 dup
.end
