// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "probe_editor_flow.hpp"
#include "../../openace-compat/screen1113/source/client/worker_bridge.hpp"
#include <chrono>
#include <cstdio>
#include <condition_variable>
#include <mutex>
#include <thread>
namespace wmp_ui { namespace native {
// Separate HTTP connection/thread. Only saved-result reads may refresh automatically.
class ProbeEditorWorker {
 using Clock=std::chrono::steady_clock;
 wmp_openace::HttpPort&http_;mutable std::mutex mutex_;std::condition_variable wake_;
 ProbeEditorFlow flow_;Json data_=Json::object(),selected_=Json::object();
 Clock::time_point observed_{},review_checked_{};Json review_context_=Json::object(),review_diagnostics_=Json::object();bool quit_=false,queued_=false,busy_=false;
 std::string refusal_,command_;std::thread thread_;
 wmp_openace::HttpPort*stop_http_=nullptr;std::thread stop_thread_;
 Json stop_request_;bool stop_queued_=false,stop_busy_=false;std::string stop_message_;
 bool refuse(const std::string&why){refusal_=why;report_rejection("probe editor",why);return false;}
 bool can_stop()const{return stop_http_&&fresh()&&stop_request_.is_null()&&!flow_.stop_request(data_).is_null();}
 void stop_loop()noexcept{
  for(;;){Json request;
   {std::unique_lock<std::mutex>lock(mutex_);wake_.wait(lock,[this]{return quit_||stop_queued_;});if(quit_)return;
    stop_queued_=false;request=stop_request_;
    if(!fresh()||flow_.stop_request(data_)!=request){stop_message_="Preparation changed before STOP delivery; no request sent.";continue;}
    stop_busy_=true;}
   bool confirmed=false;
   try{
    const auto reply=Json::parse(stop_http_->post("/printer/wmp/probe_editor/stop",request.dump()));
    const auto result=reply.value("result",Json::object());
    confirmed=!reply.contains("error")&&result.value("session","")==request.value("session","")
      &&result.value("request","")==request.value("request","")&&result.value("state","")=="requested";
   }catch(...){}
   {std::lock_guard<std::mutex>lock(mutex_);stop_busy_=false;
    if(stop_request_==request)stop_message_=confirmed?"Stop requested; waiting for preparation to stop.":"STOP delivery is unconfirmed. Waiting for printer status; it will not be repeated.";}
  }
 }

