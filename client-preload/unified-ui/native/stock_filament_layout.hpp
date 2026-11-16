// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <array>
#include <set>
#include <vector>
#include <stdexcept>
namespace wmp_ui { namespace native {
// In-place geometry only. No root creation, styling, object deletion, callback
// changes or backend dispatch. Native lifetime and callback ownership are
// handled by the page adapter, separately from this geometry calculation.
struct StockRect { int x,y,w,h; };
struct StockSlotWidgets {
 void* card=nullptr; void* number=nullptr; void* colour=nullptr;
 void* material=nullptr; void* material_label=nullptr;
};
struct StockFilamentWidgets {
 void* content=nullptr;
 std::array<StockSlotWidgets,4> slots;
 unsigned count=0;
};
struct StockPlacement { void* object; StockRect bounds; };
class StockGeometryPort {
public:
 virtual ~StockGeometryPort()=default;
 virtual bool valid(void*)const=0;
 virtual void* parent(void*)const=0;
 // Coordinates are relative to the existing parent's content origin. A native
 // adapter must set TOP_LEFT alignment as well as size, replacing old anchors.
 virtual void place(void*,StockRect)=0;
};
inline std::vector<StockPlacement> external_filament_columns(
 const StockFilamentWidgets& view, StockGeometryPort& port, int width, int height) {
 if(view.count<1||view.count>4||width<640||height<300||
    !view.content||!port.valid(view.content))throw std::runtime_error("Unverified stock filament content");
 // Validate the complete set before emitting any geometry changes. Pointer
 // existence alone is insufficient: every stock child must have the expected
 // parent, and aliases would otherwise move the wrong control twice.
 std::set<void*> seen{view.content};
 for(unsigned i=0;i<view.count;++i){const auto&s=view.slots[i];
  for(auto object:{s.card,s.number,s.colour,s.material,s.material_label})
   if(!object||!port.valid(object)||!seen.insert(object).second)
    throw std::runtime_error("Incomplete stock filament widgets");
  if(port.parent(s.card)!=view.content||port.parent(s.number)!=s.card||
     port.parent(s.colour)!=s.card||port.parent(s.material)!=s.card||
     port.parent(s.material_label)!=s.material)
   throw std::runtime_error("Stock filament hierarchy changed");
 }
 // Keep space inside the STOCK content panel for context/navigation additions.
 // The sidebar, Settings tabs, status strip and panel itself are never touched.
 const int margin=12,gap=8,top=40,bottom=48;
 const int card_width=(width-2*margin-3*gap)/4;
 const int card_height=height-top-bottom;
 std::vector<StockPlacement> result;
 for(unsigned i=0;i<view.count;++i){const auto&s=view.slots[i];
  result.push_back({s.card,{margin+int(i)*(card_width+gap),top,card_width,card_height}});
  result.push_back({s.number,{8,8,35,35}}); // Preserve stock number image size.
  result.push_back({s.colour,{(card_width-83)/2,40,83,83}});
  result.push_back({s.material,{8,126,card_width-16,38}});
  result.push_back({s.material_label,{0,5,card_width-16,28}});
 }
 return result;
}
// Call on the LVGL thread immediately after validation. The native adapter will
// also need deletion/generation binding; this helper is not a lifecycle guard.
inline void apply_stock_geometry(const std::vector<StockPlacement>& plan,StockGeometryPort& port){
 for(const auto&item:plan)port.place(item.object,item.bounds);
}
}}
