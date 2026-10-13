#include "common.h"

struct dup { int a; };

int d1(dup_t *p, struct box *b) { return p->a + (b->payload ? 1 : 0); }

#include "hbox.h"

int d1_hbox(struct hbox *b) { return b->payload ? 1 : 0; }
