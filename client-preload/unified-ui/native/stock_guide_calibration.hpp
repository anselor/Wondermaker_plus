// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "nozzle_scrub_vendor.hpp"
#include "stock_maintenance_command.hpp"
#include <array>
namespace wmp_ui { namespace native {
// The frozen guide and Maintenance both select mesh, vibration, PID, offsets.
// Only their selection flags differ; execute through one admitted worker.
struct GuideCalibrationSelection {
 std::array<unsigned char,4> selected{{0,0,0,0}};
 bool valid()const{for(auto value:selected)if(value>1)return false;return true;}
 unsigned initial_status()const{for(unsigned i=0;i<4;++i)if(selected[i])return 1+3*i;return 0;}
 static GuideCalibrationSelection read(){
  GuideCalibrationSelection result;auto*source=nozzle_scrub_vendor_data<const volatile unsigned char>(calibration_selected);
  for(unsigned i=0;i<4;++i)result.selected[i]=source[i];
  return result;
 }
 void copy_selection()const{
  auto*target=nozzle_scrub_vendor_data<volatile unsigned char>(auto_check_selected);
  for(unsigned i=0;i<4;++i)target[i]=selected[i];
 }
 void start()const{*nozzle_scrub_vendor_data<volatile std::uint32_t>(auto_checking_status)=initial_status();}
};
// Frozen guide controls: Skip=0, Start=1, four selection toggles=2..5.
// A stale, hidden, disabled or malformed control cannot launch work.
inline int stock_guide_calibration_action(void*event){
 if(!event||stock_function<int(*)(void*)>(lv_event_get_code)(event)!=7)return -1;
 const auto action=reinterpret_cast<std::uintptr_t>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(event));
 if(action>5)return -1;
 auto*target=stock_function<void*(*)(void*)>(lv_event_get_target)(event);
 auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);
 for(unsigned depth=0;target&&depth<20;++depth){
  if(!stock_object_valid(target)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(target,1)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_state)(target,128))return -1;
  if(target==screen)return int(action);
  target=stock_function<void*(*)(void*)>(lv_obj_get_parent)(target);
 }
 return -1;
}
inline bool stock_guide_calibration_sender(std::uintptr_t caller){
 for(auto address:calibration_senders)if(address>=0x509ef0&&address<0x50b3e4&&caller==address)return true;
 return false;
}
}}
