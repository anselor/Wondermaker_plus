// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include "stock_dialog_backdrop.hpp"
#include "button_caption.hpp"
#include "../model.hpp"
#include <vector>
namespace wmp_ui { namespace native {
// Presentation only: no commands, worker state, or printer activity ownership.
class StockProgressPanel {
 void*title_=nullptr,*root_=nullptr,*steps_body_=nullptr,*details_=nullptr,*text_body_=nullptr;
 void*heading_=nullptr,*instruction_=nullptr,*note_=nullptr,*value_=nullptr,*choices_=nullptr,*more_=nullptr,*steps_more_=nullptr;
 std::vector<void*>rows_;Json rendered_,rendered_steps_;int rendered_left_=-1,steps_height_=0,width_=0,height_=0;
 bool rendered_valid_=false,shown_=true,fits_=true;
 static void place(void*p,int x,int y,int w,int h){stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(p,w,h);stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(p,x,y);}
 static void hidden(void*p,bool value){stock_function<void(*)(void*,unsigned)>(value?lv_obj_add_flag:lv_obj_clear_flag)(p,1);}
 static void text(void*p,const std::string&s){stock_function<void(*)(void*,const char*)>(lv_label_set_text)(p,s.c_str());}
 static void style_label(void*p,std::uintptr_t font=MyriadPro_Regular_22){
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(font),0);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(p,0xffeeeeeeU,0);
  stock_function<void(*)(void*,int)>(lv_label_set_long_mode)(p,0);
 }
 void reset(){
  title_=root_=steps_body_=details_=text_body_=heading_=instruction_=note_=value_=choices_=more_=steps_more_=nullptr;
  rows_.clear();rendered_valid_=false;rendered_left_=-1;rendered_steps_=Json();shown_=fits_=true;
 }
 static void deleted(void*e)noexcept{try{
  auto*self=static_cast<StockProgressPanel*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));
  if(self&&stock_function<void*(*)(void*)>(lv_event_get_target)(e)==self->root_)self->reset();
 }catch(...){} }
 static int paragraph(void*label,const std::string&content,int width,int y){
  hidden(label,content.empty());if(content.empty())return y;
  text(label,content);stock_function<void(*)(void*,int)>(lv_obj_set_width)(label,width);
  stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(label,8,y);
  stock_function<void(*)(void*)>(lv_obj_update_layout)(label);
  return y+stock_function<int(*)(void*)>(lv_obj_get_height)(label)+8;
 }
 static int value_lines(const std::string&s){return s.empty()?0:1+int(std::count(s.begin(),s.end(),'\n'));}
 // A step title belongs in the numbered list, not a second time in details.
 static std::string detail_key(const std::string&s){
  std::string key;for(unsigned char c:s){if(c>='A'&&c<='Z')c+=('a'-'A');
   if((c>='a'&&c<='z')||(c>='0'&&c<='9')||c>=128)key+=char(c);}
  return key;
 }
 static std::string additional_detail(const std::string&text,const Json&steps){
  const auto key=detail_key(text);if(key.empty())return text;
  for(const auto&step:steps)if(step.value("state","")=="running"&&key==detail_key(step.value("label","")))return "";
  return text;
 }
