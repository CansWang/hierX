BJTs with three and four terminals
.model npnmod npn bf=100
q1 n3 n1 0 0 npnmod
q2 n3 n1 0 npnmod
r1 n1 0 1k
.end
