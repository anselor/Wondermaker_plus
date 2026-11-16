// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_dialog_backdrop.hpp"
#include <functional>
#include <cstring>
namespace wmp_ui { namespace native {
inline bool stock_filament_service_page(const char*name){return name&&std::strcmp(name,"nozzle_flow_page")==0;}
// Stock 1.1.13 Nozzle Flow: Back=0, Load=1..4, Unload=5..8.
// Service events must never reach the vendor's status-check-disable prefix.
inline bool stock_service_event(void*event,const std::function<void(unsigned,bool)>&open){
 if(!event)return true;
 if(dialog_function<int(*)(void*)>(lv_event_get_code)(event)!=7)return true;
 const auto action=reinterpret_cast<std::uintptr_t>(dialog_function<void*(*)(void*)>(lv_event_get_user_data)(event));
 if(action>8)return true;
 auto*target=dialog_function<void*(*)(void*)>(lv_event_get_target)(event);
 auto*screen=dialog_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);
 for(unsigned depth=0;target&&depth<20;++depth){
  if(!dialog_function<bool(*)(void*)>(lv_obj_is_valid)(target)||dialog_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(target,1)||dialog_function<bool(*)(void*,unsigned)>(lv_obj_has_state)(target,128))return true;
  if(target==screen){if(action==0)return false;if(open)open(unsigned((action-1)%4),action<=4);return true;}
  target=dialog_function<void*(*)(void*)>(lv_obj_get_parent)(target);
 }
 return true;
}
// Maintenance 1.1.13: START=0 and PROBE_CALIBRATE=8 can dispatch
// preparation commands before backend calibration macros are reached.
// 0 delegates, 1 consumes stale events, 2 reports busy, 3 opens managed probe review.
inline int stock_maintenance_event(void*event,const std::function<bool()>&allowed){
 if(!event||dialog_function<int(*)(void*)>(lv_event_get_code)(event)!=7)return 1;
 const auto action=reinterpret_cast<std::uintptr_t>(dialog_function<void*(*)(void*)>(lv_event_get_user_data)(event));
 if(action>8)return 1;
 auto*target=dialog_function<void*(*)(void*)>(lv_event_get_target)(event);
 auto*screen=dialog_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);
 for(unsigned depth=0;target&&depth<20;++depth){
  if(!dialog_function<bool(*)(void*)>(lv_obj_is_valid)(target)||dialog_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(target,1)||dialog_function<bool(*)(void*,unsigned)>(lv_obj_has_state)(target,128))return 1;
  if(target==screen)return action==8?3:action==0?(allowed&&allowed()?0:2):0;
  target=dialog_function<void*(*)(void*)>(lv_obj_get_parent)(target);
 }
 return 1;
}
// Factory action 12 opens read-only managed probe review. Trigger modes, knife
// preparation and tool/wipe calibration need admission before vendor mutation.
// 0 delegates, 1 consumes stale/invalid events, 2 reports busy, 3 opens review.
inline int stock_factory_probe_event(void*event,const std::function<bool()>&allowed={}){
 if(!event||dialog_function<int(*)(void*)>(lv_event_get_code)(event)!=7)return 1;
 const auto action=reinterpret_cast<std::uintptr_t>(dialog_function<void*(*)(void*)>(lv_event_get_user_data)(event));
 if(action>15||action==11)return 1;
 auto*target=dialog_function<void*(*)(void*)>(lv_event_get_target)(event);
 auto*screen=dialog_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);
 for(unsigned depth=0;target&&depth<20;++depth){
  if(!dialog_function<bool(*)(void*)>(lv_obj_is_valid)(target)||dialog_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(target,1)||dialog_function<bool(*)(void*,unsigned)>(lv_obj_has_state)(target,128))return 1;
  if(target==screen){
   if(action==12)return 3;
   const bool machine=action==8||action==9||action==10||action==13||action==14;
   return machine&&(!allowed||!allowed())?2:0;
  }
  target=dialog_function<void*(*)(void*)>(lv_obj_get_parent)(target);
 }
 return 1;
}
// Knife editor: 0..5 select distance, 6/7 jog Z, 8 closes, 9 disables
// motors and saves probe_position. Gate before the stock display is mutated.
inline int stock_knife_event(void*event,const std::function<bool()>&allowed={}){
 if(!event||dialog_function<int(*)(void*)>(lv_event_get_code)(event)!=7)return 1;
 const auto action=reinterpret_cast<std::uintptr_t>(dialog_function<void*(*)(void*)>(lv_event_get_user_data)(event));
 if(action>9)return 1;
 auto*target=dialog_function<void*(*)(void*)>(lv_event_get_target)(event);
 auto*screen=dialog_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);
 for(unsigned depth=0;target&&depth<20;++depth){
  if(!dialog_function<bool(*)(void*)>(lv_obj_is_valid)(target)||dialog_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(target,1)||dialog_function<bool(*)(void*,unsigned)>(lv_obj_has_state)(target,128))return 1;
  if(target==screen)return (action==6||action==7||action==9)&&(!allowed||!allowed())?2:0;
  target=dialog_function<void*(*)(void*)>(lv_obj_get_parent)(target);
 }
 return 1;
}
// The verified Factory password-success helper sends a leveling trigger outside
// the event gates. Consume only that caller when machine admission refuses.
inline bool refuse_factory_confirmation(std::uintptr_t caller,const std::function<bool()>&allowed,const std::function<void()>&notice){
 if(caller!=0x4c4160)return false;
 if(allowed&&allowed())return false;
 if(notice)notice();
 return true;
}
inline bool stock_probe_page(const char*name){return name&&std::strcmp(name,"probe_calibrate_page")==0;}
// Both legacy editors use 0..11 for jog, 12 for abort and 13 for save.
// These clicks only open managed review; no legacy mutation or command survives.
inline bool stock_probe_editor_event(void*event){
 if(!event||dialog_function<int(*)(void*)>(lv_event_get_code)(event)!=7)return false;
 const auto action=reinterpret_cast<std::uintptr_t>(dialog_function<void*(*)(void*)>(lv_event_get_user_data)(event));
 if(action>13)return false;
 auto*target=dialog_function<void*(*)(void*)>(lv_event_get_target)(event);
 auto*screen=dialog_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);
 for(unsigned depth=0;target&&depth<20;++depth){
  if(!dialog_function<bool(*)(void*)>(lv_obj_is_valid)(target)||dialog_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(target,1)||dialog_function<bool(*)(void*,unsigned)>(lv_obj_has_state)(target,128))return false;
  if(target==screen)return true;
  target=dialog_function<void*(*)(void*)>(lv_obj_get_parent)(target);
 }
 return false;
}
}}
