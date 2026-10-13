/* Shared declarations: a forward-declared struct with a typedef, a header-defined static inline function
   (one function in every TU) and a self-referential struct (fingerprint cycle). */
#ifndef SHARED_H
#define SHARED_H

struct fwd;
typedef struct fwd fwd_t;

static inline int twice(int x) { return 2 * x; }

struct node { struct node *next; int v; };

#endif
