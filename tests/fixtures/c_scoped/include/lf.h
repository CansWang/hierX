/* A header-defined function with a LOCAL forward declaration and a local struct whose layout depends on -DWIDE:
   two variants of `lf::box` across TUs pointing at one stub `lf::lnode`. A comment-only edit above moves every
   byte offset in the local USRs and must not move a single id (review round 11). */
#ifndef LF_H
#define LF_H

static inline int lf(void)
{
    struct lnode;
    struct box {
        struct lnode *next;
        int a;
#ifdef WIDE
        int pad[2];
#endif
    };
    static struct box b;
    return b.a + (int)sizeof b;
}

#endif
