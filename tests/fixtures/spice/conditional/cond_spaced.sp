conditional topology (ngspice)
.param pick=1 usemodel=1 usedevice=1
.model dmod d is=5e-14
.subckt leaf a b
.if (pick > 0)
r1 a b 1k
.else
r1 a b 2k
.endif
.ends
.subckt wrap in out
.if (pick > 0)
xl in out leaf
.else
xl out in leaf
.endif
.ends
xw n1 n2 wrap
.if (pick > 0)
.model dm d is=1e-14
.elseif (pick < 0)
.model dm d is=2e-14
.else
.model dm d is=3e-14
.endif
d1 n1 n2 dm
vsense n2 0 1
.if (pick > 0)
f1 n1 0 vsense 2
.endif
.end
