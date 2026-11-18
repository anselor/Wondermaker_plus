// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../model.hpp"
namespace wmp_ui { namespace native {
inline Json filament_temperature_detail(const Json&data,const std::string&physical_head){
 Json detail=Json::object();
 for(const auto&head:data.value("heads",Json::array()))if(head.value("id","")==physical_head){
  const int actual=head.value("actual",0),target=head.value("target",0);
  if(target>0||actual>=50)detail["value"]=std::to_string(actual)+" / "+std::to_string(target)+" °C";
  if(actual>=50)detail["note"]="The nozzle is hot.";
 }
 return detail;
}
// Captures a physical head/source and the backend's complete procedure before
// a stock dialog offers Begin. Browsing and source selection never dispatch.
class FilamentProcedureReview {
 Json context_,source_,plan_,sources_=Json::array();
 std::string head_,action_,reason_;bool attempted_=false;
 bool presence_matches(const Json&data)const{
  auto before=head(context_,head_).value("loaded",Json::object()),after=head(data,head_).value("loaded",Json::object());
  if(action_=="load"&&data.value("owner","")=="standalone"&&before.value("state","")=="empty"&&after.value("state","")=="empty"){
   before.erase("sensor_present");after.erase("sensor_present");
  }
  return before==after;
 }
 static std::string current_reason(const Json&data){
  if(data.value("calibration_active",false))return "Calibration is active.";
  if(data.value("owner","")!="standalone"&&!data.value("calibration_failed","").empty())return "Calibration failure remains unresolved: "+rejection_value(data.value("calibration_failed",""))+".";
  if(data.value("managed_operation_hold",false))return "Managed print/recovery hold is active.";
  if(!data.value("fresh",false))return "Filament procedure status is not fresh.";
  const auto owner=data.value("owner","");
  if(owner!="standalone"&&owner!="openace")return "Filament procedure owner must be standalone or openACE; current="+rejection_value(owner)+".";
  if(data.value("session","").empty())return "Filament procedure session is missing.";
  if(data.value("revision","").empty())return "Filament procedure configuration revision is missing.";
  const auto job=data.value("job",Json::object()).value("state","");
  if(job!="idle"&&job!="complete"&&!paused_filament_for(data))return "Filament procedure requires idle or captured paused context; job.state="+rejection_value(job)+".";
  return {};
 }
 std::string context_reason(const Json&data)const{
  if(!context_.is_object())return "Filament review has no captured context.";
  auto why=current_reason(data);if(!why.empty())return why;
  for(const auto*key:{"owner","session","revision"})if(data.value(key,"")!=context_.value(key,""))return "Filament review "+std::string(key)+" changed.";
  if(data.value("job",Json::object())!=context_.value("job",Json::object()))return "Filament review print job changed.";
  if(data.value("paused_filament",Json::object())!=context_.value("paused_filament",Json::object()))return "Filament review paused context changed.";
  const auto h=head(data,head_);if(!h.is_object())return "Reviewed physical head is missing or duplicated: head="+rejection_value(head_)+".";
  if(!presence_matches(data))return "Reviewed head filament presence or source changed.";
  return {};
 }
 static bool current(const Json&data){
  const auto owner=data.value("owner","");const auto job=data.value("job",Json::object()).value("state","");
  return !data.value("calibration_active",false)&&(owner=="standalone"||data.value("calibration_failed","").empty())&&!data.value("managed_operation_hold",false)&&data.value("fresh",false)&&(owner=="standalone"||owner=="openace")&&!data.value("session","").empty()&&!data.value("revision","").empty()&&(job=="idle"||job=="complete"||paused_filament_for(data));
 }
 static Json head(const Json&data,const std::string&id){
  Json found;for(const auto&h:data.value("heads",Json::array()))if(h.value("id","")==id){if(!found.is_null())return Json();found=h;}return found;
 }
 bool guidance_available(const Json&data)const{
  const auto description=plan_.value("description",Json());
  if(description.is_string()&&!description.get<std::string>().empty())return true;
  // The standalone screen already describes the selected action, head and
  // backend target. Unused prose is not additional motion authorization.
  if(data.value("owner","")!="standalone"||(action_!="load"&&action_!="unload")||
     head_.size()!=2||head_[0]!='h'||head_[1]<'0'||head_[1]>'3')return false;
  const auto target=plan_.value("target_temperature",Json());if(!target.is_string())return false;
  try{const auto text=target.get<std::string>();std::size_t used=0;const auto value=std::stod(text,&used);
   return used==text.size()&&std::isfinite(value)&&value>0;
  }catch(...){return false;}
 }
 bool context_matches(const Json&data)const{
  if(!context_.is_object()||!current(data))return false;
  for(const auto*key:{"owner","session","revision"})if(data.value(key,"")!=context_.value(key,""))return false;
  if(data.value("job",Json::object())!=context_.value("job",Json::object())||data.value("paused_filament",Json::object())!=context_.value("paused_filament",Json::object()))return false;
  const auto h=head(data,head_);if(!h.is_object())return false;
  // Loaded source/state changes invalidate a review, even without a config revision.
  return presence_matches(data);
 }
 Json find_plan(const Json&data)const{
  Json found;
  if(!source_.is_object())return found;
  for(const auto&p:data.value("procedures",Json::array()))if(p.value("head","")==head_&&p.value("action","")==action_&&p.value("source","")==source_.value("id","")&&p.value("revision","")==data.value("revision","")){
   if(!found.is_null())return Json();
   found=p;
  }
  return found;
 }
public:
 bool open(const Json&data,const std::string&physical_head,const std::string&action){
  context_=Json();source_=Json();plan_=Json();sources_=Json::array();attempted_=false;reason_.clear();head_=physical_head;action_=action;
  if(action!="load"&&action!="unload"){reason_="Unsupported filament action="+rejection_value(action)+".";return false;}
  if(!current(data)){reason_=current_reason(data);return false;}
  if(!head(data,head_).is_object()){reason_="Physical head is missing or duplicated: head="+rejection_value(head_)+".";return false;}
  if(data.value("job",Json::object()).value("state","")=="paused"&&!paused_filament_for(data,head_)){reason_="Selected head is outside the captured paused-filament context: head="+rejection_value(head_)+".";return false;}
  context_=data;
  const auto loaded=head(data,head_).value("loaded",Json::object());
  if(action=="unload"&&loaded.value("state","")!="loaded"){reason_="No confirmed loaded filament. Check the head first.";return true;}
  if(action=="load"&&loaded.value("state","")!="empty"){reason_="Unload the remaining filament before loading.";return true;}
  for(const auto&s:data.value("sources",Json::array()))if(s.value("head","")==head_&&
    (action=="load"?s.value("available",false):s.value("id","")==loaded.value("source","")))sources_.push_back(s);
  if(sources_.size()==1)return select(data,sources_[0].value("id",""));
  reason_=sources_.empty()?"No matching filament source is available.":"Select a filament source to review.";return true;
 }
 bool select(const Json&data,const std::string&id){
  if(attempted_){reason_="Filament procedure was already submitted; duplicate prevented.";return false;}
  if(!context_matches(data)){reason_=context_reason(data);return false;}
  Json candidate;for(const auto&s:sources_)if(s.value("id","")==id){if(!candidate.is_null())return false;candidate=s;}
  if(!candidate.is_object())return false;
  unsigned matches=0;for(const auto&s:data.value("sources",Json::array()))if(s==candidate)++matches;
  if(matches!=1)return false;
  source_=candidate;plan_=find_plan(data);
  reason_=plan_.is_object()?"":data.value("procedure_errors",Json::object()).value(head_+":"+action_,"Procedure details are unavailable. Nothing will move.");return true;
 }
 // Refresh only an unsubmitted standalone recipe, never its physical binding.
 // Callers redraw it and wait for a new explicit Begin; this does not submit.
 bool refresh(const Json&data){
  if(attempted_||data.value("owner","")!="standalone"||!context_.is_object()||!source_.is_object()||!current(data))return false;
  for(const auto*key:{"owner","session"})if(data.value(key,"")!=context_.value(key,""))return false;
  for(const auto*key:{"job","paused_filament"})if(data.value(key,Json::object())!=context_.value(key,Json::object()))return false;
  const auto h=head(data,head_);if(!h.is_object()||!presence_matches(data))return false;
  FilamentProcedureReview refreshed;
  if(!refreshed.open(data,head_,action_)||!refreshed.select(data,source_.value("id","")))return false;
  if(refreshed.plan_==plan_&&refreshed.source_==source_&&data.value("revision","")==context_.value("revision",""))return false;
  *this=std::move(refreshed);return true;
 }
 bool ready(const Json&data)const{
  if(attempted_||!context_matches(data)||!plan_.is_object()||!source_.is_object()||!data.value("capabilities",Json::object()).value(action_,false))return false;
  unsigned matches=0;for(const auto&s:data.value("sources",Json::array()))if(s==source_)++matches;
  const auto token=plan_.value("token","");
  return matches==1&&find_plan(data)==plan_&&guidance_available(data)&&token.size()==64&&token.find_first_not_of("0123456789abcdef")==std::string::npos;
 }
 Receipt confirm(const Json&data,Backend&backend){
  if(!ready(data)){
   std::string why;
   if(attempted_)why="Filament procedure was already submitted; duplicate prevented.";
   else if(!context_matches(data))why=context_reason(data);
   else if(!plan_.is_object())why="Filament procedure plan is unavailable.";
   else if(!source_.is_object())why="Filament source is not selected.";
   else if(!data.value("capabilities",Json::object()).value(action_,false))why="Filament capability "+rejection_value(action_)+"=false.";
   else{
    unsigned matches=0;for(const auto&source:data.value("sources",Json::array()))if(source==source_)++matches;
    if(matches!=1)why="Reviewed filament source match count="+std::to_string(matches)+"; expected=1.";
    else if(find_plan(data)!=plan_)why="Filament procedure plan changed.";
    else if(!guidance_available(data))why="Filament procedure target or instructions are unavailable.";
    else why="Filament procedure token is malformed; expected 64 lowercase hexadecimal characters.";
   }
   report_rejection("filament procedure BEGIN",why);return {"","refused",why};
  }
  attempted_=true; // No repeated Begin, including exceptions or uncertain delivery.
  return backend.submit({action_,data.value("revision",""),data.value("owner",""),{{"head",head_},{"source",source_.value("id","")},{"procedure_token",plan_.at("token")},{"job",data.value("job",Json::object())}}});
 }
 const Json&sources()const{return sources_;}const Json&source()const{return source_;}const Json&plan()const{return plan_;}
 const std::string&reason()const{return reason_;}const std::string&action()const{return action_;}const std::string&physical_head()const{return head_;}
};
}}
