// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "profile1113.hpp"
#include <algorithm>
#include <string>
namespace wmp_ui { namespace native {
#ifdef WMP_NATIVE_TEST
void* test_resolve(std::uintptr_t);
#endif
template<class F> inline F button_caption_fn(std::uintptr_t address){
#ifdef WMP_NATIVE_TEST
 return reinterpret_cast<F>(test_resolve(address));
#else
 return reinterpret_cast<F>(address);
#endif
}
inline void center_button_caption(void*button,void*label,const std::string&text){
 button_caption_fn<void(*)(void*)>(lv_obj_update_layout)(button);
 const int w=button_caption_fn<int(*)(void*)>(lv_obj_get_content_width)(button);
 const int h=button_caption_fn<int(*)(void*)>(lv_obj_get_content_height)(button);
 const int ch=std::min(h-4,22*(1+int(std::count(text.begin(),text.end(),'\n'))));
 button_caption_fn<void(*)(void*,int,int)>(lv_obj_set_size)(label,w-12,ch);
 button_caption_fn<void(*)(void*,int,int,int)>(lv_obj_align)(label,1,6,(h-ch)/2);
 button_caption_fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_text_align)(label,2,0);
}
}}
