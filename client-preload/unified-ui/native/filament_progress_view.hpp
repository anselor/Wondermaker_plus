// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../model.hpp"
namespace wmp_ui { namespace native {
// Presentation only: keep the backend's action order and cancellation points.
// Combine adjacent actions, never move a later action before an earlier one.
inline Json filament_progress_view(const Json& rows, int active, bool tool, bool unloading=false) {
 Json view={{"steps",Json::array()}};
 std::string previous;
 for(unsigned i=0;i<rows.size();++i){
  const auto phase=rows[i].value("phase","");
  std::string group=phase,label=rows[i].value("label","");
  if(!tool){
   if(phase=="homing"||phase=="docking"||phase=="mounting"||phase=="preparing") {group="prepare";label="Prepare head";}
   else if(phase=="feeding"||phase=="purging"||phase=="wiping") {group="filament";label=unloading?"Unload filament":"Load filament";}
   else if(phase=="heating") {label="Heat nozzle";}
   else if(phase=="finishing") {label="Finish";}
   else if(phase.compare(0,7,"return_")==0||phase=="returning") {group="return";label="Return previous head";}
  }
  auto& steps=view["steps"];
  const std::string state=int(i)==active?"running":int(i)<active?"complete":"pending";
  if(steps.empty()||group!=previous) steps.push_back({{"label",label},{"state",state}});
  else {auto& last=steps.back();const auto prior=last.value("state","");
   last["state"]=prior=="running"||state=="running"?"running":prior=="complete"&&state=="complete"?"complete":"pending";
  }
  if(int(i)==active)view["heading"]=rows[i].value("label","");
  previous=group;
 }
 return view;
}
}}
