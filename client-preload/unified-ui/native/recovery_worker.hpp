// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../recovery_request.hpp"
#include "../../openace-compat/screen1113/source/client/worker_bridge.hpp"
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>
#include <set>
namespace wmp_ui { namespace native {
inline std::string recovery_display_state(const Json&receipt){
 const auto state=receipt.value("state","");
 if(state=="complete"){
  const auto next=receipt.value("continuation",Json::object()).value("state","");
  return next=="scheduled"?"pending":next=="started"?"printing":next=="checkpointed"?"reconciled":
   (next=="complete"||next=="paused"||next=="cancelled")?next:"unknown";
 }
 return (state=="pending"||state=="running"||state=="unknown"||state=="stopped"||state=="abandoned")?state:"unknown";
}
inline bool recovery_display_terminal(const std::string&state){
 return state=="complete"||state=="cancelled"||state=="abandoned"||state=="reconciled";
}
// Two independent bounded transports: command acknowledgement may wait through
// preparation, while STOP must remain deliverable. Neither thread accesses LVGL.
class RecoveryWorker {
 using Clock=std::chrono::steady_clock;
 wmp_openace::HttpPort&command_http_;wmp_openace::HttpPort&stop_http_;
 mutable std::mutex mutex_;std::condition_variable wake_;
 Json helper_=Json::object(),selection_=Json::object(),request_=Json::object(),result_=Json::object();
 Clock::time_point observed_{};bool fresh_=false,quit_=false,queued_=false,busy_=false,dispatched_=false;
 bool stop_queued_=false,stop_sent_=false,stop_busy_=false,matched_=false;std::set<std::string>seen_;
 std::thread command_thread_,stop_thread_;
 bool current()const{return fresh_&&Clock::now()-observed_<std::chrono::seconds(2)
  &&helper_.value("session_id","")==selection_.value("session","")
  &&helper_.value("afc_metadata",Json::object()).value("owner","")=="standalone";}
 std::string current_reason()const{
  if(!fresh_)return "Recovery status is not fresh.";
  const auto age=std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now()-observed_).count();
  if(age>=2000)return "Recovery status expired: age_ms="+std::to_string(age)+", limit_ms=2000.";
  if(helper_.value("session_id","")!=selection_.value("session",""))return "Recovery selection session changed.";
  return "Recovery requires standalone ownership; current="+rejection_value(helper_.value("afc_metadata",Json::object()).value("owner",""))+".";
 }
 bool unresolved()const{
  const auto state=result_.value("state","");return busy_||queued_||state=="pending"||state=="running"||state=="printing"||state=="paused";
 }
 // A live request cannot survive a confirmed backend session change. Keep
 // its identity/history, but retire its local activity after transport returns.
 void retire_restarted_attempt(){
  if(!dispatched_||busy_||queued_||!fresh_||Clock::now()-observed_>=std::chrono::seconds(2)
     ||helper_.value("afc_metadata",Json::object()).value("owner","")!="standalone"
     ||helper_.value("session_id","").empty()||helper_.value("session_id","")==selection_.value("session",""))return;
  const auto state=result_.value("state","");
  if(state=="pending"||state=="running"||state=="printing"||state=="paused"){
   result_["state"]="unknown";
   result_["message"]="Printer restarted during recovery; the previous attempt is interrupted. Select recovery again to check the current printer state.";
  }
 }
 void command_loop()noexcept{
  for(;;){
   Json selected;bool ticket_mode=false;
   {std::unique_lock<std::mutex>lock(mutex_);wake_.wait(lock,[this]{return quit_||queued_;});if(quit_)return;
    queued_=false;busy_=true;selected=selection_;ticket_mode=helper_.value("recovery_ticket_protocol",0)==1;}
   bool sent=false;std::string rejected;
   try{
    {std::lock_guard<std::mutex>lock(mutex_);if(!current()){rejected=current_reason();throw std::runtime_error("Selection is stale");}}
    auto args=selected;if(ticket_mode)args["ticket_protocol"]="1";
    const auto reply=Json::parse(command_http_.post("/printer/wmp/recovery/review",args.dump()));
    if(reply.contains("error")){
     const auto error=reply.at("error");std::string reason="Recovery review refused; no preparation sent.";
     if(error.is_string())reason=error.get<std::string>();
     else if(error.is_object()&&error.contains("message")&&error.at("message").is_string())reason=error.at("message").get<std::string>();
     report_rejection("recovery review",reason+" Selection="+selected.dump());
     std::lock_guard<std::mutex>lock(mutex_);result_["state"]="refused";result_["message"]=reason.substr(0,512);busy_=false;continue;
    }
    const auto review=reply.at("result");if(ticket_mode&&!review.contains("ticket")){rejected="Advertised recovery ticket is missing from the review.";throw std::runtime_error(rejected);}
    std::string script;try{script=recovery_continue_script(selected,review);}catch(const std::exception&error){rejected=error.what();throw;}
    {std::lock_guard<std::mutex>lock(mutex_);
     if(!current()){rejected=current_reason();throw std::runtime_error("Ownership changed before dispatch");}
     request_=review.at("request");result_["review"]=review;result_["message"]="Preparing recovery";
     dispatched_=true;sent=true;}
    const auto response=Json::parse(command_http_.post("/printer/gcode/script",Json{{"script",script}}.dump()));
    std::lock_guard<std::mutex>lock(mutex_);
    if(!matched_){result_["state"]="unknown";result_["message"]=response.contains("error")?
      "Recovery command returned an error; waiting for its recorded result.":"Waiting for the recorded recovery result.";}
   }catch(const std::exception&error){
    report_rejection("recovery review/delivery",std::string(error.what())+" Selection="+selected.dump());
    std::lock_guard<std::mutex>lock(mutex_);if(!matched_){
     result_["state"]=sent?"unknown":"refused";
     result_["message"]=std::string(error.what()).substr(0,512)+(sent?" Delivery outcome unknown; request will not be repeated.":" No preparation sent.");
    }
   }catch(...){std::lock_guard<std::mutex>lock(mutex_);if(!matched_){
    report_rejection("recovery review/delivery","Unknown exception. Selection="+selected.dump());
    result_["state"]=sent?"unknown":"refused";
    result_["message"]=sent?"Recovery delivery outcome unknown; request will not be repeated.":"Recovery review failed or changed; no preparation sent.";}}
   {std::lock_guard<std::mutex>lock(mutex_);if(!rejected.empty()){report_rejection("recovery dispatch",rejected);if(!matched_)result_["message"]=rejected+" No preparation sent.";}busy_=false;retire_restarted_attempt();}
  }
 }
 void stop_loop()noexcept{
  for(;;){Json args;
   {std::unique_lock<std::mutex>lock(mutex_);wake_.wait(lock,[this]{return quit_||stop_queued_;});if(quit_)return;
    stop_queued_=false;stop_sent_=true;
    if(!current()){result_["stop"]="unconfirmed";continue;}
    stop_busy_=true;args={{"id",request_.at("id")},{"session",request_.at("session")}};}
   bool confirmed=false;
   try{auto reply=Json::parse(stop_http_.post("/printer/wmp/recovery/stop",args.dump()));
    const auto r=reply.at("result");confirmed=r.at("id")==args.at("id")&&r.at("session")==args.at("session")&&r.value("state","")=="requested";
   }catch(...){}
   std::lock_guard<std::mutex>lock(mutex_);stop_busy_=false;result_["stop"]=confirmed?"requested":"unconfirmed";
  }
 }
public:
 RecoveryWorker(wmp_openace::HttpPort&command,wmp_openace::HttpPort&stop):command_http_(command),stop_http_(stop),
  command_thread_([this]{command_loop();}),stop_thread_([this]{stop_loop();}){}
 ~RecoveryWorker(){ {std::lock_guard<std::mutex>lock(mutex_);quit_=true;}wake_.notify_all();command_thread_.join();stop_thread_.join();}
 RecoveryWorker(const RecoveryWorker&)=delete;RecoveryWorker&operator=(const RecoveryWorker&)=delete;
private:
 bool select_locked(const Json&selection){
  auto reject=[](const std::string&why){report_rejection("recovery start",why);return false;};
  if(unresolved())return reject("Previous recovery is unresolved: state="+rejection_value(result_.value("state",""))+", queued="+std::to_string(queued_)+", busy="+std::to_string(busy_)+".");
  if(stop_queued_||stop_busy_)return reject("Recovery STOP is pending: queued="+std::to_string(stop_queued_)+", busy="+std::to_string(stop_busy_)+".");
  if(helper_.value("recovery_ticket_protocol",0)!=0&&helper_.value("recovery_ticket_protocol",0)!=1)return reject("Unsupported recovery_ticket_protocol="+std::to_string(helper_.value("recovery_ticket_protocol",0))+".");
  if(helper_.value("recovery_ticket_protocol",0)!=1&&seen_.size()>=1024)return reject("Legacy recovery history is full. Update WM+ for bounded recovery tickets, or restart Klipper and the touchscreen.");
  try{if(native_recovery_selection(selection.at("id"),selection.at("session"),selection.at("file"),selection.at("checkpoint"),selection.at("checkpoint_hash"),selection.at("job_hash"))!=selection)return reject("Recovery selection has unexpected fields or changed canonical values.");}catch(...){return reject("Recovery selection is missing required fields or has malformed values.");}
  if(!fresh_)return reject("Recovery status is not fresh.");
  const auto age=std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now()-observed_).count();
  if(age>=2000)return reject("Recovery status expired: age_ms="+std::to_string(age)+", limit_ms=2000.");
  if(helper_.value("session_id","")!=selection.at("session"))return reject("Recovery selection belongs to a different printer session.");
  const auto owner=helper_.value("afc_metadata",Json::object()).value("owner","");
  if(owner!="standalone")return reject("Recovery requires standalone ownership; current owner="+rejection_value(owner)+".");
  for(const auto*key:{"recovery_review_protocol","recovery_continue_protocol","recovery_stop_protocol"})if(helper_.value(key,0)!=1)return reject("Unsupported "+std::string(key)+"="+std::to_string(helper_.value(key,0))+"; expected=1.");
  if(helper_.value("recovery_ticket_protocol",0)!=1&&!seen_.insert(selection.at("id").get<std::string>()).second)return reject("Recovery request was already submitted; duplicate delivery prevented.");
  selection_=selection;request_=Json::object();matched_=dispatched_=stop_sent_=false;
  result_={{"id",selection.at("id")},{"state","pending"},{"message","Reviewing saved recovery"}};
  queued_=true;wake_.notify_all();return true;
 }
public:
 bool select(const Json&selection){std::lock_guard<std::mutex>lock(mutex_);return select_locked(selection);}
 // Native callbacks copy their immutable selection here; no HTTP or GUI calls.
 // A repeated click reopens the same result, never creates a second attempt.
 bool select_native(unsigned version,const std::string&file,const std::string&checkpoint,
                    const std::string&checkpoint_hash,const std::string&job_hash){
  std::lock_guard<std::mutex>lock(mutex_);
  if(version!=1)return false;
  try{
   const auto session=helper_.value("session_id","");
   const auto id="screen_"+std::to_string(std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count());
   auto selection=native_recovery_selection(id,session,file,checkpoint,checkpoint_hash,job_hash);
   if(!selection_.empty()){
    bool same=true;for(const auto*key:{"session","file","checkpoint","checkpoint_hash","job_hash"})
     if(selection.at(key)!=selection_.at(key))same=false;
    if(same&&unresolved())return true;
   }
   return select_locked(selection);
  }catch(...){return false;}
 }
 void observe(const Json&helper,bool fresh){
  std::lock_guard<std::mutex>lock(mutex_);
  if(fresh&&!helper.value("session_id","").empty()&&helper.value("session_id","")!=helper_.value("session_id",""))seen_.clear();
  helper_=helper;fresh_=fresh;observed_=Clock::now();
  if(!dispatched_)return;
  retire_restarted_attempt();
  const auto receipt=helper.value("recovery_attempt",Json::object());
  const Json expected={{"id",request_.at("id")},{"session",request_.at("session")},{"file",request_.at("file")},{"execution_hash",request_.at("execution_hash")}};
  if(!current()){
   // A new backend session cannot confirm old preparation. It can publish an
   // explicit durable resolution of that exact attempt, releasing the local hold.
   if(fresh_&&!busy_&&!queued_&&helper.value("afc_metadata",Json::object()).value("owner","")=="standalone"
      &&helper.value("session_id","")!=selection_.value("session","")&&receipt.value("request",Json::object())==expected){
    const auto state=receipt.value("state","");
    if(state=="abandoned"||(state=="complete"&&receipt.value("continuation",Json::object()).value("state","")=="checkpointed")){
     result_["state"]=state=="abandoned"?"abandoned":"reconciled";result_["receipt"]=receipt;
    }
   }
   return;
  }
  if(receipt.value("request",Json::object())!=expected){
   const auto submission=helper.value("recovery_submission",Json::object());
   if(submission.value("request",Json::object())==expected&&submission.value("state","")=="refused"&&!matched_){
    matched_=true;result_["state"]="refused";result_["message"]=submission.value("message","Recovery refused before preparation.");
   }
   return;
  }
  // These are terminal outcomes of the whole attempt, not just preparation.
  // Paused, stopped and unknown remain eligible for later reconciliation.
  const auto previous=result_.value("state","");
  if(matched_&&recovery_display_terminal(previous))return;
  matched_=true;result_["receipt"]=receipt;result_["temperatures"]=helper.value("recovery_temperatures",Json::object());
  result_["state"]=recovery_display_state(receipt);
  result_["message"]=receipt.value("error","");
  if(result_.value("message","").empty())result_["message"]=receipt.value("continuation",Json::object()).value("error","");
 }
 bool stop(){std::lock_guard<std::mutex>lock(mutex_);
  const auto receipt=result_.value("receipt",Json::object());const auto state=receipt.value("state","");
  auto reject=[](const std::string&why){report_rejection("recovery STOP",why);return false;};
  if(!fresh_||Clock::now()-observed_>=std::chrono::seconds(2))return reject("Recovery status is stale: fresh="+std::to_string(fresh_)+", age_ms="+std::to_string(std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now()-observed_).count())+", limit_ms=2000.");
  if(helper_.value("session_id","")!=selection_.value("session",""))return reject("Recovery session changed.");
  const auto owner=helper_.value("afc_metadata",Json::object()).value("owner","");
  if(owner!="standalone")return reject("Recovery STOP requires standalone ownership; current="+rejection_value(owner)+".");
  if(!dispatched_)return reject("Recovery has not been dispatched.");
  if(!matched_)return reject("No matching recovery receipt has been observed.");
  if(stop_queued_||stop_sent_)return reject("Recovery STOP already queued or sent: queued="+std::to_string(stop_queued_)+", sent="+std::to_string(stop_sent_)+".");
  if(state!="running"&&state!="pending")return reject("Recovery STOP requires running or pending receipt; current="+rejection_value(state)+".");
  stop_queued_=true;result_["stop"]="queued";wake_.notify_all();return true;
 }
 Json result()const{std::lock_guard<std::mutex>lock(mutex_);auto value=result_;value["fresh"]=current();value["delivery_pending"]=busy_||queued_;return value;}
};
}}
