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
inline void stock_object_place(void*object,int x,int y,int width,int height){
 stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(object,x,y);
 stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(object,width,height);
}
}}
