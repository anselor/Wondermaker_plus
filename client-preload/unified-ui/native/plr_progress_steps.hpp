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
  {"bottom_z",2},{"home_xy",3},{"machine_frame",3},{"select_head",4},
  {"restore_mesh",5},{"heater_targets",6},{"fan_targets",6},{"heating",6},
  {"purge_position",7},{"prime",7},{"wipe",7},{"return_xy",8},{"return_z",8},
  {"return_mesh",8},{"restore_parser",8},{"select_file",9},{"restore_deposition",9},
  {"restore_routes",9},{"accounting",9},{"start_file",9}};
 const char*labels[]={"Check saved print","Prepare printer","Home bed at bottom","Home X/Y","Select print head","Restore bed mesh","Heat bed and nozzles","Prime and wipe","Return to print","Continue printing"};
 bool seen[10]={},complete[10]={true,true,true,true,true,true,true,true,true,true},running[10]={},failed[10]={};
 if(!stages.is_array())return Json::array();
 for(const auto&stage:stages){
  const auto found=groups.find(stage.value("name",""));const int i=found==groups.end()?1:found->second;
  const auto state=stage.value("state","");seen[i]=true;complete[i]=complete[i]&&state=="complete";
  running[i]=running[i]||state=="running";
  failed[i]=failed[i]||state=="failed"||state=="unknown"||state=="stopped";
 }
 auto rows=Json::array();
 for(int i=0;i<10;++i)if(seen[i])rows.push_back({{"label",labels[i]},{"state",failed[i]?"failed":running[i]?"running":complete[i]?"complete":"pending"}});
 return rows;
}
}}
