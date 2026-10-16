the same name under the same condition in two identical chains: a guarded duplicate
.param pick=1
.if (pick > 0)
ra n1 0 1k
.endif
.if (pick > 0)
ra n1 0 2k
.endif
.end
