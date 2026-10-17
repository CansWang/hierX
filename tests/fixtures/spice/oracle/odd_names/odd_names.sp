odd names: a bare-letter device and a dotted device name (ngspice 45.2 lists r.x1.r and r.x1.r.foo)
.subckt leaf a b
r1 a b 1k
r.foo a b 3k
r a b 4k
.ends
x1 n1 0 leaf
rt n1 n2 1k
vs n1 0 1
f1 fout 0 vs 2
.end
