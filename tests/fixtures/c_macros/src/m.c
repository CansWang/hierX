#include <stddef.h>
#include "m.h"

int use_macros(uint8_t *buf, void *pb, int len)
{
    uint8_t dst[4];
    uint32_t n = (uint32_t)len;
    LOG(NULL, "a, b", 1);            /* comma inside the literal: still one argument */
    LOG(NULL, "x   y");              /* spaces inside the literal are kept */
    ASSERT(len <= left_(pb));        /* a call inside the macro argument */
    FN(sample)(buf, 0);              /* the macro produces the callee name */
    WB32(dst, n);                    /* nested calls inside the expansion */
    ALIAS(NULL, "z", 2);             /* object-like alias: the list follows the bare name */
    len += PICK(len, , 2);           /* empty macro argument is positional */
    return plain(len,
                 0);                 /* an ordinary call across two lines */
}
