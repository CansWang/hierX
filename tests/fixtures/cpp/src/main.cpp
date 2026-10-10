#include "bus.hpp"

namespace hw {

int run(Bus &bus) {
    Reg r{4, 42};
    uint8_t buf[2] = {1, 2};
    int rc = bus.write(r);
    rc |= bus.write(buf, sizeof buf);
    return rc + static_cast<int>(bus.read(0));
}

}  // namespace hw

int main() {
    hw::Bus bus(0x4000);
    return hw::run(bus);
}
