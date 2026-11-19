// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../model.hpp"
#include <cmath>
#include <initializer_list>
namespace wmp_ui { namespace native {
// Scrub and calibration progress status (wmp_nozzle_scrub.py and
// wmp_calibration_progress.py, protocol 1). Anything else projects to phase
// "unavailable". request is the calibration attempt the status belongs to:
// 32 lowercase hexadecimal characters, or "" when no attempt has been admitted.
inline bool scrub_status_head(const Json&value){return value.contains("head")&&value["head"].is_number_integer()&&value["head"].get<int>()>=-1&&value["head"].get<int>()<=3;}
inline bool scrub_status_phase(const Json&value,std::initializer_list<const char*>phases){
 if(!value.contains("phase")||!value["phase"].is_string())return false;
 for(const auto*phase:phases)if(value["phase"]==phase)return true;
 return false;
}
inline bool scrub_status_request(const Json&value){
 if(!value.contains("request")||!value["request"].is_string())return false;
 const auto request=value["request"].get<std::string>();
 return request.empty()||(request.size()==32&&request.find_first_not_of("0123456789abcdef")==std::string::npos);
}
inline Json nozzle_scrub_status(const Json&value){
 if(!value.is_object()||!value.contains("protocol")||!value["protocol"].is_number_integer()||value["protocol"]!=1||!scrub_status_head(value)
    ||!scrub_status_phase(value,{"idle","mounting","positioning","heating","ended","failed"})
    ||!value.contains("target")||!value["target"].is_number()||!value.contains("error")||!value["error"].is_string()
    ||!scrub_status_request(value))return Json{{"phase","unavailable"}};
 return Json{{"protocol",1},{"head",value["head"]},{"phase",value["phase"]},{"target",value["target"]},{"error",value["error"].get<std::string>().substr(0,512)},{"request",value["request"]}};
}
// A list of 0..4 strictly ascending head numbers in 0..3.
inline bool scrub_status_heads(const Json&value){
 if(!value.is_array()||value.size()>4)return false;
 int previous=-1;
 for(const auto&head:value){
  if(!head.is_number_integer()||head.is_boolean())return false;
  const auto number=head.get<int>();
  if(number<=previous||number>3)return false;
  previous=number;
 }
 return true;
}
inline Json calibration_progress_status(const Json&value){
 if(!value.is_object()||!value.contains("protocol")||!value["protocol"].is_number_integer()||value["protocol"]!=1||!scrub_status_head(value)
    ||!scrub_status_phase(value,{"idle","homing","mounting","position","height","docking"})||!scrub_status_request(value))return Json{{"phase","unavailable"}};
 Json out{{"protocol",1},{"head",value["head"]},{"phase",value["phase"]},{"request",value["request"]}};
 // measured and measuring (heads whose offset was measured, probe running) are
 // absent from a backend without them; absent they stay absent.
 if(value.contains("measured")){if(!scrub_status_heads(value["measured"]))return Json{{"phase","unavailable"}};out["measured"]=value["measured"];}
 if(value.contains("measuring")){if(!value["measuring"].is_boolean())return Json{{"phase","unavailable"}};out["measuring"]=value["measuring"];}
 return out;
}
// Per-head readings of nozzle touch status: head (0..3), centres (0 or more),
// centre_span (mm, 0 or more) and flagged. An entry with any of them missing
// or malformed, or a head already listed, is left out; anything but a list
// projects to an empty list.
inline Json nozzle_touch_heads(const Json&value){
 Json out=Json::array();
 if(!value.is_array())return out;
 for(const auto&entry:value){
  if(!entry.is_object()||!entry.contains("head")||!entry["head"].is_number_integer()||!entry.contains("centres")||!entry["centres"].is_number_integer()
     ||!entry.contains("centre_span")||!entry["centre_span"].is_number()||!entry.contains("flagged")||!entry["flagged"].is_boolean())continue;
  const auto head=entry["head"].get<long long>(),centres=entry["centres"].get<long long>();
  const auto span=entry["centre_span"].get<double>();
  if(head<0||head>3||centres<0||centres>100000||!std::isfinite(span)||span<0||span>1000)continue;
  bool listed=false;
  for(const auto&previous:out)if(previous["head"]==head)listed=true;
  if(!listed)out.push_back(Json{{"head",int(head)},{"centres",int(centres)},{"centre_span",entry["centre_span"]},{"flagged",entry["flagged"]}});
 }
 return out;
}
// Nozzle touch status (wmp_nozzle_touch.py, protocol 2). Invalid input
// projects to an empty object; invalid heads entries alone are left out.
inline Json nozzle_touch_status(const Json&value){
 if(!value.is_object()||!value.contains("protocol")||!value["protocol"].is_number_integer()||value["protocol"]!=2||!scrub_status_request(value)
    ||!value.contains("flagged")||!scrub_status_heads(value["flagged"])
    ||!value.contains("restore")||!value["restore"].is_string()||(value["restore"]!="none"&&value["restore"]!="done"&&value["restore"]!="failed"))return Json::object();
 return Json{{"protocol",2},{"request",value["request"]},{"heads",nozzle_touch_heads(value.value("heads",Json()))},
             {"flagged",value["flagged"]},{"restore",value["restore"]}};
}
}}
