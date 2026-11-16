// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../model.hpp"
#include <map>
namespace wmp_ui { namespace native {
// Group reported PLR work for presentation. Missing stages are never invented,
// and later work cannot turn an earlier failed/pending stage into completion.
inline Json plr_progress_steps(const Json&stages){
 const std::map<std::string,int>groups={
  {"review",0},{"review_blocked",0},{"await_preparation",1},{"context",1},
  {"bottom_z",1},{"home_xy",1},{"machine_frame",1},{"select_head",1},
  {"restore_mesh",1},{"heater_targets",2},{"fan_targets",2},{"heating",2},
  {"purge_position",3},{"prime",3},{"wipe",3},{"return_xy",4},{"return_z",4},
  {"return_mesh",4},{"restore_parser",4},{"select_file",5},{"restore_deposition",5},
  {"restore_routes",5},{"accounting",5},{"start_file",5}};
 const char*labels[]={"Check saved print","Prepare printer","Heat bed and nozzles","Prime and wipe","Return to print","Continue printing"};
 bool seen[6]={},complete[6]={true,true,true,true,true,true},running[6]={},failed[6]={};
 if(!stages.is_array())return Json::array();
 for(const auto&stage:stages){
  const auto found=groups.find(stage.value("name",""));const int i=found==groups.end()?1:found->second;
  const auto state=stage.value("state","");seen[i]=true;complete[i]=complete[i]&&state=="complete";
  running[i]=running[i]||state=="running";
  failed[i]=failed[i]||state=="failed"||state=="unknown"||state=="stopped";
 }
 auto rows=Json::array();
 for(int i=0;i<6;++i)if(seen[i])rows.push_back({{"label",labels[i]},{"state",failed[i]?"failed":running[i]?"running":complete[i]?"complete":"pending"}});
 return rows;
}
}}
