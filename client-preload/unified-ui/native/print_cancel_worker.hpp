// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../../openace-compat/screen1113/source/client/worker_bridge.hpp"
#include "../model.hpp"
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>
namespace wmp_ui { namespace native {
// Dedicated reactor-intent transport. Never waits behind a service command's
// HTTP transport. Standalone explicit Stop can fall back to package CANCEL_PRINT intent.
class PrintCancelWorker {
 using Clock=std::chrono::steady_clock;
 wmp_openace::HttpPort&http_;mutable std::mutex mutex_;std::condition_variable wake_;
 Json helper_=Json::object(),stats_=Json::object(),selection_=Json::object(),result_=Json::object();
 Clock::time_point observed_{};bool fresh_=false,quit_=false,queued_=false,busy_=false,matched_=false,sent_=false;
 std::string refusal_,last_owner_;bool fallback_enabled_=false,intent_queued_=false;
 long long generation_=0;unsigned serial_=0;std::thread thread_;
 bool current()const{return fresh_&&Clock::now()-observed_<std::chrono::seconds(2)
  &&helper_.value("afc_metadata",Json::object()).value("owner","")=="standalone"
  &&helper_.value("print_cancel_protocol",0)==1;}
 bool selected_current()const{return current()&&helper_.value("session_id","")==selection_.value("session","")
  &&helper_.value("command_generation",0LL)==generation_&&stats_.value("filename","")==selection_.value("file","")
  &&(stats_.value("state","")=="printing"||stats_.value("state","")=="paused");}
 std::string selection_reason()const{
  if(!fresh_)return "Cancellation status is not fresh.";
  const auto age=std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now()-observed_).count();
  if(age>=2000)return "Cancellation status expired: age_ms="+std::to_string(age)+", limit_ms=2000.";
  const auto owner=helper_.value("afc_metadata",Json::object()).value("owner","");
  if(owner!="standalone")return "Cancellation owner changed: current="+rejection_value(owner)+".";
  if(helper_.value("print_cancel_protocol",0)!=1)return "Unsupported print_cancel_protocol="+std::to_string(helper_.value("print_cancel_protocol",0))+"; expected=1.";
  if(helper_.value("session_id","")!=selection_.value("session",""))return "Cancellation printer session changed.";
  if(helper_.value("command_generation",0LL)!=generation_)return "Cancellation command generation changed: reviewed="+std::to_string(generation_)+", current="+std::to_string(helper_.value("command_generation",0LL))+".";
  if(stats_.value("filename","")!=selection_.value("file",""))return "Cancellation print filename changed.";
  return "Cancellation requires printing or paused state; current="+rejection_value(stats_.value("state",""))+".";
 }
 bool matches(const Json&r)const{return r.is_object()&&!selection_.empty()
  &&r.value("id","")==selection_.value("id","")&&r.value("session","")==selection_.value("session","")
  &&r.value("file","")==selection_.value("file","");}
 bool record(const Json&r){
  if(!matches(r))return false;
  const auto state=r.value("state","");if(state!="pending"&&state!="unknown"&&state!="complete")return false;
  // A delayed HTTP pending reply must not replace a terminal status receipt.
  if(matched_&&result_.value("state","")=="complete"&&state!="complete")return true;
  matched_=true;result_=r;return true;
 }
 void loop()noexcept{
  for(;;){Json selected;bool sent=false,intent=false;std::string rejected;
   {std::unique_lock<std::mutex>lock(mutex_);wake_.wait(lock,[this]{return quit_||queued_;});if(quit_)return;
    queued_=false;busy_=true;selected=selection_;intent=intent_queued_;intent_queued_=false;}
   try{
    if(intent){
     bool allowed=false;{std::lock_guard<std::mutex>lock(mutex_);allowed=last_owner_=="standalone";}
     if(allowed)send_intent();
     std::lock_guard<std::mutex>lock(mutex_);if(!allowed){result_["state"]="refused";result_["message"]="Cancellation owner changed before dispatch; no cancellation sent.";}busy_=false;continue;
    }
    {std::lock_guard<std::mutex>lock(mutex_);if(!selected_current()){rejected=selection_reason();throw std::runtime_error("Print changed before review");}}
    const auto reply=Json::parse(http_.post("/printer/wmp/print/cancel_review",selected.dump()));
    if(reply.contains("error"))throw std::runtime_error("Cancellation review refused");
    auto request=reply.at("result").at("request");
    if(!request.is_object()||request.size()!=4)throw std::runtime_error("Invalid cancellation review");
    for(const auto*key:{"id","session","file"})if(request.at(key)!=selected.at(key))throw std::runtime_error("Cancellation review changed");
    const auto token=request.at("token").get<std::string>();
    if(token.size()!=32||token.find_first_not_of("0123456789abcdef")!=std::string::npos)throw std::runtime_error("Invalid cancellation token");
    {std::lock_guard<std::mutex>lock(mutex_);if(!selected_current()){rejected=selection_reason();throw std::runtime_error("Print changed before cancellation");}
     sent=sent_=true;result_["message"]="Requesting print cancellation";}
    const auto response=Json::parse(http_.post("/printer/wmp/print/cancel",request.dump()));
    std::lock_guard<std::mutex>lock(mutex_);
    if(!matched_&&!record(response.value("result",Json::object()))){result_["state"]="unknown";result_["message"]="Waiting for recorded cancellation result";}
   }catch(...){std::lock_guard<std::mutex>lock(mutex_);if(!matched_){
    result_["state"]=sent?"unknown":"refused";
    result_["message"]=sent?"Cancellation delivery outcome unknown; request will not be repeated.":"Cancellation review failed or changed; no cancellation sent.";}}
   bool fallback=false;{std::lock_guard<std::mutex>lock(mutex_);fallback=fallback_enabled_&&!sent&&last_owner_=="standalone";}
   if(fallback){send_intent();rejected.clear();}
   {std::lock_guard<std::mutex>lock(mutex_);if(!rejected.empty()){report_rejection("cancellation dispatch",rejected);if(!matched_)result_["message"]=rejected+" No cancellation sent.";}busy_=false;}
  }
 }
 void send_intent(){
  std::string message="Cancellation intent sent. Waiting for printer status.";
  try{const auto reply=Json::parse(http_.post("/printer/gcode/script",Json{{"script","CANCEL_PRINT"}}.dump()));
   if(reply.contains("error"))message="Cancellation returned an error; check whether the printer stopped.";
  }catch(...){message="Cancellation delivery is unconfirmed. Check the printer; press Stop again if needed.";}
  std::lock_guard<std::mutex>lock(mutex_);sent_=true;result_["state"]="unknown";result_["message"]=message;
 }
public:
 explicit PrintCancelWorker(wmp_openace::HttpPort&http,bool fallback=false):http_(http),fallback_enabled_(fallback),thread_([this]{loop();}){}
 ~PrintCancelWorker(){{std::lock_guard<std::mutex>lock(mutex_);quit_=true;}wake_.notify_all();thread_.join();}
 PrintCancelWorker(const PrintCancelWorker&)=delete;PrintCancelWorker&operator=(const PrintCancelWorker&)=delete;
 void observe(const Json&helper,const Json&stats,bool fresh){
  std::lock_guard<std::mutex>lock(mutex_);helper_=helper;stats_=stats;fresh_=fresh;observed_=Clock::now();
  const auto owner=helper.value("afc_metadata",Json::object()).value("owner","");if(fresh&&!owner.empty())last_owner_=owner;
  if(sent_&&current())record(helper.value("print_cancel",Json::object()));
 }
 bool request(){
  if(select())return true;
  std::lock_guard<std::mutex>lock(mutex_);
  if(!fallback_enabled_||last_owner_!="standalone")return false;
  if(queued_||busy_)return true;
  result_={{"state","pending"},{"message","Sending cancellation intent"}};
  matched_=sent_=false;intent_queued_=queued_=true;wake_.notify_all();return true;
 }
 bool select(){
  std::lock_guard<std::mutex>lock(mutex_);
  const auto state=result_.value("state","");
  // Repeated native clicks reopen the same pending/uncertain result.
  refusal_.clear();
  auto reject=[this](const std::string&why){refusal_=why;report_rejection("print cancel",why);return false;};
  if(queued_||busy_||state=="pending")return !selection_.empty()||reject("Cancellation is unresolved but has no retained selection.");
  if(!fresh_)return reject("Cancellation status is not fresh.");
  const auto age=std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now()-observed_).count();
  if(age>=2000)return reject("Cancellation status expired: age_ms="+std::to_string(age)+", limit_ms=2000.");
  const auto owner=helper_.value("afc_metadata",Json::object()).value("owner","");
  if(owner!="standalone")return reject("Cancellation requires standalone ownership; current owner="+rejection_value(owner)+".");
  if(helper_.value("print_cancel_protocol",0)!=1)return reject("Unsupported print_cancel_protocol="+std::to_string(helper_.value("print_cancel_protocol",0))+"; expected=1.");
  if(serial_>=1024)return reject("Cancellation request limit reached: count="+std::to_string(serial_)+", limit=1024.");
  const auto session=helper_.value("session_id","");const auto file=stats_.value("filename","");
  if(session.empty()||session.size()>64||session.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")!=std::string::npos)return reject("Cancellation session is missing or malformed.");
  if(file.empty()||file.size()>4096)return reject("Cancellation filename is missing or exceeds 4096 bytes.");
  const auto print_state=stats_.value("state","");
  if(print_state!="printing"&&print_state!="paused")return reject("Cancellation requires printing or paused state; current="+rejection_value(print_state)+".");
  const auto held=helper_.value("print_cancel",Json::object()).value("state","");
  if(held=="pending")return reject("Previous backend cancellation is unresolved: state="+rejection_value(held)+".");
  if(!selection_.empty()&&selection_.value("session","")==session&&selection_.value("file","")==file
     &&generation_==helper_.value("command_generation",0LL)&&state=="complete")return true;
  generation_=helper_.value("command_generation",0LL);
  selection_={{"id","cancel_"+std::to_string(std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count())+"_"+std::to_string(++serial_)},
              {"session",session},{"file",file}};
  result_=selection_;result_["state"]="pending";result_["message"]="Reviewing print cancellation";
  matched_=sent_=false;queued_=true;wake_.notify_all();return true;
 }
 std::string refusal()const{std::lock_guard<std::mutex>lock(mutex_);return refusal_;}
 std::string owner()const{std::lock_guard<std::mutex>lock(mutex_);
  return last_owner_.empty()?"unknown":last_owner_;}
 Json result()const{std::lock_guard<std::mutex>lock(mutex_);auto r=result_;r["delivery_pending"]=queued_||busy_;
  r["fresh"]=current()&&helper_.value("session_id","")==selection_.value("session","");return r;}
};
}}
