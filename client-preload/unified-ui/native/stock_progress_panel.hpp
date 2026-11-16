// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_dialog_backdrop.hpp"
#include "button_caption.hpp"
#include "../model.hpp"
#include <vector>
namespace wmp_ui { namespace native {
// Presentation only. The caller owns the operation, header actions and every
// decision callback. This panel neither sends commands nor represents busy.
class StockProgressPanel {
 void*title_=nullptr;
 void*root_=nullptr,*steps_body_=nullptr,*details_=nullptr,*instruction_=nullptr,*choices_=nullptr;
 std::vector<void*>rows_;Json rendered_;int width_=0,height_=0;bool rendered_valid_=false;
 template<class F>static F fn(std::uintptr_t a){return dialog_function<F>(a);}
 static bool valid(void*p){return p&&fn<bool(*)(void*)>(lv_obj_is_valid)(p);}
 static void place(void*p,int x,int y,int w,int h){fn<void(*)(void*,int,int)>(lv_obj_set_size)(p,w,h);fn<void(*)(void*,int,int)>(lv_obj_set_pos)(p,x,y);}
 static void hidden(void*p,bool value){fn<void(*)(void*,unsigned)>(value?lv_obj_add_flag:lv_obj_clear_flag)(p,1);}
 static void style_label(void*p){
  fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(0x34b82a8),0);
  fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(p,0xffeeeeeeU,0);
  fn<void(*)(void*,int)>(lv_label_set_long_mode)(p,0);
 }
 void reset(){title_=root_=steps_body_=details_=instruction_=choices_=nullptr;rows_.clear();rendered_valid_=false;}
 static void deleted(void*e)noexcept{try{
  auto*self=static_cast<StockProgressPanel*>(fn<void*(*)(void*)>(lv_event_get_user_data)(e));
  if(self&&fn<void*(*)(void*)>(lv_event_get_target)(e)==self->root_)self->reset();
 }catch(...){} }
public:
 StockProgressPanel()=default;
 StockProgressPanel(const StockProgressPanel&)=delete;
 StockProgressPanel&operator=(const StockProgressPanel&)=delete;
 bool attached()const{return valid(root_);}
 void close(){auto*p=root_;reset();if(valid(p))fn<void(*)(void*)>(lv_obj_del)(p);}
 bool attach(void*parent,int x,int y,int width,int height){
  close();if(!valid(parent)||width<320||height<100)return false;
  width_=width;height_=height;
  root_=fn<void*(*)(void*)>(lv_obj_create)(parent);if(!root_)return false;
  if(!fn<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(root_,&deleted,33,this)){close();return false;}
  stock_dialog_backdrop(root_);place(root_,x,y,width,height);
  fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(root_,0xff3c3f43U,0);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(root_,255,0);
  title_=fn<void*(*)(void*)>(lv_label_create)(root_);if(!title_){close();return false;}style_label(title_);
  steps_body_=fn<void*(*)(void*)>(lv_obj_create)(root_);
  details_=fn<void*(*)(void*)>(lv_obj_create)(root_);
  if(!steps_body_||!details_){close();return false;}
  for(auto*p:{steps_body_,details_}){
   stock_dialog_backdrop(p);fn<void(*)(void*,unsigned)>(lv_obj_add_flag)(p,16);fn<void(*)(void*,int)>(lv_obj_set_scroll_dir)(p,12);
  }
  instruction_=fn<void*(*)(void*)>(lv_label_create)(details_);
  choices_=fn<void*(*)(void*)>(lv_obj_create)(details_);
  if(!instruction_||!choices_){close();return false;}
  style_label(instruction_);stock_dialog_backdrop(choices_);
  // Common flows fit eight rows. Reserve them before the first observation so
  // later phases retain the same widget tree and in-progress touch targets.
  for(unsigned i=0;i<8;++i){auto*l=fn<void*(*)(void*)>(lv_label_create)(steps_body_);if(!l){close();return false;}style_label(l);hidden(l,true);rows_.push_back(l);}
  return true;
 }
 // Operation-specific radio buttons or other decisions live here. Updates do
 // not replace the container or its children, preserving presses and drafts.
 void*choices_parent()const{return valid(choices_)?choices_:nullptr;}
 void show(bool shown){if(valid(root_)){hidden(root_,!shown);if(!shown)for(auto*row:rows_)hidden(row,true);rendered_valid_=false;}}
 void update(const Json&view){
  if(!attached()||(rendered_valid_&&rendered_==view))return;
  const auto steps=view.value("steps",Json::array());
  if(!steps.is_array()||steps.size()>64)return;
  const auto instruction=view.value("instruction","");
  const auto title=view.value("title","");
  hidden(title_,title.empty());
  fn<void(*)(void*,const char*)>(lv_label_set_text)(title_,title.c_str());place(title_,8,0,width_-16,36);
  const int top=title.empty()?0:48,body_height=height_-top;
  const bool decisions=view.value("decisions",false);
  const bool split=(!instruction.empty()||decisions)&&!steps.empty();
  const int left=split?std::max(220,width_*42/100):width_;
  const int right=split?width_-left-16:width_;
  hidden(steps_body_,steps.empty());hidden(details_,instruction.empty()&&!decisions);
  place(steps_body_,0,top,left,body_height);
  place(details_,split?left+16:0,top,right,body_height);
  while(rows_.size()<steps.size()){
   auto*l=fn<void*(*)(void*)>(lv_label_create)(steps_body_);if(!l)return;style_label(l);rows_.push_back(l);
  }
  int y=0;
  for(unsigned i=0;i<rows_.size();++i){
   auto*l=rows_[i];hidden(l,i>=steps.size());if(i>=steps.size())continue;
   const auto step=steps[i];const auto state=step.value("state","");
   const auto text=std::to_string(i+1)+". "+step.value("label","");
   fn<void(*)(void*,const char*)>(lv_label_set_text)(l,text.c_str());
   fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(l,state=="complete"?0xff888888U:state=="running"?0xffff6600U:0xffeeeeeeU,0);
   fn<void(*)(void*,int)>(lv_obj_set_width)(l,left-16);
   fn<void(*)(void*,int,int)>(lv_obj_set_pos)(l,8,y);
   fn<void(*)(void*)>(lv_obj_update_layout)(l);
   y+=std::max(30,fn<int(*)(void*)>(lv_obj_get_height)(l))+8;
  }
  hidden(instruction_,instruction.empty());
  fn<void(*)(void*,const char*)>(lv_label_set_text)(instruction_,instruction.c_str());
  fn<void(*)(void*,int)>(lv_obj_set_width)(instruction_,right-16);
  fn<void(*)(void*,int,int)>(lv_obj_set_pos)(instruction_,8,0);
  fn<void(*)(void*)>(lv_obj_update_layout)(instruction_);
  const int choices_y=instruction.empty()?0:fn<int(*)(void*)>(lv_obj_get_height)(instruction_)+16;
  hidden(choices_,!decisions);place(choices_,8,choices_y,right-16,std::max(56,body_height-choices_y));
  rendered_=view;rendered_valid_=true;
 }
};
}}
