#include "ctx_b.h"
#include "ctx_a.h"

int use_rctx(rctx_t *c) { return c->a; }

int ra2(struct holder *h) { return use_rctx(h->ctx) + h->n; }
