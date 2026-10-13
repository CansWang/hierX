"""Module-level code that calls into the package (a module caller, review finding H5)."""
from .dma import DmaChan, dma_poll

VDD = 3.3
CH = DmaChan(base=0x40000000)

status = dma_poll(CH)
if VDD > 3.0:
    status = dma_poll(CH)
