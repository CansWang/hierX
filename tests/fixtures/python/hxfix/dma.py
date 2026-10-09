from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Optional

from . import hal


class Status(IntEnum):
    IDLE = 0
    BUSY = 1
    DONE = 2
    ERR = 3


@dataclass
class Desc:
    src: int = 0
    dst: int = 0
    length: int = 0
    flags: int = 0


Callback = Callable[[Desc, int], None]


@dataclass
class DmaChan:
    base: int
    desc: Desc = field(default_factory=Desc)
    cb: Optional[Callback] = None
    busy: bool = False


g_dma_active = 0


def _prog_desc(ch: DmaChan, buf: bytes) -> int:
    ch.desc.src = id(buf) & 0xFFFFFFFF
    ch.desc.length = len(buf)
    hal.write32(ch.base, ch.desc.src)
    hal.write32(ch.base + 4, ch.desc.length)
    return len(buf)


def dma_start(ch: DmaChan, buf: bytes) -> int:
    global g_dma_active
    if not buf:
        return -1
    n = _prog_desc(ch, buf)
    g_dma_active += 1
    ch.busy = True
    hal.write32(ch.base + 8, 1)
    if ch.cb is not None:
        ch.cb(ch.desc, n)
    return n


def dma_poll(ch: DmaChan) -> Status:
    global g_dma_active
    s = hal.read32(ch.base + 12)
    if s & 1:
        ch.busy = False
        g_dma_active -= 1
        return Status.DONE
    return Status.BUSY
