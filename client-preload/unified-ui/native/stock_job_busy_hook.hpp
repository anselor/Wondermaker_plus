// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <cstring>
namespace wmp_ui { namespace native {
// Verified 1.1.13 is_printing prologue: three stack instructions followed by
// ADRP X0, 0x386d000. Relocate that page reference instead of copying its PC.
inline void stock_job_busy_trampoline(void*destination,const void*entry){
 auto*out=static_cast<unsigned char*>(destination);
 std::memcpy(out,entry,12);
 const std::uint32_t code[]={0x580000a0U,0x58000050U,0xd61f0200U};
 std::memcpy(out+12,code,sizeof(code));
 const std::uint64_t resume=0x519610,page=0x386d000;
 std::memcpy(out+24,&resume,8);std::memcpy(out+32,&page,8);
}
}}
