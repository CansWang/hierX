#include "common.h"

struct dup { int a; int b; int c; int d; };

int d2(dup_t *p, struct box *b) { return p->d + (b ? 1 : 0); }

#include "hbox.h"

int d2_hbox(struct hbox *b) { return b->payload ? 1 : 0; }
