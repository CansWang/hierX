recursive hierarchy
.subckt self a b
x1 a b self
r1 a b 1k
.ends
.subckt pa a b
x1 a b pb
.ends
.subckt pb a b
x1 a b pa
.ends
xs n1 0 self
xm n1 0 pa
.end
