// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "button_caption.hpp"
#include "stock_api.hpp"
#include "stock_dialog_backdrop.hpp"
#include <algorithm>
#include <functional>
#include <string>
namespace wmp_ui { namespace native {
// Scoped explanation, optionally with an explicit confirmation callback.
// Closing a notice never dispatches that confirmation.
class StockNotice {
 void*root_=nullptr;void*close_=nullptr;void*confirm_=nullptr;
public:
 std::function<void()>dismissed,confirmed;
 bool active()const{return stock_object_valid(root_);}
 void close(){auto*root=root_;root_=nullptr;close_=nullptr;confirm_=nullptr;if(stock_object_valid(root))stock_function<void(*)(void*)>(lv_obj_del)(root);}
 bool show(void*parent,const std::string&message,const std::string&confirm_text=""){
  close();if(!stock_object_valid(parent))return false;
  root_=stock_function<void*(*)(void*)>(lv_obj_create)(parent);if(!root_)return false;
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(root_,&deleted,33,this)){close();return false;}
  const int w=stock_function<int(*)(void*)>(lv_obj_get_content_width)(parent),h=stock_function<int(*)(void*)>(lv_obj_get_content_height)(parent);
  if(w<200||h<160){close();return false;}
  style(root_,0x463c8d8);stock_dialog_backdrop(root_);stock_object_place(root_,0,0,w,h);
  auto*panel=stock_function<void*(*)(void*)>(lv_obj_create)(root_);if(!panel){close();return false;}
  const bool confirming=!confirm_text.empty();
  const int pw=std::min(confirming?560:460,w-16),ph=std::min(confirming?280:220,h-16);
  style(panel,0x463c8f8);stock_dialog_backdrop(panel);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(panel,0xff3c3f43U,0);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(panel,255,0);
  stock_object_place(panel,(w-pw)/2,(h-ph)/2,pw,ph);
  void*body=panel;
  if(confirming){
   body=stock_function<void*(*)(void*)>(lv_obj_create)(panel);if(!body){close();return false;}
   stock_dialog_backdrop(body);stock_object_place(body,16,16,pw-32,ph-104);
   stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(body,16);
   stock_function<void(*)(void*,int)>(lv_obj_set_scroll_dir)(body,12);
  }
  auto*label=stock_function<void*(*)(void*)>(lv_label_create)(body);if(!label){close();return false;}
  caption(label,message);
  if(confirming){
   stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(label,reinterpret_cast<void*>(0x34b82a8),0);
   stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(label,0,0);
   stock_function<void(*)(void*,int)>(lv_obj_set_width)(label,pw-40);
   stock_function<void(*)(void*,int)>(lv_label_set_long_mode)(label,0);
  }else stock_object_place(label,16,58,pw-32,ph-74);
  close_=stock_function<void*(*)(void*)>(lv_btn_create)(panel);if(!close_){close();return false;}
  style(close_,0x463c8e8);stock_dialog_backdrop(close_);stock_object_place(close_,confirming?pw/2+8:pw-132,confirming?ph-72:6,confirming?pw/2-24:116,confirming?56:44);
  auto*text=stock_function<void*(*)(void*)>(lv_label_create)(close_);if(!text){close();return false;}
  const char*negative=confirming?"CANCEL":"CLOSE";
  caption(text,negative);center_button_caption(close_,text,negative);
  if(confirming)large_button(close_,text);
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(close_,&pressed,7,this)){close();return false;}
  if(!confirm_text.empty()){
   confirm_=stock_function<void*(*)(void*)>(lv_btn_create)(panel);if(!confirm_){close();return false;}
   style(confirm_,0x463c8e8);stock_dialog_backdrop(confirm_);stock_object_place(confirm_,16,ph-72,pw/2-24,56);
   auto*text=stock_function<void*(*)(void*)>(lv_label_create)(confirm_);if(!text){close();return false;}
   caption(text,confirm_text);center_button_caption(confirm_,text,confirm_text);large_button(confirm_,text);
   if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(confirm_,&pressed,7,this)){close();return false;}
  }
  return true;
 }
private:
 static void large_button(void*button,void*label){
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(label,reinterpret_cast<void*>(0x1a57128),0);
  const int width=stock_function<int(*)(void*)>(lv_obj_get_width)(button);
  stock_object_place(label,4,8,width-8,40);
 }
 static void style(void*p,std::uintptr_t address){stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(p,reinterpret_cast<void*>(address),0);}
 static void caption(void*p,const std::string&s){stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(0x26297a0),0);stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(p,0xffeeeeeeU,0);stock_function<void(*)(void*,const char*)>(lv_label_set_text)(p,s.c_str());}
 static void deleted(void*e)noexcept{try{auto*o=static_cast<StockNotice*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(o&&stock_function<void*(*)(void*)>(lv_event_get_target)(e)==o->root_){o->root_=nullptr;o->close_=nullptr;o->confirm_=nullptr;}}catch(...){} }
 static void pressed(void*e)noexcept{try{
  auto*o=static_cast<StockNotice*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(!o||!o->active())return;auto*target=stock_function<void*(*)(void*)>(lv_event_get_target)(e);if(target!=o->close_&&target!=o->confirm_)return;
  auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(stock_function<void*(*)()>(lv_disp_get_default)());
  auto*top=stock_function<void*(*)(void*)>(lv_disp_get_layer_top)(nullptr);
  auto*system=stock_function<void*(*)(void*)>(lv_disp_get_layer_sys)(nullptr);
  auto*p=o->root_;bool visible=false;for(unsigned i=0;p&&i<32;++i){if(!stock_object_valid(p)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return;if(p==screen||p==top||p==system){visible=true;break;}p=stock_function<void*(*)(void*)>(lv_obj_get_parent)(p);}
  if(!visible)return;
  auto callback=target==o->confirm_?o->confirmed:o->dismissed;o->close();if(callback)callback();
 }catch(...){} }
};
}}
