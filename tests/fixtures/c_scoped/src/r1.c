#include "ra.h"
#include "rb.h"

/* unrelated types present in this TU only */
struct extra { int e; };
struct uses_extra { struct extra *x; };

int r1(struct a *p, struct uses_extra *u) { return p->av + (u ? 1 : 0); }
