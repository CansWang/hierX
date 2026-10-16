duplicate and missing reference targets (never simulated: ngspice bails out on the duplicate source)
.param pick=1
.if (pick > 0)
vdup n1 0 1
.endif
.if (pick > 0)
vdup n1 0 2
.endif
f2 n4 0 vdup 1
fx n5 0 vnone 1
r1 n1 0 1k
r4 n4 0 1k
r5 n5 0 1k
.end
