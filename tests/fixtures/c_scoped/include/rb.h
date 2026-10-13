#ifndef RB_H
#define RB_H

struct a;
struct b {
    struct a *a;
    int bv;
#ifdef GROW
    int extra;
#endif
};

#endif
