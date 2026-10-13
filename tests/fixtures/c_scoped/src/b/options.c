#include "shared.h"

static int counter;

struct ctx { int a; int b; double d; };
typedef struct ctx ctx_t;

static void cb(void) { counter += 2; }

static int get_category(const ctx_t *c) { return c->b + twice(2); }

int run_b(void)
{
    struct ctx c = { 1, 2, 3.0 };
    void (*fp)(void) = cb;
    fp();
    return get_category(&c);
}
