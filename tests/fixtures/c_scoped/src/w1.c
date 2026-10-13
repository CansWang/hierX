/* compiled with -DWIDE */
#include "cfg.h"

int w1(struct cfg *c, enum mode m) { return c->a + c->c + (int)m; }
