// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include "stock_header_action.hpp"
#include "stock_progress_panel.hpp"
#include "stock_dialog_backdrop.hpp"
#include "nozzle_scrub_view.hpp"
#include "../model.hpp"
namespace wmp_ui { namespace native {
// A failed or unobservable calibration must not expose vendor completion ticks.
// This panel never submits commands or offers a retry. DONE exits a result;
// BACK leaves the page while it waits for status or for the save.
class StockCalibrationStatus {
 StockProgressPanel progress_;
 void*page_=nullptr,*panel_=nullptr,*body_=nullptr,*action_=nullptr;std::string rendered_,failure_,session_,request_;bool setup_=false,restarted_=false,waiting_=false;
 // A save of this run was requested (fresh status of its session); kept
 // until the page is begun or created again, so stale status keeps the
 // saving text and a restart after it reports the save.
 bool save_requested_=false;
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
 void forget(){failure_.clear();restarted_=stopped_=probed_=measured_=all_heads_=save_requested_=false;}
 static void place(void*p,int x,int y,int w,int h){stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(p,w,h);stock_function<void(*)(void*,int,int,int)>(lv_obj_align)(p,1,x,y);}
 static void label(void*p,const std::string&s){stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(p,0xffffffffU,0);stock_function<void(*)(void*,const char*)>(lv_label_set_text)(p,s.c_str());stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(MyriadPro_Regular_22),0);}
 bool visible()const{
  auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);auto*p=page_;
  for(unsigned i=0;p&&i<20;++i){if(!stock_object_valid(p)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return false;if(p==screen)return true;p=stock_function<void*(*)(void*)>(lv_obj_get_parent)(p);}return false;
 }
 void clear(){progress_.close();auto*p=panel_;panel_=body_=action_=nullptr;rendered_.clear();if(stock_object_valid(p))stock_function<void(*)(void*)>(lv_obj_del)(p);}
public:
 std::function<void()> back;
 void begin(const std::string&session,const std::string&request){clear();forget();session_=session;request_=request;}
 // True while the panel shows an outcome, not the wait for printer status.
 bool result_shown()const{return stock_object_valid(panel_)&&!rendered_.empty()&&!waiting_;}

 void created(void*page,bool setup=false){
  clear();page_=nullptr;setup_=setup;forget();session_.clear();request_.clear();
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
  // DONE on a result once the vendor worker has returned (no save can follow;
  // without the key it is taken as returned); BACK while waiting for status,
  // for the save or for the worker. An override text is a result once the
  // attempt is refused, failed, saved or Klipper restarted.
  const bool terminal=override_text.empty()?!waiting_&&text!=saving_text&&data.value("maintenance_worker_returned",true)
                                           :refused||confirmed||restarted_||!failure_.empty();
  if(!override_text.empty()){text=override_text;waiting_=false;}
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
   action_=stock_header_action(panel_,terminal?"DONE":"BACK",panel_w-132,0,120);action_done_=terminal;
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
  if(stock_object_valid(action_)&&terminal!=action_done_){stock_header_action_caption(action_,terminal?"DONE":"BACK");action_done_=terminal;}
 }
private:
 static void deleted(void*e)noexcept{try{auto*o=static_cast<StockCalibrationStatus*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(!o)return;
  auto*p=stock_function<void*(*)(void*)>(lv_event_get_target)(e);
  if(p==o->page_){o->page_=nullptr;o->forget();o->session_.clear();}
  if(p==o->panel_){o->panel_=o->body_=o->action_=nullptr;o->rendered_.clear();}
 }catch(...){} }
 static void pressed(void*e)noexcept{try{auto*o=static_cast<StockCalibrationStatus*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(o&&o->visible()&&stock_object_valid(o->panel_)&&o->back)o->back();}catch(...){} }
};
}}
