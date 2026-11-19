// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include "stock_header_action.hpp"
#include "stock_progress_panel.hpp"
#include "stock_dialog_backdrop.hpp"
#include "../model.hpp"
namespace wmp_ui { namespace native {
// A failed or unobservable calibration must not expose vendor completion ticks.
// This panel never submits commands or offers a retry. DONE exits a result.
class StockCalibrationStatus {
 StockProgressPanel progress_;
 void*page_=nullptr,*panel_=nullptr,*body_=nullptr,*action_=nullptr;std::string rendered_,failure_,session_,request_;bool setup_=false,restarted_=false,save_requested_=false;
 static void place(void*p,int x,int y,int w,int h){stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(p,w,h);stock_function<void(*)(void*,int,int,int)>(lv_obj_align)(p,1,x,y);}
 static void label(void*p,const std::string&s){stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(p,0xffffffffU,0);stock_function<void(*)(void*,const char*)>(lv_label_set_text)(p,s.c_str());stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(MyriadPro_Regular_22),0);}
 bool visible()const{
  auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);auto*p=page_;
  for(unsigned i=0;p&&i<20;++i){if(!stock_object_valid(p)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return false;if(p==screen)return true;p=stock_function<void*(*)(void*)>(lv_obj_get_parent)(p);}return false;
 }
 void clear(){progress_.close();auto*p=panel_;panel_=body_=action_=nullptr;rendered_.clear();if(stock_object_valid(p))stock_function<void(*)(void*)>(lv_obj_del)(p);}
public:
 std::function<void()> back;
 void begin(const std::string&session,const std::string&request){clear();failure_.clear();session_=session;request_=request;restarted_=false;save_requested_=false;}

 void created(void*page,bool setup=false){
  clear();page_=nullptr;setup_=setup;failure_.clear();session_.clear();request_.clear();restarted_=false;save_requested_=false;
  if(stock_object_valid(page)&&stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(page,&deleted,33,this))page_=page;
 }
 void update(const Json&data,const std::string&override_text={}){
  if(!stock_object_valid(page_)){clear();return;}
  const bool fresh=data.value("display_fresh",data.value("fresh",false));const auto session=data.value("calibration_session","");
  if(fresh&&!session.empty()){
   // A new Klipper session says nothing about the result shown on this
   // existing vendor page. SAVE_CONFIG can restart normally; only a matching
   // durable save receipt can confirm the saved settings in the new session.
   if(session_.empty())session_=session;
   else if(session!=session_)restarted_=true;
   // A bound page reports only its own attempt. The global failure may still
   // belong to the previous run while this START is queued for admission.
   const auto attempt=data.value("calibration_attempt",Json::object());
   const bool bound=!request_.empty();
   const bool matches=attempt.value("session","")==session_&&attempt.value("request","")==request_;
   const auto error=bound?(matches&&attempt.value("state","")=="failed"?attempt.value("error",""):std::string()):data.value("calibration_failed","");
   if(session==session_&&!error.empty())failure_=error.substr(0,512);
  }
  if(!visible()){clear();return;}
  std::string text;
  const auto receipt=data.value("calibration_save_result",Json::object());
  const bool matched=!request_.empty()&&receipt.is_object()&&receipt.value("protocol",0)==1
   &&receipt.value("session","")==session_&&receipt.value("request","")==request_;
  const auto attempt=data.value("calibration_attempt",Json::object());
  const bool refused=fresh&&attempt.value("session","")==session_&&attempt.value("request","")==request_
   &&!request_.empty()&&attempt.value("state","")=="refused";
  const bool confirmed=matched&&fresh&&session!=session_&&!session.empty()&&failure_.empty()&&receipt.value("state","")=="confirmed";
  if(fresh&&session==session_&&!request_.empty()
    &&(data.value("maintenance_save_requested",false)||(matched&&(receipt.value("state","")=="pending"||receipt.value("state","")=="saved"))))save_requested_=true;
  if(refused)text="Calibration did not start.\n\n"+attempt.value("error","");
  else if(confirmed)text="Restarting Klipper... Done.\nCalibration settings saved.";
  else if(restarted_){
   text=save_requested_?"Restarting Klipper... Done.\nSaved calibration settings could not be verified.\nCheck the saved settings before retrying.":"Printer restarted. Calibration result could not be confirmed.\nCheck the saved settings before retrying.";
   if(!failure_.empty())text+="\n\nPrevious error: "+failure_;
  }
  else if(!failure_.empty())text="Calibration stopped.\n\n"+failure_+"\n\nInspect the printer before retrying.";
  else if(save_requested_)text="Saving calibration settings...\nRestarting Klipper...";
  else if(!fresh||session.empty())text="Waiting for printer status...";
  if(!override_text.empty())text=override_text;
  const bool terminal=confirmed||refused||restarted_||!failure_.empty();
  if(text.empty()){clear();return;}
  if(!stock_object_valid(panel_)){
   auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);
   const int w=stock_function<int(*)(void*)>(lv_obj_get_width)(screen),h=stock_function<int(*)(void*)>(lv_obj_get_height)(screen);
   const int panel_w=setup_?w:w-100,panel_h=setup_?h:h-65;
   panel_=stock_function<void*(*)(void*)>(lv_obj_create)(page_);if(!panel_)return;
   stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(panel_,&deleted,33,this);
   // Cover the complete factory content card, including its OK header, while
   // retaining the surrounding tabs/sidebar. One shared background and header.
   stock_dialog_backdrop(panel_);
   stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(panel_,0xff3c3f43U,0);
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(panel_,255,0);
   place(panel_,setup_?0:90,setup_?0:55,panel_w,panel_h);
   auto*title=stock_function<void*(*)(void*)>(lv_label_create)(panel_);label(title,"Calibration");place(title,12,8,panel_w-160,30);
   action_=stock_header_action(panel_,terminal?"DONE":"BACK",panel_w-132,0,120);
   if(!action_){clear();return;}
   stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(action_,&pressed,7,this);
   auto*rule=stock_function<void*(*)(void*)>(lv_obj_create)(panel_);stock_dialog_backdrop(rule);place(rule,12,40,panel_w-24,1);
   stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(rule,0xff606060U,0);stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(rule,255,0);
   body_=stock_function<void*(*)(void*)>(lv_label_create)(panel_);place(body_,20,60,panel_w-40,panel_h-80);stock_function<void(*)(void*,int)>(lv_label_set_long_mode)(body_,0);
   progress_.attach(panel_,20,60,panel_w-40,panel_h-80);
  }
  if(stock_object_valid(body_)&&text!=rendered_){
   label(body_,text);rendered_=text;
   if(stock_object_valid(action_))stock_header_action_caption(action_,terminal?"DONE":"BACK");
   if(progress_.attached()){progress_.update({{"instruction",text},{"steps",Json::array()}});stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(body_,1);}
  }
 }
private:
 static void deleted(void*e)noexcept{try{auto*o=static_cast<StockCalibrationStatus*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(!o)return;
  auto*p=stock_function<void*(*)(void*)>(lv_event_get_target)(e);
  if(p==o->page_){o->page_=nullptr;o->failure_.clear();o->session_.clear();o->restarted_=false;o->save_requested_=false;}
  if(p==o->panel_){o->panel_=o->body_=nullptr;o->rendered_.clear();}
 }catch(...){} }
 static void pressed(void*e)noexcept{try{auto*o=static_cast<StockCalibrationStatus*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(o&&o->visible()&&stock_object_valid(o->panel_)&&o->back)o->back();}catch(...){} }
};
}}
