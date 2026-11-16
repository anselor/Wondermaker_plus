// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../model.hpp"
#include "probe_editor_status.hpp"
#include <cstdint>
#include <cstdio>
namespace wmp_ui { namespace native {
inline Json calibration_save_result(const Json&value){
 if(!value.is_object()||!value.contains("protocol")||!value["protocol"].is_number_integer()||value["protocol"]!=1)return Json::object();
 for(const auto*key:{"session","request"})if(!value.contains(key)||!value[key].is_string()||value[key].get<std::string>().size()!=32||value[key].get<std::string>().find_first_not_of("0123456789abcdef")!=std::string::npos)return Json::object();
 if(!value.contains("state")||!value["state"].is_string())return Json::object();
 const auto state=value["state"].get<std::string>();if(state!="pending"&&state!="saved"&&state!="confirmed"&&state!="unconfirmed")return Json::object();
 if(value.contains("error")&&!value["error"].is_string())return Json::object();
 return Json{{"protocol",1},{"session",value["session"]},{"request",value["request"]},{"state",state},{"error",value.value("error","").substr(0,512)}};
}
inline Json calibration_attempt_result(const Json&value){
 if(!value.is_object()||!value.contains("protocol")||!value["protocol"].is_number_integer()||value["protocol"]!=1)return Json::object();
 for(const auto*key:{"session","request"})if(!value.contains(key)||!value[key].is_string()||value[key].get<std::string>().size()!=32||value[key].get<std::string>().find_first_not_of("0123456789abcdef")!=std::string::npos)return Json::object();
 if(!value.contains("state")||!value["state"].is_string()||!value.contains("error")||!value["error"].is_string())return Json::object();
 const auto state=value["state"].get<std::string>();if(state!="pending"&&state!="refused"&&state!="failed"&&state!="saved")return Json::object();
 return Json{{"protocol",1},{"session",value["session"]},{"request",value["request"]},{"state",state},{"error",value["error"].get<std::string>().substr(0,512)}};
}
// Brand names from OrcaSlicer CreatePresetsDialog.cpp, filament_vendors,
// supplemented with Bambu Lab (reserved/excluded in Orca custom creation),
// Generic and WonderMaker for this filament-management catalogue.
// snapshot f55615d7488fe570942f5e25548b8ab9b30778d0 (2026-11-08).
// https://github.com/OrcaSlicer/OrcaSlicer/blob/f55615d7488fe570942f5e25548b8ab9b30778d0/src/slic3r/GUI/CreatePresetsDialog.cpp
inline Json filament_brands(const Json&sources){
 static const std::vector<std::string> catalogue={
  "3D BEST-Q",
  "3D Hero",
  "3D-Fuel",
  "3Dgenius",
  "3DJake",
  "3DXTECH",
  "Aceaddity",
  "AddNorth",
  "Amazon Basics",
  "AMOLEN",
  "Ankermake",
  "Anycubic",
  "Atomic",
  "AzureFilm",
  "Bambu Lab",
  "BASF",
  "Bblife",
  "BCN3D",
  "Beyond Plastic",
  "California Filament",
  "Capricorn",
  "CC3D",
  "CERPRiSE",
  "colorFabb",
  "Comgrow",
  "Cookiecad",
  "Creality",
  "Das Filament",
  "DO3D",
  "DOW",
  "DREMC",
  "DSM",
  "Duramic",
  "ELEGOO",
  "Eryone",
  "Essentium",
  "eSUN",
  "Extrudr",
  "Fiberforce",
  "Fiberlogy",
  "Fil X",
  "FilaCube",
  "Filamentive",
  "FilamentOne",
  "Fillamentum",
  "FLASHFORGE",
  "Formfutura",
  "Francofil",
  "FusRock",
  "GEEETECH",
  "Generic",
  "Giantarm",
  "Gizmo Dorks",
  "GreenGate3D",
  "HATCHBOX",
  "Hello3D",
  "IC3D",
  "IEMAI",
  "IIID Max",
  "INLAND",
  "iProspect",
  "iSANMATE",
  "Justmaker",
  "Keene Village Plastics",
  "Kexcelled",
  "LDO",
  "MakerBot",
  "MatterHackers",
  "MIKA3D",
  "NinjaTek",
  "Nobufil",
  "Novamaker",
  "OVERTURE",
  "OVVNYXE",
  "Polymaker",
  "Priline",
  "Printed Solid",
  "Protopasta",
  "Prusament",
  "Push Plastic",
  "R3D",
  "RatRig",
  "Re-pet3D",
  "re3D",
  "Recreus",
  "Regen",
  "Sain SMART",
  "SliceWorx",
  "Snapmaker",
  "SnoLabs",
  "Spectrum",
  "SUNLU",
  "Tianse",
  "TTYT3D",
  "UltiMaker",
  "Valment",
  "Verbatim",
  "VO3D",
  "Voxelab",
  "VOXELPLA",
  "WonderMaker",
  "YOOPAI",
  "Yousu",
  "Ziro",
  "Zyltech",
 };
 auto brands=catalogue;
 // Retain the spelling of saved identities so the selected value still matches.
 for(const auto&source:sources){
  auto brand=identity_display_text(source.value("identity",Json::object()),"brand","");
  if(brand.empty())continue;
  auto found=std::find_if(brands.begin(),brands.end(),[&](const std::string&b){return brand_sort_key(b)==brand_sort_key(brand);});
  if(found==brands.end())brands.push_back(brand);else *found=brand;
 }
 std::sort(brands.begin(),brands.end(),[](const std::string&a,const std::string&b){return brand_sort_key(a)<brand_sort_key(b);});
 return brands;
}
inline Json identity(const Json&row){
 if(!row.is_object())return {{"brand","Generic"},{"material","Unknown"},{"color","#888888"}};
 auto brand=row.value("vendor","");if(brand.empty())brand="Generic";
 return {{"brand",brand},{"material",row.value("material","Unknown")},{"color",row.value("color","#888888")}};
}
inline std::string revision(const Json&value){std::uint64_t h=14695981039346656037ULL;for(unsigned char c:value.dump())h=(h^c)*1099511628211ULL;return std::to_string(h);}
// Backend evidence to display model. Never equates configured identity with
// loaded identity; absent physical evidence stays unknown.
inline Json project(const Json&status,const Json&ace,bool present,const std::string&standalone_session){
 Json out={{"owner",present?"openace":"standalone"},{"session",present?std::to_string(ace.at("session_id").get<long long>()):standalone_session},{"fresh",true},
 {"heads",Json::array()},{"sources",Json::array()},{"units",Json::array()},{"routes",Json::array()},{"candidates",Json::array()},{"capabilities",Json::object()},{"job",{{"state","unknown"}}}};
 // Moonraker can return recent object snapshots after Klipper shuts down.
 // A successful query alone cannot make those snapshots actionable.
 const auto screen_helper=status.value("wm_material",Json::object());
 const auto heater_settings=screen_helper.value("heater_settings",status.value("configfile",Json::object()).value("settings",Json::object()));
 const auto printer_state=status.value("webhooks",Json::object()).value("state","unknown");
 out["printer_state"]=printer_state;out["fresh"]=printer_state=="ready";
 if(!present&&status.contains("wm_material")&&status["wm_material"].contains("session_id"))out["session"]=status["wm_material"]["session_id"];
 out["command_generation"]=screen_helper.value("command_generation",0LL);
 auto stats=status.value("print_stats",Json::object());auto state=stats.value("state","unknown");
 if(state=="standby"||state=="cancelled")state="idle";
 if(!present){
  const bool paused=status.value("pause_resume",Json::object()).value("is_paused",false);
  const bool sd_active=status.value("virtual_sdcard",Json::object()).value("is_active",false);
  if(paused)state="paused";
  else if(sd_active)state="printing";
  else if(state=="error")state="idle";
  out["sd_active"]=sd_active;out["paused"]=paused;
 }
 out["job"]={{"state",state},{"id",stats.value("filename","")},{"name",stats.value("filename","")},{"allowed_actions",Json::array()}};
 if(present){
  auto helper=status.value("wm_material",Json::object());
  out["openace_print_start_protocol"]=helper.value("openace_print_start_protocol",0);
  out["print_helper_session"]=helper.value("session_id","");
  out["print_submission"]=helper.value("print_submission",Json::object());
  out["ace_session"]=ace.at("session_id");out["ace_config_revision"]=ace.value("config_revision",Json());
  out["ace_job"]=ace.value("job",Json());
 }
 const auto management=ace.value("management",Json::object());const auto identities=management.value("identity_settings",Json::object());
 Json units=management.value("units",Json::object());Json settings=management.value("source_settings",Json::object());
 Json routes=ace.value("default_tool_map",Json::object());
 for(int i=0;i<4;++i){std::string heater=i?"extruder"+std::to_string(i):"extruder",head="h"+std::to_string(i);if(!status.contains(heater))continue;
  const auto&temp=status.at(heater);Json loaded={{"state","unknown"}};
  for(const auto&h:ace.value("heads",Json::array()))if(h.value("id","")==head&&h.value("contents","")=="empty_unrecorded")loaded["state"]="empty";
  if(ace.contains("loaded")&&ace["loaded"].is_object()&&ace["loaded"].contains(head)) {
   const auto&actual=ace["loaded"][head];auto observed=actual.value("state","unknown");
   if(observed=="empty")loaded["state"]="empty";
   else if(observed=="loaded"&&actual.value("verified",false)&&actual.contains("destination")&&actual["destination"].is_object()&&actual.contains("identity")&&actual["identity"].is_object()) {
    const auto&dest=actual["destination"];
    auto source=dest.contains("unit")&&dest["unit"].is_string()?dest["unit"].get<std::string>()+":"+std::to_string(dest.at("slot").get<int>()):"external:"+head;
    loaded={{"state","loaded"},{"source",source},{"identity",identity(actual["identity"])}};
   }
  }
  if(!present){auto wm=status.value("wm_material",Json::object());auto checks=wm.value("filament_loaded",wm.value("filament_presence",Json::object()));if(checks.contains(head)&&checks[head].value("evidence","")=="sensor"&&checks[head].value("session","")==out.value("session",""))loaded=checks[head];}
  if(present){
   const auto sensed=status.value("wm_material",Json::object()).value("filament_presence",Json::object()).value(head,Json::object());
   if(sensed.value("state","")=="empty")loaded={{"state","empty"},{"evidence","sensor"}};

  }
  auto attachment=status.value("wm_material",Json::object()).value("attachment",Json::object());
  bool active=status.value("toolhead",Json::object()).value("extruder","")==heater;
  active=active&&attachment.value("state","")=="attached"&&attachment.value("head","")==head;
  std::string mounting=(attachment.value("state","")=="attached"&&attachment.value("head","")==head)?"Mounted":attachment.value("state","")=="empty"?"No head mounted":attachment.value("state","")=="attached"&&attachment.value("head","")!=head?"Not mounted":"Attachment unknown";
  out["heads"].push_back({{"id",head},{"name","Head "+std::to_string(i+1)},{"actual",int(temp.value("temperature",0.0))},{"target",int(temp.value("target",0.0))},{"active",active},{"mounting",mounting},{"can_extrude",temp.value("can_extrude",false)},{"loaded",loaded}});
  const auto nozzle_config=heater_settings.value(heater,Json::object());
  std::string diameter="Unknown";
  if(nozzle_config.contains("nozzle_diameter")&&nozzle_config["nozzle_diameter"].is_number()){
   const double d=nozzle_config["nozzle_diameter"].get<double>();
   if(d>0&&d<=2){diameter=std::to_string(d);while(!diameter.empty()&&diameter.back()=='0')diameter.pop_back();if(diameter.back()=='.')diameter.pop_back();diameter+=" mm";}
  }
  out["heads"].back()["nozzle"]={{"diameter",diameter},{"material","Unknown"}};
  const auto saved_nozzles=status.value("wm_material",Json::object()).value("nozzles",Json::object());
  if(!present&&saved_nozzles.contains(head)){
   const auto saved=saved_nozzles.at(head);char mm[24];std::snprintf(mm,sizeof(mm),"%.1f mm",saved.value("diameter",0.0));
   out["heads"].back()["nozzle"]={{"diameter",mm},{"material",saved.value("material","Unknown")},{"saved_diameter",saved.value("diameter",0.0)},{"active_diameter",saved.value("active_diameter",0.0)},{"restart_required",saved.value("restart_required",false)}};
  }
  auto configured=identities.contains(head)&&identities[head].is_object()?identity(identities[head].value("values",Json::object())):identity(Json());
  if(!present){auto settings=status.value("wm_material",Json::object()).value("identities",Json::object());if(settings.contains(head))configured=settings[head];}
  out["sources"].push_back({{"id","external:"+head},{"name","Head "+std::to_string(i+1)},{"kind","external"},{"head",head},{"available",true},{"identity",configured}});
 }
 for(auto it=units.begin();it!=units.end();++it){const auto uid=it.key();std::string name=uid;bool connected=false;
  for(const auto&u:ace.value("units",Json::array()))if(u.value("id","")==uid){name=u.value("name",uid);}
  auto device_units=ace.value("devices",Json::object()).value("units",Json::object());if(device_units.contains(uid))connected=device_units[uid].value("connected",false);
  Json assignments=Json::object();
  for(auto source=settings.begin();source!=settings.end();++source){auto key=source.key();if(key.compare(0,uid.size()+1,uid+":")!=0)continue;
   const int slot=std::stoi(key.substr(uid.size()+1));std::string head;
   for(const auto&r:routes)if(r.is_object()&&r.contains("unit")&&r["unit"]==uid&&r.value("slot",-1)==slot){if(!head.empty()&&head!=r.value("head","")){head.clear();break;}head=r.value("head","");}
   assignments[key]=head;auto id=identities.contains(key)&&identities[key].is_object()?identity(identities[key].value("values",Json::object())):identity(Json());
   out["sources"].push_back({{"id",key},{"unit",uid},{"slot",slot},{"name","Slot "+std::to_string(slot+1)},{"head",head},{"kind","ace"},{"available",connected&&!head.empty()},{"identity",id}});
  }
  out["units"].push_back({{"id",uid},{"name",name},{"connected",connected},{"assignments",assignments}});
 }
 // Standalone preview selects physical destinations for a new per-print map.
 // The prior vendor map is an admission expectation, not a list of available
 // heads. openACE still supplies authoritative virtual tool routes.
 Json tool_routes=routes;
 if(!present){
  tool_routes=Json::object();
  for(const auto&h:out["heads"]){auto head=h.at("id").get<std::string>();
   out["routes"].push_back({{"id","head:"+head},{"kind","physical"},{"source","external:"+head},{"head",head},{"label",h.at("name").get<std::string>()+" · External"},{"eligible",status.value("wm_material",Json::object()).contains("filament_loaded")&&h.value("loaded",Json::object()).value("state","")=="loaded"},{"reason",h.value("loaded",Json::object()).value("state","")=="loaded"?"":"Load filament before selecting this head."},{"sliced_rows",Json::array()}});
   const auto helper=status.value("wm_material",Json::object());
   if(helper.value("print_material_confirmation_protocol",0)==1){
    auto loaded=h.value("loaded",Json::object());const bool sensor=loaded.value("sensor_present",loaded.value("evidence","")=="sensor"&&loaded.value("state","")=="loaded");
    out["routes"].back()["eligible"]=sensor;out["routes"].back()["material_confirmation_required"]=loaded.value("state","")!="loaded";
    out["routes"].back()["reason"]=sensor?"":"Filament sensor does not confirm loaded filament.";
   }
  }
 }
 if(tool_routes.is_object())for(auto it=tool_routes.begin();it!=tool_routes.end();++it){
  auto tool=it.key();if(tool.empty()||tool.size()>2||tool.find_first_not_of("0123456789")!=std::string::npos)continue;
  int number=std::stoi(tool);if(number>31||std::to_string(number)!=tool)continue;
  const auto&route=it.value();if(!route.is_object()||!route.contains("head")||!route["head"].is_string())continue;
  auto head=route["head"].get<std::string>();std::string source="external:"+head,label="Tool T"+tool;
  if(route.contains("unit")&&!route["unit"].is_null()){
   if(!route["unit"].is_string()||!route.contains("slot")||!route["slot"].is_number_integer())continue;
   int slot=route["slot"].get<int>();if(slot<0||slot>3)continue;
   auto uid=route["unit"].get<std::string>();source=uid+":"+std::to_string(slot);std::string name=uid;
   for(const auto&u:out["units"])if(u.value("id","")==uid)name=u.value("name",uid);
   label+=" · "+name+" · Slot "+std::to_string(slot+1);
  }
  bool installed=false;for(const auto&h:out["heads"])if(h.value("id","")==head){installed=true;label+=" · "+h.value("name",head);}
  if(!installed)continue;
  bool available=false;for(const auto&s:out["sources"])if(s.value("id","")==source&&s.value("head","")==head)available=s.value("available",false);
  auto blocked=ace.value("blocked_tools",Json::object());std::string reason=available?"":"Source is disconnected or unassigned";
  if(present&&blocked.contains(tool)){available=false;reason=blocked[tool].is_string()?blocked[tool].get<std::string>():"Tool is blocked";}
  out["routes"].push_back({{"id","T"+tool},{"tool",number},{"source",source},{"head",head},{"label",label},{"eligible",available},{"reason",reason},{"sliced_rows",Json::array()}});
 }
 int next=0;for(const auto&c:management.value("add_candidates",Json::array())){
  while(units.contains("ace"+std::to_string(next))){++next;}
  auto name="ace"+std::to_string(next++);
  auto serial=c.contains("usb_serial")&&c["usb_serial"].is_string()?c["usb_serial"].get<std::string>():"";auto path=c.contains("usb_path")&&c["usb_path"].is_string()?c["usb_path"].get<std::string>():"";
  std::string device=serial.empty()?(path.empty()?"Device identity unavailable":"USB path: "+path):"USB serial: "+serial+(path.empty()?"":" · "+path);
  out["candidates"].push_back({{"id",c.value("expect_context","")},{"name",name},{"device_label",device},{"logical_name",name},{"context",c.value("expect_context","")}});
 }
 if(!present){
  auto helper=status.value("wm_material",Json::object());
  for(const auto*key:{"print_sequence_protocol","print_request_sequence","print_material_confirmation_protocol","material_request_sequence_protocol","filament_request_sequence","toolhead_request_sequence"})out[key]=helper.value(key,0LL);
  out["print_start_protocol"]=helper.value("print_start_protocol",0);out["print_submission"]=helper.value("print_submission",Json::object());
  out["physical_mapping"]=Json::array();auto saved=status.value("save_variables",Json::object()).value("variables",Json::object());for(int i=0;i<4;++i)out["physical_mapping"].push_back(saved.value("box_modify_t"+std::to_string(i),Json()));
  if(helper.contains("physical_mapping"))out["physical_mapping"]=helper["physical_mapping"];
  out["identity_revision"]=status.value("wm_material",Json::object()).value("identity_revision","");
  out["filament_recipe_write_protocol"]=helper.value("filament_recipe_write_protocol",Json());
  out["filament_recipe_write"]=helper.value("filament_recipe_write",Json::object());
  out["paused_filament"]=helper.value("paused_filament",Json::object());
  out["resume_progress"]=helper.value("resume_progress",Json::object());
  out["paused_toolhead_actions"]=helper.value("paused_toolhead_actions",Json::object());
 }
  out["heater_limits"]=Json::object();
  const auto&config=heater_settings;
  for(const auto&h:out["heads"]){auto head=h.at("id").get<std::string>();int i=head[1]-'0';auto heater=i?"extruder"+std::to_string(i):"extruder";
   if(config.contains(heater)){const auto&c=config[heater];if(c.contains("min_temp")&&c["min_temp"].is_number()&&c.contains("max_temp")&&c["max_temp"].is_number()&&c["max_temp"].get<double>()>c["min_temp"].get<double>())out["heater_limits"][head]={{"min",c["min_temp"]},{"max",c["max_temp"]}};}
  }
 out["heater_manual_ready"]=!present||(ace.contains("operation")&&ace["operation"].is_null()&&(state=="idle"||state=="complete"));
 out["capabilities"]={{"confirm_filament",!present&&status.value("wm_material",Json::object()).value("filament_check_protocol",0)==1},{"step",!present&&status.contains("gcode_macro WMP_EXTRUDER_STEP")},{"temperature",!out.value("heater_limits",Json::object()).empty()},{"save_identity",present||status.value("wm_material",Json::object()).value("identity_writable",false)},{"save_unit",present},{"adopt",present}};
 out["revision"]=revision(Json{{"owner",out["owner"]},{"session",out["session"]},{"command_generation",out["command_generation"]},{"ace_config_revision",out.value("ace_config_revision",Json())},{"print_helper_session",out.value("print_helper_session",Json())},{"identities",identities},{"units",units},{"routes",routes},{"sources",settings},{"heater_limits",out.value("heater_limits",Json::object())},{"identity_revision",out.value("identity_revision","")},{"route_choices",out["routes"]},{"physical_mapping",out.value("physical_mapping",Json::array())},{"paused_filament",out.value("paused_filament",Json::object())}});
 {auto helper=status.value("wm_material",Json::object());bool supported=helper.value(present?"openace_unload_protocol":"filament_sequence_protocol",0)==1;
  out["capabilities"]["load"]=present?helper.value("openace_load_protocol",0)==1:supported;out["capabilities"]["unload"]=supported;
  out["filament_operation"]=helper.value("filament_operation",Json::object());out["procedures"]=Json::array();
  out["procedure_errors"]=helper.value("filament_procedure_errors",Json::object());
  if(!present)out["filament_position"]=helper.value("filament_position",Json::object());
  if(supported||out["capabilities"]["load"].get<bool>())for(const auto&p:helper.value("filament_procedures",Json::array())){
   Json plan={{"revision",out["revision"]}};for(const auto&key:{"head","action","source","token"})plan[key]=p.at(key);
   plan["description"]=present?p.at("description"):p.contains("description")&&p["description"].is_string()?p["description"]:Json("");
   if(p.contains("temperature_description")&&p["temperature_description"].is_string())plan["temperature_description"]=p["temperature_description"];
   if(p.contains("target")&&p["target"].is_number())plan["target_temperature"]=p["target"].dump();
   if(p.contains("transition_note")&&p["transition_note"].is_string())plan["transition_note"]=p["transition_note"];
   out["procedures"].push_back(plan);
  }
 }
 out["identification"]=status.value("wmp_recovery",Json::object()).value("identification",Json::object());
 // Maintenance/restart must not discard unresolved cancellation or recovery
 // merely because print_stats already reports idle/cancelled.
 {
  const auto helper=status.value("wm_material",Json::object());
  out["recovery_restore_error"]=present?helper.value("recovery_restore_error",""):operation_display_text(helper,"recovery_restore_error","");
  bool held=present&&!out["recovery_restore_error"].get<std::string>().empty();
  for(const auto*key:{"print_cancel","recovery_attempt"}){
   const auto record=helper.value(key,Json::object());
   if(!record.is_object()){if(present)held=true;continue;}
   if(record.empty())continue;
   if(!record.contains("state")||!record["state"].is_string()){if(present)held=true;continue;}
   const auto state=record["state"].get<std::string>();
   // Recovery DISCARD ends in abandoned, whereas a refused cancellation ends
   // in failed. Do not leave a resolved recovery holding all maintenance, or
   // accept a terminal state belonging to the other protocol.
   const bool recovery=std::string(key)=="recovery_attempt";
   if(present){if(state!="complete"&&state!=(recovery?"abandoned":"failed"))held=true;}
   else if(state=="pending"||state=="running"||state=="stopping")held=true;
  }
  out["managed_operation_hold"]=held;
 }
 const auto attempt_protocol=status.value("wmp_recovery",Json::object()).value("calibration_attempt_protocol",Json());
 out["calibration_attempt_protocol"]=attempt_protocol.is_number_integer()&&attempt_protocol==1?1:0;
 const auto ticket_protocol=status.value("wmp_recovery",Json::object()).value("calibration_ticket_protocol",Json());
 const auto next_ticket=status.value("wmp_recovery",Json::object()).value("calibration_next_ticket",Json());
 out["calibration_ticket_protocol"]=ticket_protocol.is_number_integer()&&ticket_protocol==1?1:0;
 out["calibration_next_ticket"]=next_ticket.is_string()?next_ticket:Json("");
 out["calibration_attempt"]=calibration_attempt_result(status.value("wmp_recovery",Json::object()).value("calibration_attempt",Json()));
 out["calibration_save_result"]=calibration_save_result(status.value("wmp_recovery",Json::object()).value("calibration_save_result",Json()));
 out["calibration_checkpoint"]=status.value("wmp_recovery",Json::object()).value("calibration_checkpoint","");
 out["calibration_session"]=status.value("wmp_recovery",Json::object()).value("calibration_session","");
 out["calibration_failed"]=present?status.value("wmp_recovery",Json::object()).value("calibration_failed",""):operation_display_text(status.value("wmp_recovery",Json::object()),"calibration_failed","");
 out["calibration_active"]=status.value("wmp_recovery",Json::object()).value("calibration_active",false);
 out["probe_editor"]=probe_editor_status(status.value("wmp_recovery",Json::object()).value("probe_editor",Json()),out["calibration_session"].get<std::string>(),!present);
 out["attachment"]=status.value("wm_material",Json::object()).value("attachment",Json::object());
 out["toolhead_operation"]=status.value("wm_material",Json::object()).value("toolhead_operation",Json::object());
 out["toolchange_pause"]=status.value("wm_material",Json::object()).value("toolchange_pause",Json::object());
 out["capabilities"]["toolhead_action"]=!present&&status.value("wm_material",Json::object()).value("toolhead_action_protocol",0)==1;
 out["capabilities"]["profile_import"]=false; // Deferred from this release.
 out["profile_import"]=status.value("wm_material",Json::object()).value("profile_import",Json::object());
 out["capabilities"]["save_nozzle"]=!present&&status.value("wm_material",Json::object()).value("nozzle_settings_protocol",0)==1;
 out["nozzle_settings"]=status.value("wm_material",Json::object()).value("nozzles",Json::object());
 out["filament_recovery_protocol"]=status.value("wm_material",Json::object()).value("filament_recovery_protocol",0);
 out["toolhead_recovery_protocol"]=status.value("wm_material",Json::object()).value("toolhead_recovery_protocol",0);
 out["filament_cancel_protocol"]=status.value("wm_material",Json::object()).value("filament_cancel_protocol",0);
 out["nozzle_revision"]=status.value("wm_material",Json::object()).value("nozzle_revision","");
 out["nozzle_save"]=status.value("wm_material",Json::object()).value("nozzle_save",Json::object());
 out["filament_catalogue"]=Json::array(); // Preserve stored catalogues, hide import UI for now.
 // Built-in choices plus existing identities, without requiring profile imports.
 out["brands"]=filament_brands(out["sources"]);
 out["materials"]=Json::array({"PLA","PLA Silk","ABS","PETG","PLA Matte","PLA Metal","ABS Matte","PETG Matte","PVA","TPE","Marble","HIPS","TPU","PET","Wood","ASA","PA","PC","PCTG","PA6","PA12","PP"});
 for(const auto&name:status.value("wm_material",Json::object()).value("filament_materials",Json::array()))
  if(name.is_string()&&std::find(out["materials"].begin(),out["materials"].end(),name)==out["materials"].end())out["materials"].push_back(name);
 if(!present){
  // Labels are not command evidence. Keep receipt identity/state untouched and
  // localize malformed diagnostic text to the affected operation's display.
  for(const auto*key:{"filament_operation","toolhead_operation","nozzle_save","profile_import"}){
   auto&record=out[key];
   if(record.is_object()&&record.contains("message")&&!record["message"].is_string())
    record["message"]=std::string(key)+" message text unavailable.";
  }
  auto&submission=out["print_submission"];
  if(submission.is_object()&&submission.contains("error")&&!submission["error"].is_string())
   submission["error"]="Print submission error text unavailable.";
 }
 out["identity_edit_note"]=present?"Existing openACE profile brand and colour can be edited. Material changes need profile temperature support.":"Source settings only; editing does not change the filament already loaded.";
 return out;
}
}}
