// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "model.hpp"
#include "typed_management.hpp"
#include "../openace-compat/screen1113/source/client/worker_bridge.hpp"
namespace wmp_ui {
// Existing typed command path; no raw G-code and no direct network I/O here.
// Caller supplies the normalized revision and fresh raw status on the GUI thread.
// ScreenWorker revalidates the generated command/session at delivery time.
class OpenAceBackend : public Backend {
public:
 explicit OpenAceBackend(wmp_openace::UiChannel& channel):channel_(channel){}
 void update(Json raw, std::string revision, bool fresh) {raw_=std::move(raw);revision_=std::move(revision);fresh_=fresh;}
 std::string unavailable(const std::string& action)const override {
  if(!fresh_)return "Fresh openACE status is required: status marked stale.";
  if(!raw_.is_object())return "openACE status object is unavailable.";
  if(!raw_.contains("session_id"))return "openACE status has no session_id.";
  if(action=="save_identity"||action=="adopt"||action=="save_unit")return "";
  return "The unified "+action+" adapter is not implemented yet.";
 }
 Receipt submit(const Request&r)override {
  try {
   auto reason=unavailable(r.action);if(!reason.empty())return {"","refused",reason};
   if(r.owner!="openace")return {"","refused","openACE request ownership changed: reviewed="+rejection_value(r.owner)+"."};
   if(r.revision!=revision_)return {"","refused","openACE configuration revision changed. Refresh and review."};
   Json request;
   if(r.action=="adopt")request={{"action","unit_add"},{"unit",r.arguments.at("logical_name")},{"context",r.arguments.at("context")}};
   else if(r.action=="save_identity") {
    const auto&draft=r.arguments.at("draft");const auto&id=draft.at("identity");
    request={{"action","set_filament"},{"fields",{{"material",id.at("material")},{"color",id.at("color")}}}};
    std::string key;
    if(draft.value("kind","")=="ace") {request["unit"]=draft.at("unit");request["slot"]=draft.at("slot");key=draft.at("unit").get<std::string>()+":"+std::to_string(draft.at("slot").get<int>());}
    else {request["head"]=draft.at("head");key=draft.at("head").get<std::string>();}
    const auto&old=raw_.at("management").at("identity_settings").at(key);
    const auto values=old.is_object()?old.value("values",Json::object()):Json::object();auto vendor=values.value("vendor","");if(vendor.empty())vendor="Generic";
    if(id.at("brand")!=vendor||old.is_null())request["fields"]["vendor"]=id.at("brand");
    if(id.at("material")!=values.value("material","")||values.value("nozzle_temp",0.0)<=0){
     static const std::map<std::string,int> temperatures={{"PLA",220},{"PLA Silk",220},{"ABS",250},{"PETG",250},{"PLA Matte",220},{"PLA Metal",220},{"ABS Matte",250},{"PETG Matte",250},{"PVA",220},{"TPE",230},{"Marble",220},{"HIPS",250},{"TPU",230},{"PET",300},{"Wood",220},{"ASA",260},{"PA",260},{"PC",270}};
     const auto recipe=temperatures.find(id.at("material").get<std::string>());
     if(recipe==temperatures.end())return {"","refused","Choose a material with a supported loading temperature."};
     request["fields"]["nozzle_temp"]=recipe->second;
     request["fields"]["nozzle_temp_min"]=0;request["fields"]["nozzle_temp_max"]=0;
    }
   }else if(r.action=="save_unit") {
    const auto&draft=r.arguments.at("draft");const auto uid=draft.at("id").get<std::string>();
    // Rename is supported. Quick assignment changes need a transaction contract;
    // never partially apply the name and leave routing silently incomplete.
    Json assignments=Json::object();
    for(auto it=raw_.at("management").at("source_settings").begin();it!=raw_.at("management").at("source_settings").end();++it)if(it.key().compare(0,uid.size()+1,uid+":")==0)assignments[it.key()]="";
    for(auto it=raw_.at("default_tool_map").begin();it!=raw_.at("default_tool_map").end();++it){
     const auto&route=it.value();if(route.contains("unit")&&route["unit"].is_string()&&route["unit"]==uid) {
      auto source=uid+":"+std::to_string(route.at("slot").get<int>());auto head=route.at("head").get<std::string>();
      if(!assignments.value(source,std::string()).empty()&&assignments[source]!=head)return {"","refused","Conflicting source aliases require backend reconciliation."};
      assignments[source]=head;
     }
    }
    if(assignments!=draft.at("assignments"))return {"","refused","Saving slot assignments needs a backend transaction; no changes sent."};
    request={{"action","unit_rename"},{"unit",uid},{"name",draft.at("name")}};
   }
   auto command=wmp_openace::management_command(raw_,request);
   channel_.set_management_open(true);
   auto ticket=channel_.enqueue_management(request,command,raw_.at("session_id").get<std::int64_t>());
   if(!ticket)return {"","refused","Command queue busy; nothing was sent."};
   return {std::to_string(ticket),"pending","Waiting for backend readback. Delivery alone does not confirm the change."};
  }catch(const std::exception&e){return {"","refused",e.what()};}
 }
private:
 wmp_openace::UiChannel& channel_;Json raw_;std::string revision_;bool fresh_=false;
};
}
