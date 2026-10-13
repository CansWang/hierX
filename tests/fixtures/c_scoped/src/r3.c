/* compiled with -DGROW: struct b gains a field, so b (and a, through its edge) get a second layout */
#include "rb.h"
#include "ra.h"

int r3(struct b *p) { return p->bv; }
