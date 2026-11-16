// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../recovery_request.hpp"
#include "../../openace-compat/screen1113/source/client/worker_bridge.hpp"
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>
#include <functional>
#include <map>
namespace wmp_ui { namespace native {
// Read-only review and explicit confirmation are separate jobs. Neither status
// observation nor a completed review can enqueue the mutating command.
class RecoveryResolutionWorker {
 using Clock=std::chrono::steady_clock;
 wmp_openace::HttpPort&http_;mutable std::mutex mutex_;std::condition_variable wake_;
 Json helper_=Json::object(),identity_=Json::object(),request_=Json::object(),attempt_=Json::object(),result_=Json::object();
 Clock::time_point observed_{};bool fresh_=false,quit_=false,busy_=false,sent_=false,matched_=false;
 std::string queued_;std::thread thread_;
 Json choices_=Json::object();std::string auto_context_;
 std::map<std::string,Clock::time_point> auto_reads_;
 std::function<Clock::time_point()> auto_now_;
 void cache_review(){
  const auto action=identity_.value("action","");if(action.empty())return;
  auto value=result_;value["identity"]=identity_;value["attempt_request"]=attempt_;value["attempt_record"]=helper_.value("recovery_attempt",Json::object());choices_[action]=value;
 }
 bool ticket_bound(const Json&value)const{
  return current()&&value.value("identity",Json::object()).value("session","")==helper_.value("session_id","")
   &&value.value("attempt_request",Json::object())==helper_.value("recovery_attempt",Json::object()).value("request",Json::object())
   &&value.value("attempt_record",Json::object())==helper_.value("recovery_attempt",Json::object());
 }

