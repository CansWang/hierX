#ifndef DMA_H
#define DMA_H
#include <stddef.h>
#include <stdint.h>

typedef void (*dma_cb_t)(void *ctx, int status);

struct dma_desc {
    uint32_t src;
    uint32_t dst;
    uint16_t len;
    uint8_t  flags;
};

typedef struct dma_chan {
    volatile uint32_t *base;
    struct dma_desc    desc;
    dma_cb_t           cb;
    void              *cb_ctx;
    unsigned           busy : 1;
    unsigned           prio : 3;
    union {
        uint32_t raw;
        struct { uint8_t a, b, c, d; } bytes;
    } stat;
    struct {                      /* C11 anonymous member */
        uint16_t head;
        uint16_t tail;
    };
} dma_chan_t;

enum dma_status { DMA_OK = 0, DMA_BUSY = -1, DMA_ERR = -2 };

int dma_start(dma_chan_t *ch, const uint8_t *buf, size_t len);
enum dma_status dma_poll(dma_chan_t *ch);

#endif
