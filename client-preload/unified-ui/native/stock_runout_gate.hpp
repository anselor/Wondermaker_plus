// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <cstring>
namespace wmp_ui { namespace native {
// Only the verified 1.1.13 prologue: three frame instructions, then ADRP X0.
// Relocate ADRP explicitly; copying it would address the trampoline's page.
inline void stock_runout_trampoline(void* destination,const void* source){
 auto*out=static_cast<unsigned char*>(destination);
 std::memcpy(out,source,12);
 const std::uint32_t address[]={0xd2800000U | (0x5000U<<5),
  0xf2a00000U | (0xe64U<<5),0xf2c00000U,0xf2e00000U};
 std::memcpy(out+12,address,sizeof(address)); // X0 = 0x000000000e645000
 const std::uint32_t branch[]={0x58000050U,0xd61f0200U};
 const std::uintptr_t continuation=0x61ab6c;
 std::memcpy(out+28,branch,8);std::memcpy(out+36,&continuation,8);
}
}}
