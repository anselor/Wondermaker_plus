// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "profile1113.hpp"
#include <initializer_list>
namespace wmp_ui { namespace native {
#ifdef WMP_NATIVE_TEST
void*test_resolve(std::uintptr_t);
#endif
template<class F>inline F dialog_function(std::uintptr_t address){
#ifdef WMP_NATIVE_TEST
 return reinterpret_cast<F>(test_resolve(address));
#else
 return reinterpret_cast<F>(address);
#endif
}
// Keep the stock page visible around a scoped dialog. The transparent object
// still receives pointer input so taps cannot reach controls behind the dialog.
inline void stock_dialog_backdrop(void*root){
 dialog_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(root,2); // CLICKABLE
 dialog_function<void(*)(void*,unsigned)>(lv_obj_clear_flag)(root,16); // SCROLLABLE
 for(auto property:{lv_obj_set_style_bg_opa,lv_obj_set_style_border_width,
                    lv_obj_set_style_radius,lv_obj_set_style_pad_top,
                    lv_obj_set_style_pad_bottom,lv_obj_set_style_pad_left,
                    lv_obj_set_style_pad_right})
  dialog_function<void(*)(void*,int,unsigned)>(property)(root,0,0);
}
}}
