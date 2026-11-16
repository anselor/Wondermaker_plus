// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <string>
#include <cstdint>
namespace wmp_ui { namespace native {
// The verified stock constructor reads this std::string array for its
// filament swatches. Resolve the same stable asset, preserving alpha/shape.
inline const char* stock_white_filament_asset(){
#ifdef WMP_NATIVE_TEST
 extern void* test_resolve(std::uintptr_t);
 return static_cast<const std::string*>(test_resolve(0x38626e8))[0].c_str();
#elif defined(__aarch64__)
 return reinterpret_cast<const std::string*>(0x38626e8)[0].c_str();
#else
 return nullptr;
#endif
}
// Solid colours decoded from the verified 1.1.13 stock picker BGRA assets.
// Slots 16..20 are textured/multitone assets, not a single RGB identity.
inline const char* stock_solid_colour(unsigned index){
 static const char* const colours[]={"#ffffff","#e7ceb5","#714623","#97999b","#0c0809","#49c5b1","#009cde","#03257e","#00b140","#265b31","#fce300","#fe5000","#f5b6cd","#e10098","#cd001a","#5f249f"};
 return index<16?colours[index]:nullptr;
}
inline int stock_colour_index(const std::string&colour){
 std::string normalized=colour;
 for(auto&c:normalized)if(c>='A'&&c<='F')c=char(c-'A'+'a');
 for(unsigned i=0;i<16;++i)if(normalized==stock_solid_colour(i))return int(i);
 return -1;
}
inline bool stock_rgb(const std::string&colour,std::uint32_t&value){
 if(colour.size()!=7||colour[0]!='#')return false;
 std::uint32_t rgb=0;
 for(unsigned i=1;i<7;++i){char c=colour[i];unsigned n;
  if(c>='0'&&c<='9')n=unsigned(c-'0');
  else if(c>='a'&&c<='f')n=unsigned(c-'a'+10);
  else if(c>='A'&&c<='F')n=unsigned(c-'A'+10);
  else return false;
  rgb=(rgb<<4)|n;
 }
 value=0xff000000U|rgb;return true;
}
}}
