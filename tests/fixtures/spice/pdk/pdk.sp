pdk-style deck: sibling library sections, continuations across blank lines, mismatched .ends
.lib "models.lib" tt
.param
+ wdev=1u

+ ldev=0.15u
x1 d g 0 0 nfet w={wdev} l={ldev}
r1 d vdd {rsh}
vdd vdd 0 1.8
vg g 0 0.9
.op
.end
