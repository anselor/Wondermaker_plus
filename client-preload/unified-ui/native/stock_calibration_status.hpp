// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include "stock_header_action.hpp"
#include "stock_progress_panel.hpp"
#include "stock_dialog_backdrop.hpp"
#include "nozzle_scrub_view.hpp"
#include "../model.hpp"
#include <algorithm>
namespace wmp_ui { namespace native {
// Translate only known physical boundaries. Never expose arbitrary G-code or
// infer where a run stopped from its last selected calibration type.
inline std::string calibration_stop_location(const std::string&phase){
 static const std::pair<const char*,const char*> locations[]={
  {"between bed mesh points","between bed mesh points"},
  {"before bed mesh finalization","before saving the bed mesh"},
  {"before heater wait","before waiting for temperature"},
  {"before temperature wait","before waiting for temperature"},
  {"during heater wait","while heating"},
  {"during temperature wait","while heating"},
  {"during shaper calculations","while calculating input shaping"},
  {"between vibration segments","between vibration segments"},
  {"before vibration recording","before recording vibration"},
  {"before vibration calibration","before vibration calibration"},
  {"before vibration travel","before vibration travel"},
  {"before vibration dwell","between vibration segments"},
  {"after vibration measurements","after vibration measurements"},
  {"before tool-setter probing","before tool-setter probing"},
  {"before tool-setter touch","before the next tool-setter touch"},
  {"before nozzle wiping","before nozzle wiping"},
  {"after nozzle wiping","after nozzle wiping"},
  {"between XY homing moves","between XY homing moves"},
  {"before Z homing positioning","before positioning for Z homing"},
  {"after tool-service homing","after homing for the tool change"},
  {"after tool-service Z reference","after the tool-change Z reference"},
  {"before tool docking","before docking"},
  {"after verified tool docking","after verified docking"},
  {"after verified tool pickup","after verified pickup"},
  {"before scrub _WMP_CALIBRATION_TOOL","before selecting the scrub head"},
  {"before scrub _WMP_CALIBRATION_CLEARANCE","before moving to scrub clearance"},
  {"before scrub _WMP_XY_TRAVEL","before travel to the scrub position"},
  {"after scrub phase","between scrub preparation steps"},
  {"before X homing","before X homing"},{"after X homing","after X homing"},
  {"before Y homing","before Y homing"},{"after Y homing","after Y homing"},
  {"before Z homing","before Z homing"},{"after Z homing","after Z homing"},
  {"before G28","before homing"},{"after G28","after homing"},
  {"before G29","before bed leveling"},{"after G29","after bed leveling"},
  {"before SHAPER_CALIBRATE","before vibration calibration"},
  {"after SHAPER_CALIBRATE","after vibration calibration"},
  {"before PARK_CURRENT_TOOL","before docking"},{"after PARK_CURRENT_TOOL","after docking"}
 };
 for(const auto&location:locations)if(phase==location.first)return std::string("Stopped ")+location.second+".";
 return "";
}
// A failed or unobservable calibration must not expose vendor completion ticks.
// This panel never submits commands or offers a retry. DONE exits a result;
// BACK leaves the page while it waits for status or for the save.
class StockCalibrationStatus {
 StockProgressPanel progress_;
 void*page_=nullptr,*panel_=nullptr,*body_=nullptr,*action_=nullptr,*cancel_button_=nullptr;bool cancel_available_=false,action_cancel_=false;std::string rendered_,failure_,session_,request_;bool setup_=false,restarted_=false,waiting_=false;
 // A save of this run was requested (fresh status of its session); kept
 // until the page is begun or created again, so stale status keeps the
 // saving text and a restart after it reports the save.
 bool save_requested_=false;
 std::string checkpoint_note_;Json checkpoint_records_=Json::array();
 bool action_done_=false;                          // the header action reads DONE
 // This run's offset stage stopped before every head was measured; probing
 // had started. Both come from status bound to this run's attempt; progress
 // counts only when it is published for this run's request.
 bool stopped_=false,probed_=false;
 // This run's offsets are reported as measured and it has not failed; the
 // final park of a wire-brush run was admitted (progress phase "docking",
 // published only then) with every head of the run measured for this request
 // (progress measured; a backend without it: the last head was probed).
 bool measured_=false,all_heads_=false;
 void forget(){failure_.clear();checkpoint_note_.clear();checkpoint_records_=Json::array();restarted_=stopped_=probed_=measured_=all_heads_=save_requested_=false;}
 static void place(void*p,int x,int y,int w,int h){stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(p,w,h);stock_function<void(*)(void*,int,int,int)>(lv_obj_align)(p,1,x,y);}
 static void label(void*p,const std::string&s){stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(p,0xffffffffU,0);stock_function<void(*)(void*,const char*)>(lv_label_set_text)(p,s.c_str());stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(MyriadPro_Regular_22),0);}
 bool visible()const{
  auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);auto*p=page_;
  for(unsigned i=0;p&&i<20;++i){if(!stock_object_valid(p)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return false;if(p==screen)return true;p=stock_function<void*(*)(void*)>(lv_obj_get_parent)(p);}return false;
 }
 void clear(bool controls=true){progress_.close();auto*p=panel_;panel_=body_=action_=nullptr;rendered_.clear();if(stock_object_valid(p))stock_function<void(*)(void*)>(lv_obj_del)(p);if(controls){auto*c=cancel_button_;cancel_button_=nullptr;cancel_available_=false;if(stock_object_valid(c))stock_function<void(*)(void*)>(lv_obj_del)(c);}}
 void update_cancel(){
  if(stock_object_valid(panel_)||!cancel_available_){auto*c=cancel_button_;cancel_button_=nullptr;if(stock_object_valid(c))stock_function<void(*)(void*)>(lv_obj_del)(c);return;}
  if(stock_object_valid(cancel_button_))return;
  auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);
  const int w=stock_function<int(*)(void*)>(lv_obj_get_width)(screen);
  cancel_button_=stock_header_action(page_,"CANCEL",w-142,setup_?0:55,120);
  if(!cancel_button_)return;
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(cancel_button_,0xff3c3f43U,0);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(cancel_button_,255,0);
  stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(cancel_button_,&pressed,7,this);
 }
public:
 std::function<void()> back,cancel;
 void begin(const std::string&session,const std::string&request){clear();forget();session_=session;request_=request;}
 // True while the panel shows an outcome, not the wait for printer status.
 bool result_shown()const{return stock_object_valid(panel_)&&!rendered_.empty()&&!waiting_;}

