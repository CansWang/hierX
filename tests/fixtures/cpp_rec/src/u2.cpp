#include "noise2.h"
#include "nodes.h"

int u2(B::node *p, Noise2 *n) { return p->bv + (n ? 1 : 0); }
