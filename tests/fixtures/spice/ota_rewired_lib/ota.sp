Five-transistor OTA test deck (ngspice)
.include "lib/devices.inc"
.lib "lib/corners.lib" tt
.param vdd_val=1.8 ibias_val=20u
.global vdd
.subckt five_t_opamp vip vin vout ibias vdd vss
XM_in1 tail vip vmir vss nch_wrap w=3u
XM_in2 tail vin vout vss nch_wrap w=2u
M_load_1 vmir vmir vdd vdd pch_hv w=4u l=0.18u
M_load_2 vout vmir vdd vdd pch w=4u l=0.18u
X_cm tail ibias vss cm
.ends five_t_opamp
XA vip vin outa ibias vdd 0 five_t_opamp
XB vip vin outb ibias vdd 0 five_t_opamp
VDD vdd 0 {vdd_val}
VIN vip vin dc 0 ac 1
IBIAS vdd ibias {ibias_val}
VSENSE outa sense 0
CL outb 0 1p
RL sense 0 10k
E1 ecopy 0 outa 0 2
F1 fout 0 VSENSE 2
RF fout 0 1k
L1 outa lx 1u
L2 outb ly 1u
K1 L1 L2 0.5
RX lx 0 1k
RY ly 0 1k
.if (vdd_val > 1.5)
R_opt vip vin 1meg
.else
R_opt vip vin 10meg
.endif
.op
.ac dec 10 1 1g
.control
run
wrdata out.txt v(outa)
.endc
.end
