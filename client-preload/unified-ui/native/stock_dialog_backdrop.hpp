// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include <initializer_list>
namespace wmp_ui { namespace native {
// Keep the stock page visible around a scoped dialog. The transparent object
// still receives pointer input so taps cannot reach controls behind the dialog.
inline void stock_dialog_backdrop(void*root){
 stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(root,2); // CLICKABLE
 stock_function<void(*)(void*,unsigned)>(lv_obj_clear_flag)(root,16); // SCROLLABLE
 for(auto property:{lv_obj_set_style_bg_opa,lv_obj_set_style_border_width,
                    lv_obj_set_style_radius,lv_obj_set_style_pad_top,
                    lv_obj_set_style_pad_bottom,lv_obj_set_style_pad_left,
                    lv_obj_set_style_pad_right})
  stock_function<void(*)(void*,int,unsigned)>(property)(root,0,0);
}
}}
