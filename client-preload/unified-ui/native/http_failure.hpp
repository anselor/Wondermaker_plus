// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdexcept>
namespace wmp_openace {
// Fixed diagnostic codes only; never serialize exception text or reply bodies.
// Admission and retry policy must not depend on these values.
enum class HttpFailureKind {Other=0, Deadline=1, Connection=2, Io=3, Response=4};
class HttpFailure : public std::runtime_error {
public:
 HttpFailure(HttpFailureKind kind,const char*message):std::runtime_error(message),kind(kind){}
 const HttpFailureKind kind;
};
}
