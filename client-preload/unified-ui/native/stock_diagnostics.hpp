// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "button_caption.hpp"
#include "stock_dialog_backdrop.hpp"
#include "../model.hpp"
#ifndef WMP_UI_BUILD_ID
#define WMP_UI_BUILD_ID "development"
#endif
namespace wmp_ui { namespace native {
// Read-only addition to stock About. No backend submission or machine commands.
class StockDiagnostics {
 void*content_=nullptr,*entry_=nullptr,*panel_=nullptr,*text_=nullptr,*close_=nullptr;
 Json data_=Json::object();std::string rendered_;
 template<class F>static F fn(std::uintptr_t a){return dialog_function<F>(a);}
 static bool valid(void*p){return p&&fn<bool(*)(void*)>(lv_obj_is_valid)(p);}
 static void place(void*p,int x,int y,int w,int h){fn<void(*)(void*,int,int)>(lv_obj_set_size)(p,w,h);fn<void(*)(void*,int,int,int)>(lv_obj_align)(p,1,x,y);}
 static void style(void*p,std::uintptr_t s){fn<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(p,reinterpret_cast<void*>(s),0);}
 static void caption(void*p,const std::string&s){fn<void(*)(void*,const char*)>(lv_label_set_text)(p,s.c_str());fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(0x26297a0),0);}
 bool visible()const{
  auto*screen=fn<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);auto*p=content_;
  for(unsigned i=0;p&&i<20;++i){if(!valid(p)||fn<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return false;if(p==screen)return true;p=fn<void*(*)(void*)>(lv_obj_get_parent)(p);}return false;
 }
public:
 static std::string describe(const Json&d){
  const bool fresh=d.value("fresh",false);const auto owner=d.value("owner","");
  std::string out="WM+ UI: " WMP_UI_BUILD_ID "\nVerified touchscreen: WM 1.1.13\n";
  out+="Filament owner: "+std::string(fresh?(owner=="standalone"?"WM+ standalone":owner=="openace"?"openACE":"Unknown"):"Unavailable (stale status)")+"\n";
  out+="Printer status: "+std::string(fresh?"Current":"Unavailable or stale")+"\n";
  const auto age=d.value("status_age_ms",-1LL);
  out+=age>=0?"Last status update: "+std::to_string(age)+" ms ago\n":"Last status update: not received\n";
  out+="Advertised features (not hardware validation):\n";
  const auto caps=d.value("capabilities",Json::object());
  for(const auto&item:std::vector<std::pair<std::string,std::string>>{{"load","Load"},{"unload","Unload"},{"toolhead_action","Take / Dock"},{"save_nozzle","Nozzle editing"}})
   out+="  "+item.second+": "+(!fresh?"Unknown":caps.value(item.first,false)?"Supported":"Unavailable")+"\n";
  // start_print is a file-preview action capability, absent before choosing a
  // file. Report the owner's advertised mapping protocol independently.
  const bool mapping=d.value(owner=="openace"?"openace_print_start_protocol":"print_start_protocol",0)==1;
  out+="  Print mapping: "+std::string(!fresh?"Unknown":mapping?"Supported":"Unavailable")+"\n";
  out+="Profile import: Deferred\n\nFirmware details: stock About page.\nSupport: export Klipper and Moonraker logs from the web interface.\nUI log (SSH): /tmp/wmp_openace_screen_<pid>.log";
  return out;
 }
 void attach(void*content){
  if(!valid(content)||content==content_)return;
  close();content_=content;entry_=nullptr;
  if(!fn<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(content_,&deleted,33,this)){content_=nullptr;return;}
  entry_=fn<void*(*)(void*)>(lv_btn_create)(content_);if(!entry_)return;
  style(entry_,0x463c8f8);place(entry_,170,0,150,40);
  auto*label=fn<void*(*)(void*)>(lv_label_create)(entry_);caption(label,"WM+");center_button_caption(entry_,label,"WM+");
  fn<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(entry_,&pressed,7,this);
 }
 void created(void*page){
  if(!valid(page))return;
  // Stock construction sets sizes through styles; LVGL has not necessarily
  // resolved those sizes when the constructor hook returns.
  fn<void(*)(void*)>(lv_obj_update_layout)(page);
  void*content=nullptr;
  const int page_width=fn<int(*)(void*)>(lv_obj_get_width)(page);
  const auto count=fn<unsigned(*)(void*)>(lv_obj_get_child_cnt)(page);
  for(unsigned i=0;i<count;++i){auto*p=fn<void*(*)(void*,int)>(lv_obj_get_child)(page,int(i));
   const int width=fn<int(*)(void*)>(lv_obj_get_width)(p);
   // Stock About also has a full-page sidebar wrapper. Only its inset content
   // panel is eligible; accepting both makes the constructor ambiguous.
   if(width>=640&&width<page_width&&fn<int(*)(void*)>(lv_obj_get_height)(p)>=300){if(content)return;content=p;}}
  if(content)attach(content);
 }
 void update(const Json&data){data_=data;if(!visible()){close();return;}if(!valid(text_))return;
  const auto value=describe(data_);if(value!=rendered_){rendered_=value;caption(text_,value);}}
 void close(){auto*p=panel_;panel_=text_=close_=nullptr;rendered_.clear();if(valid(p))fn<void(*)(void*)>(lv_obj_del)(p);}
 bool open(){
  if(!visible())return false;
  close();
  const int w=fn<int(*)(void*)>(lv_obj_get_content_width)(content_),h=fn<int(*)(void*)>(lv_obj_get_content_height)(content_);
  panel_=fn<void*(*)(void*)>(lv_obj_create)(content_);if(!panel_)return false;
  style(panel_,0x463c8d8);stock_dialog_backdrop(panel_);fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(panel_,255,0);place(panel_,0,0,w,h);
  auto*title=fn<void*(*)(void*)>(lv_label_create)(panel_);caption(title,"WM+ diagnostics");place(title,20,10,w-180,30);
  auto*rule=fn<void*(*)(void*)>(lv_obj_create)(panel_);stock_dialog_backdrop(rule);place(rule,20,40,w-40,1);
  fn<void(*)(void*,unsigned)>(lv_obj_clear_flag)(rule,2);
  fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(rule,0xff606060U,0);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(rule,255,0);
  close_=fn<void*(*)(void*)>(lv_btn_create)(panel_);style(close_,0x463c8f8);place(close_,w-140,0,120,40);
  auto*label=fn<void*(*)(void*)>(lv_label_create)(close_);caption(label,"CLOSE");center_button_caption(close_,label,"CLOSE");
  fn<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(close_,&pressed,7,this);
  auto*body=fn<void*(*)(void*)>(lv_obj_create)(panel_);style(body,0x463c8d8);place(body,12,45,w-24,h-57);
  fn<void(*)(void*,int)>(lv_obj_set_scroll_dir)(body,12);
  text_=fn<void*(*)(void*)>(lv_label_create)(body);
  fn<void(*)(void*,int,int)>(lv_obj_set_pos)(text_,8,8);
  fn<void(*)(void*,int)>(lv_obj_set_width)(text_,w-60); // Keep label's content-driven height for scrolling.
  fn<void(*)(void*,int)>(lv_label_set_long_mode)(text_,0);update(data_);return true;
 }
private:
 static void pressed(void*e)noexcept{try{auto*o=static_cast<StockDiagnostics*>(fn<void*(*)(void*)>(lv_event_get_user_data)(e));if(!o||!o->visible())return;
  auto*target=fn<void*(*)(void*)>(lv_event_get_target)(e);if(target==o->entry_)o->open();else if(target==o->close_)o->close();}catch(...){} }
 static void deleted(void*e)noexcept{try{auto*o=static_cast<StockDiagnostics*>(fn<void*(*)(void*)>(lv_event_get_user_data)(e));if(o&&fn<void*(*)(void*)>(lv_event_get_target)(e)==o->content_){o->content_=o->entry_=o->panel_=o->text_=o->close_=nullptr;o->rendered_.clear();}}catch(...){} }
};
}}
