// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "usb_import.hpp"
#include "usb_source.hpp"
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <thread>
namespace wmp_ui { namespace native {
// Runtime-lifetime worker: never construct/destroy it for each preview.
// The transport must outlive this object. Destruction joins at application
// shutdown; UI navigation only stops reading the old origin's result.
class UsbCopyWorker {
 wmp_openace::HttpPort&http_;
 mutable std::mutex mutex_;std::condition_variable wake_;
 Json result_=Json::object();
 std::unique_ptr<UsbImport>queued_;
 std::uint64_t origin_=0,inspection_origin_=0;bool stopping_=false,running_=false,inspection_queued_=false;
 std::string inspection_root_,inspection_path_,copy_root_;Json inspected_=Json::object(),copy_identity_=Json::object();
 std::thread thread_; // Start only after every field inspected by loop exists.
 void loop()noexcept{
  for(;;){
   std::unique_ptr<UsbImport>copy;Json identity;std::uint64_t origin;bool inspection;std::string root,path;
   {
    std::unique_lock<std::mutex>lock(mutex_);
    wake_.wait(lock,[this]{return stopping_||bool(queued_)||inspection_queued_;});
    if(stopping_)return;
    inspection=inspection_queued_;inspection_queued_=false;running_=true;
    if(inspection){origin=inspection_origin_;root=inspection_root_;path=inspection_path_;}
    else{copy=std::move(queued_);origin=origin_;root=copy_root_;identity=copy_identity_;}
    if(!inspection)result_["state"]="copying";
   }
   Json result;
   try{
    if(inspection)result=inspect_usb_source(root,path);
    else{
     bool unchanged=true;
     if(!identity.empty()){
      try{unchanged=inspect_usb_source(root,identity.at("path").get<std::string>())==identity;}catch(...){unchanged=false;}
     }
     if(!unchanged)result={{"state","refused"},{"message","USB file changed or disappeared; reopen its preview."}};
     else{copy->run(http_,Json::object(),[root,identity]{
      return !identity.empty()&&inspect_usb_source(root,identity.at("path").get<std::string>())==identity;
     });result=copy->result();}
    }
   }
   catch(...){result={{"state",inspection?"unavailable":"unknown"},{"message",inspection?"USB file could not be inspected.":"Copy outcome is unknown; inspect the destination before retrying."}};}
   {
    std::lock_guard<std::mutex>lock(mutex_);
    if(inspection){if(inspection_origin_==origin)inspected_=std::move(result);}
    else if(origin_==origin)result_=std::move(result);
    running_=false;
   }
  }
 }
public:
 explicit UsbCopyWorker(wmp_openace::HttpPort&http):http_(http),thread_([this]{loop();}){}
 ~UsbCopyWorker(){
  {std::lock_guard<std::mutex>lock(mutex_);stopping_=true;queued_.reset();}
  wake_.notify_one();if(thread_.joinable())thread_.join();
 }
 UsbCopyWorker(const UsbCopyWorker&)=delete;
 UsbCopyWorker&operator=(const UsbCopyWorker&)=delete;
 bool inspect(std::uint64_t origin,const std::string&root,const std::string&path){
  if(!preview_path(path)){report_rejection("USB inspect","USB source path is invalid.");return false;}
  if(root.empty()||root.front()!='/'){report_rejection("USB inspect","USB root must be an absolute path.");return false;}
  std::lock_guard<std::mutex>lock(mutex_);
  if(stopping_||queued_||running_||inspection_queued_||origin<=origin_||origin<=inspection_origin_){
   report_rejection("USB inspect","stopping="+std::to_string(stopping_)+", copy_queued="+std::to_string(bool(queued_))+", running="+std::to_string(running_)+", inspection_queued="+std::to_string(inspection_queued_)+", origin="+std::to_string(origin)+", previous_copy_origin="+std::to_string(origin_)+", previous_inspection_origin="+std::to_string(inspection_origin_)+", result.state="+rejection_value(result_.value("state","")));return false;
  }
  inspection_origin_=origin;inspection_root_=root;inspection_path_=path;
  inspected_={{"state","inspecting"},{"path",path}};inspection_queued_=true;wake_.notify_one();return true;
 }
 void observe(const Json&){} // Copy ownership is filesystem-based, not printer status.
 bool submit(std::uint64_t origin,const Json&reviewed,const std::string&path,
             const std::string&nonce,std::int64_t size){
  auto copy=std::unique_ptr<UsbImport>(new UsbImport);
  if(!copy->begin(reviewed,path,nonce,size))return false;
  std::lock_guard<std::mutex>lock(mutex_);
  // Origins are monotonic preview generations. A new explicit preview may
  // copy to a new reservation; repeated taps never repeat the old request.
  if(stopping_||queued_||running_||inspection_queued_||origin<=origin_){
   report_rejection("USB copy","stopping="+std::to_string(stopping_)+", copy_queued="+std::to_string(bool(queued_))+", running="+std::to_string(running_)+", inspection_queued="+std::to_string(inspection_queued_)+", origin="+std::to_string(origin)+", previous_copy_origin="+std::to_string(origin_)+", result.state="+rejection_value(result_.value("state","")));return false;
  }
  copy_root_.clear();copy_identity_=Json::object();
  if(origin==inspection_origin_){
   if(inspected_.value("state","")!="ready"){report_rejection("USB copy","Inspection is not ready: state="+rejection_value(inspected_.value("state","")));return false;}
   if(inspected_.value("path","")!=path){report_rejection("USB copy","Source path differs from the inspected file.");return false;}
   if(inspected_.value("size",std::int64_t(0))!=size){report_rejection("USB copy","Source size changed: reviewed="+std::to_string(size)+", inspected="+std::to_string(inspected_.value("size",std::int64_t(0))));return false;}
   copy_root_=inspection_root_;copy_identity_=inspected_;
  }else if(origin<inspection_origin_){report_rejection("USB copy","Preview origin was superseded: selected="+std::to_string(origin)+", inspected="+std::to_string(inspection_origin_));return false;}
  origin_=origin;result_=copy->result();result_["state"]="queued";queued_=std::move(copy);
  wake_.notify_one();return true;
 }
 Json result(std::uint64_t origin)const{
  std::lock_guard<std::mutex>lock(mutex_);
  if(origin&&origin==origin_)return result_;
  return origin&&origin==inspection_origin_?inspected_:Json::object();
 }
 Json unresolved()const{
  std::lock_guard<std::mutex>lock(mutex_);
  return queued_||running_?result_:Json::object();
 }
};
}}
