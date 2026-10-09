#include "dma.h"
#include "hal.h"

static int g_dma_active;            /* written and read */
static const int g_dma_max = 4;     /* read only */
static int g_dma_errors;            /* written only through a macro */

#define DMA_COUNT_ERR() (g_dma_errors = g_dma_errors + 1)

static int dma_prog_desc(dma_chan_t *ch, const uint8_t *buf, size_t len)
{
    ch->desc.src = (uint32_t)(uintptr_t)buf;
    ch->desc.len = (uint16_t)len;
    HAL_WRITE32(ch->base, ch->desc.src);          /* call through a macro */
    HAL_WRITE32(ch->base + 1, ch->desc.len);
    hal_write_block(ch->base + 4, (const uint32_t *)buf, len / 4);
    return (int)len;
}

int dma_start(dma_chan_t *ch, const uint8_t *buf, size_t len)
{
    if (g_dma_active >= g_dma_max)
        return DMA_BUSY;
    int rc = dma_prog_desc(ch, buf, len);
    g_dma_active++;
    ch->busy = 1;
    hal_write32(ch->base + 2, 1u);
    if (ch->cb)
        ch->cb(ch->cb_ctx, rc);                   /* indirect call via function pointer */
    return rc;
}

enum dma_status dma_poll(dma_chan_t *ch)
{
    uint32_t s = hal_read32(ch->base + 3);
    ch->stat.raw = s;
    if (s & 2u)
        DMA_COUNT_ERR();                          /* assignment hidden in a macro */
    if (s & 1u) {
        g_dma_active--;
        ch->busy = 0;
        if (ch->cb)
            ch->cb(ch->cb_ctx, DMA_OK);
        return DMA_OK;
    }
    return DMA_BUSY;
}
