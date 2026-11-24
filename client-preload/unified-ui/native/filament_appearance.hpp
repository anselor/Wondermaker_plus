// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../model.hpp"
#include "stock_api.hpp"
#include <vector>
namespace wmp_ui { namespace native {
inline void clip_appearance(void*object,int radius=-1){
 if(radius>=0)stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_radius)(object,radius,0);
 stock_function<void(*)(void*,bool,unsigned)>(lv_obj_set_style_clip_corner)(object,true,0);
}
struct AppearanceTile {int x,y,w,h;std::uint32_t colour;};
// Fill the entire swatch. Native rounded-corner clipping trims partial edge
// cells smoothly; never discard whole cells to approximate a curved outline.
inline std::vector<AppearanceTile> translucent_tiles(const Json&identity,int width,int height){
 std::vector<AppearanceTile> result;
 if(identity_display_text(identity,"appearance","standard")!="translucent")return result;
 const auto hex=identity_display_text(identity,"color","#888888");
 const auto rgb=std::stoul(hex.substr(1),nullptr,16);
 const int cell=width<40?4:8;
 for(int y=0;y<height;y+=cell)for(int x=0;x<width;x+=cell){
  const int w=std::min(cell,width-x),h=std::min(cell,height-y);
  const unsigned neutral=((x/cell+y/cell)%2)?155:235;
  std::uint32_t shade=0xff000000U;
  for(unsigned shift:{0u,8u,16u})shade|=((((rgb>>shift)&255u)*4+neutral)/5)<<shift;
  result.push_back({x,y,w,h,shade});
 }
 return result;
}
}}
