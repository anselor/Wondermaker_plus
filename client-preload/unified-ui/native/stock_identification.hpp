// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "button_caption.hpp"
#include "stock_dialog_backdrop.hpp"
#include "stock_identification_flow.hpp"
namespace wmp_ui { namespace native {
class StockIdentification {
 void*page_=nullptr,*panel_=nullptr,*body_=nullptr,*action_=nullptr,*caption_=nullptr,*back_=nullptr;
 std::vector<void*>steps_;std::string rendered_;bool permitted_=false,setup_=false,can_back_=true;
 template<class F>static F fn(std::uintptr_t a){return dialog_function<F>(a);}
 static bool valid(void*p){return p&&fn<bool(*)(void*)>(lv_obj_is_valid)(p);}
 static void place(void*p,int x,int y,int w,int h){fn<void(*)(void*,int,int)>(lv_obj_set_size)(p,w,h);fn<void(*)(void*,int,int,int)>(lv_obj_align)(p,1,x,y);}
 static void label(void*p,const std::string&s){fn<void(*)(void*,const char*)>(lv_label_set_text)(p,s.c_str());fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(0x26297a0),0);fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(p,0xffffffffU,0);}
 bool visible()const{
  auto*screen=fn<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);auto*p=page_;
  for(unsigned i=0;p&&i<20;++i){if(!valid(p)||fn<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return false;if(p==screen)return true;p=fn<void*(*)(void*)>(lv_obj_get_parent)(p);}return false;
 }
 void clear(){auto*p=panel_;panel_=body_=action_=caption_=back_=nullptr;steps_.clear();rendered_.clear();if(valid(p))fn<void(*)(void*)>(lv_obj_del)(p);}
 void* button(int x,const char*text,bool action){
  auto*b=fn<void*(*)(void*)>(lv_obj_create)(panel_);stock_dialog_backdrop(b);place(b,x,0,110,40);
  auto*l=fn<void*(*)(void*)>(lv_label_create)(b);label(l,text);center_button_caption(b,l,text);
  fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(l,reinterpret_cast<void*>(0xf84928),0);
  fn<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(b,action?&pressed:&back_pressed,7,this);
  if(action){action_=b;caption_=l;}return b;
 }
public:
 std::function<void()> back,submit;
 void created(void*page,bool setup=false){
  clear();page_=nullptr;setup_=setup;
  if(valid(page)&&fn<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(page,&deleted,33,this))page_=page;
 }
 void update(const Json&data,const std::string&message,bool enabled,bool restart,bool can_back=true){
  permitted_=enabled;can_back_=can_back;
  if(!visible())return;
  if(!valid(panel_)){
   auto*screen=fn<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);
   const int w=fn<int(*)(void*)>(lv_obj_get_width)(screen),h=fn<int(*)(void*)>(lv_obj_get_height)(screen);
   panel_=fn<void*(*)(void*)>(lv_obj_create)(page_);if(!panel_)return;
   fn<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(panel_,&deleted,33,this);
   fn<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(panel_,reinterpret_cast<void*>(0x463c8d8),0);
   stock_dialog_backdrop(panel_);fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(panel_,255,0);fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(panel_,0xff3c3f41U,0);place(panel_,setup_?0:90,setup_?0:55,setup_?w:w-105,setup_?h:h-120);
   auto*t=fn<void*(*)(void*)>(lv_label_create)(panel_);label(t,"Extruder Setup");place(t,12,10,w-350,30);
   if(!setup_)back_=button(w-340,"BACK",false);
   button(setup_?w-120:w-220,"START",true);
   auto*rule=fn<void*(*)(void*)>(lv_obj_create)(panel_);stock_dialog_backdrop(rule);place(rule,12,40,w-124,1);
   fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(rule,0xff606060U,0);fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(rule,255,0);
   body_=fn<void*(*)(void*)>(lv_label_create)(panel_);place(body_,12,48,w-130,65);fn<void(*)(void*,int)>(lv_label_set_long_mode)(body_,0);
   for(unsigned i=0;i<7;++i){auto*l=fn<void*(*)(void*)>(lv_label_create)(panel_);place(l,20,116+int(i)*29,w-140,28);steps_.push_back(l);}
  }
  const auto op=data.value("identification",Json::object());const auto rows=op.value("steps",Json::array());
  const std::string signature=message+rows.dump()+(restart?"restart":"start")+(enabled?"yes":"no")+(can_back?"back":"locked")+(data.value("fresh",false)?"fresh":"stale");
  if(signature==rendered_)return;
  if(valid(back_))fn<void(*)(void*,unsigned)>(can_back?lv_obj_clear_flag:lv_obj_add_flag)(back_,1);
  label(body_,message);label(caption_,restart?"RESTART":"START");fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(caption_,reinterpret_cast<void*>(0xf84928),0);center_button_caption(action_,caption_,restart?"RESTART":"START");
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_text_opa)(caption_,enabled?255:100,0);
  unsigned visible_rows=0;
  for(unsigned i=0;i<steps_.size();++i){
   std::string text;std::uint32_t color=0xffffffffU;
   if(rows.is_array()&&i<rows.size()&&op.value("state","")!="complete"){
    const auto&r=rows[i];const auto state=r.value("state","");
    if(state=="active"||state=="failed"){
     text=r.value("label","");
     if(data.value("fresh",false)||state=="failed")color=0xffd24b00U;
    }
   }
   label(steps_[i],text);
   fn<void(*)(void*,unsigned)>(text.empty()?lv_obj_add_flag:lv_obj_clear_flag)(steps_[i],1);
   if(!text.empty())fn<void(*)(void*,int,int)>(lv_obj_set_pos)(steps_[i],20,116+int(visible_rows++)*29);
   fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(steps_[i],color,0);
  }
  rendered_=signature;
 }
private:
 static void deleted(void*e)noexcept{try{auto*o=static_cast<StockIdentification*>(fn<void*(*)(void*)>(lv_event_get_user_data)(e));if(!o)return;
  auto*p=fn<void*(*)(void*)>(lv_event_get_target)(e);if(p==o->page_)o->page_=nullptr;
  if(p==o->panel_){o->panel_=o->body_=o->action_=o->caption_=o->back_=nullptr;o->steps_.clear();o->rendered_.clear();}
 }catch(...){} }
 static void pressed(void*e)noexcept{try{auto*o=static_cast<StockIdentification*>(fn<void*(*)(void*)>(lv_event_get_user_data)(e));if(o&&o->visible()&&valid(o->panel_)&&o->permitted_&&o->submit)o->submit();}catch(...){} }
 static void back_pressed(void*e)noexcept{try{auto*o=static_cast<StockIdentification*>(fn<void*(*)(void*)>(lv_event_get_user_data)(e));if(o&&o->visible()&&o->can_back_&&o->back)o->back();}catch(...){} }
};
}}
