// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdlib>
#include "stock_api.hpp"
#include "button_caption.hpp"
#include "stock_header_action.hpp"
#include "stock_dialog_backdrop.hpp"
#include "../model.hpp"
#ifndef WMP_UI_BUILD_ID
#define WMP_UI_BUILD_ID "development"
#endif
namespace wmp_ui { namespace native {
// Read-only addition to stock About. No backend submission or machine commands.
class StockDiagnostics {
 void*content_=nullptr,*entry_=nullptr,*panel_=nullptr,*text_=nullptr,*close_=nullptr;
 struct Covered{void*node;bool hidden;};std::vector<Covered>covered_;
 void restore(){
  for(const auto&o:covered_){
   if(stock_object_valid(o.node)&&stock_function<void*(*)(void*)>(lv_obj_get_parent)(o.node)==content_)
    stock_function<void(*)(void*,unsigned)>(o.hidden?lv_obj_add_flag:lv_obj_clear_flag)(o.node,1);
  }
  covered_.clear();
 }

 Json data_=Json::object();std::string rendered_;
 static void place(void*p,int x,int y,int w,int h){stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(p,w,h);stock_function<void(*)(void*,int,int,int)>(lv_obj_align)(p,1,x,y);}
 static void style(void*p,std::uintptr_t s){stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(p,reinterpret_cast<void*>(s),0);}
 static void caption(void*p,const std::string&s){stock_function<void(*)(void*,const char*)>(lv_label_set_text)(p,s.c_str());stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(MyriadPro_Regular_16),0);}
 bool visible()const{
  auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);auto*p=content_;
  for(unsigned i=0;p&&i<20;++i){if(!stock_object_valid(p)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return false;if(p==screen)return true;p=stock_function<void*(*)(void*)>(lv_obj_get_parent)(p);}return false;
 }
public:
 static std::string release_identity(){
  const auto*value=std::getenv("WMP_RELEASE_IDENTITY");
  return value&&*value?std::string(value):std::string("UI ")+WMP_UI_BUILD_ID;
 }
 static std::string release_caption(){
  const auto value=release_identity();
  return value.size()>43?value.substr(0,20)+"..."+value.substr(value.size()-20):value;
 }
 static std::string describe(const Json&d){
  const bool fresh=d.value("fresh",false);const auto owner=d.value("owner","");
  std::string out="WM+ release: "+release_identity()+"\nWM+ UI: " WMP_UI_BUILD_ID "\nVerified touchscreen: WM 1.1.13\n";
  out+="Filament owner: "+std::string(fresh?(owner=="standalone"?"WM+ standalone":owner=="openace"?"openACE":"Unknown"):"Unavailable (stale status)")+"\n";
  out+="Printer status: "+std::string(fresh?"Current":"Unavailable or stale")+"\n";
  const auto age=d.value("status_age_ms",-1LL);
  out+=age>=0?"Last status update: "+std::to_string(age)+" ms ago\n":"Last status update: not received\n";
  out+="Advertised features (not hardware validation):\n";
  const auto caps=d.value("capabilities",Json::object());
  for(const auto&item:std::vector<std::pair<std::string,std::string>>{{"load","Load"},{"unload","Unload"},{"toolhead_action","Mount / Dock"},{"save_nozzle","Nozzle editing"}})
   out+="  "+item.second+": "+(!fresh?"Unknown":caps.value(item.first,false)?"Supported":"Unavailable")+"\n";
  // start_print is a file-preview action capability, absent before choosing a
  // file. Report the owner's advertised mapping protocol independently.
  const bool mapping=d.value(owner=="openace"?"openace_print_start_protocol":"print_start_protocol",0)==1;
  out+="  Print mapping: "+std::string(!fresh?"Unknown":mapping?"Supported":"Unavailable")+"\n";
  out+="Profile import: Deferred\n\nFirmware details: stock About page.\nSupport: export Klipper and Moonraker logs from the web interface.\nUI log (SSH): /tmp/wmp_openace_screen_<pid>.log";
  return out;
 }
 void attach(void*content){
  if(!stock_object_valid(content)||content==content_)return;
  close();content_=content;entry_=nullptr;
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(content_,&deleted,33,this)){content_=nullptr;return;}
  void*list=nullptr;
  const auto count=stock_function<unsigned(*)(void*)>(lv_obj_get_child_cnt)(content_);
  for(unsigned i=0;i<count;++i){
   auto*candidate=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(content_,int(i));
   if(stock_function<int(*)(void*)>(lv_obj_get_width)(candidate)<640||stock_function<int(*)(void*)>(lv_obj_get_height)(candidate)<250)continue;
   const auto children=stock_function<unsigned(*)(void*)>(lv_obj_get_child_cnt)(candidate);unsigned rows=0;
   for(unsigned n=0;n<children;++n){auto*row=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(candidate,int(n));
    if(stock_function<int(*)(void*)>(lv_obj_get_height)(row)==56&&stock_function<int(*)(void*)>(lv_obj_get_width)(row)>=640)++rows;
   }
   if(rows==6){if(list)return;list=candidate;}
  }
  if(!list)return; // The frozen constructor has one six-row scroll list.
  const int width=stock_function<int(*)(void*)>(lv_obj_get_content_width)(list);
  entry_=stock_function<void*(*)(void*)>(lv_obj_create)(list);if(!entry_)return;
  stock_dialog_backdrop(entry_);place(entry_,0,0,width,56);
  // Keep stock row objects and their refresh pointers intact; only shift
  // their positions, leaving WonderMaker+ first in the visible list.
  const auto rows=stock_function<unsigned(*)(void*)>(lv_obj_get_child_cnt)(list);
  unsigned index=0;
  for(unsigned i=0;i<rows;++i){auto*row=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(list,int(i));
   if(row==entry_||stock_function<int(*)(void*)>(lv_obj_get_height)(row)!=56||stock_function<int(*)(void*)>(lv_obj_get_width)(row)<640)continue;
   stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(row,0,int(++index)*57);
  }
  auto*label=stock_function<void*(*)(void*)>(lv_label_create)(entry_);caption(label,"WonderMaker+");place(label,35,12,350,32);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(label,0xffffffffU,0);
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(label,reinterpret_cast<void*>(MyriadPro_Regular_22),0);
  auto*value=stock_function<void*(*)(void*)>(lv_label_create)(entry_);caption(value,release_caption());place(value,300,14,width-310,32);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(value,0xffffffffU,0);
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(value,reinterpret_cast<void*>(MyriadPro_Regular_16),0);
  auto*line=stock_function<void*(*)(void*)>(lv_obj_create)(entry_);stock_dialog_backdrop(line);place(line,25,0,width-50,1);
  stock_function<void(*)(void*,unsigned)>(lv_obj_clear_flag)(line,2);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(line,0xff707070U,0);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(line,127,0);
  stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(entry_,&pressed,7,this);
 }
 void created(void*page){
  if(!stock_object_valid(page))return;
  // Stock construction sets sizes through styles; LVGL has not necessarily
  // resolved those sizes when the constructor hook returns.
  stock_function<void(*)(void*)>(lv_obj_update_layout)(page);
  void*content=nullptr;
  const int page_width=stock_function<int(*)(void*)>(lv_obj_get_width)(page);
  const auto count=stock_function<unsigned(*)(void*)>(lv_obj_get_child_cnt)(page);
  for(unsigned i=0;i<count;++i){auto*p=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(page,int(i));
   const int width=stock_function<int(*)(void*)>(lv_obj_get_width)(p);
   // Stock About also has a full-page sidebar wrapper. Only its inset content
   // panel is eligible; accepting both makes the constructor ambiguous.
   if(width>=640&&width<page_width&&stock_function<int(*)(void*)>(lv_obj_get_height)(p)>=300){if(content)return;content=p;}}
  if(content)attach(content);
 }
 void update(const Json&data){
  // The About page needs this compact summary, not copies of every procedure,
  // mapping and receipt on every refresh while the page is hidden.
  data_=Json::object();
  for(const auto*key:{"fresh","owner","status_age_ms","capabilities","print_start_protocol","openace_print_start_protocol"})
   if(data.contains(key))data_[key]=data.at(key);
  if(!visible()){close();return;}if(!stock_object_valid(text_))return;
  const auto value=describe(data_);if(value!=rendered_){rendered_=value;caption(text_,value);}}
 void close(){restore();auto*p=panel_;panel_=text_=close_=nullptr;rendered_.clear();if(stock_object_valid(p))stock_function<void(*)(void*)>(lv_obj_del)(p);}
 bool open(){
  if(!visible())return false;
  close();
  const int w=stock_function<int(*)(void*)>(lv_obj_get_content_width)(content_),h=stock_function<int(*)(void*)>(lv_obj_get_content_height)(content_);
  panel_=stock_function<void*(*)(void*)>(lv_obj_create)(content_);if(!panel_)return false;
  style(panel_,0x463c8d8);stock_dialog_backdrop(panel_);stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(panel_,255,0);place(panel_,0,0,w,h);
  auto*title=stock_function<void*(*)(void*)>(lv_label_create)(panel_);caption(title,"About WonderMaker+");place(title,16,12,w-180,40);
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(title,reinterpret_cast<void*>(MyriadPro_Bold_24),0);
  auto*rule=stock_function<void*(*)(void*)>(lv_obj_create)(panel_);stock_dialog_backdrop(rule);place(rule,16,60,w-32,1);
  stock_function<void(*)(void*,unsigned)>(lv_obj_clear_flag)(rule,2);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(rule,0xff606060U,0);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(rule,255,0);
  close_=stock_header_action(panel_,"CLOSE",w-148,8,132,48,40);if(!close_){close();return false;}
  stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(close_,&pressed,7,this);
  auto*body=stock_function<void*(*)(void*)>(lv_obj_create)(panel_);style(body,0x463c8d8);place(body,12,68,w-24,h-80);
  stock_function<void(*)(void*,int)>(lv_obj_set_scroll_dir)(body,12);
  text_=stock_function<void*(*)(void*)>(lv_label_create)(body);
  stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(text_,8,8);
  stock_function<void(*)(void*,int)>(lv_obj_set_width)(text_,w-60); // Keep label's content-driven height for scrolling.
  stock_function<void(*)(void*,int)>(lv_label_set_long_mode)(text_,0);
  const auto count=stock_function<unsigned(*)(void*)>(lv_obj_get_child_cnt)(content_);
  for(unsigned i=0;i<count;++i){auto*child=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(content_,int(i));if(child==panel_)continue;
   covered_.push_back({child,stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(child,1)});stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(child,1);
  }
  update(data_);return true;
 }
private:
 static void pressed(void*e)noexcept{try{auto*o=static_cast<StockDiagnostics*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(!o||!o->visible())return;
  auto*target=stock_function<void*(*)(void*)>(lv_event_get_target)(e);if(target==o->entry_)o->open();else if(target==o->close_)o->close();}catch(...){} }
 static void deleted(void*e)noexcept{try{auto*o=static_cast<StockDiagnostics*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(o&&stock_function<void*(*)(void*)>(lv_event_get_target)(e)==o->content_){o->content_=o->entry_=o->panel_=o->text_=o->close_=nullptr;o->covered_.clear();o->rendered_.clear();}}catch(...){} }
};
}}
