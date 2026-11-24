// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../model.hpp"
namespace wmp_ui { namespace native {
// A normal Stop already has its own terminal result. Only suppress a duplicate
// stock warning when a fresh, matching receipt proves cleanup completed. Neither
// Stop intent alone nor text resembling a cancellation is enough authority.
inline bool confirmed_calibration_cancel_notice(const Json&data,
 const std::string&session,const std::string&request,const std::string&ticket,
 const std::string&text)noexcept {
 try {
  if(session.size()!=32||request.size()!=32||ticket.empty()||text.empty()
     ||!data.value("fresh",false)||data.value("printer_state","")!="ready"
     ||data.value("owner","")!="standalone"||data.value("calibration_active",true)
     ||data.value("calibration_session","")!=session
     ||!data.value("maintenance_cancel_requested",false)
     ||data.value("maintenance_cancel_session","")!=session
     ||data.value("maintenance_cancel_request","")!=request)return false;
  const auto attempt=data.value("calibration_attempt",Json::object());
  if(attempt.value("protocol",0)!=1||attempt.value("session","")!=session
     ||attempt.value("request","")!=request||attempt.value("ticket","")!=ticket
     ||attempt.value("state","")!="failed"||!attempt.value("cancel_requested",false)
     ||attempt.value("error","")!=text)return false;
  const auto phase=attempt.value("cancel_phase","");
  if(phase.empty())return false;
  const auto operation=attempt.value("operation","");
  const std::string prefix=operation=="home"?"Homing":operation=="calibration"?"Calibration":"";
  if(prefix.empty()||text!=prefix+" cancellation requested; stopped "+phase)return false;
  const auto cleanup=attempt.value("cancel_cleanup",Json::object());
  const auto offsets=cleanup.value("offsets",""),park=cleanup.value("park","");
  return cleanup.value("state","")=="complete"&&cleanup.value("error","").empty()
    &&(offsets=="restored"||offsets=="not_needed")
    &&(park=="parked"||park=="already_docked"||park=="not_moved"||(operation=="home"&&park=="held"));
 }catch(...){return false;}
}
}}
