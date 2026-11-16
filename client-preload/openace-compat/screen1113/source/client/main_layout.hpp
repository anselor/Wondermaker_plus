#pragma once
#include "native_renderer.hpp"
namespace wmp_openace {
// Native main-page layout facts only, never printer/job/physical authority.
struct MainLayout {
 bool main_current=false,main_visible=false,stop_owned=false,print_owned=false,group_owned=false;
 bool stop_visible=false,print_visible=false,group_hidden=false;
 Rect stop,print,group;
};
inline bool contains(const Rect&outer,const Rect&inner){
 return outer.valid()&&inner.valid()&&inner.x1>=outer.x1&&inner.y1>=outer.y1&&inner.x2<=outer.x2&&inner.y2<=outer.y2;
}
inline bool main_protected_regions(const MainLayout&x,const Rect&viewport,ProtectedRegions&out){
 out=ProtectedRegions();
 if(!x.main_current||!x.main_visible||!x.stop_owned||!contains(viewport,x.stop))return false;
 if(x.stop_visible){
  if(x.print_owned&&x.print_visible)return false; // Unknown simultaneous native modes.
  out=ProtectedRegions(x.stop);return true; // Existing visible-Stop printing domain.
 }
 if(!x.print_owned||!x.group_owned||!x.print_visible||!x.group_hidden
   ||!contains(viewport,x.print)||!contains(viewport,x.group)||!contains(x.group,x.stop))return false;
 // Preserve both complete footprints; the space between them is not a control.
 out=ProtectedRegions(x.group,x.print);return true;
}
}
