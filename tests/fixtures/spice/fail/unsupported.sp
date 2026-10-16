unsupported statements are preserved with locations
Y1 n1 0 ymodel
A1 [n1 n2] n3 adc_model
r1 n1 0 1k
.measure tran vmax max v(n1)
.alter
.prot
r_secret n1 0 1k
.unprot
.bogus 1 2 3
.end
