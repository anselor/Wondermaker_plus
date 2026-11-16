// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../model.hpp"
namespace wmp_ui { namespace native {
// Local assignment preview only. Never issues a backend request or mutates the
// observed source map. A future save adapter must bind the same context again.
class AceUnitPreview {
public:
 bool begin(const Json&data,const std::string&id){
  clear();if(!current(data))return false;
  for(const auto&unit:data.value("units",Json::array()))if(unit.value("id","")==id){
   unit_=unit;name_=unit.value("name",id);assignments_=unit.value("assignments",Json::object());
   owner_=data.value("owner","");session_=data.value("session","");revision_=data.value("revision","");return true;
  }
  return false;
 }
 void clear(){unit_=Json();name_.clear();assignments_=Json::object();slot_.clear();}
 bool active()const{return unit_.is_object();}
 bool valid(const Json&data)const{
  if(!active()||!current(data)||data.value("owner","")!=owner_||data.value("session","")!=session_||data.value("revision","")!=revision_)return false;
  for(const auto&u:data.value("units",Json::array()))if(u.value("id","")==unit_.value("id","")&&u.value("name","")==unit_.value("name","")&&u.value("assignments",Json::object())==unit_.value("assignments",Json::object()))return true;
  return false;
 }
 std::string invalid_reason(const Json&data)const{
  if(!active())return "Unit editor has no draft.";
  if(!data.value("fresh",false))return "Unit editor requires fresh status.";
  if(data.value("owner","")!="openace")return "Unit editor requires openACE ownership; current="+rejection_value(data.value("owner",""))+".";
  for(const auto*key:{"session","revision"})if(data.value(key,"").empty())return "Unit editor "+std::string(key)+" is missing.";
  if(data.value("owner","")!=owner_)return "Unit editor owner changed.";
  if(data.value("session","")!=session_)return "Unit editor session changed.";
  if(data.value("revision","")!=revision_)return "Unit editor configuration revision changed.";
  for(const auto&u:data.value("units",Json::array()))if(u.value("id","")==unit_.value("id","")&&u.value("name","")==unit_.value("name","")&&u.value("assignments",Json::object())==unit_.value("assignments",Json::object()))return {};
  return "Reviewed unit identity, name or assignments no longer match an observed unit.";
 }
 const Json&unit()const{return unit_;}const Json&assignments()const{return assignments_;}
 Json draft()const{if(!active())return Json();auto out=unit_;out["name"]=name_;out["assignments"]=assignments_;return out;}
 bool rename(const Json&data,const std::string&name){
  if(!valid(data)||!idle(data)||name.empty()||name.size()>64||name.find_first_not_of(' ')==std::string::npos)return false;
  for(unsigned char c:name)if(c<32||c==127)return false;
  name_=name;return true;
 }
 const std::string&slot()const{return slot_;}
 void cancel_slot(){slot_.clear();}
 void select_slot(const std::string&id){if(assignments_.contains(id))slot_=id;}
 bool assign(const Json&data,const std::string&head){
  if(!valid(data)||slot_.empty()||!head_exists(data,head))return false;
  assignments_[slot_]=head;slot_.clear();return true;
 }
 bool all_to(const Json&data,const std::string&head){
  if(!valid(data)||head.empty()||!head_exists(data,head))return false;
  for(auto it=assignments_.begin();it!=assignments_.end();++it)it.value()=head;
  return true;
 }
 bool distribute(const Json&data){
  if(!valid(data))return false;
  for(unsigned i=0;i<4;++i)if(!head_exists(data,"h"+std::to_string(i)))return false;
  Json proposed=assignments_;std::set<int>slots;
  for(const auto&s:data.value("sources",Json::array()))if(s.value("unit","")==unit_.value("id","")&&s.value("kind","")=="ace"){
   const int index=s.value("slot",-1);const auto id=s.value("id","");
   if(index<0||index>=4||!assignments_.contains(id)||!slots.insert(index).second)return false;
   proposed[id]="h"+std::to_string(index);
  }
  if(slots.size()!=4)return false;
  assignments_=std::move(proposed);return true;
 }
 static bool idle(const Json&data){const auto state=data.value("job",Json::object()).value("state","");return state=="idle"||state=="complete";}
private:
 Json unit_,assignments_=Json::object();std::string name_,owner_,session_,revision_,slot_;
 static bool current(const Json&data){return data.value("fresh",false)&&data.value("owner","")=="openace"&&!data.value("session","").empty()&&!data.value("revision","").empty();}
 static bool head_exists(const Json&data,const std::string&id){if(id.empty())return true;for(const auto&h:data.value("heads",Json::array()))if(h.value("id","")==id)return true;return false;}
};
}}
