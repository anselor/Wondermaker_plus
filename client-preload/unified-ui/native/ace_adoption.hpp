// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "ace_unit_preview.hpp"
namespace wmp_ui { namespace native {
// Confirmation binds the observed device context; submission is one-shot. The
// delivery worker still validates the typed command before sending it.
class AceAdoption {
 Json candidate_,context_,operation_;
public:
 void clear(){candidate_=Json();context_=Json();operation_=Json();}
 bool active()const{return candidate_.is_object();}
 const Json&candidate()const{return candidate_;}const Json&operation()const{return operation_;}
 const Json&context()const{return context_;}
 bool begin(const Json&data,const std::string&id){
  if(pending()||!data.value("fresh",false)||data.value("owner","")!="openace")return false;
  for(const auto&c:data.value("candidates",Json::array()))if(c.value("id","")==id){candidate_=c;context_=data;operation_=Json();return true;}
  return false;
 }
 bool pending()const {return operation_.is_object()&&(operation_.value("state","")=="pending"||operation_.value("state","")=="unknown");}
 std::string unavailable(const Json&data)const{
  if(!active())return "This discovery is no longer available.";
  if(!operation_.is_null())return "A request was already submitted; check its result.";
  if(!data.value("fresh",false)||data.value("owner","")!="openace")return "Fresh openACE status is required.";
  if(!AceUnitPreview::idle(data))return "Adoption is unavailable during an active or paused print.";
  for(const auto*key:{"owner","session","revision"})if(data.value(key,"").empty()||data.value(key,"")!=context_.value(key,""))return "Printer context changed; reopen adoption.";
  if(!data.value("capabilities",Json::object()).value("adopt",false))return "This backend does not support adoption from the screen.";
  for(const auto&c:data.value("candidates",Json::array()))if(c==candidate_)return "";
  return "This discovery changed; reopen adoption.";
 }
 bool can_confirm(const Json&data)const{return unavailable(data).empty();}
 void confirmed(const Receipt&r){if(!operation_.is_null())return;operation_={{"id",r.id},{"state",r.state},{"message",r.message},{"action","adopt"},{"owner",context_.value("owner","")},{"session",context_.value("session","")},{"arguments",candidate_}};}
 void observe(const Json&data){
  if(!pending()||!data.value("fresh",false))return;
  if(data.value("owner","")!=operation_.value("owner","")||data.value("session","")!=operation_.value("session","")){
   operation_["state"]="unknown";operation_["message"]="Backend changed; check registration before retrying.";return;
  }
  auto receipts=data.value("receipts",Json::object());const auto id=operation_.value("id","");if(!receipts.contains(id))return;
  const auto&r=receipts[id];for(const auto*key:{"owner","session","action"})if(r.value(key,"")!=operation_.value(key,""))return;
  const auto state=r.value("state","");if(state!="pending"&&state!="unknown"&&state!="refused"&&state!="complete")return;
  if(state=="complete"){
   bool present=false;for(const auto&u:data.value("units",Json::array()))if(u.value("id","")==candidate_.value("logical_name",""))present=true;
   if(!present)return;
  }
  operation_["state"]=state;operation_["message"]=r.value("message","");
 }
};
}}
