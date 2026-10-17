library reference errors: a missing library file, a missing section, a self-referencing section, an inline section
.lib "nowhere.lib" tt
.lib "sections.lib" nosuch
.lib "sections.lib" tt
.lib inline
r9 n1 0 9k
.endl
m1 n1 n2 0 0 nch w=1u l=1u
r1 n1 0 1k
.end
