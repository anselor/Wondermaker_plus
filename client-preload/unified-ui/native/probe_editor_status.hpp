// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../model.hpp"
#include <cmath>
namespace wmp_ui { namespace native {
inline Json probe_editor_status(const Json&raw,const std::string&session,bool standalone){
 const auto unavailable=[](const char*reason){return Json{{"available",false},{"reason",reason}};};
 if(!standalone)return unavailable("Probe editor owner is not supported.");
 if(!raw.is_object()||raw.empty())return unavailable("Probe editor is unavailable.");
 try{
  if(!raw.at("protocol").is_number_integer()||raw.at("protocol")!=1)
   return unavailable("Unsupported probe editor protocol.");
  for(const auto*key:{"session","request","state","error"})
   if(!raw.at(key).is_string())return unavailable("Invalid probe editor status.");
  if(session.empty()||raw.at("session")!=session)return unavailable("Probe editor session changed.");
  const auto state=raw.at("state").get<std::string>();
  bool known=false;
  for(const auto*name:{"idle","rejected","preparing","stopping","editing","jogging","accepting","aborting","accepted","saving","saved","save_review","save_acknowledged","discarding","discarded","keeping","kept","aborted","failed","unknown"})
   if(state==name)known=true;
  if(!known||!raw.at("binding_valid").is_boolean()||!raw.at("sequence").is_number_integer())
   return unavailable("Invalid probe editor status.");
  const auto sequence=raw.at("sequence").get<long long>();
  if(sequence < -1||sequence>1000000000)return unavailable("Invalid probe editor sequence.");
  const auto hex=[](const std::string&v){if(v.size()!=32)return false;for(char c:v)if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')))return false;return true;};
  const auto request=raw.at("request").get<std::string>();
  if((state=="idle"&&!request.empty())||(state!="idle"&&!hex(request)))
   return unavailable("Invalid probe editor request.");
  Json out={{"available",true},{"protocol",1},{"session",session},{"request",request},
            {"state",state},{"sequence",sequence},{"binding_valid",raw.at("binding_valid")},
            {"error",raw.at("error").get<std::string>().substr(0,512)},{"z_position",nullptr},{"position",nullptr}};
  if(raw.contains("config_conflict")&&!raw["config_conflict"].is_null()){
   const auto&c=raw["config_conflict"];
   if(state!="accepted"||!c.is_object())return unavailable("Invalid calibration conflict.");
   for(const auto*key:{"accepted_offset","current_offset"}){
    if(!c.at(key).is_string())return unavailable("Invalid calibration offset.");
    const auto v=c.at(key).get<std::string>();size_t end=0;
    if(v.empty()||v.size()>64||!std::isfinite(std::stod(v,&end))||end!=v.size())return unavailable("Invalid calibration offset.");
   }
   if(c.at("accepted_offset")==c.at("current_offset")||!c.at("review").is_string())return unavailable("Invalid calibration review.");
   const auto review=c.at("review").get<std::string>();
   if(review.size()!=64||!hex(review.substr(0,32))||!hex(review.substr(32)))return unavailable("Invalid calibration review.");
   out["config_conflict"]={{"accepted_offset",c.at("accepted_offset")},{"current_offset",c.at("current_offset")},{"review",review}};
  }
  if(raw.contains("save_review_required")){
   if(!raw["save_review_required"].is_boolean())return unavailable("Invalid probe save review status.");
   out["save_review_required"]=raw["save_review_required"];
  }
  if(raw.value("save_review_protocol",0)==2){
   if(!raw.at("save_review_sequence").is_number_integer()||!raw.at("save_review_confirmable").is_boolean())return unavailable("Invalid save review protocol.");
   const auto seq=raw.at("save_review_sequence").get<long long>();
   if(seq<0||seq>999999999)return unavailable("Invalid save review sequence.");
   out["save_review_protocol"]=2;out["save_review_sequence"]=seq;
   out["save_review_confirmable"]=raw.at("save_review_confirmable");
   const bool retain=raw.value("save_retain_protocol",0)==1;
   if(retain)out["save_retain_protocol"]=1;
   if(raw.contains("save_review")){
    const auto&r=raw.at("save_review");
    const auto token=r.at("token").get<std::string>(),offset=r.at("offset").get<std::string>();size_t end=0;
    const auto section=r.at("section").get<std::string>(),outcome=r.at("outcome").get<std::string>();
    if(token.size()!=64||!hex(token.substr(0,32))||!hex(token.substr(32))||section.empty()||section.size()>128
      ||offset.empty()||offset.size()>64||!std::isfinite(std::stod(offset,&end))||end!=offset.size()
      ||!r.at("configuration_matches").is_boolean()||(outcome!="review_required"&&outcome!="acknowledged"))return unavailable("Invalid saved calibration review.");
    out["save_review"]={{"token",token},{"offset",offset},{"section",section},{"outcome",outcome},{"configuration_matches",r.at("configuration_matches")}};
    if(r.contains("differences")){
     if(!r.at("differences").is_array()||r.at("differences").size()>8||!r.at("difference_count").is_number_integer()
       ||r.at("difference_count").get<long long>()<static_cast<long long>(r.at("differences").size())
       ||!r.at("pending_changes").is_boolean())return unavailable("Invalid save comparison.");
     for(const auto&entry:r.at("differences")){
      for(const auto*key:{"section","key","recorded","disk","loaded"}){
       const auto&v=entry.at(key);const bool name=std::string(key)=="section"||std::string(key)=="key";
       if((name||!v.is_null())&&(!v.is_string()||v.get<std::string>().size()>128))return unavailable("Invalid save comparison value.");
      }
     }
     out["save_review"]["differences"]=r.at("differences");
     out["save_review"]["difference_count"]=r.at("difference_count");
     out["save_review"]["pending_changes"]=r.at("pending_changes");
    }
    if(retain){
     if(!r.at("retainable").is_boolean())return unavailable("Invalid retained offset review.");
     const auto&loaded=r.at("loaded_offset");
     if(!loaded.is_null()){
      if(!loaded.is_string())return unavailable("Invalid loaded offset.");
      const auto value=loaded.get<std::string>();size_t end=0;
      if(value.empty()||value.size()>64||!std::isfinite(std::stod(value,&end))||end!=value.size())return unavailable("Invalid loaded offset.");
     }
     if(r.at("retainable")==true&&(loaded.is_null()||loaded==r.at("offset")||r.at("configuration_matches")==true))return unavailable("Invalid offset retention permission.");
     out["save_review"]["loaded_offset"]=loaded;out["save_review"]["retainable"]=r.at("retainable");
    }
   }
   if(raw.contains("save_review_result")){
    const auto&r=raw.at("save_review_result");
    const auto rs=r.at("state").get<std::string>(),action=r.at("action").get<std::string>();
    if(r.at("session")!=session||!r.at("request").is_string()||!hex(r.at("request").get<std::string>())
      ||!r.at("sequence").is_number_integer()||r.at("sequence")!=seq||seq==0
      ||(action!="REVIEW"&&action!="ACK"&&!(retain&&action=="RETAIN"))||(rs!="pending"&&rs!="complete"&&rs!="refused"&&rs!="unknown")||!r.at("error").is_string())return unavailable("Invalid save review result.");
    out["save_review_result"]={{"session",session},{"request",r.at("request")},{"sequence",seq},{"action",action},{"state",rs},{"error",r.at("error").get<std::string>().substr(0,512)}};
   }
  }
  if(raw.contains("action_refused")){
   if(!raw["action_refused"].is_boolean())return unavailable("Invalid probe action refusal.");
   out["action_refused"]=raw["action_refused"];
  }
  if(raw.contains("failure_discard_available")){
   if(!raw["failure_discard_available"].is_boolean())return unavailable("Invalid probe discard status.");
   out["failure_discard_available"]=raw["failure_discard_available"];
  }
  if(raw.contains("cleanup_available")){
   if(!raw["cleanup_available"].is_boolean())return unavailable("Invalid probe cleanup status.");
   out["cleanup_available"]=raw["cleanup_available"];
  }
  if(raw.contains("stop_protocol")){
   if(!raw["stop_protocol"].is_number_integer()||raw["stop_protocol"]!=1)return unavailable("Unsupported probe stop protocol.");
   out["stop_protocol"]=1;
  }
  if(raw.contains("stop_requested")){
   if(!raw["stop_requested"].is_boolean())return unavailable("Invalid probe stop status.");
   out["stop_requested"]=raw["stop_requested"];
  }
  if(raw.contains("token")){
   if(!raw["token"].is_string()||!hex(raw["token"].get<std::string>()))return unavailable("Invalid probe editor token.");
   out["token"]=raw["token"];
  }
  if(raw.contains("receipt_state")){
   if(!raw["receipt_state"].is_string())return unavailable("Invalid probe receipt state.");
   const auto receipt=raw["receipt_state"].get<std::string>();bool valid=false;
   for(const auto*name:{"editing","preparation_failed","finalizing","accepted","aborted","failed","invalidated","saving","saved","save_review","unknown"})if(receipt==name)valid=true;
   if(!valid)return unavailable("Invalid probe receipt state.");
   out["receipt_state"]=receipt;
  }
  for(const auto*key:{"z_position","position"}){
   if(!raw.contains(key)||raw[key].is_null())continue;
   if(std::string(key)=="position"){
    if(!raw[key].is_array()||raw[key].size()!=3)return unavailable("Invalid probe position.");
    for(const auto&v:raw[key])if(!v.is_number()||!std::isfinite(v.get<double>()))return unavailable("Invalid probe position.");
   }else if(!raw[key].is_number()||!std::isfinite(raw[key].get<double>()))return unavailable("Invalid probe position.");
   out[key]=raw[key];
  }
  return out;
 }catch(const std::exception&){return unavailable("Invalid probe editor status.");}
}
}}
