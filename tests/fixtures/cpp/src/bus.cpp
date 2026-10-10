#include "bus.hpp"

namespace hw {

static uint32_t g_writes = 0;

int Bus::write(uint32_t addr, uint32_t value) {
    g_writes++;
    volatile uint32_t *p = reinterpret_cast<volatile uint32_t *>(static_cast<uintptr_t>(base_ + addr));
    *p = value;
    return 0;
}

int Bus::write(const Reg &reg) {
    return write(reg.addr, clamp<uint32_t>(reg.value, 0u, 0xFFFFu));
}

int Bus::write(const uint8_t *buf, size_t len) {
    int rc = 0;
    for (size_t i = 0; i < len; ++i)
        rc |= write(static_cast<uint32_t>(i), buf[i]);
    return rc;
}

uint32_t Bus::read(uint32_t addr) const {
    return *reinterpret_cast<volatile uint32_t *>(static_cast<uintptr_t>(base_ + addr));
}

}  // namespace hw
