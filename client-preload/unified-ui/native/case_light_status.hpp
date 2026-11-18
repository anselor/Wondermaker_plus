// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../model.hpp"
#include <dlfcn.h>
namespace wmp_ui { namespace native {
using CaseLightStatusSink = void(*)(int,int,long long);
inline CaseLightStatusSink case_light_status_sink(){
 static auto sink=reinterpret_cast<CaseLightStatusSink>(dlsym(RTLD_DEFAULT,"wmp_case_light_observe_status"));
 return sink;
}
inline bool publish_case_light_status(const Json&status,std::int64_t received_at,CaseLightStatusSink sink){
 if(!sink||!status.contains("wmp_case_light"))return false;
 // Moonraker may retain object values after Klipper stops. Such a reply must
 // not renew the door observation used for screen wake.
 if(status.contains("webhooks")&&(!status.at("webhooks").is_object()||status.at("webhooks").value("state","")!="ready")){
  sink(-1,-1,-1);return false;
 }
 const auto&light=status.at("wmp_case_light");
 if(!light.is_object()||light.value("policy_version",0)!=2)return false;
 const auto enabled=light.value("enabled",Json());
 const int preference=enabled.is_boolean()?(enabled.get<bool>()?1:0):-1;
 int doors=0;bool found=false;
 for(int i=0;i<2;++i){
  const auto key="gcode_button Door_button"+std::to_string(i+1);
  if(!status.contains(key)||!status.at(key).is_object())continue;
  const auto state=status.at(key).value("state",Json());
  if(state=="RELEASED"){doors|=1<<i;found=true;}
  else if(state=="PRESSED")found=true;
 }
 sink(preference,found?doors:-1,received_at);return true;
}
inline void invalidate_case_light_status(CaseLightStatusSink sink){if(sink)sink(-1,-1,-1);}
}}
