wrong terminal counts
.subckt two a b
r1 a b 1k
.ends
x1 n1 n2 n3 two
x2 n1 two
m1 n1 n2 nch
.model nch nmos level=1
.end
