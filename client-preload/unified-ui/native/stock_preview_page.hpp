// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include "stock_preview_controls.hpp"
#include "stock_preview_rows.hpp"
#include "stock_ace_filaments.hpp"
#include "stock_notice.hpp"
#include "stock_image_preview.hpp"
namespace wmp_ui { namespace native {
// Coordinates existing stock preview widgets and the shared controller. Source
// selection and explanations are scoped modals, not replacement app shells.
class StockPreviewPage {
 App&app_;StockPreviewWidgets widgets_;StockPreviewControls controls_;
 StockPreviewRows rows_;StockAceFilaments picker_;void*modal_=nullptr;void*notice_=nullptr;
 StockImagePreview image_preview_;StockNotice explanation_,material_review_;bool attached_=false,header_ready_=false;
public:
 std::function<void()>closed;
 explicit StockPreviewPage(App&app):app_(app){
  material_review_.dismissed=[this]{app_.event("material-review-cancel");controls_.admission_settled();tick();};
  material_review_.confirmed=[this]{app_.event("material-review-confirm");controls_.admission_settled();tick();};
  image_preview_.dismissed=[this](){tick();};picker_.picker_mode(true);explanation_.dismissed=[this](){tick();};
  rows_.select=[this](const std::string&id){if(attached_&&!explanation_.active()&&!material_review_.active()&&!image_preview_.active()&&!app_.source_picker_state().value("picker_open",false)){app_.event("map:"+id);tick();}};
  picker_.action=[this](const std::string&id){if(attached_){app_.event(id);tick();}};
 }
 bool attach(StockPreviewWidgets widgets,const std::string&white){
  close();
  if(!StockPreviewInventory::resolve(widgets))return false;
  if(!controls_.attach(widgets,[this](unsigned action){dispatch(action);}))return false;
  widgets_=widgets;attached_=true;header_ready_=false;
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(widgets_.content,&deleted,33,this)){close();return false;}
  if(!rows_.mount(widgets_,white)){close();return false;}
  notice_=stock_function<void*(*)(void*)>(lv_label_create)(widgets_.content);
  if(!notice_){close();return false;}
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(notice_,reinterpret_cast<void*>(MyriadPro_Regular_16),0);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(notice_,0xffeeeeeeU,0);
  if(stock_object_valid(widgets_.thumbnail)){
   stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(widgets_.thumbnail,2); // CLICKABLE
   if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(widgets_.thumbnail,&thumbnail_pressed,7,this)){close();return false;}
  }
  tick();return true;
 }
 bool active()const{return attached_;}
 void close(){
  image_preview_.close();explanation_.close();material_review_.close();app_.event("material-review-cancel");controls_.retire();auto*content=attached_?widgets_.content:nullptr;
  attached_=false;modal_=nullptr;notice_=nullptr;
  if(stock_object_valid(content))stock_function<void(*)(void*)>(lv_obj_del)(content);
 }
 void tick(){
  if(!attached_||!stock_object_valid(widgets_.content))return;
  const auto state=app_.preview_state();const auto chooser=app_.source_picker_state();
  if(state.value("material_review",false)){if(!material_review_.active())material_review_.show(widgets_.content,"Start print?\n\n"+state.value("mapping_summary","")+(state.value("material_warning","").empty()?"":"\n\n"+state.value("material_warning","")),"PRINT");}
  else material_review_.close();
  const bool picking=chooser.value("picker_open",false);
  const auto op=state.value("operation",Json::object());const auto status=op.value("state","");
  if(op.empty()||status=="refused"||status=="failed"||status=="complete")controls_.admission_settled();
  controls_.readiness(!picking&&!explanation_.active()&&!material_review_.active()&&!image_preview_.active()&&state.value("editable",false),state.value("can_start",false));
  auto*panel=stock_function<void*(*)(void*)>(lv_obj_get_parent)(widgets_.sources[0]);
  rows_.update(state,stock_function<int(*)(void*)>(lv_obj_get_content_width)(panel));
  const int width=stock_function<int(*)(void*)>(lv_obj_get_content_width)(widgets_.content);
  const int height=stock_function<int(*)(void*)>(lv_obj_get_content_height)(widgets_.content);
  stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(notice_,12,42);
  stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(notice_,width-24,24);
  stock_function<void(*)(void*,int)>(lv_label_set_long_mode)(notice_,1); // Use the full header gap, above both preview columns.
  auto text=state.value("notice","").empty()?state.value("reason",""):state.value("notice","");
  if(app_.page()=="preview-loading")text="Loading file information...";
  const bool admitting=op.value("action","")=="start_print"&&(status=="pending"||status=="unknown");
  if(admitting)text=status=="pending"?"Starting print...":"Waiting for print status...";
  if(!header_ready_&&stock_function<unsigned(*)(void*)>(lv_obj_get_child_cnt)(widgets_.cancel)==1){
   auto*caption=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(widgets_.cancel,0);
   stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(widgets_.cancel,100,32);
   stock_function<void(*)(void*,int,int,int)>(lv_obj_align)(widgets_.cancel,1,stock_function<int(*)(void*)>(lv_obj_get_content_width)(widgets_.content)-210,2);
   stock_function<void(*)(void*,const char*)>(lv_label_set_text)(caption,"CANCEL");center_button_caption(widgets_.cancel,caption,"CANCEL");
   controls_.fit_header();header_ready_=true;
  }else if(stock_function<unsigned(*)(void*)>(lv_obj_get_child_cnt)(widgets_.cancel)!=1&&admitting&&chooser.value("owner","")!="standalone")stock_function<void(*)(void*,unsigned)>(lv_obj_add_state)(widgets_.cancel,128);
  stock_function<void(*)(void*,const char*)>(lv_label_set_text)(notice_,text.c_str());
  const auto options=state.value("options",Json::object());
  for(unsigned i:{0U,2U})if(stock_object_valid(widgets_.option_icons[i])){
   const bool selected=options.value(i==0?"leveling":"timelapse",false);
   stock_function<void(*)(void*,const void*)>(lv_img_set_src)(widgets_.option_icons[i],selected?"/home/t13dp/TM_T1/access/screen_maintenance_selected.bin":"/home/t13dp/TM_T1/access/screen_maintenance_no_select.bin");
  }
  // The retained knife-pairing control opens a read-only explanation.
  // It never toggles an option or dispatches the vendor workflow.
  if(stock_object_valid(widgets_.option_icons[1]))stock_function<void(*)(void*,const void*)>(lv_img_set_src)(widgets_.option_icons[1],"/home/t13dp/TM_T1/access/screen_maintenance_no_select.bin");
  if(stock_object_valid(widgets_.options[2])&&!state.value("timelapse_available",false))stock_function<void(*)(void*,unsigned)>(lv_obj_add_state)(widgets_.options[2],128);
  if(!picking){if(stock_object_valid(modal_))stock_function<void(*)(void*)>(lv_obj_del)(modal_);modal_=nullptr;return;}
  if(!stock_object_valid(modal_)){
   modal_=stock_function<void*(*)(void*)>(lv_obj_create)(widgets_.content);
   if(!modal_)throw std::runtime_error("Preview chooser allocation failed");
   stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(modal_,reinterpret_cast<void*>(0x463c8d8),0);
   stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(modal_,0,0);stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(modal_,width,height);
   if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(modal_,&modal_deleted,33,this)){
    auto*failed=modal_;modal_=nullptr;stock_function<void(*)(void*)>(lv_obj_del)(failed);throw std::runtime_error("Preview chooser binding failed");
   }
   picker_.mount(modal_);
  }
  picker_.update(chooser,"",width,height);
 }
