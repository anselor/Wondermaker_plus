// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <string>
namespace wmp_ui { namespace native {
// Exact verified 1.1.13 Maintenance/first-run PID and head-identification loops.
// No other issuer, including print-file logical tool selection, is rewritten.
inline std::string stock_maintenance_command(std::uintptr_t caller,const std::string&command){
 if(caller!=0x4b7cb8&&caller!=0x50a968&&caller!=0x51095c)return command;
 if(command.size()==2&&command[0]=='T'&&command[1]>='0'&&command[1]<='3')
  return "_WMP_CALIBRATION_TOOL T="+command.substr(1);
 // A changed worker contract must fail backend validation, never select a
 // guessed or mapped head. The supported profile only emits T0 through T3.
 return "_WMP_CALIBRATION_TOOL T=-1";
}

// Return addresses of every direct command send in Maintenance and the four
// first-run calibration workers in the verified stock binary.
// Page navigation and unrelated print/motion senders must remain untouched.
constexpr std::uintptr_t calibration_senders[] = {0x4b7828,0x4b7a1c,0x4b7a6c,0x4b7bcc,0x4b7c08,0x4b7c44,0x4b7cb8,0x4b7cf4,0x4b7d90,0x4b7df8,0x4b7fbc,0x4b80b8,0x4b82e4,0x4b842c,0x4b847c,0x4b869c,0x509fb8,0x50a068,0x50a3d4,0x50a448,0x50a4f8,0x50a870,0x50a8ac,0x50a904,0x50a968,0x50a9a8,0x50aa44,0x50aadc,0x50ab8c,0x50af78,0x50b0c8,0x50b134};
inline std::string stock_calibration_command(std::uintptr_t caller,const std::string&command){
 // Identification has its own lifecycle and writes UUID configuration directly.
 // Correct its physical selection without claiming the calibration latch covers
 // that workflow or admitting its persistence/restart commands to the latch.
 if(caller==0x51095c)return stock_maintenance_command(caller,command);
 bool calibration=false;
 for(auto address:calibration_senders)if(caller==address){calibration=true;break;}
 if(!calibration)return command;
 const auto physical=stock_maintenance_command(caller,command);
 std::string result="_WMP_CALIBRATION_COMMAND HEX=";
 if(physical.size()>256)return result; // backend latches a malformed contract
 constexpr char digits[]="0123456789abcdef";
 for(unsigned char c:physical){result+=digits[c>>4];result+=digits[c&15];}
 return result;
}
}}
