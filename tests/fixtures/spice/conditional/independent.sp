independent conditions (a model under one .if used under another; two compatible-guard models)
.param usemodel=1 usedevice=1 other=1
.if (usemodel > 0)
.model dm d is=1e-14
.endif
.if (usedevice > 0)
d1 n1 0 dm
.endif
.if (other > 0)
.model dup d is=2e-14
.endif
.if (usemodel > 0)
.model dup d is=3e-14
.endif
d2 n1 0 dup
r1 n1 0 1k
.end
