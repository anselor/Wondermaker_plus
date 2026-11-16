// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../model.hpp"
#include <random>
namespace wmp_ui { namespace native {
class StockIdentificationFlow {
 bool sent_=false,restart_sent_=false;
 std::string session_,failure_,request_,refusal_;
public:
 void observe(const Json&data){
  if(!data.value("fresh",false))return;
  const auto current=data.value("calibration_session","");
  const auto op=data.value("identification",Json::object());
  const auto receipt=op.value("request_result",Json::object());
  if(sent_&&!restart_sent_&&current==session_&&receipt.value("session","")==session_&&receipt.value("request","")==request_){
   if(receipt.value("state","")=="refused"&&op.value("state","")=="idle"){
    sent_=false;failure_.clear();refusal_=receipt.value("error","Identification was refused.");
   }else if(receipt.value("state","")=="failed")failure_=receipt.value("error","Identification stopped.");
  }
  if(sent_&&!current.empty()&&current!=session_){
   if(restart_sent_){sent_=restart_sent_=false;session_.clear();failure_.clear();}
   else failure_="Printer restarted before the identification result was confirmed.";
  }
 }
 bool can_start(const Json&data,bool allowed)const{
  if(restart_sent_||!allowed||!data.value("fresh",false)||data.value("owner","")!="standalone")return false;
  const auto op=data.value("identification",Json::object());
  if(op.value("protocol",0)!=2||(op.value("state","")!="idle"&&op.value("state","")!="failed")||data.value("calibration_session","").empty())return false;
  if(sent_&&failure_.empty()&&session_==data.value("calibration_session","")&&op.value("state","")=="idle")return false;
  return true;
 }
 bool start(const Json&data,bool allowed){
  if(!can_start(data,allowed))return false;
  auto session=data.value("calibration_session","");std::string request;
  std::random_device random;constexpr char hex[]="0123456789abcdef";
  for(int i=0;i<32;++i)request+=hex[random()&15];
  session_=std::move(session);request_=std::move(request);sent_=true;refusal_.clear();failure_.clear();
  return true;
 }
 std::string command()const{return "_WMP_IDENTIFY_HEADS SESSION="+session_+" REQUEST="+request_;}
 void send_failed(){failure_="Identification result unavailable. Check printer status.";}
 bool can_restart(const Json&data)const{
  const auto op=data.value("identification",Json::object());
  if(sent_&&!restart_sent_){
   const auto receipt=op.value("request_result",Json::object());
   if(receipt.value("session","")!=session_||receipt.value("request","")!=request_||receipt.value("state","")!="complete")return false;
  }
  return !restart_sent_&&failure_.empty()&&data.value("fresh",false)&&data.value("owner","")=="standalone"&&!data.value("calibration_session","").empty()&&op.value("protocol",0)==2&&op.value("state","")=="complete"&&op.value("restart_required",false);
 }
 bool restart(const Json&data){if(!can_restart(data))return false;restart_sent_=sent_=true;session_=data.value("calibration_session","");return true;}
 std::string message(const Json&data)const{
  if(!failure_.empty())return failure_;
  if(!refusal_.empty())return refusal_;
  if(restart_sent_)return "Restarting to apply head mapping...";
  if(!data.value("fresh",false))return "Waiting for printer status...";
  const auto op=data.value("identification",Json::object());
  if(op.value("protocol",0)!=2)return "Head identification is unavailable. Update WM+.";
  const auto state=op.value("state","");
  if(state=="failed")return op.value("failure","Identification stopped.");
  if(state=="complete")return "Head mapping saved. Restart to apply.";
  if(sent_&&state=="idle")return "Starting head identification...";
  if(state=="running"||state=="pending")return "Identifying heads...";
  return "Dock all heads and release the carriage.\nSTART homes and identifies the heads.";
 }
 bool blocks_navigation(const Json&data)const{
  if(restart_sent_)return true;
  if(!sent_||!failure_.empty()||session_!=data.value("calibration_session",""))return false;
  const auto op=data.value("identification",Json::object());
  const auto state=op.value("state","idle");
  const auto receipt=op.value("request_result",Json::object());
  // Observing another caller's operation does not reserve this page.
  if((state=="running"||state=="pending")&&!receipt.value("request","").empty()&&
     (receipt.value("request","")!=request_||receipt.value("session","")!=session_))return false;
  return state=="running"||state=="pending"||state=="idle";
 }
 bool pending()const{return sent_||restart_sent_;}
};
}}