public:
 StockProgressPanel()=default;
 StockProgressPanel(const StockProgressPanel&)=delete;
 StockProgressPanel&operator=(const StockProgressPanel&)=delete;
 bool attached()const{return stock_object_valid(root_);}
 bool content_fits()const{return attached()&&fits_;}
 void close(){auto*p=root_;reset();if(stock_object_valid(p))stock_function<void(*)(void*)>(lv_obj_del)(p);}
 bool attach(void*parent,int x,int y,int width,int height){
  close();if(!stock_object_valid(parent)||width<320||height<100)return false;
  width_=width;height_=height;
  root_=stock_function<void*(*)(void*)>(lv_obj_create)(parent);if(!root_)return false;
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(root_,&deleted,33,this)){close();return false;}
  stock_dialog_backdrop(root_);place(root_,x,y,width,height);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(root_,0xff3c3f43U,0);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(root_,255,0);
  title_=stock_function<void*(*)(void*)>(lv_label_create)(root_);if(!title_){close();return false;}style_label(title_,MyriadPro_Bold_24);
  steps_body_=stock_function<void*(*)(void*)>(lv_obj_create)(root_);
  details_=stock_function<void*(*)(void*)>(lv_obj_create)(root_);
  if(!steps_body_||!details_){close();return false;}
  for(auto*p:{steps_body_,details_})stock_dialog_backdrop(p);
  text_body_=stock_function<void*(*)(void*)>(lv_obj_create)(details_);if(!text_body_){close();return false;}
  stock_dialog_backdrop(text_body_);
  for(auto*p:{steps_body_,text_body_}){
   stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(p,16);
   stock_function<void(*)(void*,int)>(lv_obj_set_scroll_dir)(p,12);
  }
  instruction_=stock_function<void*(*)(void*)>(lv_label_create)(text_body_);
  choices_=stock_function<void*(*)(void*)>(lv_obj_create)(text_body_);
  heading_=stock_function<void*(*)(void*)>(lv_label_create)(text_body_);
  value_=stock_function<void*(*)(void*)>(lv_label_create)(text_body_);
  note_=stock_function<void*(*)(void*)>(lv_label_create)(details_);
  more_=stock_function<void*(*)(void*)>(lv_label_create)(details_);
  steps_more_=stock_function<void*(*)(void*)>(lv_label_create)(root_);
  if(!instruction_||!choices_||!heading_||!value_||!note_||!more_||!steps_more_){close();return false;}
  for(auto*p:{instruction_,note_,more_,steps_more_})style_label(p);
  for(auto*p:{heading_,value_})style_label(p,MyriadPro_Bold_24);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(note_,0xffffbb66U,0);
  stock_dialog_backdrop(choices_);
  for(unsigned i=0;i<8;++i){auto*l=stock_function<void*(*)(void*)>(lv_label_create)(steps_body_);if(!l){close();return false;}style_label(l);hidden(l,true);rows_.push_back(l);}
  return true;
 }
 // Stable caller-owned decisions; updates never replace its children.
 void*choices_parent()const{return stock_object_valid(choices_)?choices_:nullptr;}
 void show(bool shown){if(attached()&&shown!=shown_){
  hidden(root_,!shown);shown_=shown;rendered_valid_=false;
  if(!shown){for(auto*row:rows_)hidden(row,true);rendered_left_=-1;}
 }}
 void update(const Json&view){
  if(!attached()||(rendered_valid_&&rendered_==view))return;
  const auto steps=view.value("steps",Json::array());
  if(!steps.is_array()||steps.size()>64)return;
  const auto value=view.value("value","");
  // Whole-degree changes do not move the instruction, rows, choices or a
  // pressed action. Multiline temperature lists reserve a line per heater.
  if(rendered_valid_&&value_lines(value)==value_lines(rendered_.value("value",""))){
   auto before=rendered_,after=view;before.erase("value");after.erase("value");
   if(before==after){text(value_,value);rendered_=view;return;}
  }
  const auto instruction=additional_detail(view.value("instruction",""),steps),heading=additional_detail(view.value("heading",""),steps),note=view.value("note","");
  const auto title=view.value("title","");
  hidden(title_,title.empty());text(title_,title);
  place(title_,8,0,std::max(1,std::min(width_-16,view.value("title_width",width_-16))),MyriadPro_Bold_24_line_height);
  const int top=title.empty()?0:48,body_height=height_-top;
  const bool decisions=view.value("decisions",false);
  const bool details=!instruction.empty()||!heading.empty()||!note.empty()||!value.empty()||decisions;
  const bool split=details&&!steps.empty();
  const int left=split?std::max(160,std::min(view.value("steps_width",width_*42/100),width_-160)):width_;
  const int right=split?width_-left-16:width_;
  hidden(steps_body_,steps.empty());hidden(details_,!details);
  place(details_,split?left+16:0,top,right,body_height);
  while(rows_.size()<steps.size()){
   auto*l=stock_function<void*(*)(void*)>(lv_label_create)(steps_body_);if(!l)return;style_label(l);rows_.push_back(l);
  }
  if(rendered_steps_!=steps||rendered_left_!=left){
   int y=0;
   for(unsigned i=0;i<rows_.size();++i){
    auto*l=rows_[i];hidden(l,i>=steps.size());if(i>=steps.size())continue;
    const auto step=steps[i];const auto state=step.value("state","");
    text(l,std::to_string(i+1)+". "+step.value("label",""));
    stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(l,state=="complete"?0xff888888U:state=="running"?0xffff6600U:state=="failed"?0xffff6666U:0xffeeeeeeU,0);
    stock_function<void(*)(void*,int)>(lv_obj_set_width)(l,left-16);
    stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(l,8,y);
    stock_function<void(*)(void*)>(lv_obj_update_layout)(l);
    y+=std::max(MyriadPro_Regular_22_line_height,stock_function<int(*)(void*)>(lv_obj_get_height)(l))+8;
   }
   steps_height_=y?y-8:0;rendered_steps_=steps;rendered_left_=left;
  }
  const bool steps_overflow=steps_height_>body_height;
  place(steps_body_,0,top,left,body_height-(steps_overflow?36:0));
  hidden(steps_more_,!steps_overflow);text(steps_more_,"Scroll for more");place(steps_more_,8,height_-28,left-16,28);
  int y=paragraph(heading_,heading,right-16,0);
  hidden(value_,value.empty());text(value_,value);
  if(!value.empty()){const int h=MyriadPro_Bold_24_line_height*value_lines(value);place(value_,8,y,right-16,h);y+=h+8;}
  y=paragraph(instruction_,instruction,right-16,y);
  const int note_height=paragraph(note_,note,right-16,0);
  const int footer=note.empty()?0:note_height;
  const int room=std::max(1,body_height-footer);
  const int choices_height=decisions?std::max(64,view.value("choices_height",room-y)):0;
  hidden(choices_,!decisions);place(choices_,8,y,right-16,choices_height);
  if(decisions)y+=choices_height;
  else if(y)y-=8;
  const bool overflow=y>room;
  place(text_body_,0,0,right,std::max(1,room-(overflow?36:0)));
  hidden(more_,!overflow);text(more_,"Scroll for more");place(more_,8,std::max(0,room-28),right-16,28);
  if(!note.empty())stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(note_,8,std::max(0,body_height-note_height+8));
  fits_=!steps_overflow&&!overflow&&note_height<=body_height;
  rendered_=view;rendered_valid_=true;
 }
};
}}
