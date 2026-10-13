/* An opaque handle: the struct is never defined by anything that includes this header. src/impl.c defines an
   UNRELATED complete `struct handle` that must not be attached to it. */
#ifndef HANDLE_H
#define HANDLE_H

struct handle;
int h(struct handle *x);

#endif
