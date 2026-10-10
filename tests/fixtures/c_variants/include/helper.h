/* A header-defined inline function whose body depends on a per-TU macro.
 * a.c is compiled with -DUSE_FA, b.c with -DUSE_FB: the project index sees two
 * different versions of `helper`. hx must pick one deterministically (TU-path
 * order) no matter which TUs were served from the cache, and must say so. */
#ifndef HELPER_H
#define HELPER_H
int fa(int x);
int fb(int x);

static inline int helper(int x)
{
#ifdef USE_FA
    return fa(x);
#else
    return fb(x);
#endif
}
#endif
