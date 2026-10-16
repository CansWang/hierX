nested guards: two guarded xw instances swap n1/n2, each wrap swaps in/out for its xl
.param pick=1
.subckt leaf a b
r1 a b 1k
.ends
.subckt wrap in out
.if (pick > 0)
xl in out leaf
.else
xl out in leaf
.endif
.ends
.if (pick > 0)
xw n1 n2 wrap
.else
xw n2 n1 wrap
.endif
v1 n1 0 1
r2 n2 0 1k
.end
