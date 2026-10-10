#pragma once
#include <cstdint>
#include <cstddef>

namespace hw {

struct Reg {
    uint32_t addr;
    uint32_t value;
};

class Bus {
public:
    explicit Bus(uint32_t base) : base_(base) {}
    int write(uint32_t addr, uint32_t value);          // overload 1
    int write(const Reg &reg);                          // overload 2
    int write(const uint8_t *buf, size_t len);          // overload 3
    uint32_t read(uint32_t addr) const;
private:
    uint32_t base_;
};

template <typename T>
T clamp(T v, T lo, T hi) { return v < lo ? lo : (v > hi ? hi : v); }

int run(Bus &bus);

}  // namespace hw
