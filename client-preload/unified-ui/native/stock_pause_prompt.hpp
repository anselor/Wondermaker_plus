// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include "button_caption.hpp"
#include <algorithm>
#include "stock_dialog_backdrop.hpp"
#include "../model.hpp"
namespace wmp_ui { namespace native {
// One invitation per captured pause. LOAD opens a review, never a command.
class StockPausePrompt {
 void*root_=nullptr,*panel_=nullptr,*screen_=nullptr,*load_=nullptr,*body_=nullptr;
 Json data_=Json::object();std::string shown_,dismissed_;
 static void place(void*p,int x,int y,int w,int h){stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(p,w,h);stock_function<void(*)(void*,int,int,int)>(lv_obj_align)(p,1,x,y);}
 static void label(void*p,const std::string&text){stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(p,0xffeeeeeeU,0);stock_function<void(*)(void*,const char*)>(lv_label_set_text)(p,text.c_str());stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(MyriadPro_Regular_22),0);}
 static std::string key(const Json&d){return d.value("session","")+":"+d.value("paused_filament",Json::object()).value("origin",Json::object()).dump();}
 void*button(const char*text,int x,int y,int width){
  auto*b=stock_function<void*(*)(void*)>(lv_obj_create)(panel_);stock_dialog_backdrop(b);
  place(b,x,y,width,56);auto*l=stock_function<void*(*)(void*)>(lv_label_create)(b);label(l,text);center_button_caption(b,l,text);
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(l,reinterpret_cast<void*>(MyriadPro_Bold_24),0);
  place(l,4,8,width-8,40);
  stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(b,&pressed,7,this);return b;
 }
public:
 std::function<void(unsigned)> review;
 static bool eligible(const Json&d){
  if(!paused_filament_for(d)||d["paused_filament"].value("serviced",false))return false;
  for(const auto*k:{"filament_operation","toolhead_operation"}){
   const auto op=d.value(k,Json::object());const auto state=op.value("state","");
   if(state=="pending"||state=="running"||(d.value("owner","")!="standalone"&&(state=="unknown"||(state=="failed"&&!op.value("recovered",false)))))return false;
  }
  const auto head=d["paused_filament"].value("head","");
  for(const auto&h:d.value("heads",Json::array()))if(h.value("id","")==head)
   return h.value("loaded",Json::object()).value("state","")=="empty";
  return false;
 }
 void close(){auto*p=root_;root_=panel_=screen_=load_=body_=nullptr;shown_.clear();if(stock_object_valid(p))stock_function<void(*)(void*)>(lv_obj_del)(p);}
 void dismiss(){if(!shown_.empty())dismissed_=shown_;close();}
 void update(const Json&d,bool allow=true){
  data_=d;auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);
  if(!allow||!stock_object_valid(screen)||(stock_object_valid(root_)&&screen_!=screen)){close();return;}
  if(!d.value("fresh",false)){if(stock_object_valid(root_))readiness(false);return;}
  if(!eligible(d)){close();return;}
  const auto id=key(d);if(id==dismissed_){close();return;}
  if(stock_object_valid(root_)&&screen_==screen&&shown_==id){readiness(true);return;}
  close();if(!stock_object_valid(screen))return;
  screen_=screen;shown_=id;root_=stock_function<void*(*)(void*)>(lv_obj_create)(screen);if(!root_){shown_.clear();return;}
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(root_,&deleted,33,this)){close();return;}
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(root_,reinterpret_cast<void*>(0x463c8d8),0);
  stock_dialog_backdrop(root_);
  const int w=stock_function<int(*)(void*)>(lv_obj_get_width)(screen),h=stock_function<int(*)(void*)>(lv_obj_get_height)(screen);
  place(root_,0,0,w,h);
  const int pw=std::min(560,w-24),ph=std::min(280,h-24);
  panel_=stock_function<void*(*)(void*)>(lv_obj_create)(root_);if(!panel_){close();return;}
  stock_dialog_backdrop(panel_);place(panel_,(w-pw)/2,(h-ph)/2,pw,ph);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(panel_,0xff3c3f43U,0);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(panel_,255,0);
  const auto head=d["paused_filament"].value("head","");
  auto*title=stock_function<void*(*)(void*)>(lv_label_create)(panel_);label(title,"Filament needed - Head "+std::to_string(head[1]-'0'+1));place(title,16,16,pw-32,36);
  load_=button("LOAD",16,ph-72,pw/2-24);button("CANCEL",pw/2+8,ph-72,pw/2-24);
  auto*body=stock_function<void*(*)(void*)>(lv_obj_create)(panel_);stock_dialog_backdrop(body);place(body,16,58,pw-32,ph-146);
  stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(body,16);stock_function<void(*)(void*,int)>(lv_obj_set_scroll_dir)(body,12);
  body_=stock_function<void*(*)(void*)>(lv_label_create)(body);label(body_,guidance(d));
  stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(body_,0,0);stock_function<void(*)(void*,int)>(lv_obj_set_width)(body_,pw-40);stock_function<void(*)(void*,int)>(lv_label_set_long_mode)(body_,0);
 }
private:
 static std::string guidance(const Json&d){
  for(const auto*key:{"filament_operation","toolhead_operation"}){
   const auto op=d.value(key,Json::object());const auto state=op.value("state","");
   if(d.value("owner","")=="standalone"&&(state=="unknown"||(state=="failed"&&!op.value("recovered",false))))
    return "The previous operation needs attention. Check the head, then choose LOAD to review the current procedure. The print stays paused.";
  }
  return "The print is paused. Load filament into this head, then use Resume when ready.";
 }
 void readiness(bool ready){
  stock_function<void(*)(void*,unsigned)>(ready?lv_obj_clear_state:lv_obj_add_state)(load_,128);
  auto*caption=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(load_,0);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(caption,ready?0xffeeeeeeU:0xff888888U,0);
  label(body_,ready?guidance(data_):"Waiting for printer status...");
 }
 static void deleted(void*e)noexcept{try{
  auto*o=static_cast<StockPausePrompt*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));
  if(o&&stock_function<void*(*)(void*)>(lv_event_get_target)(e)==o->root_){o->root_=o->panel_=o->screen_=o->load_=o->body_=nullptr;o->shown_.clear();}
 }catch(...){} }
 static void pressed(void*e)noexcept{try{
  auto*o=static_cast<StockPausePrompt*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(!o||!stock_object_valid(o->root_))return;
  if(stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr)!=o->screen_){o->close();return;}
  const bool load=stock_function<void*(*)(void*)>(lv_event_get_target)(e)==o->load_;
  if(!load){o->dismiss();return;}
  if(!o->data_.value("fresh",false))return;
  if(!eligible(o->data_)||key(o->data_)!=o->shown_){o->close();return;}
  const unsigned head=unsigned(o->data_["paused_filament"].value("head","")[1]-'0');
  o->dismiss();if(load&&o->review)o->review(head);
 }catch(...){} }
};
}}
