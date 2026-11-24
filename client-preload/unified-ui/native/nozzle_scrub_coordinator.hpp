// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "nozzle_scrub_vendor.hpp"
#include "stock_nozzle_scrub.hpp"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <vector>
namespace wmp_ui { namespace native {
// Guided nozzle scrub (docs/nozzle-scrub.md): connects the flow and the screen
// to Maintenance START, calibration admission, the vendor worker's offset
// stage and the GUI tick.
//
// The coordinator shares Runtime's mutex. It guards the flow, the bound and
// result requests, the re-check result, pending_, stopping_ and failure_wait_ms_, together with
// Runtime's calibration reservation and binding (read here through reserved_
// and run_request_, only with the mutex held). The screen and the remaining
// members belong to the GUI thread. The mutex is never held across the
// command sender, lv_event_send, a screen call or snapshot_ (which takes it).
class NozzleScrubCoordinator {
 enum{ActionNone=0,ActionConfirm,ActionCancel,ActionBack};
 enum{ScreenNone=0,ScreenShown,ScreenLeft};
 std::mutex&mutex_;const bool&reserved_;const std::string&run_request_;
 const std::function<Json()>snapshot_;const std::function<double()>now_;
 NozzleScrubFlow flow_;std::condition_variable wake_;std::string request_,result_request_;unsigned result_heads_=0;bool pending_=false,stopping_=false;
 // Re-check outcome of the result request, kept after the flow closes:
 // heads named by Save anyway (0-based), Save anyway chosen, a re-check
 // cancel whose restore was sent, and the last restore state status reported
 // for the request.
 std::vector<unsigned> result_flagged_;bool result_saved_anyway_=false,result_cancelled_=false;std::string result_restore_;
 StockNozzleScrub screen_;void*start_button_=nullptr;bool decided_=false;int shown_=ScreenNone;std::atomic<int>action_{ActionNone};
 // Display inactive time (ms) at the previous GUI tick and that tick's time
 // (seconds, now_); -1 before the first tick.
 std::uint32_t inactive_=0;double inactive_at_=-1;
 // Longest wait at the park send for status to report a failure the vendor
 // worker already knows of. Status is polled well within this time.
 int failure_wait_ms_=5000;
#ifdef WMP_NATIVE_TEST
 friend struct RuntimeReceiptTest;
#endif
 // The backend must publish nozzle_scrub and calibration_progress at protocol
 // 1; the module that publishes them registers the scrub and progress commands.
 static bool backend_supported(const Json&data){
  for(const auto*key:{"nozzle_scrub","calibration_progress"}){
   const auto status=data.value(key,Json::object());
   if(!status.is_object()||!status.contains("protocol")||!status["protocol"].is_number_integer()||status["protocol"]!=1)return false;
  }
  return true;
 }
 // mutex_ held. The reserved run is the one the scrub is bound to.
 bool bound_locked()const{return reserved_&&!request_.empty()&&request_==run_request_;}
 // One timed wait slice on the system clock (pthread_cond_timedwait). A
 // steady-clock wait needs pthread_cond_clockwait, which is GLIBC_2.30.
 // Callers re-check their condition after each slice. A forward wall-clock
 // jump ends one slice early. After a backward jump one slice can last as
 // long as the jump unless the condition is notified; the GUI tick notifies
 // it on every tick while a scrub is shown or its flow is not idle.
 void wait(std::unique_lock<std::mutex>&lock,int ms){wake_.wait_until(lock,std::chrono::system_clock::now()+std::chrono::milliseconds(ms));}
 // Vendor worker thread, mutex_ held through lock. Sends every command the
 // flow hands out and waits until the flow no longer holds the worker. The
 // wait is timed; the GUI tick observes status and the clock for the flow and
 // wakes it. When the runtime stops the flow is cancelled and nothing more is
 // sent.
 void hold_locked(std::unique_lock<std::mutex>&lock,const std::function<void(const std::string&inner)>&send){
  for(;;){
   std::string command;
   while(!stopping_&&flow_.next_command(command)){
    lock.unlock();bool sent=true;
    // The vendor did not issue this command, so its failure never unwinds into
    // the vendor worker. The flow drops what is queued and tries END once.
    try{send(command);}catch(...){sent=false;}
    lock.lock();
    if(!sent)flow_.send_failed(command,now_());
   }
   if(stopping_){flow_.cancel(now_());return;}
   if(!flow_.hold())return;
   wait(lock,250);
  }
 }
 void dismiss(int shown=ScreenNone){screen_.created(nullptr);shown_=shown;if(shown==ScreenNone)start_button_=nullptr;}
 // CONFIRM on Prepare. Wire brush sets the vendor mode byte to rapid and binds
 // the scrub to the request the admission below creates. The remembered START
 // click is then sent again and takes the normal admission path.
 void start_from_prepare(bool brush){
  auto*button=start_button_;dismiss();
  if(!stock_object_valid(button)){std::lock_guard<std::mutex>lock(mutex_);flow_.close();return;}
  if(brush){*nozzle_scrub_vendor().rapid=1;std::lock_guard<std::mutex>lock(mutex_);pending_=true;}
  decided_=true;
  try{stock_function<int(*)(void*,int,void*)>(lv_event_send)(button,7,nullptr);}catch(...){}
  decided_=false;
  std::lock_guard<std::mutex>lock(mutex_);pending_=false;
  // Admission refused or nothing enqueued: no scrub. No worker will read the
  // mode byte, so it goes back to Accurate and the next START offers Prepare again.
  if(brush&&!bound_locked()){request_.clear();flow_.close();*nozzle_scrub_vendor().rapid=0;}
 }
public:
 std::function<bool()> cancel_requested;
 // snapshot and now are Runtime's status snapshot and clock (seconds).
 // reserved and run_request are Runtime's calibration reservation and the
 // request of its binding, both guarded by mutex.
 NozzleScrubCoordinator(std::mutex&mutex,const bool&reserved,const std::string&run_request,std::function<Json()>snapshot,std::function<double()>now)
  :mutex_(mutex),reserved_(reserved),run_request_(run_request),snapshot_(std::move(snapshot)),now_(std::move(now)){
  // Taps only record the action. The next GUI tick acts on it, so the screen
  // is never deleted inside the click event of one of its own controls.
  screen_.on_confirm=[this]{action_.store(ActionConfirm);};
  screen_.on_cancel=[this]{action_.store(ActionCancel);};
  screen_.on_back=[this]{action_.store(ActionBack);};
  // The first option row: Wire brush on Prepare, Clean again on Re-check.
  screen_.on_select=[this](bool first){
   std::lock_guard<std::mutex>lock(mutex_);
   if(flow_.facts().state==ScrubState::Recheck)flow_.select_recheck(first?ScrubChoice::Clean:ScrubChoice::Save);else flow_.select(first);
  };
 }
 NozzleScrubCoordinator(const NozzleScrubCoordinator&)=delete;
 NozzleScrubCoordinator&operator=(const NozzleScrubCoordinator&)=delete;
 // True while the START click re-sent from Prepare is being handled.
 bool decided()const{return decided_;}
 // GUI thread, Maintenance START on the verified client with calibration
 // allowed to start. True when the Prepare screen was opened instead of
 // starting: offset calibration is ticked in Accurate mode.
 bool offer(void*start_button){
  if(!stock_object_valid(start_button))return false;
  const auto vendor=nozzle_scrub_vendor();
  if(vendor.selected[3]!=1||*vendor.rapid!=0)return false;
  const unsigned heads=*vendor.heads;
  const bool combined=vendor.selected[0]==1||vendor.selected[1]==1||vendor.selected[2]==1;
  const auto data=snapshot_();ScrubView view;
  if(!backend_supported(data))return false;
  {std::lock_guard<std::mutex>lock(mutex_);
   // A reserved run owns the flow and its bound request until its worker returns.
   if(reserved_||flow_.hold())return false;
   flow_.open(heads,combined,data.value("calibration_session",""));
   request_.clear();pending_=false;
   flow_.observe(data,now_());view=nozzle_scrub_view(flow_.facts());}
  action_.store(ActionNone);start_button_=nullptr;shown_=ScreenNone;
  if(view.state==ScrubState::Prepare){
   screen_.created(stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr));screen_.update(view);
   if(screen_.visible()){start_button_=start_button;shown_=ScreenShown;return true;}
  }
  // Head count outside 1..4 or no screen: stock behaviour, nothing changed.
  screen_.created(nullptr);
  std::lock_guard<std::mutex>lock(mutex_);flow_.close();return false;
 }
 // mutex_ held, at calibration admission. A wire-brush choice made on Prepare
 // binds the scrub to this request only. The flow then trusts backend status
 // for this request alone.
 void bind_admitted_locked(const std::string&request){
  request_=pending_?request:std::string();pending_=false;
  if(!request_.empty())flow_.bind(request_);
  result_request_.clear();result_heads_=0;
  result_flagged_.clear();result_saved_anyway_=result_cancelled_=false;result_restore_.clear();
 }
 // mutex_ held. Head count of the wire-brush scrub of the current run, 0 for
 // any other run. For the result panel.
 unsigned result_heads_locked()const{return result_request_==run_request_?result_heads_:0U;}
 // mutex_ held. Re-check outcome of the current run's wire-brush scrub, for
 // the result panel; empty or false for any other run. Flagged heads are
 // 0-based and named only when Save anyway released the worker. Cancelled: the
 // re-check was cancelled and the restore of the stored offsets was sent.
 // Restore failed: that restore was not reported done.
 std::vector<unsigned> result_flagged_heads_locked()const{return result_request_==run_request_?result_flagged_:std::vector<unsigned>();}
 bool result_saved_anyway_locked()const{return result_request_==run_request_&&result_saved_anyway_;}
 bool result_cancelled_locked()const{return result_request_==run_request_&&result_cancelled_;}
 bool result_restore_failed_locked()const{return result_cancelled_locked()&&result_restore_!="done";}
 // Vendor worker thread, after the offset-stage G28 was forwarded; request is
 // the worker's calibration request. Returns at once unless a brush scrub is
 // bound to it. Otherwise holds the worker while the flow needs it
 // (hold_locked).
 void at_offset_stage(const std::string&request,const std::function<void(const std::string&inner)>&send){
  if(request.empty())return;
  std::unique_lock<std::mutex>lock(mutex_);
  if(request_!=request)return;
  // Kept after the flow closes, for the result panel of this request.
  result_request_=request;result_heads_=flow_.facts().heads;
  flow_.offset_stage_reached(now_());
  hold_locked(lock,send);
 }
 // Vendor worker thread; request is the worker's calibration request. True
 // for the RAPID_MODE and PARK_CURRENT_TOOL sends of the offset stage when
 // this worker's brush run stopped: the scrub was cancelled or failed, or the
 // backend latched a failure during probing.
 //
 // The park send with a sender first holds the worker for the re-check
 // (park_reached, hold_locked): the flow holds it while fresh status for this
 // request flags heads, and its commands leave through send on this thread
 // with the attempt's next sequence numbers. Without a sender the worker is
 // not held. Every decision below is made after that hold ends, so a failure
 // during a re-clean or re-measurement takes the same path as one in the
 // first pass.
 //
 // The vendor worker learns of a failed probing command from its error
 // response (knife_pairing_failed = 1), usually before polled status reports
 // the backend's latch. A park send that finds the byte set therefore waits,
 // for a bounded time, until the flow has seen that status.
 //
 // A withheld park send writes knife_pairing_failed = 0 when the backend
 // reports that it will admit the early save (early_save_available_locked,
 // called with mutex_ held: fresh status, this worker's attempt,
 // early_save_available). The vendor worker then neither calls quick_stop nor
 // skips its SAVE_CONFIG. In every other case the byte is left as it is: a
 // byte of 1 takes the vendor's own failure path (quick_stop, no
 // SAVE_CONFIG), so the worker never sends a save the backend would refuse.
 // With the byte at 0 (a cancelled scrub) nothing is written and the vendor
 // sends its ordinary save.
 //
 // When the byte is cleared no command of this run can still raise: the
 // attempt has failed, so the failing command has raised and the backend
 // refuses every other command of the attempt except that one save. Its
 // error response has reached the client: either it set the byte, or the
 // vendor wait helper (at least 1 s) ran for each withheld probing send.
 // knife_pairing_ing is never written.
 bool withhold_offset_send(std::uintptr_t caller,const std::string&request,const std::function<bool()>&early_save_available_locked,
                           const std::function<void(const std::string&inner)>&send=std::function<void(const std::string&)>()){
  if((caller!=offset_rapid&&caller!=offset_park)||request.empty())return false;
  std::unique_lock<std::mutex>lock(mutex_);
  if(request_!=request)return false;
  if(caller==offset_park&&send){
   flow_.park_reached(now_());hold_locked(lock,send);
   const auto facts=flow_.facts();
   if(result_request_==request){
    // A shutdown during a re-measurement leaves its restore unsent.
    result_saved_anyway_=facts.saved_anyway;result_cancelled_=facts.restored_requested||(stopping_&&facts.state==ScrubState::Remeasure);
    result_flagged_=facts.saved_anyway?facts.flagged:std::vector<unsigned>();
   }
  }
  const auto vendor=nozzle_scrub_vendor();
  // A runtime that stops during a re-measurement withholds the park: the
  // re-measurement cut short is not completed by the park. Every other
  // cancel at shutdown sets Skip itself; outside the re-check a shutdown
  // leaves the sends as they are.
  const auto skip=[this]{return flow_.outcome()==ScrubOutcome::Skip||(stopping_&&flow_.facts().state==ScrubState::Remeasure);};
  if(caller==offset_park&&*vendor.failed==1){
   const auto deadline=std::chrono::steady_clock::now()+std::chrono::milliseconds(failure_wait_ms_);
   while(!stopping_&&!skip()){
    const auto left=std::chrono::duration_cast<std::chrono::milliseconds>(deadline-std::chrono::steady_clock::now()).count();
    if(left<=0)break;
    wait(lock,int(std::min<long long>(left,250)));
   }
  }
  if(!skip())return false;
  if(caller==offset_park&&*vendor.failed==1&&early_save_available_locked())*vendor.failed=0;
  return true;
 }
 // Ends a worker hold unconditionally. Called when the runtime goes away.
 void shutdown()noexcept{
  try{{std::lock_guard<std::mutex>lock(mutex_);stopping_=true;}wake_.notify_all();}catch(...){}
 }
 // GUI tick: user actions, status and clock for the flow, and the screen.
 // result_shown: the stock calibration result panel shows an outcome.
 void tick(bool result_shown){
  const int action=action_.exchange(ActionNone);
  {std::lock_guard<std::mutex>lock(mutex_);if(shown_==ScreenNone&&flow_.facts().state==ScrubState::Idle)return;}
  const auto data=snapshot_();const double now=now_();
  const bool external=action==ActionCancel&&data.value("calibration_cancel_protocol",0)==2&&cancel_requested&&cancel_requested();
  // Any touch on the screen resets the display's inactive time, which the
  // client counts in its own (wall-clock) LVGL tick. A touch is a decrease of
  // that value since the previous GUI tick; it is reported at the previous
  // tick's time on this clock, the earliest it can have happened, so a touch
  // just before the signal started never releases it. A wall-clock step back
  // smaller than the inactive time also reads as a decrease.
  const auto inactive=stock_function<std::uint32_t(*)(void*)>(lv_disp_get_inactive_time)(nullptr);
  const bool touch=inactive_at_>=0&&inactive<inactive_;const double touched_at=inactive_at_;
  inactive_=inactive;inactive_at_=now;
  ScrubView view;bool start=false,brush=false,hold=false,bound=false;
  {std::lock_guard<std::mutex>lock(mutex_);
   if(touch)flow_.touched(touched_at);
   if((external||data.value("maintenance_cancel_requested",false))&&data.value("maintenance_cancel_request",run_request_)==run_request_)flow_.cancel_out_of_band(now);
   flow_.observe(data,now);
   // The restore outcome of the result request, before the save's restart loses it.
   if(!result_request_.empty()&&data.value("fresh",false)&&data.contains("nozzle_touch")&&data["nozzle_touch"].is_object()){
    const auto&touch=data["nozzle_touch"];
    if(touch.contains("request")&&touch["request"]==result_request_&&touch.contains("restore")&&touch["restore"].is_string())result_restore_=touch["restore"].get<std::string>();
   }
   if(action==ActionConfirm){start=flow_.confirm(now);brush=flow_.brush();}
   else if(action==ActionCancel&&!external&&(flow_.facts().state==ScrubState::Prepare||data.value("calibration_cancel_protocol",0)!=2))flow_.cancel(now);
  }
  if(start)start_from_prepare(brush);
  {std::lock_guard<std::mutex>lock(mutex_);
   view=nozzle_scrub_view(flow_.facts());hold=flow_.hold();bound=bound_locked();}
  if(data.value("calibration_cancel_protocol",0)==2&&(view.state==ScrubState::Calibrate||view.state==ScrubState::Remeasure))view.cancel_visible=data.value("maintenance_cancel_available",false);
  if(view.state==ScrubState::Cancelling&&!data.value("maintenance_cancel_message","").empty())view.body=data.value("maintenance_cancel_message","");
  bool cancel=false,close=false;
  if(view.state==ScrubState::Idle)dismiss();
  else if(view.state==ScrubState::Prepare){
   // Prepare is created on the active screen; once it is gone nothing was chosen.
   if(screen_.visible())screen_.update(view);else cancel=true;
  }
  else if(view.state==ScrubState::StockChecks)close=!bound; // admission refused or the worker ended early
  else{
   if(action==ActionBack&&view.back_visible)dismiss(ScreenLeft);
   // A worker held for a choice always has a screen: a screen left earlier
   // (removed while the worker measured, or under the result overlay) is
   // created again.
   if(shown_==ScreenLeft&&hold&&view.cancel_visible)shown_=ScreenNone;
   if(shown_==ScreenNone){
    screen_.created(stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr));shown_=ScreenShown;
    screen_.update(view);
   }else if(shown_==ScreenShown)screen_.update(view);
   // The stock UI removed the screen while the worker waits on it: same as CANCEL.
   if(shown_==ScreenShown&&!screen_.visible()){dismiss(ScreenLeft);cancel=hold;}
   // Probing has ended once the stock result overlay is up. The same holds
   // for a cancelled scrub ("Cancelling..."): the result page takes over
   // through the save and the restart.
   if((view.state==ScrubState::Calibrate||view.state==ScrubState::Finished)&&result_shown)dismiss(ScreenLeft);
   // The worker returned. A failure stays on screen until BACK.
   if(!bound&&!(view.state==ScrubState::Failed&&shown_==ScreenShown))close=true;
  }
  const bool auto_external=cancel&&view.state!=ScrubState::Prepare&&data.value("calibration_cancel_protocol",0)==2&&cancel_requested&&cancel_requested();
  if(cancel||close){
   std::lock_guard<std::mutex>lock(mutex_);
   if(auto_external)flow_.cancel_out_of_band(now);
   // close with the flow still holding happens only after its worker has
   // returned (runtime shutdown); queued commands then have no sender left.
   if(!auto_external&&(cancel||flow_.hold()))flow_.cancel(now);
   if(close){flow_.close();request_.clear();}
  }
  if(close||(cancel&&view.state==ScrubState::Prepare))dismiss();
  wake_.notify_all();
 }
};
}}