private:
 void dispatch(unsigned action){
  if(!attached_||explanation_.active()||material_review_.active()||image_preview_.active()||app_.source_picker_state().value("picker_open",false))return;
  if(action==3){const auto op=app_.operation();if(app_.source_picker_state().value("owner","")!="standalone"&&op.value("action","")=="start_print"&&(op.value("state","")=="pending"||op.value("state","")=="unknown")&&stock_function<unsigned(*)(void*)>(lv_obj_get_child_cnt)(widgets_.cancel)!=1)return;close();if(closed)closed();return;}
  if(action==1){explanation_.show(widgets_.content,"Knife pairing is not available in WM+ yet. This option will remain off for this print.");tick();return;}
  if(action==0)app_.event("leveling");
  else if(action==2)app_.event("timelapse");
  else if(action==4)app_.event("start");
  else if(action>=5&&action<=12){const auto state=app_.preview_state();const auto rows=state.value("rows",Json::array());unsigned i=action<9?action-5:action-9;if(i<rows.size())app_.event("map:"+rows[i].value("id",""));}
  tick();
 }
 static void thumbnail_pressed(void*e)noexcept{try{
  auto*o=static_cast<StockPreviewPage*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));
  if(!o||!o->attached_||stock_function<void*(*)(void*)>(lv_event_get_target)(e)!=o->widgets_.thumbnail||o->explanation_.active()||o->material_review_.active()||o->image_preview_.active()||o->app_.source_picker_state().value("picker_open",false))return;
  auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(stock_function<void*(*)()>(lv_disp_get_default)());
  bool visible=false;for(void*p=o->widgets_.thumbnail;p;p=stock_function<void*(*)(void*)>(lv_obj_get_parent)(p)){
   if(!stock_object_valid(p)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return;
   if(p==screen){visible=true;break;}
  }
  if(!visible)return;
  if(!o->image_preview_.show(o->widgets_.content,o->widgets_.thumbnail))o->explanation_.show(o->widgets_.content,"No preview image is available for this file.");
  o->tick();
 }catch(...){} }
 static void deleted(void*e)noexcept{try{auto*o=static_cast<StockPreviewPage*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(o&&stock_function<void*(*)(void*)>(lv_event_get_target)(e)==o->widgets_.content){o->attached_=false;o->modal_=nullptr;o->notice_=nullptr;}}catch(...){} }
 static void modal_deleted(void*e)noexcept{try{auto*o=static_cast<StockPreviewPage*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(o&&stock_function<void*(*)(void*)>(lv_event_get_target)(e)==o->modal_)o->modal_=nullptr;}catch(...){} }
};
}}
