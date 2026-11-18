// SPDX-License-Identifier: GPL-3.0-or-later
#include "native/filament_procedure_review.hpp"
#include <cassert>
using namespace wmp_ui;using namespace wmp_ui::native;
struct RecordingBackend:Backend{
 unsigned calls=0;Request request;bool throws=false;
 std::string unavailable(const std::string&)const override{return "";}
 Receipt submit(const Request&r)override{++calls;request=r;if(throws)throw std::runtime_error("uncertain");return {"one","pending","Queued"};}
};
int main(){
 for(const auto*owner:{"standalone","openace"}){
  Json source={{"id","source-a"},{"head","h2"},{"available",true},{"identity",{{"material","PLA"},{"color","#aaaaaa"}}}};
  Json plan={{"head","h2"},{"source","source-a"},{"action","load"},{"revision","rev"},{"token",std::string(64,'a')},{"description","Heat physical Head 3 to 210 C, then feed 20 mm."}};
  Json data={{"owner",owner},{"session","session"},{"revision","rev"},{"fresh",true},{"job",{{"state","idle"}}},{"capabilities",{{"load",true},{"unload",true}}},{"heads",Json::array({{{"id","h2"},{"loaded",{{"state","empty"}}}}})},{"sources",Json::array({source})},{"procedures",Json::array({plan})}};
  if(std::string(owner)=="standalone"){
   auto external=source;external["kind"]="external";
   auto editing=data;editing["sources"][0]=external;
   auto inserted=editing;inserted["heads"][0]["loaded"]["sensor_present"]=true;inserted["revision"]="sensor-revision";
   assert(filament_source_edit_context_matches(inserted,editing,external));
   for(const auto*key:{"session","identity_revision","command_generation","job"}){
    auto drift=inserted;drift[key]="changed";
    assert(!filament_source_edit_context_matches(drift,editing,external));
   }
   auto changed_profile=inserted;changed_profile["sources"][0]["identity"]["material"]="ABS";
   assert(!filament_source_edit_context_matches(changed_profile,editing,external));
   auto duplicate=inserted;duplicate["sources"].push_back(external);
   assert(!filament_source_edit_context_matches(duplicate,editing,external));
   FilamentProcedureReview early;assert(early.open(data,"h2","load"));
   auto early_data=data;early_data["heads"][0]["loaded"]["sensor_present"]=true;
   assert(early.ready(early_data));
   early_data["revision"]="sensor-revision";early_data["procedures"][0]["revision"]="sensor-revision";
   assert(early.refresh(early_data)&&early.ready(early_data));
   early_data["heads"][0]["loaded"]["state"]="loaded";
   assert(!early.ready(early_data));
   auto temperatures=data;temperatures["heads"][0]["actual"]=75;temperatures["heads"][0]["target"]=250;
   temperatures["heads"].push_back({{"id","h0"},{"actual",200},{"target",220}});
   assert(filament_temperature_detail(temperatures,"h2")["value"]=="75 / 250 °C");
   assert(filament_temperature_detail(temperatures,"h2")["note"]=="The nozzle is hot.");
   temperatures["heads"][0]["actual"]=25;
   assert(!filament_temperature_detail(temperatures,"h2").contains("note"));
   assert(filament_temperature_detail(temperatures,"h3").empty());
   FilamentProcedureReview refresh;RecordingBackend sink;assert(refresh.open(data,"h2","load"));
   auto newer=data;newer["revision"]="new";newer["procedures"][0]["revision"]="new";
   newer["procedures"][0]["token"]=std::string(64,'b');newer["procedures"][0]["description"]="Heat to 230 C";
   assert(!refresh.ready(newer));assert(refresh.refresh(newer));assert(refresh.ready(newer)&&sink.calls==0);
   assert(refresh.plan()["description"]=="Heat to 230 C");assert(!refresh.refresh(newer));
   for(const auto*change:{"session","presence","job","owner"}){
    auto changed=newer;
    if(std::string(change)=="presence")changed["heads"][0]["loaded"]["state"]="loaded";
    else if(std::string(change)=="job")changed["job"]["state"]="printing";
    else changed[change]="other";
    assert(!refresh.refresh(changed)&&!refresh.ready(changed));
   }
   assert(refresh.confirm(newer,sink).state=="pending"&&sink.calls==1);
   assert(sink.request.arguments["procedure_token"]==std::string(64,'b'));
   assert(!refresh.refresh(data)&&!refresh.refresh(newer));
   assert(refresh.confirm(newer,sink).state=="refused"&&sink.calls==1);
  }
  for(const auto&description:{Json(),Json(3),Json::object(),Json("")}){
   auto current=data;current["procedures"][0]["description"]=description;current["procedures"][0]["target_temperature"]="220";
   FilamentProcedureReview text;RecordingBackend sink;assert(text.open(current,"h2","load"));
   const bool standalone=std::string(owner)=="standalone";
   assert(text.ready(current)==standalone);
   if(standalone){assert(text.confirm(current,sink).state=="pending"&&sink.calls==1);}
   for(const auto*field:{"target_temperature","token"}){
    auto incomplete=current;incomplete["procedures"][0].erase(field);
    FilamentProcedureReview missing;RecordingBackend untouched;assert(missing.open(incomplete,"h2","load"));
    assert(missing.confirm(incomplete,untouched).state=="refused"&&untouched.calls==0);
   }
  }
  FilamentProcedureReview review;RecordingBackend backend;
  assert(review.open(data,"h2","load")&&review.ready(data)&&backend.calls==0);
  for(const auto*key:{"owner","session","revision"}){auto changed=data;changed[key]="changed";assert(!review.ready(changed));}
  for(const auto*flag:{"calibration_active","managed_operation_hold"}){
   auto blocked=data;blocked[flag]=true;
   assert(!review.ready(blocked));assert(review.confirm(blocked,backend).state=="refused"&&backend.calls==0);
  }
  auto failed=data;failed["calibration_failed"]="Docking failed";
  assert(review.ready(failed)==(std::string(owner)=="standalone"));if(std::string(owner)!="standalone")assert(review.confirm(failed,backend).state=="refused"&&backend.calls==0);
  auto changed=data;changed["fresh"]=false;assert(!review.ready(changed));
  changed=data;changed["job"]["state"]="paused";assert(!review.ready(changed));
  changed=data;changed["heads"][0]["loaded"]["state"]="loaded";assert(!review.ready(changed));
  changed=data;changed["procedures"][0]["description"]="Feed 100 mm";assert(!review.ready(changed));
  changed=data;changed["sources"][0]["identity"]["color"]="#bbbbbb";assert(!review.ready(changed));
  changed=data;changed["procedures"].push_back(plan);assert(!review.ready(changed));
  assert(review.confirm(data,backend).state=="pending"&&backend.calls==1);
  assert(backend.request.arguments["head"]=="h2"&&backend.request.arguments["source"]=="source-a"&&backend.request.arguments["procedure_token"]==std::string(64,'a'));
  assert(review.confirm(data,backend).state=="refused"&&backend.calls==1);
  if(std::string(owner)=="standalone"){
   auto paused=data;paused["job"]["state"]="paused";
   paused["paused_filament"]={{"available",true},{"head","h2"},
    {"origin",{{"head","h2"},{"session","session"},{"id",std::string(32,'a')},{"file_position",120}}}};
   paused["procedures"][0]["pause_origin"]=paused["paused_filament"]["origin"];
   assert(review.open(paused,"h2","load")&&review.ready(paused));
   for(const auto*c:{"origin","position","cancelled","unavailable","session"}){
    auto drift=paused;const std::string change=c;
    if(change=="origin")drift["paused_filament"]["origin"]["id"]=std::string(32,'b');
    if(change=="position")drift["paused_filament"]["origin"]["file_position"]=121;
    if(change=="cancelled")drift["job"]["state"]="idle";
    if(change=="unavailable")drift["paused_filament"]["available"]=false;
    if(change=="session")drift["session"]="new-session";
    assert(!review.ready(drift));assert(review.confirm(drift,backend).state=="refused"&&backend.calls==1);
   }
   assert(review.confirm(paused,backend).state=="pending"&&backend.calls==2);
   auto other=paused;other["heads"].push_back({{"id","h1"},{"loaded",{{"state","empty"}}}});
   assert(!review.open(other,"h1","load"));
   auto recovery=other;recovery["paused_filament"]["filament_required"]=Json::array({"h1"});
   recovery["sources"][0]["head"]="h1";recovery["procedures"][0]["head"]="h1";
   assert(review.open(recovery,"h1","load")&&review.ready(recovery));
   auto revoked=recovery;revoked["paused_filament"]["filament_required"]=Json::array();
   assert(!review.ready(revoked));
   assert(!paused_filament_for(recovery,"h0"));
   assert(review.confirm(recovery,backend).state=="pending"&&backend.request.arguments["head"]=="h1");

   paused["heads"][0]["loaded"]={{"state","loaded"},{"source","source-a"}};
   paused["procedures"][0]["action"]="unload";
   assert(review.open(paused,"h2","unload")&&review.ready(paused));
   // Missing Z prevents unload review/dispatch too, with the backend's
   // actionable guidance retained for idle and paused users.
   for(bool is_paused:{false,true}){
    auto blocked=paused;if(!is_paused)blocked["job"]["state"]="idle";
    const std::string reason=is_paused?
     "Z position was lost. Keep the print paused; do not home Z over the print.":
     "Z position is unknown. With the bed clear, home from XYZ before loading or unloading. Filament service will not home Z.";
    blocked["procedures"]=Json::array();blocked["procedure_errors"]={{"h2:unload",reason}};
    assert(review.open(blocked,"h2","unload")&&!review.ready(blocked)&&review.reason()==reason);
    const auto calls=backend.calls;
    assert(review.confirm(blocked,backend).state=="refused"&&backend.calls==calls);
   }
  }
  auto second=source;second["id"]="source-b";data["sources"].push_back(second);
  assert(review.open(data,"h2","load")&&!review.ready(data)&&review.sources().size()==2);
  assert(review.select(data,"source-a")&&review.ready(data));
  backend.throws=true;try{review.confirm(data,backend);assert(false);}catch(const std::runtime_error&){}
  assert(!review.ready(data)&&review.confirm(data,backend).state=="refused");backend.throws=false;
  data["heads"][0]["loaded"]={{"state","loaded"},{"source","source-b"}};
  plan["source"]="source-b";plan["action"]="unload";data["procedures"]=Json::array({plan});
  assert(review.open(data,"h2","unload")&&review.source()["id"]=="source-b"&&review.ready(data));
  assert(review.open(data,"h2","load")&&!review.ready(data));
  data["procedures"]=Json::array();assert(review.open(data,"h2","unload")&&!review.ready(data)&&!review.reason().empty());
  if(std::string(owner)=="openace"){
   const std::string reason="This openACE version does not support managed unloading of externally fed filament";
   data["procedure_errors"]={{"h2:unload",reason}};
   assert(review.open(data,"h2","unload")&&review.reason()==reason&&!review.ready(data));
   const auto calls=backend.calls;
   assert(review.confirm(data,backend).state=="refused"&&backend.calls==calls);
  }
 }
}
