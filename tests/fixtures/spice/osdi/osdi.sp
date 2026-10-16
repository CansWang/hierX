osdi (compiled Verilog-A) devices use the N letter in ngspice
.model osdi_nmos psp103va type=1
.model osdi_res resva rsh=100
n1 d g 0 0 osdi_nmos w=1u l=0.13u
n2 a b osdi_res l=2u
v1 d 0 1.2
v2 g 0 0.6
.op
.end
