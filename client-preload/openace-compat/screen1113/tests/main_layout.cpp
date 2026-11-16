#include "main_layout.hpp"
#include <cassert>
using namespace wmp_openace;
int main(){
 MainLayout x;Rect view{0,0,479,799};ProtectedRegions out;
 x.main_current=x.main_visible=x.stop_owned=x.print_owned=x.group_owned=true;
 x.stop={320,700,459,739};x.print={20,700,159,739};x.group={180,690,479,749};
 x.stop_visible=true;assert(main_protected_regions(x,view,out));assert(out.count==1&&out.rectangles[0].x1==320&&out.rectangles[0].x2==459);
 x.stop_visible=false;x.print_visible=true;x.group_hidden=true;
 assert(main_protected_regions(x,view,out));assert(out.count==2&&out.rectangles[0].x1==180&&out.rectangles[0].x2==479&&out.rectangles[1].x1==20&&out.rectangles[1].x2==159);
 auto idle=x;
 x.group_hidden=false;assert(!main_protected_regions(x,view,out));x=idle;
 x.main_current=false;assert(!main_protected_regions(x,view,out));x=idle;
 x.main_visible=false;assert(!main_protected_regions(x,view,out));x=idle;
 x.stop_owned=false;assert(!main_protected_regions(x,view,out));x=idle;
 x.print_owned=false;assert(!main_protected_regions(x,view,out));x=idle;
 x.group_owned=false;assert(!main_protected_regions(x,view,out));x=idle;
 x.print_visible=false;assert(!main_protected_regions(x,view,out));x=idle;
 x.group=Rect();assert(!main_protected_regions(x,view,out));x=idle;
 x.stop={0,0,5,5};assert(!main_protected_regions(x,view,out));x=idle;
 x.group={180,690,490,749};assert(!main_protected_regions(x,view,out));x=idle;
 x.print={-1,700,150,739};assert(!main_protected_regions(x,view,out));x=idle;
 x.stop_visible=true;assert(!main_protected_regions(x,view,out)); // contradictory visible Print/Stop.
}