 static Json binding(const Json&data){
  const auto op=data.value("probe_editor",Json::object());Json value=Json::object();
  for(const auto*key:{"owner","calibration_session","command_generation"})value[key]=data.value(key,Json());
  for(const auto*key:{"available","session","request","state","sequence","token","binding_valid","receipt_state","config_conflict","save_review_protocol","save_retain_protocol","save_review_required","save_review_sequence","save_review_confirmable","save_review","save_review_result"})value["editor"][key]=op.value(key,Json());
  return value;
 }
 bool fresh()const{return data_.value("fresh",false)&&Clock::now()-observed_<std::chrono::seconds(2);}
 bool enqueue(const std::string&command){
  if(command.empty())return false;
  command_=command;selected_=binding(data_);queued_=true;wake_.notify_all();return true;
 }
 void loop()noexcept{
  for(;;){std::string command;
   {std::unique_lock<std::mutex>lock(mutex_);wake_.wait(lock,[this]{return quit_||queued_;});if(quit_)return;
    queued_=false;
    if(!fresh()||binding(data_)!=selected_||flow_.invalidated()){flow_.delivery_refused();continue;}
    busy_=true;command=command_;}
   try{
    const auto reply=Json::parse(http_.post("/printer/gcode/script",Json{{"script",command}}.dump()));
    // A successful HTTP reply is not a motion/calibration receipt.
    if(!reply.is_object()||reply.contains("error")||!reply.contains("result"))throw std::runtime_error("Unconfirmed editor response");
   }catch(...){std::lock_guard<std::mutex>lock(mutex_);flow_.delivery_unknown();}
   {std::lock_guard<std::mutex>lock(mutex_);busy_=false;}
  }
 }
public:
 explicit ProbeEditorWorker(wmp_openace::HttpPort&http,wmp_openace::HttpPort*stop=nullptr):http_(http),stop_http_(stop){
  thread_=std::thread([this]{loop();});
  try{if(stop_http_)stop_thread_=std::thread([this]{stop_loop();});}
  catch(...){{std::lock_guard<std::mutex>lock(mutex_);quit_=true;}wake_.notify_all();thread_.join();throw;}
 }
 ~ProbeEditorWorker(){{std::lock_guard<std::mutex>lock(mutex_);quit_=true;}wake_.notify_all();thread_.join();if(stop_thread_.joinable())stop_thread_.join();}
 ProbeEditorWorker(const ProbeEditorWorker&)=delete;ProbeEditorWorker&operator=(const ProbeEditorWorker&)=delete;
 void observe(const Json&data){
  std::lock_guard<std::mutex>lock(mutex_);const bool pending=flow_.pending();data_=data;observed_=Clock::now();flow_.observe(data_);if(pending&&!flow_.pending())refusal_.clear();
  const auto op=data_.value("probe_editor",Json::object());
  if(data_.value("fresh",false)&&op.value("save_review_required",false)){
   auto evidence=op.value("save_review",Json::object());evidence.erase("token");
   const Json diagnostic={{"session",op.value("session","")},{"request",op.value("request","")},{"error",op.value("error","")},{"evidence",evidence}};
   if(diagnostic!=review_diagnostics_){review_diagnostics_=diagnostic;std::fprintf(stderr,"WM+ probe saved-result evidence: %s\n",diagnostic.dump().c_str());}
  }
 }
 bool begin(const std::string&request,bool admitted){
  std::lock_guard<std::mutex>lock(mutex_);
  refusal_.clear();
  if(queued_||busy_)return refuse("Probe command delivery is pending: queued="+std::to_string(queued_)+", busy="+std::to_string(busy_)+".");
  if(stop_queued_||stop_busy_)return refuse("Probe STOP delivery is pending: queued="+std::to_string(stop_queued_)+", busy="+std::to_string(stop_busy_)+".");
  if(!fresh())return refuse("Probe status is unavailable or expired; maximum age_ms=2000.");
  const auto command=flow_.begin(data_,request,admitted);
  if(command.empty())return refuse(flow_.message());
  stop_request_=Json();stop_message_.clear();
  return enqueue(command);
 }
 bool stop(){
  std::lock_guard<std::mutex>lock(mutex_);
  refusal_.clear();
  if(!stop_http_)return refuse("Probe STOP transport is unavailable.");
  if(!fresh())return refuse("Probe STOP requires fresh status; maximum age_ms=2000.");
  if(!stop_request_.is_null())return refuse("Probe STOP was already requested.");
  if(flow_.stop_request(data_).is_null())return refuse(flow_.stop_reason(data_));
  stop_request_=flow_.stop_request(data_);stop_queued_=true;stop_message_="Sending STOP.";wake_.notify_all();return true;
 }
 bool act(const std::string&action,const std::string&step=""){
  std::lock_guard<std::mutex>lock(mutex_);
  refusal_.clear();
  if(queued_||busy_)return refuse("Probe command delivery is pending: queued="+std::to_string(queued_)+", busy="+std::to_string(busy_)+".");
  if(!fresh())return refuse("Probe action requires fresh status; maximum age_ms=2000.");
  const auto command=flow_.act(data_,action,step);
  if(command.empty())return refuse(flow_.message());
  return enqueue(command);
 }
 // Runtime calls this only while the editor is visible. Reuse a successful
 // read, and bound failures/context changes to one attempt per five seconds.
 bool auto_review(){
  std::lock_guard<std::mutex>lock(mutex_);
  if(!fresh()||queued_||busy_||stop_queued_||stop_busy_)return false;
  const auto op=data_.value("probe_editor",Json::object());
  if(!op.value("save_review_required",false)||data_.value("owner","")!="standalone")return false;
  auto evidence=op.value("save_review",Json::object());evidence.erase("token");
  Json context={{"session",data_.value("calibration_session","")},{"request",op.value("request","")},{"evidence",evidence}};
  if(context==review_context_&&op.value("save_review_confirmable",false)&&!flow_.pending())return false;
  if(Clock::now()-review_checked_<std::chrono::seconds(5))return false;
  auto candidate=flow_;
  if(!candidate.release_pending_review())return false;
  const auto command=candidate.act(data_,"REVIEW");
  if(command.empty())return false;
  flow_=candidate;review_context_=context;review_checked_=Clock::now();refusal_.clear();
  return enqueue(command);
 }
 Json result()const{
  std::lock_guard<std::mutex>lock(mutex_);
  Json actions=Json::object();
  // Ask a copy of the same controller used for dispatch. Rendering cannot
  // advance sequence state or enqueue a command.
  for(const auto*action:{"JOG","ACCEPT","ABORT","SAVE","DISCARD","KEEP","REVIEW","ACK","RETAIN"}){
   auto preview=flow_;
   const auto conflict=data_.value("probe_editor",Json::object()).value("config_conflict",Json());
   const auto review=conflict.is_object()?conflict.value("review",""):"";
   const auto save_review=data_.value("probe_editor",Json::object()).value("save_review",Json::object()).value("token","");
   actions[action]=fresh()&&!queued_&&!busy_
     &&!preview.act(data_,action,std::string(action)=="JOG"?"0.1":std::string(action)=="KEEP"?review:(std::string(action)=="ACK"||std::string(action)=="RETAIN")?save_review:"").empty();
  }
  auto start_preview=flow_;
  const auto current_request=data_.value("probe_editor",Json::object()).value("request","");
  actions["START"]=fresh()&&!queued_&&!busy_&&!stop_queued_&&!stop_busy_
    &&!start_preview.begin(data_,std::string(32,current_request==std::string(32,'e')?'f':'e'),true).empty();
  actions["STOP"]=can_stop();
  const auto op=data_.value("probe_editor",Json::object());
  const bool stopping=fresh()&&(op.value("state","")=="preparing"||op.value("state","")=="stopping")&&op.value("stop_requested",false);
  const bool terminal=op.value("state","")=="aborted"||op.value("state","")=="failed"||op.value("state","")=="unknown";
  const std::string stop_message=terminal?"":stopping?"Stop requested; waiting for preparation to stop.":stop_message_;
  return {{"stop_delivery_pending",stop_queued_||stop_busy_},{"stop_message",stop_message},
          {"delivery_pending",queued_||busy_},{"pending",flow_.pending()},
          {"invalidated",flow_.invalidated()},{"message",refusal_.empty()?flow_.message():refusal_},
          {"fresh",fresh()},{"editor",data_.value("probe_editor",Json::object())},
          {"actions",actions}};
 }
};
}}
