#include "handle.h"
#include "shared.h"

int h(struct handle *x) { return x != 0; }

int use_handle(struct handle *x) { return h(x); }

int walk(struct node *n) { return n->next ? n->v : 0; }

int app(void)
{
    struct node n = { 0, 1 };
    return twice(walk(&n));
}
