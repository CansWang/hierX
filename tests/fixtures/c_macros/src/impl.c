#include <stdarg.h>
#include "m.h"

void logf_(void *ctx, const char *fmt, ...) { (void)ctx; (void)fmt; }
void fail_(const char *expr) { (void)expr; }
int left_(void *pb) { (void)pb; return 8; }
void sample_impl(uint8_t *buf, int n) { buf[0] = (uint8_t)n; }
uint32_t bswap_(uint32_t v) { return (v >> 24) | (v << 24); }
void store32_(uint8_t *dst, uint32_t v) { dst[0] = (uint8_t)v; }
int plain(int a, int b) { return a + b; }
