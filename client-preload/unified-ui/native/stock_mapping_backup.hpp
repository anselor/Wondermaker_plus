// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <string>
namespace wmp_ui { namespace native {
// Verified 1.1.13 parse_print_stats remote-start loop only. Managed Start writes
// its own backups; PAUSE snapshots live mapping before RESUME uses the backups.
// Do not enqueue these redundant identity writes behind a running SD command.
inline bool suppress_stock_mapping_backup(std::uintptr_t caller,const std::string&command,bool standalone){
 if(caller!=0x63dc20||!standalone)return false;
 for(unsigned head=0;head<4;++head){
  const auto index=std::to_string(head);
  if(command=="SAVE_VARIABLE VARIABLE=box_modify_t"+index+"_backup VALUE="+index)return true;
 }
 return false;
}
}}
