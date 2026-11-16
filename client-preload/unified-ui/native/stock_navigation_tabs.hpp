// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include <array>
#include <functional>
#include <list>
namespace wmp_ui { namespace native {
// Only tab presentation and routing. Stock owns the pages and their file actions.
class StockNavigationTabs {
 struct Binding {StockNavigationTabs*owner;void*object;bool tools;};
 struct Files {void*video;std::array<void*,3>buttons;int x;bool selected;};
 std::list<Binding>bindings_;std::list<Files>files_;
 static bool visible(void*object){
  for(auto*p=object;p;p=stock_function<void*(*)(void*)>(lv_obj_get_parent)(p))
   if(!stock_object_valid(p)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return false;
  return object!=nullptr;
 }
 void bind(void*object,bool tools){
  stock_function<bool(*)(void*,void(*)(void*))>(lv_obj_remove_event_cb)(object,&event);
  for(auto it=bindings_.begin();it!=bindings_.end();)if(it->object==object)it=bindings_.erase(it);else ++it;
  bindings_.push_back({this,object,tools});
  stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(object,&event,0,&bindings_.back());
 }
 static void event(void*e)noexcept{try{
  auto*b=static_cast<Binding*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(!b)return;
  auto*owner=b->owner;const auto code=stock_function<int(*)(void*)>(lv_event_get_code)(e);
  if(code==33){
   for(auto it=owner->files_.begin();it!=owner->files_.end();)if(it->video==b->object)it=owner->files_.erase(it);else ++it;
   for(auto it=owner->bindings_.begin();it!=owner->bindings_.end();++it)if(&*it==b){owner->bindings_.erase(it);break;}
  }else if(code==7&&visible(b->object)&&!stock_function<bool(*)(void*,unsigned)>(lv_obj_has_state)(b->object,128)){
   if(b->tools){if(owner->tools)owner->tools();}else if(owner->video)owner->video();
  }
 }catch(...){} }
public:
 std::function<void()>tools,video,refresh_video_files;
 ~StockNavigationTabs(){for(const auto&b:bindings_)if(stock_object_valid(b.object))stock_function<bool(*)(void*,void(*)(void*))>(lv_obj_remove_event_cb)(b.object,&event);}
 void settings(const std::array<void*,5>&buttons){
  auto*button=buttons[2];if(!stock_object_valid(button))return;
  auto*label=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(button,0);
  stock_function<void(*)(void*,const char*)>(lv_label_set_text)(label,"Tools");
  stock_function<bool(*)(void*,void(*)(void*))>(lv_obj_remove_event_cb)(button,reinterpret_cast<void(*)(void*)>(stock_menu_event));
  bind(button,true);
 }
 void files(const std::array<void*,3>&buttons,bool selected){
  if(!stock_object_valid(buttons[0]))return;
  auto*parent=stock_function<void*(*)(void*)>(lv_obj_get_parent)(buttons[0]);
  auto*button=stock_function<void*(*)(void*)>(lv_btn_create)(parent);if(!button)return;
  stock_function<void(*)(void*)>(stock_remove_all_styles)(button);
  for(unsigned state:{0U,32U,128U}){
   stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(button,reinterpret_cast<void*>(0x463c8e8),state);
   stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(button,state?0xffcc4815U:0xff404146U,state);
  }
  stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(button,135,45);
  auto*label=stock_function<void*(*)(void*)>(lv_label_create)(button);
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(label,reinterpret_cast<void*>(MyriadPro_Regular_22),0);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(label,0xffffffffU,0);
  stock_function<void(*)(void*,const char*)>(lv_label_set_text)(label,stock_function<const char*(*)(const char*)>(lv_i18n_get_text)("Video"));
  stock_object_place(label,0,6,135,32);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_text_align)(label,2,0);
  stock_function<void(*)(void*,unsigned)>(selected?lv_obj_add_state:lv_obj_clear_state)(button,128);
  bind(button,false);files_.push_back({button,buttons,-1,selected});refresh();
 }
 void refresh(){
  for(auto&f:files_){
   if(!visible(f.video))continue;
   if(f.selected&&refresh_video_files)refresh_video_files();
   const bool usb=stock_object_valid(f.buttons[1])&&!stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(f.buttons[1],1);
   const int x=usb?420:280;
   if(x!=f.x){stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(f.video,x,0);f.x=x;}
  }
 }
};
}}
