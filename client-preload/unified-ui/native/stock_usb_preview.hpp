// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include "button_caption.hpp"
#include "stock_preview_controls.hpp"
#include "preview.hpp"
namespace wmp_ui { namespace native {
// Reuses the vendor preview's title, thumbnail, footer and source panel.
// Copy and review are separate actions; this view has no print submission.
class StockUsbPreview {
 StockPreviewControls controls_;StockPreviewWidgets widgets_;
 void*message_=nullptr;Json result_=Json::object();bool attached_=false,ready_=false,submitted_=false,reviewed_=false;
 static bool caption(void*button,const std::string&text){
  if(stock_function<unsigned(*)(void*)>(lv_obj_get_child_cnt)(button)!=1)return false;
  auto*label=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(button,0);
  stock_function<void(*)(void*,const char*)>(lv_label_set_text)(label,text.c_str());center_button_caption(button,label,text);return true;
 }
 void dispatch(unsigned action){
  if(!active())return;
  if(action==3){close();if(closed)closed();return;}
  if(action!=4)return;
  if(result_.value("state","")=="copied"){
   const auto destination=result_.value("destination","");
   if(!ready_||reviewed_||!preview_path(destination)||!review)return;
   reviewed_=true;controls_.readiness(false,false,true);review(destination);return;
  }
  if(!ready_||submitted_||!copy)return;
  submitted_=true;update({{"state","copying"}},false);copy();
 }
public:
 std::function<void()>copy,closed;
 std::function<void(const std::string&)>review;
 bool active()const{return attached_&&stock_object_valid(widgets_.content);}
 bool attach(StockPreviewWidgets widgets){
  close();
  if(!StockPreviewInventory::resolve(widgets))return false;
  if(!caption(widgets.start,"COPY")||!caption(widgets.cancel,"CANCEL"))return false;
  if(!controls_.attach(widgets,[this](unsigned action){dispatch(action);}))return false;
  widgets_=widgets;attached_=true;submitted_=reviewed_=false;result_=Json::object();
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(widgets.content,&deleted,33,this)){close();return false;}
  for(auto*p:widgets.sources)stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(p,1);
  for(auto*p:widgets.destinations)stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(p,1);
  auto*panel=stock_function<void*(*)(void*)>(lv_obj_get_parent)(widgets.sources[0]);
  stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(panel,16);
  stock_function<void(*)(void*,int)>(lv_obj_set_scroll_dir)(panel,12);
  stock_function<void(*)(void*,int)>(lv_obj_set_scrollbar_mode)(panel,3);
  message_=stock_function<void*(*)(void*)>(lv_label_create)(panel);if(!message_){close();return false;}
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(message_,reinterpret_cast<void*>(0x26297a0),0);
  stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(message_,8,8);
  // A new LVGL label has content-sized height. Constrain only its width so
  // wrapped filenames grow the scrollable stock panel rather than being clipped.
  stock_function<void(*)(void*,int)>(lv_label_set_long_mode)(message_,0);
  stock_function<void(*)(void*,int)>(lv_obj_set_width)(message_,stock_function<int(*)(void*)>(lv_obj_get_content_width)(panel)-16);
  update(Json::object(),false);return true;
 }
 void update(const Json&result,bool ready){
  if(!active())return;
  result_=result;ready_=ready;const auto state=result.value("state","");
  std::string text="Copy this file to the printer?";
  std::string label="COPY";bool enabled=ready&&!submitted_;
  if(state=="inspecting"){text="Checking USB file...";enabled=false;}
  else if(state=="unavailable"){label="COPY";text=result.value("message","USB file is unavailable.");enabled=false;}
  else if(state=="queued"||state=="copying"){label="COPYING";text="Copying file...";enabled=false;}
  else if(state=="copied"){label="OPEN FILE";text="File copied.";enabled=ready&&!reviewed_;}
  else if(state=="unknown"||state=="refused"){label="COPY";text=result.value("message","Copy unconfirmed. Check the destination.");enabled=false;}
  const auto destination=result.value("destination","");
  if(state=="unknown"&&!destination.empty())text+="\nLocal file: "+destination;
  if(state=="copied")controls_.admission_settled();
  caption(widgets_.start,label);stock_function<void(*)(void*,const char*)>(lv_label_set_text)(message_,text.c_str());
  controls_.readiness(enabled,enabled,true);
 }
 void close(){controls_.retire();auto*content=attached_?widgets_.content:nullptr;attached_=false;message_=nullptr;ready_=false;if(stock_object_valid(content))stock_function<void(*)(void*)>(lv_obj_del)(content);}
private:
 static void deleted(void*e)noexcept{try{auto*o=static_cast<StockUsbPreview*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(o&&stock_function<void*(*)(void*)>(lv_event_get_target)(e)==o->widgets_.content){o->attached_=false;o->message_=nullptr;}}catch(...){} }
};
}}
