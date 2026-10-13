#include "ctx_a.h"
#include "ctx_b.h"

int ra1(struct holder *h) { return h->ctx ? h->n : 0; }
