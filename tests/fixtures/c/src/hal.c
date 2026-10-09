#include "hal.h"

void hal_write32(volatile uint32_t *addr, uint32_t val)
{
    *addr = val;
}

uint32_t hal_read32(const volatile uint32_t *addr)
{
    return *addr;
}

void hal_write_block(volatile uint32_t *base, const uint32_t words[], size_t n)
{
    for (size_t i = 0; i < n; i++)
        base[i] = words[i];
}
