/* Shared typedef and wrapper over whichever `struct opq` the TU declared first. To libclang the typedef over an
   already visible tag is a reference, not a declaration; to C it names THIS TU's `struct opq`, so a TU that saw
   a_opaque.h and this file links the two, another links b_opaque.h: one declaration-only class, keyed by the file
   every TU saw (this one). Nothing about layouts is involved. */
#ifndef OPQ_H
#define OPQ_H

typedef struct opq opq_t;
struct owrap { opq_t *p; };

#endif
