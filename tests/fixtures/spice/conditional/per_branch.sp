per-branch declarations: leaf and dm declared in both branches, used inside each branch and once unconditionally
.param pick=1
.if (pick > 0)
.subckt leaf a b
r1 a b 1k
.ends
.model dm d is=1e-14
x1 n1 n2 leaf
d1 n1 0 dm
.else
.subckt leaf a b
r1 a b 2k
.ends
.model dm d is=2e-14
x1 n1 n2 leaf
d1 n1 0 dm
.endif
x2 n2 0 leaf
.end