 bool reject(const std::string&why)const{report_rejection("recovery resolution",why);return false;}
 std::string current_reason()const{
  if(!fresh_)return "Status is not fresh.";
  const auto age=std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now()-observed_).count();
  if(age>=2000)return "Status expired: age_ms="+std::to_string(age)+", limit_ms=2000.";
  const auto owner=helper_.value("afc_metadata",Json::object()).value("owner","");
  if(owner!="standalone")return "Standalone ownership required; current="+rejection_value(owner)+".";
  if(helper_.value("recovery_ticket_protocol",0)!=0&&helper_.value("recovery_ticket_protocol",0)!=1)return "Unsupported recovery_ticket_protocol="+std::to_string(helper_.value("recovery_ticket_protocol",0))+".";
  if(helper_.value("recovery_resolution_protocol",0)!=1)return "Unsupported recovery_resolution_protocol="+std::to_string(helper_.value("recovery_resolution_protocol",0))+"; expected=1.";
  return {};
 }
 bool current()const{return fresh_&&Clock::now()-observed_<std::chrono::seconds(2)
  &&helper_.value("afc_metadata",Json::object()).value("owner","")=="standalone"
  &&helper_.value("recovery_resolution_protocol",0)==1
  &&(helper_.value("recovery_ticket_protocol",0)==0||helper_.value("recovery_ticket_protocol",0)==1);}
 bool bound()const{return current()&&helper_.value("session_id","")==identity_.value("session","")
  &&helper_.value("recovery_attempt",Json::object()).value("request",Json::object())==attempt_;}
 std::string binding_reason()const{
  if(!current())return current_reason();
  if(helper_.value("session_id","")!=identity_.value("session",""))return "Reviewed printer session changed.";
  if(helper_.value("recovery_attempt",Json::object()).value("request",Json::object())!=attempt_)return "Reviewed recovery attempt changed.";
  return "Reviewed operation binding is unavailable.";
 }
 void loop()noexcept{
  for(;;){std::string job;Json identity,request,ticket;bool ticket_mode=false;
   {std::unique_lock<std::mutex>lock(mutex_);wake_.wait(lock,[this]{return quit_||!queued_.empty();});if(quit_)return;
    job=queued_;queued_.clear();busy_=true;identity=identity_;request=request_;ticket=result_.value("ticket",Json());ticket_mode=helper_.value("recovery_ticket_protocol",0)==1;}
   bool dispatched=false;std::string rejected;
   try{
    {std::lock_guard<std::mutex>lock(mutex_);if(!bound()){rejected=binding_reason();throw std::runtime_error("Resolution selection is stale");}}
    if(job=="review"){
     auto args=identity;if(ticket_mode)args["ticket_protocol"]="1";
     const auto response=Json::parse(http_.post("/printer/wmp/recovery/resolve_review",args.dump()));
     if(response.contains("error")){
      const auto error=response.at("error");std::string reason="Resolution review refused; no action sent.";
      if(error.is_string())reason=error.get<std::string>();
      else if(error.is_object()&&error.contains("message")&&error.at("message").is_string())reason=error.at("message").get<std::string>();
      std::lock_guard<std::mutex>lock(mutex_);result_["state"]="refused";result_["message"]=reason.substr(0,512);cache_review();busy_=false;continue;
     }
     request=response.at("result").at("request");ticket=response.at("result").value("ticket",Json());
     if(ticket_mode&&ticket.is_null()){rejected="Advertised resolution ticket is missing from review.";throw std::runtime_error(rejected);}
     try{(void)recovery_resolution_script(identity,request,ticket);}catch(const std::exception&error){rejected=error.what();throw;}
     std::lock_guard<std::mutex>lock(mutex_);if(!bound()){rejected=binding_reason();throw std::runtime_error("Resolution context changed");}
     request_=request;result_["ticket"]=ticket;result_["state"]="reviewed";result_["request"]=request;
     result_["message"]=identity.at("action")=="abandon"?
      "Discard this recovery? The saved print will no longer be resumable.":
      "Use the newer saved checkpoint? This updates the recovery record only. It does not move the printer or resume printing.";
    }else{
     const auto script=recovery_resolution_script(identity,request,ticket);
     {std::lock_guard<std::mutex>lock(mutex_);if(!bound()){rejected=binding_reason();throw std::runtime_error("Resolution context changed");}sent_=true;dispatched=true;}
     (void)http_.post("/printer/gcode/script",Json{{"script",script}}.dump());
     std::lock_guard<std::mutex>lock(mutex_);if(!matched_){result_["state"]="unknown";result_["message"]="Waiting for the recorded resolution result; request will not be repeated.";}
    }
   }catch(...){std::lock_guard<std::mutex>lock(mutex_);if(!matched_){
    result_["state"]=dispatched?"unknown":"refused";
    result_["message"]=dispatched?"Resolution delivery outcome unknown; request will not be repeated.":"Resolution review refused or changed. No action sent.";}}
   {std::lock_guard<std::mutex>lock(mutex_);if(!rejected.empty()){report_rejection("review dispatch",rejected);if(!matched_)result_["message"]=rejected+" No new action sent.";}if(job=="review")cache_review();busy_=false;}
  }
 }
public:
 explicit RecoveryResolutionWorker(wmp_openace::HttpPort&http,
  std::function<Clock::time_point()> auto_now=[](){return Clock::now();})
  :http_(http),auto_now_(std::move(auto_now)){thread_=std::thread([this]{loop();});}
 ~RecoveryResolutionWorker(){{std::lock_guard<std::mutex>lock(mutex_);quit_=true;}wake_.notify_all();thread_.join();}
 RecoveryResolutionWorker(const RecoveryResolutionWorker&)=delete;RecoveryResolutionWorker&operator=(const RecoveryResolutionWorker&)=delete;
 void observe(const Json&helper,bool fresh){
  std::lock_guard<std::mutex>lock(mutex_);helper_=helper;fresh_=fresh;observed_=Clock::now();
  // After a backend restart, its durable attempt is the authority. Discard only
  // the old session's volatile action ticket, never replay its submission.
  if(current()&&!busy_&&queued_.empty()&&!identity_.empty()&&helper_.value("session_id","")!=identity_.value("session","")){
   identity_=request_=attempt_=result_=choices_=Json::object();auto_context_.clear();auto_reads_.clear();sent_=matched_=false;
  }
  if(!sent_||!bound())return;
  const auto receipt=helper.value("recovery_resolution",Json::object());
  if(receipt.value("request",Json::object())!=request_)return;
  const auto state=receipt.value("state","");
  if(state!="pending"&&state!="complete"&&state!="unknown"&&state!="refused")return;
  // Keep the first recorded terminal outcome for this exact request. A late
  // snapshot must not reopen it; a new review or session resets matched_.
  if(matched_&&result_.value("state","")!="pending")return;
  matched_=true;result_["state"]=state;result_["message"]=receipt.value("message","");
 }
 // Call only while the result page is visible. Fetch both alternatives;
 // eligibility is not user intent, so neither read chooses or submits one.
 bool auto_read(){
  std::string action;
  {std::lock_guard<std::mutex>lock(mutex_);
   if(!current()||busy_||!queued_.empty())return false;
   if(sent_&&(!matched_||result_.value("state","")=="pending"||result_.value("state","")=="complete"))return false;
   const auto receipt=helper_.value("recovery_attempt",Json::object());
   const auto state=receipt.value("state","");
   if(state!="unknown"&&state!="stopped")return false;
   const auto request=receipt.value("request",Json::object());
   if(request.value("id","").empty()||helper_.value("session_id","").empty())return false;
   const auto context=helper_.value("session_id","")+":"+receipt.dump();
   if(context!=auto_context_||sent_){choices_=Json::object();auto_reads_.clear();auto_context_=context;sent_=matched_=false;}
   const auto now=auto_now_();
   for(const auto*name:{"reconcile","abandon"}){
    if(std::string(name)=="reconcile"&&(receipt.value("continuation",Json::object()).value("state","")!="interrupted"
       ||request.value("session","")==helper_.value("session_id","")))continue;
    const auto choice=choices_.value(name,Json::object());
    if(ticket_bound(choice)&&choice.value("state","")=="reviewed")continue;
    const auto last=auto_reads_.find(name);
    if(last!=auto_reads_.end()&&now-last->second<std::chrono::seconds(5))continue;
    action=name;auto_reads_[action]=now;break;
   }
  }
  return !action.empty()&&review(action);
 }
 bool review(const std::string&action){
  std::lock_guard<std::mutex>lock(mutex_);
  if(!current())return reject(current_reason());
  if(busy_||!queued_.empty())return reject("Request delivery pending: busy="+std::to_string(busy_)+", queued="+rejection_value(queued_)+".");
  if(action!="abandon"&&action!="reconcile")return reject("Unsupported resolution action="+rejection_value(action)+".");
  const auto receipt=helper_.value("recovery_attempt",Json::object());const auto attempt_state=receipt.value("state","");
  if(attempt_state!="unknown"&&attempt_state!="stopped")return reject("Recovery attempt must be unknown or stopped; current="+rejection_value(attempt_state)+".");
  auto attempt=receipt.value("request",Json::object());
  if(attempt.value("id","").empty())return reject("Recovery attempt identifier is missing.");
  if(helper_.value("session_id","").empty())return reject("Printer session identifier is missing.");
  if(action=="reconcile"&&receipt.value("continuation",Json::object()).value("state","")!="interrupted")return reject("Reconcile requires interrupted continuation; current="+rejection_value(receipt.value("continuation",Json::object()).value("state",""))+".");
  if(action=="reconcile"&&attempt.value("session","")==helper_.value("session_id",""))return reject("Reconcile requires a printer session newer than the recovery attempt.");
  identity_={{"id","resolve_"+std::to_string(std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count())},
   {"attempt_id",attempt.at("id")},{"session",helper_.at("session_id")},{"action",action}};
  attempt_=attempt;request_=Json::object();sent_=matched_=false;
  result_={{"id",identity_.at("id")},{"action",action},{"state","reviewing"},{"message","Reviewing recovery resolution"}};
  queued_="review";wake_.notify_all();return true;
 }
 bool confirm(const std::string&id){
  std::lock_guard<std::mutex>lock(mutex_);
  if(busy_||!queued_.empty())return reject("Recovery request delivery is pending.");
  if(sent_)return reject("Resolution already sent; waiting for its recorded result.");
  {
   bool found=false;
   for(const auto&choice:choices_){
    if(choice.value("id","")!=id)continue;
    if(!ticket_bound(choice)||choice.value("state","")!="reviewed")return reject("Selected recovery choice is stale or unavailable.");
    identity_=choice.at("identity");request_=choice.at("request");attempt_=choice.at("attempt_request");result_=choice;
    found=true;break;
   }
   if(!found)return reject("Confirmation identity differs from the reviewed operation.");
  }
  if(!bound())return reject(binding_reason());
  if(busy_||!queued_.empty())return reject("Confirmation delivery pending: busy="+std::to_string(busy_)+", queued="+rejection_value(queued_)+".");
  if(result_.value("state","")!="reviewed")return reject("Confirmation requires reviewed state; current="+rejection_value(result_.value("state",""))+".");
  if(identity_.value("id","")!=id)return reject("Confirmation identity differs from the reviewed operation.");
  result_["state"]="pending";result_["message"]="Submitting reviewed resolution";queued_="confirm";wake_.notify_all();return true;
 }
 Json result()const{std::lock_guard<std::mutex>lock(mutex_);auto value=result_;value["recorded"]=matched_;value["available"]=current();value["session"]=helper_.value("session_id","");value["attempt"]=helper_.value("recovery_attempt",Json::object());value["fresh"]=bound();value["delivery_pending"]=busy_||!queued_.empty();
  value["choices"]=Json::object();for(auto it=choices_.begin();it!=choices_.end();++it){auto choice=it.value();
   choice["fresh"]=ticket_bound(choice)&&!sent_;choice.erase("identity");choice.erase("attempt_request");choice.erase("attempt_record");value["choices"][it.key()]=choice;}
  return value;}
};
}}
