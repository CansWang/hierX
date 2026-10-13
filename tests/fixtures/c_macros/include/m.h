/* Macro shapes from the FFmpeg review (finding C2): a wrapper macro around a variadic call, an assertion
   whose argument contains a call, a macro that GENERATES the callee name, and a macro whose expansion nests
   one call inside another. */
#ifndef M_H
#define M_H
#include <stdint.h>

void logf_(void *ctx, const char *fmt, ...);
void fail_(const char *expr);
int left_(void *pb);
void sample_impl(uint8_t *buf, int n);
uint32_t bswap_(uint32_t v);
void store32_(uint8_t *dst, uint32_t v);
int plain(int a, int b);

#define LOG(ctx, ...)   logf_(ctx, __VA_ARGS__)
#define ASSERT(cond)    do { if (!(cond)) fail_(#cond); } while (0)
#define FN(name)        name##_impl
#define WB32(dst, n)    store32_(dst, bswap_(n))
#define ALIAS           LOG                       /* an object-like macro standing for a function-like one */
#define PICK(a, b, c)   plain(a, c)               /* invoked with an EMPTY middle argument */

#endif
