#include "dma.h"
#include "hal.h"

static int g_done_count;

static void on_done(void *ctx, int status)
{
    (void)ctx;
    (void)status;
    g_done_count++;
}

int app_run(const uint8_t *data, size_t n)
{
    static dma_chan_t ch;                 /* function-local static: persistent state */
    hal_board_init();                     /* declared only -> unresolved */
    ch.cb = on_done;                      /* function referenced, not called */
    int rc = dma_start(&ch, data, n);     /* cross-file call */
    while (rc >= 0 && ch.busy)
        rc = (int)dma_poll(&ch);
    return rc;
}

int main(void)
{
    uint8_t buf[16] = {0};
    return app_run(buf, sizeof buf);
}
