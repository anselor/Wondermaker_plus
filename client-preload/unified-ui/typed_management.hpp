// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// Candidate-only extension. Include before any legacy native/worker headers so
// enqueue and delivery both resolve the same serializer. The sealed source and
// its source/archive binding remain untouched. Wrong include order fails build.
#define management_command sealed_management_command
#include "../openace-compat/screen1113/source/client/management_commands.hpp"
#undef management_command
namespace wmp_openace {
inline std::string management_command(const json&status,const json&request) {
 if(request.value("action","")!="set_filament"||!request.contains("fields")||!request["fields"].is_object())return sealed_management_command(status,request);
 auto base=request;auto edited=status;
 const auto&m=status.at("management");std::string key;
 if(base.contains("unit"))(void)source_address(m,base,&key);else key=exact_text(base,"head");
 for(const auto*field:{"vendor","nozzle_temp_min","nozzle_temp_max"}){
  if(!base["fields"].contains(field))continue;
  if(std::string(field)=="vendor"){
   const auto vendor=exact_text(base["fields"],field);
   if(vendor.empty()||vendor.size()>64)throw std::runtime_error("Choose a brand between 1 and 64 characters");
   (void)safe_gcode_literal(vendor);
  }else if(!base["fields"][field].is_number()||base["fields"][field].get<double>()<0||base["fields"][field].get<double>()>350)throw std::runtime_error("Invalid filament temperature range");
  if(!management_capability(m,"identity_settings")||!m.at("identity_settings").contains(key))throw std::runtime_error("Filament settings unavailable");
  if(edited["management"]["identity_settings"][key].is_null())edited["management"]["identity_settings"][key]={{"values",{{"material",""},{"color",""},{"nozzle_temp",0},{"bed_temp",0},{"name",""},{"vendor",""},{"line",""},{"color_name",""},{"spool_id",nullptr},{"nozzle_temp_min",0},{"nozzle_temp_max",0}}}};
  edited["management"]["identity_settings"][key]["values"][field]=base["fields"][field];base["fields"].erase(field);
 }
 (void)sealed_management_command(status,base);
 return sealed_management_command(edited,base);
}
}
