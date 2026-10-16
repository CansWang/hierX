one include read from both branches of a conditional: same source, two guarded declarations each
.param pick=1
.if (pick > 0)
.include "shared.inc"
.else
.include "shared.inc"
.endif
x1 n1 n2 leaf
d1 n1 0 dm
r1 n2 0 1k
.end
