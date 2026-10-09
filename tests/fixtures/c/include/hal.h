#ifndef HAL_H
#define HAL_H
#include <stdint.h>
#include <stddef.h>

/* Register access goes through a macro so the extractor must see through it. */
#define HAL_WRITE32(addr, val) hal_write32((addr), (val))

void hal_write32(volatile uint32_t *addr, uint32_t val);
uint32_t hal_read32(const volatile uint32_t *addr);
void hal_write_block(volatile uint32_t *base, const uint32_t words[], size_t n);

/* Declared only: no definition in any translation unit (expect "unresolved"). */
int hal_board_init(void);

#endif
