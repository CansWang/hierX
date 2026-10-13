/* Does NOT include handle.h: this complete `struct handle` is unrelated to the opaque one. */
struct handle { int a; int b; int c; };

int use_impl_handle(struct handle *x) { return x->a + x->b + x->c; }
