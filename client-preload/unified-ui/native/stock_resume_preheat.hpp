// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <string>
namespace wmp_ui { namespace native {
// WM1.1.13 resume_printing_handler calls resume_preheat before its direct
// RESUME branch (0x51b850 -> 0x51a344), bypassing resume_printing_prepare.
// These are the three exact run_a_gcode return addresses inside preheat:
// M104, the RESUME temperature-variable write, and M109. Do not infer this
// origin from command text: identical manual heater commands remain ordinary.
inline std::string stock_resume_preheat_command(std::uintptr_t caller,const std::string&command){
 if(caller!=0x51a4dc&&caller!=0x51a580&&caller!=0x51a644)return command;
 static const char digits[]="0123456789abcdef";
 std::string encoded;encoded.reserve(command.size()*2);
 for(unsigned char value:command){encoded+=digits[value>>4];encoded+=digits[value&15];}
 // The backend decides using the authoritative current job, not a UI poll.
 return "_WMP_SCREEN_RESUME_PREHEAT COMMAND_HEX="+encoded;
}
}}
