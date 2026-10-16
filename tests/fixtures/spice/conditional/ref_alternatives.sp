reference alternatives: unconditional F, H and K referencing sources and inductors declared in exclusive branches
.param pick=1
.if (pick > 0)
vs n2 0 1
.else
vs n2 0 2
.endif
f1 n1 0 vs 2
h1 n3 0 vs 1k
r1 n1 0 1k
r2 n2 0 1k
r3 n3 0 1k
l1 n1 n4 1u
.if (pick > 0)
l2 n3 n5 1u
.else
l2 n5 n3 1u
.endif
k1 l1 l2 0.5
r4 n4 0 1k
r5 n5 0 1k
.end
