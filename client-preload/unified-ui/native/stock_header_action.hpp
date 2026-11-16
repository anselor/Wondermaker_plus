// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include "stock_dialog_backdrop.hpp"
#include "button_caption.hpp"
namespace wmp_ui { namespace native {
// An action's visible bar and touch target may differ. Ownership and callbacks
// remain with the screen; this helper only creates/styles its widgets.
inline void stock_header_action_caption(void*button,const std::string&text,bool enabled=true,int visible_height=40){
 auto*caption=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(button,0);
 stock_function<void(*)(void*,const char*)>(lv_label_set_text)(caption,text.c_str());
 stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(caption,reinterpret_cast<void*>(MyriadPro_Bold_20),0);
 center_button_caption(button,caption,text,visible_height);
 stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(caption,enabled?0xffeeeeeeU:0xff888888U,0);
 stock_function<void(*)(void*,unsigned)>(enabled?lv_obj_clear_state:lv_obj_add_state)(button,128);
}
inline void*stock_header_action(void*parent,const std::string&text,int x,int y,int width,int hit_height=40,int visible_height=40){
 auto*button=stock_function<void*(*)(void*)>(lv_obj_create)(parent);if(!button)return nullptr;
 stock_dialog_backdrop(button);stock_object_place(button,x,y,width,hit_height);
 auto*caption=stock_function<void*(*)(void*)>(lv_label_create)(button);
 if(!caption){stock_function<void(*)(void*)>(lv_obj_del)(button);return nullptr;}
 stock_header_action_caption(button,text,true,visible_height);return button;
}
}}
