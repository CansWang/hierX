#include "shared.h"

static int counter;

struct ctx { int a; };
typedef struct ctx ctx_t;

static void cb(void) { counter++; }

static int get_category(const ctx_t *c) { return c->a + twice(1); }

int run_a(void)
{
    struct ctx c = { 1 };
    void (*fp)(void) = cb;
    fp();
    return get_category(&c);
}
