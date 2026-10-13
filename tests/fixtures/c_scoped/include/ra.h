/* Mutual recursion across two headers: include ra.h/rb.h in either order. */
#ifndef RA_H
#define RA_H

struct b;
struct a { struct b *b; int av; };

#endif
