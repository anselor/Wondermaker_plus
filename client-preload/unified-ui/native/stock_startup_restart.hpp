#pragma once
#include <cstdint>
#include <string>
namespace wmp_ui { namespace native {
// Only the verified main() shell call. Other callers/commands keep stock behavior.
inline bool suppress_startup_restart(std::uintptr_t caller,const std::string&command){
 return caller==0x44a454 && command=="systemctl restart klipper";
}
// Browsing stock Files must not persist completion of managed setup.
// Verified file-list constructor's shell call only; all other callers forward.
inline bool suppress_file_setup_completion(std::uintptr_t caller,const std::string&command,bool onboarding){
 return onboarding&&caller==0x4fd4d4&&command=="rm /home/t13dp/need_oobe -f";
}
// Discovery queries only unassigned nodes, then rewrites topology/configuration.
// Screen startup must preserve commissioned identities, including partial CAN
// outages. Explicit managed identification is a separate user action.
inline bool suppress_startup_discovery(std::uintptr_t caller,const std::string&command){
 return caller==0x44a2a4 && command=="/home/t13dp/klippy-env/bin/python /home/t13dp/TM_T1/scripts/canbus_query.py can0 2>&1";
}
// Installed backend ExecStartPre owns defaults only with the paired contract.
inline bool suppress_startup_defaults(std::uintptr_t caller,const std::string&command,bool managed){
 return managed&&caller==0x44a258&&command=="/home/t13dp/klippy-env/bin/python /home/t13dp/TM_T1/scripts/merge_config.py";
}
}}
