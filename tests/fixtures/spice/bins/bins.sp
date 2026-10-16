model bin families (GF180 style: nfet_03v3.0 … with no base card)
.model nm.0 nmos level=1 lmin=0.1u lmax=1u
.model nm.1 nmos level=1 lmin=1u lmax=10u
.model nm.2 nmos level=1 lmin=10u lmax=100u
.subckt nm d g s b w=1u l=1u
m1 d g s b nm w={w} l={l}
.ends
xmn n1 n2 0 0 nm w=2u l=1u
r1 n1 n2 1k
.end
