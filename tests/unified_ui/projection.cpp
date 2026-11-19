#include "native/gui_status_snapshot.hpp"
#include "native/case_light_status.hpp"
// SPDX-License-Identifier: GPL-3.0-or-later
#include "native/projection.hpp"
#include "screens.hpp"
#include <cassert>
#include <fstream>
using namespace wmp_ui;
static int light_calls, light_preference, light_doors;static long long light_at;
static void light_observation(int preference,int doors,long long at){++light_calls;light_preference=preference;light_doors=doors;light_at=at;}
int main(int argc,char**argv){
 {
  wmp_ui::native::GuiStatusSnapshot cache;
  Json source={{"fresh",true},{"printer_state","ready"},{"payload",Json::array({1,2,3})}};
  const auto&view=cache.observe(source,100,100,1);assert(cache.changed()&&view["fresh"]==true);
  const auto*payload=&view.at("payload").at(0);
  const auto&same=cache.observe(source,100,200,1);assert(!cache.changed()&&same["status_age_ms"]==100);
  assert(&same.at("payload").at(0)==payload); // No payload allocation on GUI-only ticks.
  cache.observe(source,100,2100,1);assert(!cache.changed());
  assert(cache.observe(source,100,2101,1)["fresh"]==false&&cache.changed());
  cache.observe(source,100,2200,1);assert(!cache.changed());
  assert(cache.observe(source,100,4101,1)["display_fresh"]==false&&cache.changed());
  assert(cache.observe(source,5000,5000,2)["fresh"]==true&&cache.changed());
  source["payload"][0]=4;assert(cache.observe(source,5000,5001,3)["payload"][0]==4&&cache.changed());
  assert(cache.observe(source,5000,4999,3)["fresh"]==false&&cache.changed());
  source["fresh"]=false;assert(cache.observe(source,5000,5002,4)["fresh"]==false&&cache.changed());
  assert(source.count("status_age_ms")==0); // Shared input remains immutable.
 }

 {
  using namespace wmp_ui::native;
  assert(!publish_case_light_status(Json::object(),1,light_observation)&&light_calls==0);
  Json state={{"wmp_case_light",{{"policy_version",2},{"enabled",true}}},
    {"gcode_button Door_button1",{{"state","PRESSED"}}},
    {"gcode_button Door_button2",{{"state","RELEASED"}}}};
  assert(publish_case_light_status(state,42,light_observation));
  assert(light_calls==1&&light_preference==1&&light_doors==2&&light_at==42);
  state["wmp_case_light"]["enabled"]=false;
  state["gcode_button Door_button1"]["state"]="RELEASED";
  assert(publish_case_light_status(state,43,light_observation)&&light_preference==0&&light_doors==3);
  state["wmp_case_light"]["enabled"]=1;
  state.erase("gcode_button Door_button1");state.erase("gcode_button Door_button2");
  assert(publish_case_light_status(state,44,light_observation)&&light_preference==-1&&light_doors==-1);
  state["wmp_case_light"]["policy_version"]=1;
  assert(!publish_case_light_status(state,45,light_observation));
  invalidate_case_light_status(light_observation);assert(light_at==-1&&light_preference==-1&&light_doors==-1);
  state["wmp_case_light"]["policy_version"]=2;state["webhooks"]={{"state","shutdown"}};
  assert(!publish_case_light_status(state,46,light_observation)&&light_at==-1);
 }

 {Json raw_status={{"wm_material",{{"toolchange_pause",{{"manual_toolhead_available",true},{"manual_toolhead_reason",""}}}}}};
  const auto data=native::project(raw_status,Json::object(),false,"test");assert(data.at("toolchange_pause").at("manual_toolhead_available")==true);}

 assert(argc==2);std::ifstream input(argv[1]);Json raw;input>>raw;
 Json status={{"webhooks",{{"state","ready"}}},{"print_stats",{{"state","standby"},{"filename",""}}},{"extruder",{{"temperature",28.4},{"target",0.0}}},{"extruder1",{{"temperature",31.2},{"target",220.0}}}};
 {
  auto sequenced=status;sequenced["wm_material"]={{"material_request_sequence_protocol",1},{"filament_request_sequence",1025},{"toolhead_request_sequence",2048}};
  auto data=native::project(sequenced,Json::object(),false,"session");
  assert(data["material_request_sequence_protocol"]==1&&data["filament_request_sequence"]==1025&&data["toolhead_request_sequence"]==2048);
 }
 {
  auto policy=status;policy["wm_material"]={{"filament_recipe_write_protocol",1},{"filament_recipe_write",{{"h0",{{"allowed",true},{"reason",""}}},{"h1",{{"allowed",false},{"reason","Head is used by print"}}}}}};
  auto data=native::project(policy,Json::object(),false,"session");data["job"]["state"]="printing";
  assert(filament_recipe_write_allowed(data,"h0")&&!filament_recipe_write_allowed(data,"h1"));
  assert(data["filament_recipe_write"]==policy["wm_material"]["filament_recipe_write"]);
  data["fresh"]=false;assert(!filament_recipe_write_allowed(data,"h0"));
  data["fresh"]=true;data["owner"]="openace";assert(!filament_recipe_write_allowed(data,"h0"));
 }
 // Only current execution holds the printer; history remains visible for review.
 for(const auto*key:{"print_cancel","recovery_attempt"}){
  for(const auto*state:{"pending","running","stopping"}){
   auto held=status;held["wm_material"][key]={{"state",state}};
   assert(native::project(held,Json::object(),false,"session")["managed_operation_hold"]==true);
  }
  const bool recovery=std::string(key)=="recovery_attempt";
  for(const auto*state:{"complete",recovery?"abandoned":"failed","unknown","stopped","unrecognized"}){
   auto settled=status;settled["wm_material"][key]={{"state",state}};
   assert(native::project(settled,Json::object(),false,"session")["managed_operation_hold"]==false);
  }
  auto wrong_terminal=status;wrong_terminal["wm_material"][key]={{"state",recovery?"failed":"abandoned"}};
  assert(native::project(wrong_terminal,Json::object(),false,"session")["managed_operation_hold"]==false);
  auto malformed=status;malformed["wm_material"][key]={{"state",3}};
  assert(native::project(malformed,Json::object(),false,"session")["managed_operation_hold"]==false);
 }
 // An error label is stopped only when the independent SD/pause facts agree.
 for(bool active:{false,true})for(bool paused:{false,true}){
  auto stopped=status;stopped["print_stats"]["state"]="error";
  stopped["virtual_sdcard"]={{"is_active",active}};stopped["pause_resume"]={{"is_paused",paused}};
  auto p=native::project(stopped,Json::object(),false,"session");
  assert(p["job"]["state"]==(paused?"paused":active?"printing":"idle"));
 }
 // Compact helper values replace bulk config/saved-variable objects for both owners.
 {
  auto damaged=status;
  damaged["wm_material"]={{"recovery_attempt",Json::object()},
                         {"recovery_restore_error","Saved recovery requires review"}};
  auto projected=native::project(damaged,Json::object(),false,"session");
  assert(projected["managed_operation_hold"]==false);
  assert(projected["recovery_restore_error"]=="Saved recovery requires review");
 }
 {
  auto compact=status;
  compact["wm_material"]={{"screen_status_protocol",1},{"heater_settings",{{"extruder",{{"min_temp",0},{"max_temp",300},{"nozzle_diameter",0.6}}}}},{"physical_mapping",Json::array({3,1,2,0})}};
  for(bool ace:{false,true}){
   auto projected=native::project(compact,raw,ace,"session");
   assert(projected["heater_limits"]["h0"]["max"]==300);
   assert(projected["heads"][0]["nozzle"]["diameter"]=="0.6 mm");
   if(!ace)assert(projected["physical_mapping"]==Json::array({3,1,2,0}));
  }
  auto old=native::project(compact,raw,false,"session");
  compact["wm_material"]["physical_mapping"][0]=2;
  auto changed=native::project(compact,raw,false,"session");
  assert(old["revision"]!=changed["revision"]);
  compact["wm_material"]["heater_settings"]=Json::object();
  assert(!native::project(compact,raw,false,"session")["capabilities"]["temperature"].get<bool>());
 }
 auto projected=native::project(status,raw,true,"standalone");
 assert(projected["owner"]=="openace");assert(projected["heads"].size()==2);assert(projected["heads"][0]["actual"]==28);
 assert(projected["heads"][0]["loaded"]["state"]=="unknown");assert(projected["sources"][0]["identity"]["brand"]=="Maker Co");
 StubBackend backend;App app(backend);app.update(projected);assert(app.data()["fresh"]==true);assert(app.render()["page"]=="home");
 auto standalone=native::project(status,Json::object(),false,"session");assert(standalone["owner"]=="standalone");assert(standalone["units"].empty());assert(!standalone["capabilities"]["save_identity"].get<bool>());
 for(const auto*brand:{"Bambu Lab","Generic","WonderMaker","SUNLU","eSUN","Polymaker"})assert(std::find(standalone["brands"].begin(),standalone["brands"].end(),brand)!=standalone["brands"].end());
 for(const auto*material:{"PLA Silk","PVA","HIPS","PCTG","PA6","PA12","PP"})assert(std::find(standalone["materials"].begin(),standalone["materials"].end(),material)!=standalone["materials"].end());
 assert(std::find(projected["brands"].begin(),projected["brands"].end(),"Maker Co")!=projected["brands"].end());
 auto failed_status=status;failed_status["wmp_recovery"]={{"calibration_failed","PID failed"},{"calibration_active",false},{"calibration_checkpoint","abc"},{"calibration_session","cal-session"}};
 for(bool ace:{false,true}){auto failed=native::project(failed_status,ace?raw:Json::object(),ace,"session");assert(failed["calibration_checkpoint"]=="abc"&&failed["calibration_session"]=="cal-session");assert(failed["calibration_failed"]=="PID failed"&&!failed["calibration_active"].get<bool>());}
 {
  auto input=failed_status;
  Json editor={{"protocol",1},{"session","cal-session"},{"request",std::string(32,'a')},
   {"state","editing"},{"error",""},{"sequence",2},{"token",std::string(32,'b')},
   {"binding_valid",true},{"z_position",1.25},{"position",nullptr},{"private", "omit"}};
  input["wmp_recovery"]["probe_editor"]=editor;
  auto projected_editor=native::project(input,Json::object(),false,"session")["probe_editor"];
  assert(projected_editor["available"]==true&&projected_editor["z_position"]==1.25);
  assert(!projected_editor.contains("private"));
  assert(native::project(input,raw,true,"session")["probe_editor"]["available"]==false);
  for(const auto&bad:{Json(),Json::array(),Json("bad"),Json(1)})
   assert(native::probe_editor_status(bad,"cal-session",true)["available"]==false);
  for(const auto*key:{"protocol","session","request","state","sequence","binding_valid","token","z_position","position","stop_requested","stop_protocol","cleanup_available","failure_discard_available","action_refused"}){
   auto bad=editor;bad[key]=Json::object();
   assert(native::probe_editor_status(bad,"cal-session",true)["available"]==false);
  }
  auto conflict=editor;conflict["state"]="accepted";
  conflict["config_conflict"]={{"accepted_offset","1.5"},{"current_offset","2.0"},{"review",std::string(64,'d')}};
  assert(native::probe_editor_status(conflict,"cal-session",true)["config_conflict"]==conflict["config_conflict"]);
  for(const auto*key:{"accepted_offset","current_offset","review"}){
   auto bad=conflict;bad["config_conflict"][key]="nan";
   assert(native::probe_editor_status(bad,"cal-session",true)["available"]==false);
  }
  conflict["state"]="kept";conflict.erase("config_conflict");
  assert(native::probe_editor_status(conflict,"cal-session",true)["available"]==true);
  auto save_review=editor;save_review["state"]="save_review";save_review["save_review_required"]=true;
  assert(native::probe_editor_status(save_review,"cal-session",true)["save_review_required"]==true);
  save_review["save_review_protocol"]=2;save_review["save_review_sequence"]=1;save_review["save_review_confirmable"]=true;
  save_review["save_review"]={{"token",std::string(64,'a')},{"section","probe"},{"offset","1.25"},{"configuration_matches",true},{"outcome","review_required"}};
  save_review["save_review_result"]={{"session","cal-session"},{"request",save_review["request"]},{"sequence",1},{"action","REVIEW"},{"state","complete"},{"error",""}};
  assert(native::probe_editor_status(save_review,"cal-session",true)["save_review_result"]==save_review["save_review_result"]);
  for(const auto&change:{Json{{"sequence",0}},Json{{"action","SAVE"}},Json{{"session","old"}},Json{{"state","saved"}}}){
   auto bad=save_review;bad["save_review_result"].update(change);
   assert(native::probe_editor_status(bad,"cal-session",true)["available"]==false);
  }
  auto retained=save_review;retained["save_retain_protocol"]=1;
  retained["save_review"]["configuration_matches"]=false;retained["save_review"]["retainable"]=true;retained["save_review"]["loaded_offset"]="2.0";
  assert(native::probe_editor_status(retained,"cal-session",true)["save_review"]["retainable"]==true);
  retained["save_review"]["loaded_offset"]=nullptr;
  assert(native::probe_editor_status(retained,"cal-session",true)["available"]==false);
  auto compared=save_review;
  compared["save_review"]["differences"]=Json::array({{{"section","probe"},{"key","z_offset"},{"recorded","1.5"},{"disk",nullptr},{"loaded","2.0"}}});
  compared["save_review"]["difference_count"]=1;compared["save_review"]["pending_changes"]=false;
  assert(native::probe_editor_status(compared,"cal-session",true)["save_review"]["differences"]==compared["save_review"]["differences"]);
  compared["save_review"]["difference_count"]=0;
  assert(native::probe_editor_status(compared,"cal-session",true)["available"]==false);
  auto acknowledged=save_review;acknowledged["state"]="save_acknowledged";acknowledged["save_review_required"]=false;
  assert(native::probe_editor_status(acknowledged,"cal-session",true)["available"]==true);
  save_review["save_review_required"]="bad";
  assert(native::probe_editor_status(save_review,"cal-session",true)["available"]==false);
  auto stopping=editor;stopping["state"]="stopping";stopping["stop_requested"]=true;stopping["stop_protocol"]=1;
  auto stop_view=native::probe_editor_status(stopping,"cal-session",true);
  assert(stop_view["available"]==true&&stop_view["stop_requested"]==true&&stop_view["stop_protocol"]==1);
  auto failed=editor;failed["state"]="failed";failed["receipt_state"]="preparation_failed";failed["cleanup_available"]=true;
  auto cleanup_view=native::probe_editor_status(failed,"cal-session",true);
  assert(cleanup_view["available"]==true&&cleanup_view["cleanup_available"]==true);
  failed.erase("receipt_state");failed["cleanup_available"]=false;failed["failure_discard_available"]=true;
  assert(native::probe_editor_status(failed,"cal-session",true)["failure_discard_available"]==true);
  auto rejected=editor;rejected["state"]="rejected";rejected["action_refused"]=true;
  assert(native::probe_editor_status(rejected,"cal-session",true)["action_refused"]==true);
  auto stale=editor;stale["session"]="old";
  assert(native::probe_editor_status(stale,"cal-session",true)["available"]==false);
  editor["binding_valid"]=false;
  assert(native::probe_editor_status(editor,"cal-session",true)["binding_valid"]==false);
 }
 {
  const std::string attempt_request(32,'c');
  Json scrub={{"protocol",1},{"head",2},{"phase","heating"},{"target",160.0},{"error",""},{"request",attempt_request}};
  Json progress={{"protocol",1},{"head",-1},{"phase","homing"},{"request",attempt_request}};
  auto input=status;input["wmp_recovery"]={{"nozzle_scrub",scrub},{"calibration_progress",progress}};
  for(bool ace:{false,true}){
   auto projected_scrub=native::project(input,ace?raw:Json::object(),ace,"session");
   assert(projected_scrub["nozzle_scrub"]==scrub&&projected_scrub["calibration_progress"]==progress);
  }
  auto failed=input;failed["wmp_recovery"]["nozzle_scrub"]["phase"]="failed";failed["wmp_recovery"]["nozzle_scrub"]["error"]="Head 3 did not mount.";
  assert(native::project(failed,Json::object(),false,"session")["nozzle_scrub"]==failed["wmp_recovery"]["nozzle_scrub"]);
  const Json unavailable={{"phase","unavailable"}};
  assert(native::project(status,Json::object(),false,"session")["nozzle_scrub"]==unavailable);
  assert(native::project(status,Json::object(),false,"session")["calibration_progress"]==unavailable);
  for(const auto&change:{Json{{"protocol",2}},Json{{"protocol","1"}},Json{{"head",4}},Json{{"head",-2}},Json{{"head",1.5}},Json{{"phase","positioned"}},Json{{"phase",1}},Json{{"target","160"}},Json{{"error",nullptr}}}){
   auto bad=input;bad["wmp_recovery"]["nozzle_scrub"].update(change);
   assert(native::project(bad,Json::object(),false,"session")["nozzle_scrub"]==unavailable);
  }
  for(const auto*key:{"protocol","head","phase","target","error","request"}){
   auto bad=input;bad["wmp_recovery"]["nozzle_scrub"].erase(key);
   assert(native::project(bad,Json::object(),false,"session")["nozzle_scrub"]==unavailable);
  }
  for(const auto&change:{Json{{"protocol",0}},Json{{"head",4}},Json{{"head","1"}},Json{{"phase","heating"}},Json{{"phase",nullptr}}}){
   auto bad=input;bad["wmp_recovery"]["calibration_progress"].update(change);
   assert(native::project(bad,Json::object(),false,"session")["calibration_progress"]==unavailable);
  }
  // request: the attempt's 32 lowercase hexadecimal characters, or "" when none.
  for(const auto*key:{"nozzle_scrub","calibration_progress"}){
   auto none=input;none["wmp_recovery"][key]["request"]="";
   assert(native::project(none,Json::object(),false,"session")[key]==none["wmp_recovery"][key]);
   for(const auto&bad_request:{Json(std::string(31,'c')),Json(std::string(33,'c')),Json(std::string(32,'C')),Json(std::string(32,'g')),Json(1),Json(),Json::object()}){
    auto bad=input;bad["wmp_recovery"][key]["request"]=bad_request;
    assert(native::project(bad,Json::object(),false,"session")[key]==unavailable);
   }
  }
  {auto bad=input;bad["wmp_recovery"]["calibration_progress"].erase("request");
   assert(native::project(bad,Json::object(),false,"session")["calibration_progress"]==unavailable);}
  for(const auto&bad_value:{Json(),Json::array(),Json("homing"),Json(1)}){
   auto bad=input;bad["wmp_recovery"]["nozzle_scrub"]=bad_value;bad["wmp_recovery"]["calibration_progress"]=bad_value;
   auto projected_bad=native::project(bad,Json::object(),false,"session");
   assert(projected_bad["nozzle_scrub"]==unavailable&&projected_bad["calibration_progress"]==unavailable);
  }
  for(const auto*phase:{"idle","mounting","position","height","docking"}){
   auto good=input;good["wmp_recovery"]["calibration_progress"]={{"protocol",1},{"head",3},{"phase",phase},{"request",attempt_request}};
   assert(native::project(good,Json::object(),false,"session")["calibration_progress"]==good["wmp_recovery"]["calibration_progress"]);
  }
 }
 {
  // Open doors: bit n while door switch n+1 reports RELEASED; -1 without any
  // door state or while Klipper is not ready.
  const auto doors=[](const Json&in){return native::project(in,Json::object(),false,"session")["doors"];};
  assert(doors(status)==-1);
  auto both=status;both["gcode_button Door_button1"]={{"state","PRESSED"}};both["gcode_button Door_button2"]={{"state","RELEASED"}};
  assert(doors(both)==2);
  both["gcode_button Door_button1"]["state"]="RELEASED";assert(doors(both)==3);
  both["gcode_button Door_button1"]["state"]="PRESSED";both["gcode_button Door_button2"]["state"]="PRESSED";assert(doors(both)==0);
  {auto one=status;one["gcode_button Door_button1"]={{"state","RELEASED"}};assert(doors(one)==1);}
  {auto bad=both;bad["gcode_button Door_button1"]["state"]="open";bad["gcode_button Door_button2"]=Json("RELEASED");assert(doors(bad)==-1);}
  {auto down=both;down["gcode_button Door_button2"]["state"]="RELEASED";down["webhooks"]["state"]="shutdown";assert(doors(down)==-1);}
 }
 {
  // Nozzle touch status and the measured/measuring progress fields.
  const std::string attempt_request(32,'c');
  Json touch={{"protocol",2},{"request",attempt_request},{"heads",Json::array({0,1,2,3})},{"flagged",Json::array({1,3})},{"restore","none"}};
  Json progress={{"protocol",1},{"head",2},{"phase","height"},{"request",attempt_request}};
  auto input=status;input["wmp_recovery"]={{"nozzle_touch",touch},{"calibration_progress",progress}};
  // heads entries that are not objects are left out.
  const Json expected_touch={{"protocol",2},{"request",attempt_request},{"heads",Json::array()},{"flagged",Json::array({1,3})},{"restore","none"}};
  assert(native::project(input,Json::object(),false,"session")["nozzle_touch"]==expected_touch);
  // Protocol 1 (the per-group rule) and any other protocol project to an empty object.
  for(const auto&protocol:{Json(1),Json(3),Json(2.0),Json("2"),Json()}){
   auto other=input;other["wmp_recovery"]["nozzle_touch"]["protocol"]=protocol;
   assert(native::project(other,Json::object(),false,"session")["nozzle_touch"]==Json::object());
  }
  {
   // Per-head readings: head, centres, centre_span and flagged. Malformed
   // entries and repeated heads are left out; anything but a list projects
   // to an empty list.
   const Json one={{"head",1},{"centres",3},{"centre_span",0.0062},{"flagged",false}};
   auto good=input;
   good["wmp_recovery"]["nozzle_touch"]["heads"]=Json::array({{{"head",0},{"centres",0},{"centre_span",0},{"flagged",false}},one,
                                                              {{"head",3},{"centres",5},{"centre_span",0.0217},{"flagged",true},{"extra",1}}});
   assert(native::project(good,Json::object(),false,"session")["nozzle_touch"]["heads"]==Json::array({
    {{"head",0},{"centres",0},{"centre_span",0},{"flagged",false}},one,{{"head",3},{"centres",5},{"centre_span",0.0217},{"flagged",true}}}));
   for(const auto&change:{Json{{"head",4}},Json{{"head",-1}},Json{{"head",1.5}},Json{{"head","1"}},Json{{"head",true}},Json{{"head",nullptr}},
                          Json{{"centres",-1}},Json{{"centres",1.5}},Json{{"centres","3"}},Json{{"centres",true}},
                          Json{{"centre_span",-0.001}},Json{{"centre_span","0.006"}},Json{{"centre_span",true}},Json{{"centre_span",nullptr}},
                          Json{{"flagged",1}},Json{{"flagged","true"}},Json{{"flagged",nullptr}}}){
    auto entry=one;entry.update(change);
    auto bad=input;bad["wmp_recovery"]["nozzle_touch"]["heads"]=Json::array({entry,{{"head",2},{"centres",1},{"centre_span",0.001},{"flagged",false}}});
    const auto projected=native::project(bad,Json::object(),false,"session")["nozzle_touch"];
    assert(projected["heads"]==Json::array({{{"head",2},{"centres",1},{"centre_span",0.001},{"flagged",false}}}));
    assert(projected["flagged"]==Json::array({1,3})&&projected["restore"]=="none");
   }
   for(const auto*key:{"head","centres","centre_span","flagged"}){
    auto entry=one;entry.erase(key);
    auto bad=input;bad["wmp_recovery"]["nozzle_touch"]["heads"]=Json::array({entry});
    assert(native::project(bad,Json::object(),false,"session")["nozzle_touch"]["heads"]==Json::array());
   }
   // Entries of the earlier protocol carry none of the fields.
   {auto old=input;old["wmp_recovery"]["nozzle_touch"]["heads"]=Json::array({{{"head",1},{"groups",3},{"spread_max",0.0062},{"over",0},{"discards",1},{"flagged",false}}});
    assert(native::project(old,Json::object(),false,"session")["nozzle_touch"]["heads"]==Json::array());}
   {auto twice=input;twice["wmp_recovery"]["nozzle_touch"]["heads"]=Json::array({one,{{"head",1},{"centres",9},{"centre_span",0.5},{"flagged",true}}});
    assert(native::project(twice,Json::object(),false,"session")["nozzle_touch"]["heads"]==Json::array({one}));}
   for(const auto&not_list:{Json(),Json::object(),Json("heads"),Json(1)}){
    auto bad=input;bad["wmp_recovery"]["nozzle_touch"]["heads"]=not_list;
    const auto projected=native::project(bad,Json::object(),false,"session")["nozzle_touch"];
    assert(projected["heads"]==Json::array()&&projected["flagged"]==Json::array({1,3}));
   }
   {auto absent=input;absent["wmp_recovery"]["nozzle_touch"].erase("heads");
    assert(native::project(absent,Json::object(),false,"session")["nozzle_touch"]["heads"]==Json::array());}
  }
  assert(native::project(input,Json::object(),false,"session")["calibration_progress"]==progress);
  assert(native::project(status,Json::object(),false,"session")["nozzle_touch"]==Json::object());
  for(const auto*restore:{"none","done","failed"}){
   auto good=input;good["wmp_recovery"]["nozzle_touch"]["restore"]=restore;
   assert(native::project(good,Json::object(),false,"session")["nozzle_touch"]["restore"]==restore);
  }
  for(const auto&flagged:{Json::array(),Json::array({0}),Json::array({0,1,2,3})}){
   auto good=input;good["wmp_recovery"]["nozzle_touch"]["flagged"]=flagged;
   assert(native::project(good,Json::object(),false,"session")["nozzle_touch"]["flagged"]==flagged);
  }
  {auto none=input;none["wmp_recovery"]["nozzle_touch"]["request"]="";
   assert(native::project(none,Json::object(),false,"session")["nozzle_touch"]["request"]=="");}
  for(const auto&bad_flagged:{Json::array({4}),Json::array({-1}),Json::array({1,1}),Json::array({3,1}),Json::array({1.5}),Json::array({"1"}),Json::array({true}),Json::array({0,1,2,3,3}),Json::array({0,1,2,3,4}),Json("1"),Json(1),Json::object(),Json()}){
   auto bad=input;bad["wmp_recovery"]["nozzle_touch"]["flagged"]=bad_flagged;
   assert(native::project(bad,Json::object(),false,"session")["nozzle_touch"]==Json::object());
  }
  for(const auto&change:{Json{{"restore","unknown"}},Json{{"restore",1}},Json{{"restore",nullptr}},Json{{"protocol",1}},Json{{"protocol","2"}},Json{{"request",std::string(31,'c')}},Json{{"request",std::string(32,'C')}},Json{{"request",1}}}){
   auto bad=input;bad["wmp_recovery"]["nozzle_touch"].update(change);
   assert(native::project(bad,Json::object(),false,"session")["nozzle_touch"]==Json::object());
  }
  for(const auto*key:{"protocol","request","flagged","restore"}){
   auto bad=input;bad["wmp_recovery"]["nozzle_touch"].erase(key);
   assert(native::project(bad,Json::object(),false,"session")["nozzle_touch"]==Json::object());
  }
  for(const auto&bad_value:{Json(),Json::array(),Json("none"),Json(1)}){
   auto bad=input;bad["wmp_recovery"]["nozzle_touch"]=bad_value;
   assert(native::project(bad,Json::object(),false,"session")["nozzle_touch"]==Json::object());
  }
  // measured and measuring are projected when present; absent they stay absent.
  {auto good=input;good["wmp_recovery"]["calibration_progress"]["measured"]=Json::array({0,2});good["wmp_recovery"]["calibration_progress"]["measuring"]=true;
   assert(native::project(good,Json::object(),false,"session")["calibration_progress"]==good["wmp_recovery"]["calibration_progress"]);}
  {auto good=input;good["wmp_recovery"]["calibration_progress"]["measured"]=Json::array();good["wmp_recovery"]["calibration_progress"]["measuring"]=false;
   assert(native::project(good,Json::object(),false,"session")["calibration_progress"]==good["wmp_recovery"]["calibration_progress"]);}
  for(const auto&bad_measured:{Json::array({4}),Json::array({1,1}),Json::array({2,1}),Json::array({1.5}),Json::array({0,1,2,3,3}),Json("0"),Json::object(),Json()}){
   auto bad=input;bad["wmp_recovery"]["calibration_progress"]["measured"]=bad_measured;bad["wmp_recovery"]["calibration_progress"]["measuring"]=false;
   assert(native::project(bad,Json::object(),false,"session")["calibration_progress"]==Json({{"phase","unavailable"}}));
  }
  for(const auto&bad_measuring:{Json(1),Json("true"),Json(),Json::array()}){
   auto bad=input;bad["wmp_recovery"]["calibration_progress"]["measured"]=Json::array();bad["wmp_recovery"]["calibration_progress"]["measuring"]=bad_measuring;
   assert(native::project(bad,Json::object(),false,"session")["calibration_progress"]==Json({{"phase","unavailable"}}));
  }
 }
 {
  // Attempt status: only the protocol values of offsets are projected, and
  // early_save_available only as a boolean; anything else reads as false.
  Json attempt={{"protocol",1},{"session",std::string(32,'a')},{"request",std::string(32,'c')},{"state","failed"},{"error","x"},
   {"next",3},{"earlier_results",true},{"offset_stage",true}};
  assert(native::calibration_attempt_result(attempt).size()==5);
  for(const auto*value:{"none","measured","stopped"}){
   attempt["offsets"]=value;const auto projected=native::calibration_attempt_result(attempt);
   assert(projected.size()==6&&projected["offsets"]==value);
  }
  for(const auto&bad:{Json("saved"),Json(1),Json(),Json::object()}){
   attempt["offsets"]=bad;assert(native::calibration_attempt_result(attempt).size()==5);
  }
  for(const bool value:{true,false}){
   attempt["offsets"]="stopped";attempt["early_save_available"]=value;const auto projected=native::calibration_attempt_result(attempt);
   assert(projected.size()==7&&projected["early_save_available"].is_boolean()&&projected.value("early_save_available",!value)==value);
  }
  for(const auto&bad:{Json(1),Json("true"),Json(),Json::object()}){
   attempt["early_save_available"]=bad;const auto projected=native::calibration_attempt_result(attempt);
   assert(!projected.contains("early_save_available")&&!projected.value("early_save_available",false));
  }
  // The fields pass through project() with the attempt.
  attempt["early_save_available"]=true;
  auto input=status;input["wmp_recovery"]={{"calibration_attempt_protocol",1},{"calibration_attempt",attempt}};
  const auto projected=native::project(input,Json::object(),false,"session")["calibration_attempt"];
  assert(projected.size()==7&&projected["offsets"]=="stopped"&&projected["early_save_available"]==true&&projected["state"]=="failed");
  // A refused attempt is projected: the scrub flow stops on it.
  attempt["state"]="refused";
  assert(native::calibration_attempt_result(attempt)["state"]=="refused");
 }
 auto position_status=status;position_status["wm_material"]["filament_position"]={{"ready",false},{"reason","Z position is unknown"}};
 auto standalone_position=native::project(position_status,Json::object(),false,"position-session");
 assert(standalone_position["filament_position"]==position_status["wm_material"]["filament_position"]);
 auto ace_position=native::project(position_status,raw,true,"position-session");
 assert(!ace_position.contains("filament_position"));
 auto thermal_status=status;
 thermal_status["wm_material"]={{"filament_sequence_protocol",1},{"filament_procedures",Json::array({{{"head","h0"},{"action","load"},{"source","external:h0"},{"token","review-token"},{"description","Prepare head"},{"temperature_description","Load temperature: 245 C. Material transition."},{"target",245},{"transition_note","Material transition."}}})}};
 auto thermal_projected=native::project(thermal_status,Json::object(),false,"session");
 assert(thermal_projected["procedures"][0]["target_temperature"]=="245"&&thermal_projected["procedures"][0]["transition_note"]=="Material transition.");
 assert(thermal_projected["procedures"][0]["temperature_description"]=="Load temperature: 245 C. Material transition.");
 App thermal_app(backend);thermal_app.update(thermal_projected);assert(thermal_app.data()["fresh"]==true);
 auto import_status=status;import_status["wm_material"]={{"profile_import_protocol",1},{"filament_catalogue",Json::array({{{"name","Saved preset"}}})}};
 auto deferred=native::project(import_status,Json::object(),false,"session");assert(deferred["capabilities"]["profile_import"]==false&&deferred["filament_catalogue"].empty());
 raw["management"]["units"]["ace0"]=Json::object();raw["management"]["source_settings"]["ace0:0"]=Json::object();
 raw["units"]=Json::array({{{"id","ace0"},{"name","Front ACE"},{"connected",false}}});
 raw["default_tool_map"]={{"7",{{"head","h1"},{"unit","ace0"},{"slot",0}}}};
 projected=native::project(status,raw,true,"session");assert(projected["units"][0]["assignments"]["ace0:0"]=="h1");assert(projected["sources"].back()["available"]==false);assert(projected["sources"].back()["slot"]==0);
 raw["devices"]["units"]["ace0"]={{"connected",true}};assert(native::project(status,raw,true,"session")["units"][0]["connected"]==true);
 raw["loaded"]["h1"]={{"state","loaded"},{"verified",true},{"identity",{{"material","PETG"},{"vendor","Actual brand"},{"color","#abcdef"}}},{"destination",{{"head","h1"},{"unit","ace0"},{"slot",0}}}};
 auto observed=native::project(status,raw,true,"session");assert(observed["heads"][1]["loaded"]["source"]=="ace0:0");assert(observed["heads"][1]["loaded"]["identity"]["brand"]=="Actual brand");
 assert(projected["revision"]!=observed["revision"]); // connection availability changed
 auto prior=observed["revision"];status["extruder"]["temperature"]=35.0;assert(native::project(status,raw,true,"session")["revision"]==prior);
 raw["default_tool_map"]["7"]["head"]="h0";assert(native::project(status,raw,true,"session")["revision"]!=prior);
 // A selected extruder is not physical attachment evidence, including openACE.
 status["toolhead"]={{"extruder","extruder1"}};auto mounting=native::project(status,raw,true,"session");assert(mounting["heads"][1]["active"]==false);assert(mounting["heads"][1]["mounting"]=="Attachment unknown");
 status["wm_material"]={{"attachment",{{"state","attached"},{"head","h1"}}}};mounting=native::project(status,raw,true,"session");assert(mounting["heads"][1]["active"]==true);assert(mounting["heads"][1]["mounting"]=="Mounted");assert(mounting["heads"][0]["mounting"]=="Not mounted");
 App mounted(backend);mounted.update(mounting);mounted.event("nav:tools");mounted.event("head:h1");auto mounted_frame=mounted.render();bool displayed=false;for(const auto&w:mounted_frame["widgets"])if(w["id"]=="mounting")displayed=w["text"]=="Mounted";assert(displayed);
 raw["management"]["add_candidates"]=Json::array({{{"expect_context",std::string(64,'a')},{"usb_serial","device-ABC"},{"usb_path","1-2.3"}}});
 auto discovered=native::project(status,raw,true,"session");assert(discovered["candidates"][0]["context"]==std::string(64,'a'));assert(discovered["candidates"][0]["device_label"]=="USB serial: device-ABC · 1-2.3");
 App discovery(backend);discovery.update(discovered);discovery.event("nav:adopt");auto discovery_frame=discovery.render();for(const auto&w:discovery_frame["widgets"])assert(w["text"].get<std::string>().find(std::string(64,'a'))==std::string::npos);
 raw["management"]["add_candidates"][0]["usb_serial"]=nullptr;assert(native::project(status,raw,true,"session")["candidates"][0]["device_label"]=="USB path: 1-2.3");

 auto flags=status;
 flags["wm_material"]["session_id"]="flags-session";
 flags["wm_material"]["filament_presence"]["h1"]={{"state","loaded"},{"evidence","sensor"},{"session","flags-session"}};
 flags["wm_material"]["filament_loaded"]["h1"]={{"state","empty"},{"sensor_present",true},{"evidence","sensor"},{"session","flags-session"}};
 auto waiting=native::project(flags,Json::object(),false,"flags-session");
 assert(waiting["heads"][1]["loaded"]["state"]=="empty");
 assert(waiting["heads"][1]["loaded"]["sensor_present"]==true);
 for(const auto&route:waiting["routes"])assert(!route.value("eligible",true));
 flags["wm_material"]["filament_loaded"]["h1"]["state"]="loaded";
 auto loaded_routes=native::project(flags,Json::object(),false,"flags-session")["routes"];
 for(const auto&route:loaded_routes)assert(route.value("eligible",false)==(route.value("head","")=="h1"));
 auto ace_waiting=raw;ace_waiting["loaded"]["h1"]={{"state","empty"}};
 assert(native::project(flags,ace_waiting,true,"session")["heads"][1]["loaded"]["state"]=="empty");

}
