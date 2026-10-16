numeric net names are nets, never values
.model qm npn bf=50
.model nm nmos level=1
q1 1 2 3 0 qm
r1 1 2 1k
m1 1 2 3 4 nm w=1u l=1u
.end
