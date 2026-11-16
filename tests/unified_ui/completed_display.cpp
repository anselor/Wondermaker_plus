// SPDX-License-Identifier: GPL-3.0-or-later
#include "native/stock_completed_display.hpp"
#include <cassert>
using wmp_ui::native::StockCompletedDisplay;
int main(){
 using wmp_ui::native::stock_job_busy;
 for(const auto&host:{"ready","shutdown","disconnected"}){
  for(const auto&job:{"standby","printing","paused","complete","error","cancelled"}){
   for(bool busy:{false,true}){
    const bool expected=std::string(host)=="ready"&&std::string(job)=="complete"?false:busy;
    assert(stock_job_busy(busy,host,job)==expected);
   }
  }
 }
 StockCompletedDisplay display;
 assert(display.visible(true,"complete","coupon.gcode"));
 display.dismiss("complete","coupon.gcode");
 for(int i=0;i<10;++i)assert(!display.visible(true,"complete","coupon.gcode"));
 // Neither a stale popup during printing nor a non-completion dismissal hides a job.
 assert(display.visible(true,"printing","coupon.gcode"));
 display.dismiss("printing","coupon.gcode");
 assert(display.visible(true,"printing","coupon.gcode"));
 assert(display.visible(true,"paused","coupon.gcode"));
 assert(display.visible(true,"complete","coupon.gcode"));
 // A different completed file is independently visible.
 display.dismiss("complete","coupon.gcode");
 assert(display.visible(true,"complete","other.gcode"));
 // Standby resets acknowledgement, including repeating the same filename.
 display.dismiss("complete","other.gcode");
 assert(!display.visible(false,"standby",""));
 assert(display.visible(true,"complete","other.gcode"));
 display.dismiss("complete","");
 assert(display.visible(true,"complete","other.gcode"));
 assert(!display.visible(false,"error","other.gcode"));
}
