malformed deck: every structural error the parser reports, extraction still continues
.elseif (a > 0)
.else
.endif
.ends
.endl
.lib
.include
.model onlyname
.subckt
r1 n1 0 1k
.control
.endc
+ orphan continuation
.if (a > 0)
r2 n1 0 2k
.end
