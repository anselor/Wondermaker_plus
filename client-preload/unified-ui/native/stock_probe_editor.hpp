// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include "button_caption.hpp"
#include "stock_dialog_backdrop.hpp"
#include "../model.hpp"
#include <array>
#include <iomanip>
#include <sstream>
namespace wmp_ui { namespace native {
// Retained controls: status changes update captions/permissions, never dispatch.
// The owning runtime revalidates every action through ProbeEditorWorker.
class StockProbeEditor {
 struct Control {void*node=nullptr;void*caption=nullptr;std::string action,step;bool enabled=false;};
 void*page_=nullptr,*panel_=nullptr,*body_=nullptr,*body_view_=nullptr;
 std::array<Control,17> controls_{};std::string rendered_;
 static void place(void*p,int x,int y,int w,int h){stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(p,w,h);stock_function<void(*)(void*,int,int,int)>(lv_obj_align)(p,1,x,y);}
 static void label(void*p,const std::string&s){stock_function<void(*)(void*,const char*)>(lv_label_set_text)(p,s.c_str());stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(0x26297a0),0);stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(p,0xffffffffU,0);}
public:
 bool visible()const{
  auto*p=page_;auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);
  for(unsigned i=0;p&&i<20;++i){if(!stock_object_valid(p)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return false;if(p==screen)return true;p=stock_function<void*(*)(void*)>(lv_obj_get_parent)(p);}return false;
 }
private:
 void clear(){auto*p=panel_;panel_=body_=body_view_=nullptr;controls_={};rendered_.clear();if(stock_object_valid(p))stock_function<void(*)(void*)>(lv_obj_del)(p);}
 void button(unsigned i,const char*text,const char*action,const std::string&step,int x,int y,int w,int h){
  auto&c=controls_[i];c.action=action;c.step=step;
  c.node=stock_function<void*(*)(void*)>(lv_obj_create)(panel_);stock_dialog_backdrop(c.node);place(c.node,x,y,w,h);
  c.caption=stock_function<void*(*)(void*)>(lv_label_create)(c.node);label(c.caption,text);center_button_caption(c.node,c.caption,text);
  stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(c.node,&pressed,7,this);
 }
public:
 std::function<void()> close;
 std::function<void(const std::string&,const std::string&)> submit;
 void dismiss(){page_=nullptr;clear();}
 void created(void*page){clear();page_=nullptr;if(stock_object_valid(page)&&stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(page,&deleted,33,this))page_=page;}
 void update(const Json&view){
  if(!visible())return;
  if(!stock_object_valid(panel_)){
   const int w=stock_function<int(*)(void*)>(lv_obj_get_width)(page_),h=stock_function<int(*)(void*)>(lv_obj_get_height)(page_);
   panel_=stock_function<void*(*)(void*)>(lv_obj_create)(page_);if(!panel_)return;
   stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(panel_,&deleted,33,this);
   stock_dialog_backdrop(panel_);place(panel_,0,0,w,h);
   stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(panel_,0xff3c3f41U,0);
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(panel_,255,0);
   auto*t=stock_function<void*(*)(void*)>(lv_label_create)(panel_);label(t,"Probe calibration");place(t,12,8,w-470,28);
   button(0,"CLOSE","CLOSE","",w-450,0,90,40);
   button(1,"ABORT","ABORT","",w-360,0,90,40);
   button(2,"ACCEPT","ACCEPT","",w-270,0,90,40);
   auto*rule=stock_function<void*(*)(void*)>(lv_obj_create)(panel_);stock_dialog_backdrop(rule);place(rule,12,40,w-24,1);
   stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(rule,0xff606060U,0);
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(rule,255,0);
   body_view_=stock_function<void*(*)(void*)>(lv_obj_create)(panel_);stock_dialog_backdrop(body_view_);
   stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(body_view_,16);
   stock_function<void(*)(void*,int)>(lv_obj_set_scroll_dir)(body_view_,12);
   body_=stock_function<void*(*)(void*)>(lv_label_create)(body_view_);
   // Keep the label's default content height; wrapping expands the scroll content.
   stock_function<void(*)(void*,int)>(lv_obj_set_width)(body_,w-40);
   stock_function<void(*)(void*,int,int,int)>(lv_obj_align)(body_,1,0,0);
   stock_function<void(*)(void*,int)>(lv_label_set_long_mode)(body_,0);
   const char*steps[]={"1","0.1","0.05","0.025","0.01","0.005"};const int cell=(w-24)/6;
   for(unsigned i=0;i<6;++i){
    const auto plus=std::string("+")+steps[i],minus=std::string("-")+steps[i];
    button(3+i,plus.c_str(),"JOG",steps[i],12+i*cell,h-116,cell-6,52);
    button(9+i,minus.c_str(),"JOG",minus,12+i*cell,h-52,cell-6,52);
   }
   button(15,"DISCARD","DISCARD","",w-180,0,90,40);
   button(16,"SAVE","SAVE","",w-90,0,90,40);
  }
  const auto signature=view.dump();if(signature==rendered_)return;
  const auto op=view.value("editor",Json::object()),actions=view.value("actions",Json::object());
  const auto phase_name=op.value("state","");
  const bool adjusting=phase_name=="editing"||phase_name=="jogging"||phase_name=="accepting";
  const int width=stock_function<int(*)(void*)>(lv_obj_get_width)(panel_),height=stock_function<int(*)(void*)>(lv_obj_get_height)(panel_);
  place(body_view_,12,52,width-24,height-52-(adjusting?128:12));
  for(unsigned i=3;i<15;++i)
   stock_function<void(*)(void*,unsigned)>(adjusting?lv_obj_clear_flag:lv_obj_add_flag)(controls_[i].node,1);
  std::string text;
  if(!view.value("fresh",false))text="Calibration status unavailable.";
  else if(!op.value("available",false))text=op.value("reason","Probe editor unavailable.");
  else{
   if(phase_name=="preparing")text="Preparing probe calibration...";
   else if(phase_name=="editing")text="Adjust Z until paper drags lightly, then ACCEPT.";
   else if(phase_name=="jogging")text="Adjusting Z...";
   else if(phase_name=="accepting")text="Accepting offset...";
   else if(phase_name=="accepted")text="Offset accepted. SAVE writes the settings and restarts Klipper.";
   else if(phase_name=="saving")text="Saving offset and restarting Klipper...";
   else if(phase_name=="saved")text="Offset saved.";
   else if(phase_name=="aborting"||phase_name=="stopping")text="Stopping probe calibration...";
   else if(phase_name=="aborted")text="Probe calibration stopped.";
   else if(phase_name=="discarding")text="Discarding offset adjustment...";
   else if(phase_name=="discarded")text="Offset adjustment discarded.";
   else if(phase_name=="keeping")text="Keeping current settings...";
   else if(phase_name=="kept")text="Current settings kept; nothing saved.";
   else if(phase_name=="save_acknowledged")text="Saved offset confirmed.";
   else if(phase_name=="failed"||phase_name=="rejected")text="Probe calibration could not continue.";
   else if(phase_name=="unknown")text="Probe calibration result unconfirmed.";
   else text="Ready to calibrate probe offset.";
   const auto z=op.value("z_position",Json());if(z.is_number()){
    std::ostringstream value;value<<std::fixed<<std::setprecision(3)<<z.get<double>();
    text+="\nZ: "+value.str()+" mm";
   }
   const auto error=op.value("error","");if(!error.empty())text+="\n"+error;
  }
  const auto save_review=op.value("save_review",Json::object());
  const bool save_hold=op.value("save_review_required",false);
  const bool retain=save_hold&&op.value("save_retain_protocol",0)==1&&save_review.value("retainable",false);
  if(save_hold){
   text=view.value("fresh",false)?"":"Waiting for updated probe status.\n";
   text+="Previous probe offset save";
   const auto saved=save_review.value("offset",""),loaded=save_review.value("loaded_offset","");
   if(!saved.empty())text+="\nRecorded offset: "+saved+" mm";
   if(!loaded.empty())text+="\nCurrent offset: "+loaded+" mm";
   if(!op.value("save_review_confirmable",false))text+="\nChecking the saved result automatically.";
   else if(retain)text+="\nKEEP uses the current offset without saving.";
   else if(save_review.value("configuration_matches",false))text+="\nSaved settings match. CONFIRM finishes this review; it does not save again.";
   else text+="\nSaved settings differ. Keep the current settings or start a new calibration.";
   if(save_review.value("pending_changes",false))text+="\nThere are unsaved configuration changes.";
   const auto count=save_review.value("difference_count",0LL);
   if(count>0)text+="\nSettings that differ: "+std::to_string(count);
  }
  controls_[16].action=save_hold?(retain?"RETAIN":"ACK"):"SAVE";
  controls_[16].step=save_hold?save_review.value("token",""):"";
  const std::string save_caption=save_hold?(retain?"KEEP":"CONFIRM"):"SAVE";
  label(controls_[16].caption,save_caption);center_button_caption(controls_[16].node,controls_[16].caption,save_caption);
  const auto conflict=op.value("config_conflict",Json());
  const bool reviewing=op.value("state","")=="accepted"&&conflict.is_object();
  if(reviewing)text+="\nAccepted: "+conflict.value("accepted_offset","")+" mm; current: "+conflict.value("current_offset","")+" mm\nKEEP leaves current pending settings unchanged; it does not save.";
  controls_[15].action=save_hold?"REVIEW":reviewing?"KEEP":"DISCARD";
  controls_[15].step=reviewing?conflict.value("review",""):"";
  stock_function<void(*)(void*,unsigned)>(save_hold?lv_obj_add_flag:lv_obj_clear_flag)(controls_[15].node,1);
  label(controls_[15].caption,save_hold?"":controls_[15].action);
  center_button_caption(controls_[15].node,controls_[15].caption,controls_[15].action);
  const auto message=view.value("message","");if(!message.empty())text+="\n"+message;
  const auto stop_message=view.value("stop_message","");if(!stop_message.empty())text+="\n"+stop_message;
  label(body_,text);
  const bool preparation=op.value("state","")=="preparing"||op.value("state","")=="stopping";
  controls_[1].action=preparation?"STOP":"ABORT";
  label(controls_[1].caption,controls_[1].action);center_button_caption(controls_[1].node,controls_[1].caption,controls_[1].action);
  const auto phase=op.value("state","");
  const bool can_start=phase=="idle"||phase=="aborted"||phase=="saved"||phase=="discarded"||phase=="kept"||phase=="rejected"||phase=="save_acknowledged"||phase=="save_review"||phase=="unknown"||phase=="failed";
  controls_[2].action=can_start?"START":"ACCEPT";
  label(controls_[2].caption,controls_[2].action);
  center_button_caption(controls_[2].node,controls_[2].caption,controls_[2].action);
  for(auto&c:controls_){c.enabled=c.action=="CLOSE"||(view.value("fresh",false)&&(!view.value("invalidated",true)||c.action=="REVIEW"||c.action=="START")&&actions.value(c.action,false));
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_text_opa)(c.caption,c.enabled?255:100,0);}
  rendered_=signature;
 }
private:
 static void deleted(void*e)noexcept{try{auto*o=static_cast<StockProbeEditor*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(!o)return;auto*p=stock_function<void*(*)(void*)>(lv_event_get_target)(e);if(p==o->page_)o->page_=nullptr;if(p==o->panel_){o->panel_=o->body_=o->body_view_=nullptr;o->controls_={};o->rendered_.clear();}}catch(...){} }
 static void pressed(void*e)noexcept{try{auto*o=static_cast<StockProbeEditor*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(!o||!o->visible()||!stock_object_valid(o->panel_))return;auto*p=stock_function<void*(*)(void*)>(lv_event_get_target)(e);for(const auto&c:o->controls_)if(c.node==p&&c.enabled&&!stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(c.node,1)){if(c.action=="CLOSE"){if(o->close)o->close();}else if(o->submit)o->submit(c.action,c.step);return;}}catch(...){} }
};
}}
