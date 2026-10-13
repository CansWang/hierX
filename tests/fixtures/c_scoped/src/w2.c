/* compiled without -DWIDE */
#include "cfg.h"

int w2(struct cfg *c, enum mode m) { return c->a - c->c + (int)m; }
