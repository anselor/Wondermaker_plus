// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../model.hpp"
namespace wmp_ui { namespace native {
// State for existing stock picker widgets, independent of their geometry.
// Capture on picker entry, never reconstruct the selected source on save.
class StockIdentityEdit {
public:
 bool begin(const Json&s,const std::string&head,const std::string&field) {
  cancel();if(!ready(s,field))return reject(ready_reason(s,field));
  if(s.value("owner","")!="standalone")return reject("Physical filament editor requires standalone ownership; current="+rejection_value(s.value("owner",""))+".");
  for(const auto&source:s.value("sources",Json::array()))
   if(source.value("kind","")=="external"&&source.value("head","")==head){
    if(draft_.is_object()){cancel();return reject("Filament source selection is duplicated.");}
    draft_=source;
   }
  return capture(s,field);
 }
 // An ACE slot is identified by its source ID, not the selected physical head:
 // several slots may feed one head, and none may currently be loaded.
 bool begin_source(const Json&s,const std::string&id,const std::string&field){
  cancel();if(!ready(s,field))return reject(ready_reason(s,field));
  if(s.value("owner","")!="openace"&&s.value("owner","")!="standalone")return reject("Filament editor requires standalone or openACE ownership; current="+rejection_value(s.value("owner",""))+".");
  if(id.empty())return reject("Filament source identifier is missing.");
  for(const auto&source:s.value("sources",Json::array()))if(source.value("id","")==id){
   if(draft_.is_object()){cancel();return reject("Filament source selection is duplicated.");}
   const auto kind=source.value("kind","");if(kind!="ace"&&kind!="external")return reject("Unsupported filament source kind="+rejection_value(kind)+".");
   draft_=source;
  }
  return capture(s,field);
 }
 Receipt choose(const Json&s,const std::string&value,Backend&backend) {
  return choose_fields(s,Json{{field_,value}},backend);
 }
 Receipt choose_fields(const Json&s,const Json&fields,Backend&backend) {
  if(!active_)return refused("Open a filament picker first.");
  active_=false; // A click can be dispatched at most once, including unknown outcomes.
  if(!s.is_object())return refused("Printer status object is unavailable.");
  if(!s.value("fresh",false))return refused("Printer status is not fresh.");
  if(s.value("owner","")!=owner_)return refused("Filament editor owner changed: reviewed="+rejection_value(owner_)+", current="+rejection_value(s.value("owner",""))+".");
  if(s.value("session","")!=session_)return refused("Filament editor printer session changed.");
  if(s.value("revision","")!=revision_)return refused("Filament editor configuration revision changed.");
  if(s.value("identity_revision","")!=identity_revision_)return refused("Filament identity revision changed.");
  auto candidate=draft_.value("identity",Json::object());
  if(fields.is_object())for(auto it=fields.begin();it!=fields.end();++it)candidate[it.key()]=it.value();
  const bool cosmetic=owner_=="standalone"&&fields.is_object()&&filament_cosmetic_edit(original_.value("identity",Json()),candidate);
  const bool recipe_write=filament_recipe_write_allowed(s,draft_.value("head",""));
  const auto identification=s.value("identification",Json::object()).value("state","");
  if(owner_=="standalone"&&(identification=="pending"||identification=="running"))return refused("Wait for head identification to finish before saving filament settings: identification.state="+rejection_value(identification)+".");
  if(!cosmetic&&!recipe_write&&(s.value("job",Json::object())!=job_||s.value("paused_filament",Json::object())!=pause_))
   return refused("Print context changed; reopen the picker.");
  bool found=false;
  for(const auto&source:s.value("sources",Json::array()))if(source.value("id","")==original_.value("id","")){
   if(found||source!=original_)return refused("Filament source changed; reopen the picker.");
   found=true;
  }
  if(!found)return refused("Filament source is no longer available.");
  if(!cosmetic&&!filament_identity_editable(s,draft_.value("head","")))return refused(filament_identity_reason(s,draft_.value("head","")));
  const auto why=backend.unavailable("save_identity");if(!why.empty())return refused(why);
  if(!fields.is_object()||fields.empty()||fields.size()>(owner_=="standalone"?8u:3u))return refused("Invalid filament fields.");
  for(auto it=fields.begin();it!=fields.end();++it){
   const bool text=it.key()=="brand"||it.key()=="material"||it.key()=="color"||(owner_=="standalone"&&it.key()=="appearance");
   const bool temperature=owner_=="standalone"&&(it.key()=="nozzle_temp"||it.key()=="nozzle_temp_min"||it.key()=="nozzle_temp_max"||it.key()=="bed_temp");
   if((text&&!it.value().is_string())||(temperature&&!it.value().is_number())||(!text&&!temperature))return refused("Invalid filament fields.");
  }
  if(owner_=="standalone"&&fields.contains("material")&&fields["material"]!=draft_["identity"].value("material",""))
   for(const auto*key:{"nozzle_temp","nozzle_temp_min","nozzle_temp_max","bed_temp"})draft_["identity"].erase(key);
  for(auto it=fields.begin();it!=fields.end();++it)draft_["identity"][it.key()]=it.value();
  Json args={{"draft",draft_}};if(!cosmetic&&!recipe_write&&paused_filament_for(s,draft_.value("head","")))args["pause_origin"]=s["paused_filament"]["origin"];
  return backend.submit({"save_identity",revision_,owner_,args});
 }
 void cancel(){reason_.clear();active_=false;draft_=Json();original_=Json();field_.clear();}
 bool active()const{return active_;}
 const Json&draft()const{return draft_;}
 const std::string&reason()const{return reason_;}
private:
 std::string reason_;
 bool reject(const std::string&why){reason_=why;report_rejection("filament editor",why);return false;}
 static std::string ready_reason(const Json&s,const std::string&field){
  if(!s.is_object())return "Printer status object is unavailable.";
  if(!s.value("fresh",false))return "Filament editor requires fresh status.";
  if(field!="color"&&field!="material"&&field!="brand")return "Unsupported filament field="+rejection_value(field)+".";
  if(s.value("session","").empty())return "Filament editor printer session is missing.";
  if(s.value("revision","").empty())return "Filament editor configuration revision is missing.";
  return "Filament editor requires idle or captured paused context; job.state="+rejection_value(s.value("job",Json::object()).value("state",""))+".";
 }
 static bool ready(const Json&s,const std::string&field){
  if(!s.is_object()||!s.value("fresh",false)||(field!="color"&&field!="material"&&field!="brand")||s.value("session","").empty()||s.value("revision","").empty())return false;
  const auto job=s.value("job",Json::object()).value("state","");return s.value("owner","")=="standalone"||job=="idle"||job=="complete"||paused_filament_for(s);
 }
 bool capture(const Json&s,const std::string&field){
  if(!draft_.is_object()){cancel();return reject("Filament source is unavailable.");}
  if(s.value("owner","")!="standalone"&&!filament_identity_editable(s,draft_.value("head",""))){const auto head=draft_.value("head","");cancel();return reject(filament_identity_reason(s,head));}
  if(!draft_.contains("identity")||!draft_["identity"].is_object()){cancel();return reject("Filament source identity object is unavailable.");}
  job_=s.value("job",Json::object());pause_=s.value("paused_filament",Json::object());
  original_=draft_;owner_=s.at("owner");session_=s.at("session");revision_=s.at("revision");
  identity_revision_=s.value("identity_revision","");field_=field;active_=true;return true;
 }
 static Receipt refused(const std::string&why){return {"","refused",why};}
 Json draft_,original_,job_,pause_;std::string owner_,session_,revision_,identity_revision_,field_;bool active_=false;
};
}}
