#include "c_opaque.h"

int oc(struct cwrap *w) { return w->p ? 1 : 0; }
