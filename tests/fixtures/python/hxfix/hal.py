REGS: dict[int, int] = {}


def write32(addr: int, val: int) -> None:
    REGS[addr] = val & 0xFFFFFFFF


def read32(addr: int) -> int:
    return REGS.get(addr, 0)
