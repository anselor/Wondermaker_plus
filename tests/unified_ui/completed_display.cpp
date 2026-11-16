// SPDX-License-Identifier: GPL-3.0-or-later
#include "native/stock_completed_display.hpp"
#include <cassert>
using wmp_ui::native::StockCompletedDisplay;
int main(){
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
