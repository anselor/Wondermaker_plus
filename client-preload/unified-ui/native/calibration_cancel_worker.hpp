// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../model.hpp"
#include "../../openace-compat/screen1113/source/client/worker_bridge.hpp"
#include <condition_variable>
#include <mutex>
#include <thread>
namespace wmp_ui { namespace native {
// Shared bounded connection for calibration and identification Cancel.
// No polling, G-code fallback, retry or extra worker thread.
class CalibrationCancelWorker {
 wmp_openace::HttpPort&http_;mutable std::mutex mutex_;std::condition_variable wake_;
 bool quit_=false,queued_=false,busy_=false,acknowledged_=false,identification_=false;
 Json request_=Json::object();std::string message_;std::thread thread_;
 static bool valid(const Json&r,bool identification){
  if(!r.is_object()||r.size()!=(identification?2u:3u))return false;
  for(const auto*key:{"session","request"})if(!r.contains(key)||!r[key].is_string()||r[key].get<std::string>().size()!=32||r[key].get<std::string>().find_first_not_of("0123456789abcdef")!=std::string::npos)return false;
  if(identification)return true;
  if(!r.contains("ticket")||!r["ticket"].is_string())return false;
  const auto t=r["ticket"].get<std::string>();return !t.empty()&&t.size()<=256&&t[0]!='0'&&t.find_first_not_of("0123456789")==std::string::npos;
 }
 void loop()noexcept{
  for(;;){Json request;bool identification;
   {std::unique_lock<std::mutex>lock(mutex_);wake_.wait(lock,[this]{return quit_||queued_;});if(quit_)return;
    queued_=false;busy_=true;request=request_;identification=identification_;}
   bool confirmed=false;
   try{const auto reply=Json::parse(http_.post(identification?"/printer/wmp/identification/cancel":"/printer/wmp/calibration/cancel",request.dump()));
    const auto result=reply.value("result",Json::object());
    confirmed=!reply.contains("error")&&result.value("session","")==request.value("session","")&&result.value("request","")==request.value("request","")
      &&(identification||result.value("ticket","")==request.value("ticket",""))&&result.value("state","")=="requested";
   }catch(...){}
   {std::lock_guard<std::mutex>lock(mutex_);busy_=false;acknowledged_=confirmed;
    message_=confirmed?"Cancellation requested. Waiting for the printer to stop.":"Cancellation delivery is unconfirmed. Waiting for printer status; no retry was sent.";}
  }
 }
public:
 explicit CalibrationCancelWorker(wmp_openace::HttpPort&http):http_(http),thread_([this]{loop();}){}
 ~CalibrationCancelWorker(){{std::lock_guard<std::mutex>lock(mutex_);quit_=true;}wake_.notify_all();thread_.join();}
 bool enqueue(const Json&r,bool identification){
  if(!valid(r,identification))return false;
  std::lock_guard<std::mutex>lock(mutex_);
  if(r==request_&&identification==identification_)return true;
  if(quit_||queued_||busy_)return false;
  request_=r;identification_=identification;queued_=true;acknowledged_=false;message_="Requesting cancellation...";wake_.notify_one();return true;
 }
 bool request(const Json&r){return enqueue(r,false);}
 bool request_identification(const Json&r){return enqueue(r,true);}
 Json result()const{std::lock_guard<std::mutex>lock(mutex_);return {{"binding",request_},{"kind",identification_?"identification":"calibration"},{"delivery_pending",queued_||busy_},{"acknowledged",acknowledged_},{"message",message_}};}
};
}}
