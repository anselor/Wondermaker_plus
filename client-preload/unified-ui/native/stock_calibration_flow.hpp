// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../model.hpp"
namespace wmp_ui { namespace native {
// GUI-thread state. A vendor worker's navigation request is not proof that its
// queued commands succeeded. Only the backend's matching M400 acknowledgement
// permits continuation. Errors remain latched for this touchscreen process.
class StockCalibrationFlow {
 bool started_=false,sent_=false;
 std::string destination_,token_,session_,failure_;
public:
 static bool target(const char*name){return name&&(std::string(name)=="guide_calibrating_page"||std::string(name)=="guide_filament_page"||std::string(name)=="guide_calibration_finish_page");}
 bool request(const std::string&destination,const std::string&token){
  if(!target(destination.c_str()))return false;
  started_=true;
  if(!destination_.empty()||!failure_.empty())return false;
  destination_=destination;token_=token;sent_=false;session_.clear();return true;
 }
 void observe(const Json&data){
  if(!started_||!data.value("fresh",false))return;
  auto error=data.value("calibration_failed","");
  if(failure_.empty()&&!error.empty())failure_=error.substr(0,512);
  if(failure_.empty()&&sent_&&!data.value("calibration_session","").empty()&&data.value("calibration_session","")!=session_)
   failure_="Printer restarted before calibration completion was confirmed.";
 }
 bool needs_checkpoint(const Json&data)const{return !destination_.empty()&&failure_.empty()&&!sent_&&data.value("fresh",false)&&!data.value("calibration_session","").empty()&&!data.value("calibration_active",false);}
 std::string command()const{return "_WMP_CALIBRATION_COMMAND HEX=4d343030 TOKEN="+token_;}
 void sent(const Json&data){sent_=true;session_=data.value("calibration_session","");}
 void send_failed(){if(failure_.empty())failure_="Could not request calibration completion status.";}
 std::string complete(const Json&data){
  observe(data);
  if(!sent_||!failure_.empty()||!data.value("fresh",false)||data.value("calibration_active",false)||data.value("calibration_checkpoint","")!=token_)return {};
  auto destination=destination_;destination_.clear();sent_=false;return destination;
 }
 bool blocked()const{return !failure_.empty()||!destination_.empty();}
 std::string message()const{
  if(!failure_.empty())return "Calibration stopped.\n\n"+failure_+"\n\nRestart the printer to retry setup.";
  if(!destination_.empty())return "Finishing calibration...";
  return {};
 }
};
}}
