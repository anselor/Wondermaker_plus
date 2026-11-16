// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../recovery_request.hpp"
#include "../../openace-compat/screen1113/source/client/worker_bridge.hpp"
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>
namespace wmp_ui { namespace native {
inline std::string print_cancel_resolution_script(const Json&identity,const Json&request){
 if(!request.is_object()||request.size()!=6)throw std::runtime_error("Invalid cancellation review");
 for(const auto*key:{"id","session","cancel_id"}){
  if(request.at(key)!=identity.at(key))throw std::runtime_error("Cancellation review changed identity");
  const auto value=request.at(key).get<std::string>();
  if(value.empty()||value.size()>96||value.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")!=std::string::npos)
   throw std::runtime_error("Invalid cancellation identity");
 }
 const auto action=request.at("action").get<std::string>();
 if((action!="finish_cleanup"&&action!="finish_idle_cleanup"&&action!="discard_saved_job"&&action!="acknowledge_complete")
    ||!recovery_hex(request.at("token"),32)||!request.at("job_id").is_string()
    ||request.dump().size()>4096)throw std::runtime_error("Invalid cancellation resolution action");
 std::string hex;const char*digits="0123456789abcdef";
 for(unsigned char c:request.dump()){hex+=digits[c>>4];hex+=digits[c&15];}
 return "WMP_RESOLVE_PRINT_CANCEL REQUEST="+hex;
}
// Review never submits cleanup. Only confirm() can schedule the one-use command.
// Receipt matching remains valid when cleanup changes the original cancel state.
class PrintCancelResolutionWorker {
 using Clock=std::chrono::steady_clock;
 wmp_openace::HttpPort&http_;mutable std::mutex mutex_;std::condition_variable wake_;
 Json helper_=Json::object(),identity_=Json::object(),request_=Json::object(),record_=Json::object(),result_=Json::object();
 Clock::time_point observed_{},reviewed_{},last_auto_review_{};bool fresh_=false,quit_=false,busy_=false,sent_=false,matched_=false;
 unsigned serial_=0;std::string queued_;std::thread thread_;
 bool reject(const std::string&why)const{report_rejection("cancellation resolution",why);return false;}
 std::string current_reason()const{
  if(!fresh_)return "Status is not fresh.";
  const auto age=std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now()-observed_).count();
  if(age>=2000)return "Status expired: age_ms="+std::to_string(age)+", limit_ms=2000.";
  const auto owner=helper_.value("afc_metadata",Json::object()).value("owner","");
  if(owner!="standalone")return "Standalone ownership required; current="+rejection_value(owner)+".";
  if(helper_.value("print_cancel_resolution_protocol",0)!=1)return "Unsupported print_cancel_resolution_protocol="+std::to_string(helper_.value("print_cancel_resolution_protocol",0))+"; expected=1.";
  return {};
 }
 bool current()const{return fresh_&&Clock::now()-observed_<std::chrono::seconds(2)
  &&helper_.value("afc_metadata",Json::object()).value("owner","")=="standalone"
  &&helper_.value("print_cancel_resolution_protocol",0)==1;}
 bool bound()const{
  if(!current()||identity_.empty()||helper_.value("session_id","")!=identity_.value("session",""))return false;
  const auto record=helper_.value("print_cancel",Json::object());
  for(const auto*key:{"id","session","file"})if(record.value(key,"")!=record_.value(key,""))return false;
  return true;
 }
 bool review_current()const{return bound()&&helper_.value("print_cancel",Json::object())==record_;}
 std::string binding_reason()const{
  if(!current())return current_reason();
  if(identity_.empty())return "No cancellation resolution has been reviewed.";
  if(helper_.value("session_id","")!=identity_.value("session",""))return "Reviewed printer session changed.";
  const auto record=helper_.value("print_cancel",Json::object());
  for(const auto*key:{"id","session","file"})if(record.value(key,"")!=record_.value(key,""))return "Reviewed cancellation "+std::string(key)+" changed.";
  if(record!=record_)return "Reviewed cancellation result changed.";
  return "Reviewed operation binding is unavailable.";
 }
 void loop()noexcept{
  for(;;){std::string job;Json identity,request;
   {std::unique_lock<std::mutex>lock(mutex_);wake_.wait(lock,[this]{return quit_||!queued_.empty();});if(quit_)return;
    job=queued_;queued_.clear();busy_=true;identity=identity_;request=request_;}
   bool dispatched=false;std::string rejected;
   try{
    {std::lock_guard<std::mutex>lock(mutex_);if(!review_current()){rejected=binding_reason();throw std::runtime_error("Cancellation context changed");}}
    if(job=="review"){
     const auto response=Json::parse(http_.post("/printer/wmp/print/cancel_resolve_review",identity.dump())).at("result");
     request=response.at("request");(void)print_cancel_resolution_script(identity,request);
     std::lock_guard<std::mutex>lock(mutex_);
     if(!review_current()){rejected=binding_reason();throw std::runtime_error("Cancellation review changed");}
     if(response.at("file")!=record_.at("file")){rejected="Cancellation review returned a different file identity.";throw std::runtime_error("Cancellation review changed");}
     request_=request;reviewed_=Clock::now();result_["state"]="reviewed";result_["request"]=request;
     result_["message"]=response.at("message").get<std::string>().substr(0,512);
    }else{
     const auto script=print_cancel_resolution_script(identity,request);
     {std::lock_guard<std::mutex>lock(mutex_);
      if(!review_current()){rejected=binding_reason();throw std::runtime_error("Cancellation review changed");}
      if(Clock::now()-reviewed_>=std::chrono::seconds(60)){rejected="Cancellation review expired: maximum age_ms=60000.";throw std::runtime_error("Cancellation review expired");}
      sent_=true;dispatched=true;}
     (void)http_.post("/printer/gcode/script",Json{{"script",script}}.dump());
     std::lock_guard<std::mutex>lock(mutex_);if(!matched_){result_["state"]="unknown";result_["message"]="Waiting for recorded cancellation resolution; request will not be repeated.";}
    }
   }catch(...){std::lock_guard<std::mutex>lock(mutex_);if(!matched_){
    result_["state"]=dispatched?"unknown":"refused";
    result_["message"]=dispatched?"Resolution outcome unknown; request will not be repeated.":"Cancellation status check did not finish. Checking again automatically; no cleanup action was sent.";}}
   {std::lock_guard<std::mutex>lock(mutex_);if(!rejected.empty()){report_rejection("review dispatch",rejected);if(!matched_)result_["message"]=rejected+" No new action sent.";}busy_=false;}
  }
 }
public:
 explicit PrintCancelResolutionWorker(wmp_openace::HttpPort&http):http_(http),thread_([this]{loop();}){}
 ~PrintCancelResolutionWorker(){{std::lock_guard<std::mutex>lock(mutex_);quit_=true;}wake_.notify_all();thread_.join();}
 PrintCancelResolutionWorker(const PrintCancelResolutionWorker&)=delete;
 PrintCancelResolutionWorker&operator=(const PrintCancelResolutionWorker&)=delete;
 void observe(const Json&helper,bool fresh){
  std::lock_guard<std::mutex>lock(mutex_);helper_=helper;fresh_=fresh;observed_=Clock::now();
  if(current()&&!busy_&&queued_.empty()&&!identity_.empty()&&helper_.value("session_id","")!=identity_.value("session","")){
   identity_=request_=record_=result_=Json::object();sent_=matched_=false;
  }
  if(!sent_||!bound())return;
  const auto receipt=helper.value("print_cancel_resolution",Json::object());
  for(auto it=request_.begin();it!=request_.end();++it)if(!receipt.contains(it.key())||receipt.at(it.key())!=it.value())return;
  const auto state=receipt.value("state","");
  if(state!="pending"&&state!="complete"&&state!="unknown"&&state!="refused")return;
  if(matched_&&result_.value("state","")!="pending")return;
  matched_=true;result_["state"]=state;result_["message"]=receipt.value("message","");
 }
 bool review(){
  std::lock_guard<std::mutex>lock(mutex_);
  if(!current())return reject(current_reason());
  if(busy_||!queued_.empty())return reject("Request delivery pending: busy="+std::to_string(busy_)+", queued="+rejection_value(queued_)+".");
  const auto record=helper_.value("print_cancel",Json::object());
  if(record.value("state","")!="unknown")return reject("Cancellation resolution requires unknown state; current="+rejection_value(record.value("state",""))+".");
  if(record.value("id","").empty())return reject("Cancellation record identifier is missing.");
  if(record.value("file","").empty())return reject("Cancellation record filename is missing.");
  identity_={{"id","cancel_resolve_"+std::to_string(Clock::now().time_since_epoch().count())+"_"+std::to_string(++serial_)},
   {"cancel_id",record.at("id")},{"session",helper_.value("session_id","")}};
  record_=record;request_=Json::object();sent_=matched_=false;
  result_={{"id",identity_.at("id")},{"state","reviewing"},{"message","Reviewing interrupted cancellation"}};
  queued_="review";wake_.notify_all();return true;
 }
 // Called only while the result is visible. Read-only checks never dispatch
 // cleanup, overlap an outstanding request, or replace an uncertain command.
 bool auto_review(){
  {
   std::lock_guard<std::mutex>lock(mutex_);
   const auto record=helper_.value("print_cancel",Json::object());
   if(!current()||busy_||!queued_.empty()||record.value("state","")!="unknown")return false;
   if(sent_&&bound())return false;
   if(review_current()&&result_.value("state","")=="reviewed"&&Clock::now()-reviewed_<std::chrono::seconds(55))return false;
   if(Clock::now()-last_auto_review_<std::chrono::seconds(5))return false;
   last_auto_review_=Clock::now();
  }
  return review();
 }
 bool confirm(const std::string&id){
  std::lock_guard<std::mutex>lock(mutex_);
  if(!review_current())return reject(binding_reason());
  if(busy_||!queued_.empty())return reject("Confirmation delivery pending: busy="+std::to_string(busy_)+", queued="+rejection_value(queued_)+".");
  if(result_.value("state","")!="reviewed")return reject("Confirmation requires reviewed state; current="+rejection_value(result_.value("state",""))+".");
  if(identity_.value("id","")!=id)return reject("Confirmation identity differs from the reviewed operation.");
  if(Clock::now()-reviewed_>=std::chrono::seconds(60))return reject("Cancellation review expired: maximum age_ms=60000.");
  result_["state"]="pending";queued_="confirm";wake_.notify_all();return true;
 }
 Json result()const{
  std::lock_guard<std::mutex>lock(mutex_);auto result=result_;result["recorded"]=matched_;result["available"]=current();
  result["fresh"]=review_current()&&Clock::now()-reviewed_<std::chrono::seconds(60);
  result["session"]=helper_.value("session_id","");result["cancel"]=helper_.value("print_cancel",Json::object());
  result["delivery_pending"]=busy_||!queued_.empty();return result;
 }
};
}}
