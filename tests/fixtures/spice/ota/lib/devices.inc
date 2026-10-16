* device wrappers used by the OTA (an include whose line 1 is a comment)
.subckt nch_wrap d g s b w=1u
M1 d g s b nch w={w} l=0.18u
.ends
.subckt cm tail ibias vss
* a definition nested inside cm: only visible from cm's body
.subckt mirror_leg g d s
M1 d g s s nch w=1u l=0.18u
.ends
Xref ibias ibias vss mirror_leg
Xout ibias tail vss mirror_leg
.ends cm
