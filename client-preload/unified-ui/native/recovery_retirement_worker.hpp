// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../recovery_request.hpp"
#include "../../openace-compat/screen1113/source/client/worker_bridge.hpp"
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>
namespace wmp_ui { namespace native {
// Observe never enqueues work. Visible pages may request automatic readback;
// a lost acknowledgement can only cause another read, never another command.
class RecoveryRetirementWorker {
 using Clock=std::chrono::steady_clock;
 wmp_openace::HttpPort&http_;mutable std::mutex mutex_;std::condition_variable wake_;
 Json helper_=Json::object(),identity_=Json::object(),request_=Json::object(),result_=Json::object();
 Clock::time_point automatic_read_at_{};
 Clock::time_point observed_{};bool fresh_=false,busy_=false,quit_=false,sent_=false;
 static bool discard_evidence(const Json&receipt){
  const auto version=receipt.value("version",1);
  if(version==1||version==2)return receipt.contains("archive")&&recovery_hex(receipt.at("archive"),64);
  if(version!=3||receipt.contains("archive")||!receipt.contains("archive_warning")||!receipt.at("archive_warning").is_string())return false;
  const auto warning=receipt.at("archive_warning").get<std::string>();if(warning.empty()||warning.size()>512)return false;
  for(const auto*key:{"manifest","retired_manifest"}){
   if(!receipt.contains(key)||!receipt.at(key).is_object())return false;
   const auto&manifest=receipt.at(key);
   if(manifest.value("version",0)!=1||!manifest.contains("records")||!manifest.at("records").is_object())return false;
  }
  return true;
 }
 static std::string completed_message(const Json&receipt){
  return receipt.value("version",0)==3?"Recovery discarded. Diagnostic archive was not saved: "+receipt.value("archive_warning",""):
   "Recovery discarded. Original records are archived.";
 }
 std::string queued_;std::thread thread_;unsigned long revision_=0;
 bool reject(const std::string&why)const{report_rejection("recovery discard",why);return false;}
 std::string current_reason()const{
  if(!fresh_)return "Status is not fresh.";
  const auto age=std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now()-observed_).count();
  if(age>=2000)return "Status expired: age_ms="+std::to_string(age)+", limit_ms=2000.";
  const auto owner=helper_.value("afc_metadata",Json::object()).value("owner","");
  if(owner!="standalone")return "Standalone ownership required; current="+rejection_value(owner)+".";
  if(helper_.value("recovery_retirement_protocol",0)!=1)return "Unsupported recovery_retirement_protocol="+std::to_string(helper_.value("recovery_retirement_protocol",0))+"; expected=1.";
  return {};
 }
 bool current()const{return fresh_&&Clock::now()-observed_<std::chrono::seconds(2)
  &&helper_.value("afc_metadata",Json::object()).value("owner","")=="standalone"
  &&helper_.value("recovery_retirement_protocol",0)==1;}
 bool bound()const{return current()&&helper_.value("session_id","")==identity_.value("session","");}
 Json post(const std::string&path,const Json&args){
  const auto response=Json::parse(http_.post(path,args.dump()));
  if(response.contains("error")){
   const auto error=response.at("error");
   throw std::runtime_error(error.is_string()?error.get<std::string>():error.value("message","Recovery discard refused"));
  }
  return response.at("result");
 }
 std::string binding_reason()const{
  if(!current())return current_reason();
  if(helper_.value("session_id","")!=identity_.value("session",""))return "Reviewed printer session changed.";
  return "Reviewed operation binding is unavailable.";
 }
 void loop()noexcept{
  for(;;){std::string job;Json identity,request;unsigned long revision;
   {std::unique_lock<std::mutex>lock(mutex_);wake_.wait(lock,[this]{return quit_||!queued_.empty();});if(quit_)return;
    job=queued_;queued_.clear();busy_=true;identity=identity_;request=request_;revision=revision_;}
   try{
    {std::lock_guard<std::mutex>lock(mutex_);
     if(!current()||(job!="readback"&&!bound()))throw std::runtime_error("Recovery discard context changed");
     if(job=="readback")identity["session"]=helper_.at("session_id");}
    if(job=="review"){
     const auto review=post("/printer/wmp/recovery/retire_review",identity);request=review.at("request");
     (void)recovery_retirement_script(identity,request);
     std::lock_guard<std::mutex>lock(mutex_);
     if(revision!=revision_||!bound())throw std::runtime_error("Recovery discard context changed");
     request_=request;result_["state"]="reviewed";result_["request"]=request;
     result_["file"]=review.contains("file")&&review.at("file").is_string()?review.at("file"):Json("Unknown");
     result_["message"]="Discard saved print recovery? This saved print can no longer be resumed. Diagnostic records will be archived if storage permits. The physical print remains.";
    }else{
     if(job=="confirm"){
      const auto script=recovery_retirement_script(identity,request);
      {std::lock_guard<std::mutex>lock(mutex_);if(!bound())throw std::runtime_error("Recovery discard context changed");sent_=true;}
      try{(void)post("/printer/gcode/script",Json{{"script",script}});}catch(...){}
     }
     const auto response=post("/printer/wmp/recovery/retire_result",identity);
     const auto receipt=response.at("result");
     if(response.at("session")!=identity.at("session")||receipt.at("id")!=identity.at("id"))
      throw std::runtime_error("Discard readback changed identity");
     const auto state=receipt.value("state","");
     if(state!="complete"&&state!="unknown"&&state!="superseded")throw std::runtime_error("Invalid discard result");
     if(state!="unknown"&&(!discard_evidence(receipt)||!recovery_hex(receipt.at("fingerprint"),64)
        ||receipt.at("fingerprint")!=request.at("evidence").at("fingerprint")||receipt.at("session")!=request.at("session")))
      throw std::runtime_error("Discard result lacks matching retirement evidence");
     std::lock_guard<std::mutex>lock(mutex_);
     if(!current()||helper_.value("session_id","")!=identity.at("session"))throw std::runtime_error("Discard readback session changed");
     result_["state"]=state;result_["receipt"]=receipt;result_["restored"]=false;
     result_["message"]=state=="complete"?completed_message(receipt):state=="superseded"?
      "Recovery records have changed since this discard. Review the current saved print.":"Discard outcome is not confirmed. Refresh to check; the command will not be repeated.";
    }
   }catch(const std::exception&error){std::lock_guard<std::mutex>lock(mutex_);
    if(revision==revision_){result_["state"]=sent_?"unknown":"refused";result_["message"]=std::string(error.what()).substr(0,512);}
   }catch(...){std::lock_guard<std::mutex>lock(mutex_);if(revision==revision_){result_["state"]=sent_?"unknown":"refused";result_["message"]="Recovery discard response unavailable";}}
   {std::lock_guard<std::mutex>lock(mutex_);busy_=false;}
  }
 }
public:
 explicit RecoveryRetirementWorker(wmp_openace::HttpPort&http):http_(http),thread_([this]{loop();}){}
 ~RecoveryRetirementWorker(){{std::lock_guard<std::mutex>lock(mutex_);quit_=true;}wake_.notify_all();thread_.join();}
 void observe(const Json&helper,bool fresh){
  std::lock_guard<std::mutex>lock(mutex_);helper_=helper;fresh_=fresh;observed_=Clock::now();
  if(!current()||busy_||!queued_.empty()||!identity_.empty())return;
  const auto receipt=helper.value("recovery_retirement",Json::object());
  const auto state=receipt.value("state","");
  if((state!="complete"&&state!="superseded")||!receipt.contains("version")
     ||!discard_evidence(receipt)||!receipt.contains("fingerprint")
     ||!recovery_hex(receipt.at("fingerprint"),64))return;
  for(const auto*key:{"id","session"}){
   if(!receipt.contains(key)||!receipt.at(key).is_string())return;
   const auto s=receipt.at(key).get<std::string>();
   if(s.empty()||s.size()>64||s.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")!=std::string::npos)return;
  }
  identity_={{"id",receipt.at("id")},{"session",receipt.at("session")}};
  request_=identity_;request_["evidence"]={{"fingerprint",receipt.at("fingerprint")}};
  sent_=true;result_={{"id",receipt.at("id")},{"state",state},{"receipt",receipt},{"restored",true},
    {"message",state=="complete"?completed_message(receipt)+" Refresh to verify the current evidence.":"Recorded recovery discard restored. Refresh to verify the current evidence."}};
 }
 // Only read operations are automatic; confirm() remains an explicit action.
 bool auto_read(){
  bool readback=false;
  {std::lock_guard<std::mutex>lock(mutex_);
   if(!current()||busy_||!queued_.empty())return false;
   const auto state=result_.value("state","");
   if(bound()&&(state=="reviewed"||(state=="complete"&&!result_.value("restored",false))))return false;
   const auto now=Clock::now();
   if(automatic_read_at_!=Clock::time_point{}&&now-automatic_read_at_<std::chrono::seconds(5))return false;
   automatic_read_at_=now;
   readback=bound()&&sent_&&(state=="unknown"||result_.value("restored",false));
  }
  return readback?refresh():review();
 }
 bool review(){std::lock_guard<std::mutex>lock(mutex_);
  if(!current())return reject(current_reason());
  if(busy_||!queued_.empty())return reject("Discard delivery pending: busy="+std::to_string(busy_)+", queued="+rejection_value(queued_)+".");
  identity_={{"id","discard_"+std::to_string(std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count())},
             {"session",helper_.at("session_id")}};
  request_=Json::object();sent_=false;result_={{"id",identity_.at("id")},{"state","reviewing"},{"message","Reviewing saved recovery"}};
  queued_="review";wake_.notify_all();return true;
 }
 bool confirm(const std::string&id){std::lock_guard<std::mutex>lock(mutex_);
  if(!bound())return reject(binding_reason());
  if(busy_||!queued_.empty())return reject("Confirmation delivery pending: busy="+std::to_string(busy_)+", queued="+rejection_value(queued_)+".");
  if(sent_)return reject("Confirmation was already sent; duplicate prevented.");
  if(result_.value("state","")!="reviewed")return reject("Confirmation requires reviewed state; current="+rejection_value(result_.value("state",""))+".");
  if(identity_.value("id","")!=id)return reject("Confirmation identity differs from the reviewed operation.");
  result_["state"]="pending";queued_="confirm";wake_.notify_all();return true;
 }
 bool refresh(){std::lock_guard<std::mutex>lock(mutex_);
  if(!current())return reject(current_reason());
  if(busy_||!queued_.empty())return reject("Discard delivery pending: busy="+std::to_string(busy_)+", queued="+rejection_value(queued_)+".");
  if(!sent_)return reject("No discard has been sent for readback.");
  queued_="readback";wake_.notify_all();return true;
 }
 void cancel_review(){std::lock_guard<std::mutex>lock(mutex_);
  if(sent_||queued_=="confirm")return;
  // A late HTTP response belongs to the dismissed view, including errors.
  ++revision_;identity_=request_=result_=Json::object();queued_.clear();automatic_read_at_=Clock::time_point{};
 }
 Json result()const{std::lock_guard<std::mutex>lock(mutex_);auto out=result_;
  out["available"]=current();out["fresh"]=bound();out["delivery_pending"]=busy_||!queued_.empty();
  out["session"]=helper_.value("session_id","");out["restore_error"]=operation_display_text(helper_,"recovery_restore_error","");return out;}
};
}}
