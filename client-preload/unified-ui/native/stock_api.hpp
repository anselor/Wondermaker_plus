// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "profile1113.hpp"
namespace wmp_ui { namespace native {
#ifdef WMP_NATIVE_TEST
void*test_resolve(std::uintptr_t);
#endif
template<class F>inline F stock_function(std::uintptr_t address){
#ifdef WMP_NATIVE_TEST
 return reinterpret_cast<F>(test_resolve(address));
#else
 return reinterpret_cast<F>(address);
#endif
}
inline bool stock_object_valid(void*object){return object&&stock_function<bool(*)(void*)>(lv_obj_is_valid)(object);}
inline bool stock_object_visible(void*object){
 if(!stock_object_valid(object))return false;
 auto*display=stock_function<void*(*)()>(lv_disp_get_default)();
 auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(display);
 auto*top=stock_function<void*(*)(void*)>(lv_disp_get_layer_top)(display);
 auto*system=stock_function<void*(*)(void*)>(lv_disp_get_layer_sys)(display);
 for(unsigned depth=0;object&&depth<32;++depth){
  if(!stock_object_valid(object)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(object,1))return false;
  if(object==screen||object==top||object==system)return true;
  object=stock_function<void*(*)(void*)>(lv_obj_get_parent)(object);
 }
 return false;
}
inline void stock_object_place(void*object,int x,int y,int width,int height){
 stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(object,x,y);
 stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(object,width,height);
}
}}
