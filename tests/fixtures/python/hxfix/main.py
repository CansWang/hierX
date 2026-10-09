from .dma import Desc, DmaChan, Status, dma_poll, dma_start


def on_done(desc: Desc, status: int) -> None:
    _ = (desc, status)


def app_run(data: bytes, n: int) -> int:
    ch = DmaChan(base=0x40000000)
    ch.cb = on_done
    rc = dma_start(ch, data[:n])
    while dma_poll(ch) == Status.BUSY:
        pass
    return rc


if __name__ == "__main__":
    print(app_run(b"\x00" * 16, 16))
