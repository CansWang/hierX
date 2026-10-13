/* Truly disconnected: c_opaque.h and d_opaque.h each declare `struct opq2` with their OWN typedef and wrapper, and no
   file mentions the tag in both TUs — two identities, nothing shared, nothing to split. */
#ifndef C_OPAQUE_H
#define C_OPAQUE_H

struct opq2;
typedef struct opq2 c_t;
struct cwrap { c_t *p; };

#endif
