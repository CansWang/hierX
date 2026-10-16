switches: a current-controlled switch takes its model after the controlling source
vsense n2 0 1
vin n1 0 1
r1 n1 n2 1k
w1 out 0 vsense sm
s1 out2 0 n1 0 sw
f1 n3 0 vsense 2
h1 n4 0 vsense 1k
rl out 0 1k
rl2 out2 0 1k
r3 n3 0 1k
r4 n4 0 1k
.model sm csw it=0.5 ron=1 roff=1meg
.model sw sw vt=0.5 ron=1 roff=1meg
.end
