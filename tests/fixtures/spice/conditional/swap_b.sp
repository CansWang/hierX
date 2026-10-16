two identical-condition blocks, order B
.param pick=1
.if (pick > 0)
rb n1 0 2k
.endif
.if (pick > 0)
ra n1 0 1k
.endif
.end
