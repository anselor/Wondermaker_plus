#pragma once
#include "openace_view.hpp"
#include <set>
#include <cmath>
#include <cstdlib>
namespace wmp_openace {
inline bool management_capability(const json&m,const std::string&key){
 if(!m.is_object()||!m.contains("capabilities")||!m["capabilities"].is_object())return false;
 const auto&caps=m["capabilities"];
 return caps.contains(key)&&caps[key].is_number_integer()&&!caps[key].is_boolean()&&caps[key]==1;
}
inline std::string safe_gcode_literal(const std::string&value){
 if(value.size()>256||std::any_of(value.begin(),value.end(),[](unsigned char c){
  return c<32||c==127||c=='#'||c=='*'||c==';'||c=='"'||c=='\\';
 }))throw std::runtime_error("This editor cannot safely send these characters; value was not changed");
 return "\""+value+"\"";
}
inline std::string scalar_number(const json&value){
 std::string text=value.is_string()?value.get<std::string>():value.is_number()?value.dump():"";
 if(text.empty()||text.size()>24||std::any_of(text.begin(),text.end(),[](char c){
  return !(c>='0'&&c<='9')&&c!='.'&&c!='-'&&c!='+'&&c!='e'&&c!='E';
 }))throw std::runtime_error("Enter a finite number");
 char*end=nullptr;double n=std::strtod(text.c_str(),&end);
 if(!end||*end||!std::isfinite(n))throw std::runtime_error("Enter a finite number");
 return text;
}
inline int exact_integer(const json&object,const char*name,int upper){
 if(!object.contains(name)||!object[name].is_number_integer()||object[name].is_boolean())throw std::runtime_error("Select a whole-number item");
 auto n=object[name].get<std::int64_t>();if(n<0||n>upper)throw std::runtime_error("Selection is outside this command's supported range");return int(n);
}
inline std::string exact_text(const json&object,const char*name){
 if(!object.contains(name)||!object[name].is_string())throw std::runtime_error("Missing selected value");
 return object[name].get<std::string>();
}
inline bool hex_context(const std::string&s){return s.size()==64&&std::all_of(s.begin(),s.end(),[](char c){return(c>='0'&&c<='9')||(c>='a'&&c<='f');});}
inline void known_keys(const json&object,const std::set<std::string>&keys){
 if(!object.is_object())throw std::runtime_error("Invalid form");
 for(auto it=object.begin();it!=object.end();++it)if(!keys.count(it.key()))throw std::runtime_error("Unsupported form field");
}
inline const json& current_head(const json&management,const std::string&head){
 if(!management.contains("head_settings")||!management["head_settings"].is_object()||!management["head_settings"].contains(head))throw std::runtime_error("Head is no longer configured");
 return management["head_settings"][head];
}
inline const json& current_unit(const json&management,const std::string&unit){
 if(!management.contains("units")||!management["units"].is_object()||!management["units"].contains(unit))throw std::runtime_error("Unit is no longer registered");
 return management["units"][unit];
}
inline std::string source_address(const json&m,const json&r,std::string*key=nullptr){
 auto unit=exact_text(r,"unit");current_unit(m,unit);int slot=exact_integer(r,"slot",255);
 auto source=unit+":"+std::to_string(slot);
 if(!m.contains("source_settings")||!m["source_settings"].contains(source))throw std::runtime_error("Slot is no longer configured");
 if(key)*key=source;
 return " UNIT="+safe_gcode_literal(unit)+" SLOT="+std::to_string(slot);
}
inline std::string fields_clause(const json&fields,const std::set<std::string>&numeric,const std::set<std::string>&textual){
 if(!fields.is_object()||fields.empty())throw std::runtime_error("Select a setting to change");
 std::string out;
 for(auto it=fields.begin();it!=fields.end();++it){
  std::string key=it.key(),value;
  if(numeric.count(key))value=scalar_number(it.value());
  else if(textual.count(key)){value=safe_gcode_literal(it.value().get<std::string>());}
  else throw std::runtime_error("Unsupported setting field");
  std::transform(key.begin(),key.end(),key.begin(),[](unsigned char c){return char(std::toupper(c));});
  out+=" "+key+"="+value;
 }return out;
}
// Typed fixed command vocabulary. No arbitrary command field, physical prepare,
// DONE, RECOVER, movement, reset-budget, approval or calibration-import action.
inline std::string management_command(const json&status,const json&r){
 if(!status.is_object()||!status.contains("management")||!status["management"].is_object())throw std::runtime_error("Management is unavailable");
 const auto&m=status["management"];
 if(!management_capability(m,"version"))throw std::runtime_error("Unsupported management version");
 known_keys(r,{"action","unit","slot","head","tool","context","name","fields"});
 std::string action=exact_text(r,"action"),out;
 std::set<std::string>allowed={"action"};
 if(action=="unit_add"||action=="unit_accept")allowed.insert({"unit","context"});
 else if(action=="unit_set")allowed.insert({"unit","fields"});
 else if(action=="unit_remove")allowed.insert("unit");
 else if(action=="unit_rename")allowed.insert({"unit","name"});
 else if(action=="map_tool")allowed.insert({"tool","head","unit","slot"});
 else if(action=="unmap_tool")allowed.insert("tool");
 else if(action=="source_set"||action=="source_reset")allowed.insert({"unit","slot","fields"});
 else if(action=="head_set"||action=="head_reset")allowed.insert({"head","fields"});
 else if(action=="set_filament")allowed.insert({"head","unit","slot","fields"});
 known_keys(r,allowed);
 if(action=="scan")out="OPENACE_UNIT_SCAN";
 else if(action=="unit_add"){
  if(!management_capability(m,"unit_add_expect_context"))throw std::runtime_error("Bound registration is unavailable");
  auto context=exact_text(r,"context");if(!hex_context(context))throw std::runtime_error("Refresh selected observation");
  const json*selected=nullptr;
  for(const auto&row:m.at("add_candidates"))if(row.value("expect_context","")==context)selected=&row;
  if(!selected)throw std::runtime_error("Displayed observation changed; refresh before Add");
  auto unit=exact_text(r,"unit");if(unit.empty())throw std::runtime_error("Enter a logical unit name");
  out="OPENACE_UNIT_ADD UNIT="+safe_gcode_literal(unit);
  if(selected->contains("usb_serial")&&(*selected)["usb_serial"].is_string()&&!(*selected)["usb_serial"].get<std::string>().empty())out+=" USB_SERIAL="+safe_gcode_literal((*selected)["usb_serial"]);
  else out+=" USB_PATH="+safe_gcode_literal(exact_text(*selected,"usb_path"));
  out+=" EXPECT_CONTEXT="+context;
 }else if(action=="unit_accept"){
  if(!management_capability(m,"unit_accept_expect_context"))throw std::runtime_error("Bound acceptance is unavailable");
  auto unit=exact_text(r,"unit"),context=exact_text(r,"context");const auto&row=current_unit(m,unit);
  if(!hex_context(context)||!row.contains("accept_context")||row["accept_context"]!=context)throw std::runtime_error("Displayed replacement changed; refresh before Accept");
  out="OPENACE_UNIT_ACCEPT UNIT="+safe_gcode_literal(unit)+" EXPECT_CONTEXT="+context;
 }else if(action=="unit_set"||action=="unit_remove"||action=="unit_rename"){
  auto unit=exact_text(r,"unit");current_unit(m,unit);
  out=(action=="unit_set"?"OPENACE_UNIT_SET":action=="unit_remove"?"OPENACE_UNIT_REMOVE":"OPENACE_RENAME_UNIT")+std::string(" UNIT=")+safe_gcode_literal(unit);
  if(action=="unit_set")out+=fields_clause(r.at("fields"),{"slots","feed_speed","retract_speed","max_feed_mm"},{"generation","usb_serial","usb_path","assist_mode","stop_survives_disconnect"});
  if(action=="unit_rename")out+=" NAME="+safe_gcode_literal(exact_text(r,"name"));
 }else if(action=="map_tool"||action=="unmap_tool"){
  out=(action=="map_tool"?"OPENACE_MAP_TOOL":"OPENACE_UNMAP_TOOL")+std::string(" TOOL=")+std::to_string(exact_integer(r,"tool",31));
  if(action=="map_tool"){
   auto head=exact_text(r,"head");current_head(m,head);out+=" HEAD="+safe_gcode_literal(head);
   if(r.contains("unit"))out+=source_address(m,r);
   else if(r.contains("slot"))throw std::runtime_error("Slot requires a selected unit");
  }
 }else if(action=="source_set"||action=="source_reset"||action=="head_set"||action=="head_reset"){
  if(!management_capability(m,"effective_settings"))throw std::runtime_error("Effective settings are unavailable");
  const bool source=action.compare(0,6,"source")==0;
  std::set<std::string> numeric=source?std::set<std::string>{"path_clear_mm","feeder_hold_mm","feeder_to_inlet_mm","feed_timeout_s","feed_to_sensor_mm"}:std::set<std::string>{"capture_mm","capture_step_mm"};
  std::set<std::string> text=source?std::set<std::string>{"unload_mode"}:std::set<std::string>{};
  std::string name=action;std::transform(name.begin(),name.end(),name.begin(),[](unsigned char c){return char(std::toupper(c));});out="OPENACE_"+name;
  if(source)out+=source_address(m,r);else{auto head=exact_text(r,"head");current_head(m,head);out+=" HEAD="+safe_gcode_literal(head);}
  if(action.find("_reset")!=std::string::npos){
   const auto&fields=r.at("fields");if(!fields.is_array()||fields.empty())throw std::runtime_error("Select reset fields");
   std::set<std::string>seen;std::string names;
   for(const auto&field:fields){auto key=field.get<std::string>();if((!numeric.count(key)&&!text.count(key))||!seen.insert(key).second)throw std::runtime_error("Unsupported reset field");names+=(names.empty()?"":",")+key;}
   out+=" FIELDS="+names;
  }else out+=fields_clause(r.at("fields"),numeric,text);
 }else if(action=="set_filament"){
  std::string key,address;
  if(r.contains("unit")){address=source_address(m,r,&key);if(r.contains("head"))throw std::runtime_error("Choose a head or slot, not both");}
  else{if(r.contains("slot"))throw std::runtime_error("Slot requires a selected unit");key=exact_text(r,"head");current_head(m,key);address=" HEAD="+safe_gcode_literal(key);}
  json old=nullptr;
  if(management_capability(m,"identity_settings"))old=m.at("identity_settings").at(key);
  else if(!status.contains("inventory")||!status["inventory"].is_object()
          ||(status["inventory"].contains(key)&&!status["inventory"][key].is_null()))
   throw std::runtime_error("Raw identity editing is unavailable; recorded names were not changed");
  json values=old.is_null()?json{{"material",""},{"color",""},{"nozzle_temp",0},{"bed_temp",0},{"name",""},{"vendor",""},{"line",""},{"color_name",""},{"spool_id",nullptr},{"nozzle_temp_min",0},{"nozzle_temp_max",0}}:old.at("values");
  const auto&fields=r.at("fields");known_keys(fields,{"material","nozzle_temp","color"});
  for(auto it=fields.begin();it!=fields.end();++it)values[it.key()]=it.value();
  std::string color=exact_text(values,"color");if(color.size()==7&&color[0]=='#')color=color.substr(1); // Explicit colour representation conversion, never label stripping.
  if(color.size()!=6||!std::all_of(color.begin(),color.end(),[](unsigned char c){return std::isxdigit(c);}))throw std::runtime_error("Enter exactly six hexadecimal colour digits");
  out="OPENACE_SET_FILAMENT"+address+" MATERIAL="+safe_gcode_literal(exact_text(values,"material"))+" TEMP="+scalar_number(values.at("nozzle_temp"))+" COLOR="+color;
  out+=" BED="+scalar_number(values.at("bed_temp"));
  for(const auto&pair:{std::make_pair("name","NAME"),{"vendor","VENDOR"},{"line","LINE"},{"color_name","COLOR_NAME"}})out+=" "+std::string(pair.second)+"="+safe_gcode_literal(exact_text(values,pair.first));
  out+=" TEMP_MIN="+scalar_number(values.at("nozzle_temp_min"))+" TEMP_MAX="+scalar_number(values.at("nozzle_temp_max"));
  if(!values.at("spool_id").is_null())out+=" SPOOL_ID="+std::to_string(exact_integer(values,"spool_id",2147483647));
 }else throw std::runtime_error("Unsupported screen action");
 if(out.size()>384)throw std::runtime_error("This command is too large for this bounded editor; nothing was sent");
 return out;
}
}