 void created(void*page,bool setup=false,void*factory_title=nullptr){
  clear();page_=nullptr;setup_=setup;forget();session_.clear();request_.clear();
  if(stock_object_valid(page)&&stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(page,&deleted,33,this))page_=page;
  // Normal Maintenance leaves this original header label blank. Reuse only
  // the verified constructor's label beneath this exact page; never add a
  // duplicate title or borrow a stale page's global. Result overlays cover it.
  if(setup_||!page_||!stock_object_valid(factory_title)
     ||!stock_function<bool(*)(void*,const void*)>(lv_obj_check_type)(factory_title,reinterpret_cast<void*>(lv_label_class)))return;
  auto*p=stock_function<void*(*)(void*)>(lv_obj_get_parent)(factory_title);auto*card=p;
  for(unsigned depth=0;p&&p!=page_&&depth<32;++depth){
   if(!stock_object_valid(p))return;
   p=stock_function<void*(*)(void*)>(lv_obj_get_parent)(p);
  }
  if(p!=page_||!card)return;
  stock_function<void(*)(void*)>(lv_obj_update_layout)(card);
  const int width=stock_function<int(*)(void*)>(lv_obj_get_content_width)(card);
  stock_function<void(*)(void*,const char*)>(lv_label_set_text)(factory_title,"Calibration");
  stock_function<void(*)(void*,int)>(lv_label_set_long_mode)(factory_title,1);
  stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(factory_title,std::max(1,width-180),20);
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
   if(bound&&matches&&!restarted_&&attempt.contains("checkpoints")&&attempt["checkpoints"].is_array()&&attempt["checkpoints"]!=checkpoint_records_){
    checkpoint_records_=attempt["checkpoints"];
    std::vector<std::string> saved;
    for(const auto&r:attempt["checkpoints"]){
     if(r.value("state","")!="saved")continue;
     const auto type=r.value("type","");std::string name;
     if(type=="mesh")name="bed mesh";else if(type=="vibration")name="vibration";
     else if(type=="pid:extruder")name="Head 1 PID";
     else if(type.size()==13&&type.compare(0,12,"pid:extruder")==0&&type.back()>='1'&&type.back()<='3')name="Head "+std::to_string(type.back()-'0'+1)+" PID";
     bool duplicate=false;for(const auto&old:saved)if(old==name)duplicate=true;
     if(!name.empty()&&!duplicate)saved.push_back(name);
    }
    if(!saved.empty()){
     checkpoint_note_="Saved: ";for(std::size_t i=0;i<saved.size();++i){if(i)checkpoint_note_+=", ";checkpoint_note_+=saved[i];}
     checkpoint_note_+=". Restart Klipper to apply saved settings.";
    }
   }
   const auto error=bound?(matches&&attempt.value("state","")=="failed"?attempt.value("error",""):std::string()):data.value("calibration_failed","");
   if(session==session_&&!error.empty())failure_=error.substr(0,512);
   if(session==session_&&bound&&matches){
    if(attempt.value("offsets","")=="stopped")stopped_=true;
    measured_=attempt.value("offsets","")=="measured"&&attempt.value("state","")=="pending";
    const auto progress=data.value("calibration_progress",Json::object());
    if(progress.is_object()&&progress.value("request","")==request_&&progress.contains("head")&&progress["head"].is_number_integer()&&progress["head"].get<int>()>=0){
     probed_=true;
     // maintenance_scrub_heads: head count of this run's wire-brush scrub, 0 for any other run.
     const int heads=data.value("maintenance_scrub_heads",0);
     if(heads>0&&heads<=4&&progress.value("phase","")=="docking"){
      if(!progress.contains("measured")){if(progress["head"].get<int>()==heads-1)all_heads_=true;}
      else if(progress["measured"].is_array()){
       int all=0;for(const auto&h:progress["measured"])if(h.is_number_integer()&&h.get<int>()>=0&&h.get<int>()<heads)all|=1<<h.get<int>();
       if(all==(1<<heads)-1)all_heads_=true;
      }
     }
    }
   }
  }
  if(!visible()){clear();return;}
  cancel_available_=cancel&&data.value("maintenance_cancel_available",false)&&!request_.empty();
  std::string text;waiting_=false;
  const auto receipt=data.value("calibration_save_result",Json::object());
  const bool matched=!request_.empty()&&receipt.is_object()&&receipt.value("protocol",0)==1
   &&receipt.value("session","")==session_&&receipt.value("request","")==request_;
  const auto attempt=data.value("calibration_attempt",Json::object());
  const bool refused=fresh&&attempt.value("session","")==session_&&attempt.value("request","")==request_
   &&!request_.empty()&&attempt.value("state","")=="refused";
  // A receipt confirmed in a new session: the saved values were loaded.
  const bool loaded=matched&&fresh&&session!=session_&&!session.empty()&&receipt.value("state","")=="confirmed";
  const bool confirmed=loaded&&failure_.empty();
  // maintenance_save_requested is local (the run's save was sent) and counts
  // whatever the status; a pending or saved receipt counts from fresh status
  // of this run's session.
  if(!request_.empty()&&(data.value("maintenance_save_requested",false)
    ||(fresh&&session==session_&&matched&&(receipt.value("state","")=="pending"||receipt.value("state","")=="saved"))))save_requested_=true;
  const bool saving=save_requested_;
  const std::string saving_text="Saving calibration settings...\nRestarting Klipper...",restarted_text="Restarting Klipper... Done.\n";
  // The "Offset calibration stopped" results belong to a wire-brush run
  // (maintenance_scrub_heads > 0 for this run). Any other run keeps the stock
  // result texts, which carry the backend's reason.
  const bool stopped=stopped_&&data.value("maintenance_scrub_heads",0)>0;
  // The save of a stopped run was refused or failed: no restart follows, so
  // the page does not wait for one. The save's error is the reason when no
  // failure of this run was seen.
  const bool unsaved=stopped&&matched&&receipt.value("state","")=="unconfirmed"&&!receipt.value("error","").empty();
  const std::string reason=failure_.empty()&&unsaved?receipt.value("error","").substr(0,512):failure_;
  // After a failure the raw text is not repeated on the stopped-offsets results.
  const std::string check=reason.empty()?"":"\n\nCheck the printer before trying again.";
  // Re-check outcome of this run's wire-brush scrub, kept natively across the
  // save's restart. Cancelled: the restore of the offsets the heads had at the
  // start was sent; restore_failed: it was not reported done. Flagged heads
  // (0-based) are named when Save anyway released the worker.
  const bool cancelled=data.value("maintenance_scrub_heads",0)>0&&data.value("maintenance_recheck_cancelled",false);
  const bool restore_failed=cancelled&&data.value("maintenance_restore_failed",false);
  // Probing had started and the stage stopped with no failure: the heads
  // probed in this run have new offsets.
  const std::string changed_text="Offsets were changed and may not be reliable. Run the calibration again.";
  const std::string restore_text="Offsets could not be restored. Run the calibration again.";
  std::string unclean;
  if(data.value("maintenance_scrub_heads",0)>0&&data.value("maintenance_saved_anyway",false)&&data.contains("maintenance_flagged_heads")&&data["maintenance_flagged_heads"].is_array()){
   std::vector<unsigned> flagged;
   for(const auto&h:data["maintenance_flagged_heads"])if(h.is_number_integer()&&h.get<int>()>=0&&h.get<int>()<4)flagged.push_back(unsigned(h.get<int>()));
   if(!flagged.empty())unclean=" "+nozzle_scrub_head_names(flagged)+" may not be clean.";
  }
  if(refused)text="Calibration did not start.\n\n"+attempt.value("error","");
  // A restore that failed is reported over a failure of the attempt.
  else if(cancelled&&loaded&&(restore_failed||reason.empty()))
   text=restarted_text+(restore_failed?"Earlier results were saved. "+restore_text:"Offset calibration cancelled. Earlier results were saved.");
  else if(stopped&&loaded&&probed_&&reason.empty())text=restarted_text+"Offset calibration stopped. Earlier results were saved. "+changed_text;
  else if(stopped&&loaded)text=restarted_text+"Offset calibration stopped. Earlier results were saved."+check;
  else if(confirmed)text=restarted_text+"Calibration settings saved."+unclean;
  else if(restarted_){
   text=save_requested_?restarted_text+"Saved calibration settings could not be verified.\nCheck the saved settings before retrying."
                       :"Printer restarted. Calibration result could not be confirmed.\nCheck the saved settings before retrying.";
   if(!failure_.empty())text+="\n\nPrevious error: "+failure_;
   if(restore_failed)text+="\n\n"+restore_text;
  }
  // An offsets-only run sends no save; shown once the vendor worker has returned.
  else if(cancelled&&!saving&&(restore_failed||reason.empty())&&data.value("maintenance_worker_returned",false))
   text=restore_failed?restore_text:"Offset calibration cancelled. Offsets are unchanged.";
  else if(stopped&&unsaved&&!probed_)text="Offset calibration stopped. Offsets are unchanged. Earlier results were not saved."+check;
  else if(stopped&&saving&&!unsaved)text=saving_text;
  // Probing stores each head's offsets as it goes, so only a stage that
  // stopped before probing leaves them unchanged.
  else if(stopped&&!probed_)text="Offset calibration stopped. Offsets are unchanged."+check;
  // An offsets-only run sends no save; shown once the vendor worker has returned.
  else if(stopped&&probed_&&reason.empty()&&!saving&&data.value("maintenance_worker_returned",false))
   text="Offset calibration stopped. "+changed_text;
  else if(!reason.empty())text="Calibration stopped.\n\n"+reason+"\n\nInspect the printer before retrying.";
  else if(saving)text=saving_text;
  // An offsets-only run sends no SAVE_CONFIG: the probing macros store each
  // head's offsets. A wire-brush run whose final park followed the measurement of every head
  // shows its result once the vendor worker has returned. Other runs are unchanged.
  else if(measured_&&all_heads_&&data.value("maintenance_worker_returned",false))text="Nozzle offsets saved."+unclean;
  else if(!fresh||session.empty()){text="Waiting for printer status...";waiting_=true;}
  if(data.value("maintenance_cancel_requested",false)&&data.value("maintenance_cancel_request","")==request_&&!request_.empty()&&!restarted_){
   const auto cleanup=attempt.value("cancel_cleanup",Json::object());
   const bool own=fresh&&attempt.value("session","")==session_&&attempt.value("request","")==request_&&attempt.value("cancel_requested",false);
   if(own&&cleanup.value("state","")=="complete"){
    text="Calibration cancelled.";waiting_=false;
    if(cleanup.value("park","")=="not_moved")text+=" No calibration commands ran.";
    else if(cleanup.value("park","")=="parked"||cleanup.value("park","")=="already_docked")text+=" All heads are docked.";
    if(cleanup.value("offsets","")=="restored")text+=" Previous nozzle offsets were restored.";
    const auto location=calibration_stop_location(attempt.value("cancel_phase",""));
    if(!location.empty())text+="\n\n"+location;
   }else if(own&&cleanup.value("state","")=="incomplete"){
    text="Calibration stopped. Cleanup is incomplete.\n\n"+cleanup.value("error","")+"\n\nInspect the printer before retrying.";waiting_=false;
   }else{waiting_=true;text=data.value("maintenance_cancel_message","");if(text.empty())text="Cancelling... Waiting for the printer to stop.";}
  }
  if(!checkpoint_note_.empty()&&!waiting_&&!confirmed&&!saving&&!restarted_&&!text.empty()
     &&(!reason.empty()||stopped||cancelled||attempt.value("cancel_requested",false))){
   const std::string old=" Earlier results were not saved.";const auto pos=text.find(old);if(pos!=std::string::npos)text.erase(pos,old.size());
   text+="\n\n"+checkpoint_note_;
  }
  // DONE on a result once the vendor worker has returned (no save can follow;
  // without the key it is taken as returned); BACK while waiting for status,
  // for the save or for the worker. An override text is a result once the
  // attempt is refused, failed, saved or Klipper restarted.
  const bool terminal=override_text.empty()?!waiting_&&text!=saving_text&&data.value("maintenance_worker_returned",true)
                                           :refused||confirmed||restarted_||!failure_.empty();
  if(!override_text.empty()){text=override_text;waiting_=false;}
  if(text.empty()){clear(false);update_cancel();return;}
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
   action_=stock_header_action(panel_,terminal?"DONE":"BACK",panel_w-132,0,120);action_done_=terminal;action_cancel_=false;
   if(!action_){clear();return;}
   stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(action_,&pressed,7,this);
   auto*rule=stock_function<void*(*)(void*)>(lv_obj_create)(panel_);stock_dialog_backdrop(rule);place(rule,12,40,panel_w-24,1);
   stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(rule,0xff606060U,0);stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(rule,255,0);
   body_=stock_function<void*(*)(void*)>(lv_label_create)(panel_);place(body_,20,60,panel_w-40,panel_h-80);stock_function<void(*)(void*,int)>(lv_label_set_long_mode)(body_,0);
   progress_.attach(panel_,20,60,panel_w-40,panel_h-80);
  }
  if(stock_object_valid(body_)&&text!=rendered_){
   label(body_,text);rendered_=text;
   if(progress_.attached()){progress_.update({{"instruction",text},{"steps",Json::array()}});stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(body_,1);}
  }
  // The caption follows the worker as well as the text.
  update_cancel();
  if(stock_object_valid(action_)&&(terminal!=action_done_||cancel_available_!=action_cancel_)){stock_header_action_caption(action_,cancel_available_?"CANCEL":terminal?"DONE":"BACK");action_done_=terminal;action_cancel_=cancel_available_;}
 }
private:
 static void deleted(void*e)noexcept{try{auto*o=static_cast<StockCalibrationStatus*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(!o)return;
  auto*p=stock_function<void*(*)(void*)>(lv_event_get_target)(e);
  if(p==o->page_){o->page_=o->cancel_button_=nullptr;o->forget();o->session_.clear();}
  if(p==o->panel_){o->panel_=o->body_=o->action_=nullptr;o->rendered_.clear();}
 }catch(...){} }
 static void pressed(void*e)noexcept{try{auto*o=static_cast<StockCalibrationStatus*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));auto*target=stock_function<void*(*)(void*)>(lv_event_get_target)(e);if(o&&o->visible()&&stock_object_valid(target)&&(target==o->cancel_button_||target==o->action_)){if(o->cancel_available_&&o->cancel)o->cancel();else if(stock_object_valid(o->panel_)&&o->back)o->back();}}catch(...){} }
};
}}
