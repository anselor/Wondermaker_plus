#pragma once
#include <cstdint>
namespace wmp_openace {
// Queue delivery bookkeeping only. This is never backend approval or movement
// authority. A settled ticket cannot be automatically sent again.
struct Delivery {
 enum Outcome{None,NotSent,Replied,Unknown};
 std::uint64_t ticket=0,status_generation=0;
 Outcome outcome=None;
};
}
