// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "preview.hpp"
#include <functional>
#include "../../openace-compat/screen1113/source/client/worker_bridge.hpp"
namespace wmp_ui { namespace native {
// Blocking I/O adapter for a dedicated copy worker, never the LVGL/status loop.
// Copy is not print admission. The caller must open the confirmed local file
// for metadata/mapping review. No G-code, stock copy callback or auto-start.
class UsbImport {
 Json result_;std::string source_,directory_,destination_;
 std::int64_t size_=0;bool attempted_=false,prepared_=false;
 static bool matches(const std::string&body,const std::string&action,const std::string&path,std::int64_t size=-1){
  if(body.size()>65536)return false;
  const auto response=Json::parse(body);if(response.contains("error"))return false;
  const auto result=response.at("result"),item=result.at("item");
  return result.value("action","")==action&&item.value("root","")=="gcodes"&&
   item.value("path","")==path&&(size<0||(item.contains("size")&&item["size"].is_number_integer()&&item["size"].get<std::int64_t>()==size));
 }
public:
 // nonce must be a fresh 128-bit random hex value supplied by the caller.
 // Atomic mkdir, not a prior existence check, reserves the destination.
 bool begin(const Json&data,const std::string&usb_relative,const std::string&nonce,std::int64_t size){
  auto refuse=[](const std::string&why){report_rejection("USB import",why);return false;};
  if(attempted_)return refuse("Copy was already attempted; duplicate prevented.");
  if(prepared_)return refuse("Copy already has a reviewed source.");
  (void)data; // Filesystem operations do not depend on printer telemetry.
  if(!preview_path(usb_relative))return refuse("USB source path is invalid.");
  if(size<=0)return refuse("USB source size must be positive; size="+std::to_string(size)+".");
  if(nonce.size()!=32||nonce.find_first_not_of("0123456789abcdef")!=std::string::npos)return refuse("USB copy nonce must be 32 lowercase hexadecimal characters.");
  const auto base=usb_relative.substr(usb_relative.find_last_of('/')+1);
  directory_="WM_USB_"+nonce;destination_=directory_+"/"+base;
  if(!preview_path(destination_))return refuse("USB destination path is invalid.");
  prepared_=true;source_="gcodes/USB/"+usb_relative;size_=size;
  result_={{"state","ready"},{"source",source_},{"destination",destination_},{"message","Copy to printer, then review the local file."}};
  return true;
 }
 const Json&result()const{return result_;}
 void run(wmp_openace::HttpPort&http,const Json&,const std::function<bool()>&source_current={}){
  if(attempted_||!prepared_)return;
  attempted_=true; // Never repeat an uncertain mkdir/copy request.
  result_["state"]="copying";
  bool reserved_here=false;
  try{
   const auto reserved=http.post("/server/files/directory",Json{{"path","gcodes/"+directory_}}.dump());
   if(!matches(reserved,"create_dir",directory_))throw std::runtime_error("Unconfirmed destination reservation");
   reserved_here=true;
   const auto copied=http.post("/server/files/copy",Json{{"source",source_},{"dest","gcodes/"+destination_}}.dump());
   if(!matches(copied,"create_file",destination_,size_))throw std::runtime_error("Unconfirmed destination copy");
   result_["state"]="copied";result_["message"]="Copied. Review the local file before starting.";
  }catch(...){
   // A lost copy reply is not a reason to repeat the write. Read back only our
   // confirmed private reservation, with the original USB identity still live.
   if(reserved_here&&source_current)try{
    const auto body=http.get(metadata_query(destination_));
    if(body.size()>65536)throw std::runtime_error("Oversized destination metadata");
    const auto response=Json::parse(body);const auto item=response.at("result");
    if(!response.contains("error")&&item.value("filename","")==destination_&&
       item.contains("size")&&item["size"].is_number_integer()&&item["size"].get<std::int64_t>()==size_&&source_current()){
     result_["state"]="copied";result_["message"]="Copied file confirmed at the destination. Review the local file before starting.";return;
    }
   }catch(...){}
   result_["state"]="unknown";result_["message"]="Copy could not be confirmed. No copy was repeated or print started. You can close this preview and select a USB file again; a new copy uses a new destination.";
  }
 }
};
}}
