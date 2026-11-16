// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include <array>
#include <set>
#include <vector>
namespace wmp_ui { namespace native {
// Read-only inventory of the existing preview. No replacement root, new
// controls, callback removal or movement commands are created by this adapter.
struct StockPreviewWidgets {
 void*page=nullptr;void*content=nullptr;void*title=nullptr;
 void*start=nullptr;void*cancel=nullptr;void*thumbnail=nullptr;
 std::array<void*,3>options{{nullptr,nullptr,nullptr}};
 std::array<void*,3>option_icons{{nullptr,nullptr,nullptr}};
 std::array<void*,4>sources{{nullptr,nullptr,nullptr,nullptr}};
 std::array<void*,4>destinations{{nullptr,nullptr,nullptr,nullptr}};
};
class StockPreviewInventory {
public:
 static StockPreviewWidgets capture(){
  StockPreviewWidgets w;
#if defined(__aarch64__) && !defined(WMP_NATIVE_TEST)
  w.page=pointer(0x386ee30);w.content=pointer(0x386ee38);w.title=pointer(0x386ee40);
  for(unsigned i=0;i<3;++i){w.options[i]=pointer(0x386ee48+i*16);w.option_icons[i]=pointer(0x386ee50+i*16);}
  for(unsigned i=0;i<4;++i){w.sources[i]=pointer(0x386eeb8+i*8);w.destinations[i]=pointer(0x386ef58+i*8);}
#endif
  return w;
 }
 // Validate globals against the newly constructed page before finding buttons.
 // Labels are translated; coordinates and child indexes are not identities.
 static bool resolve(StockPreviewWidgets&w){
  w.start=nullptr;w.cancel=nullptr;w.thumbnail=nullptr;
  if(!stock_object_valid(w.page)||!stock_object_valid(w.content)||parent(w.content)!=w.page)return false;
  std::set<void*>required{w.page,w.content};
  auto accept=[&](void*p){return stock_object_valid(p)&&below(p,w.content)&&required.insert(p).second;};
  if(!accept(w.title))return false;
  if(!accept(w.options[0]))return false; // Leveling is always constructed.
  // Knife pairing and timelapse are conditional stock widgets. Their globals
  // can be null or retain an older page's address when not constructed.
  for(unsigned i=1;i<3;++i){
   auto*p=w.options[i];
   const bool present=stock_object_valid(p)&&below(p,w.content)&&
    reinterpret_cast<std::uintptr_t>(stock_function<void*(*)(void*,void(*)(void*))>(lv_obj_get_event_user_data)(p,reinterpret_cast<void(*)(void*)>(preview_event)))==i;
   if(!present){w.options[i]=nullptr;w.option_icons[i]=nullptr;continue;}
   if(!accept(p))return false;
  }
  for(unsigned i=0;i<3;++i)if(w.option_icons[i]&&(!accept(w.option_icons[i])||parent(w.option_icons[i])!=w.options[i]))return false;
  for(auto*p:w.sources)if(!accept(p))return false;
  for(auto*p:w.destinations)if(!accept(p))return false;
  std::vector<void*>pending{w.content};std::set<void*>visited;
  void*start=nullptr;void*cancel=nullptr;
  while(!pending.empty()){
   auto*p=pending.back();pending.pop_back();
   if(!stock_object_valid(p)||!visited.insert(p).second||visited.size()>256)return false;
   auto action=reinterpret_cast<std::uintptr_t>(stock_function<void*(*)(void*,void(*)(void*))>(lv_obj_get_event_user_data)(p,reinterpret_cast<void(*)(void*)>(preview_event)));
   if(action==3){if(cancel)return false;cancel=p;}
   if(action==4){if(start)return false;start=p;}
   auto count=stock_function<unsigned(*)(void*)>(lv_obj_get_child_cnt)(p);
   if(count>256||pending.size()+count>256)return false;
   for(unsigned i=0;i<count;++i){auto*c=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(p,int(i));if(!stock_object_valid(c)||parent(c)!=p)return false;pending.push_back(c);}
  }
  if(!start||!cancel||required.count(start)||required.count(cancel))return false;
  w.start=start;w.cancel=cancel;w.thumbnail=find_thumbnail(w.content);return true;
 }
 // The constructor keeps the image local (0x537b3c), not in a global.
 // Identify only the unique image inside its direct 149x149 content panel.
 // Geometry alone is insufficient: require image class, exact ancestry and
 // a single child. Ambiguity disables enlargement without breaking preview.
 static void*find_thumbnail(void*content){
  if(!stock_object_valid(content))return nullptr;
  void*found=nullptr;
  const auto count=stock_function<unsigned(*)(void*)>(lv_obj_get_child_cnt)(content);
  if(count>256)return nullptr;
  for(unsigned i=0;i<count;++i){
   auto*panel=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(content,int(i));
   if(!stock_object_valid(panel)||parent(panel)!=content)return nullptr;
   if(stock_function<int(*)(void*)>(lv_obj_get_width)(panel)!=149||stock_function<int(*)(void*)>(lv_obj_get_height)(panel)!=149||stock_function<unsigned(*)(void*)>(lv_obj_get_child_cnt)(panel)!=1)continue;
   auto*image=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(panel,0);
   if(!stock_object_valid(image)||parent(image)!=panel)return nullptr;
   if(!stock_function<bool(*)(void*,const void*)>(lv_obj_check_type)(image,reinterpret_cast<const void*>(lv_img_class)))continue;
   if(found)return nullptr;
   found=image;
  }
  return found;
 }
private:
 static void*parent(void*p){return stock_function<void*(*)(void*)>(lv_obj_get_parent)(p);}
 static bool below(void*p,void*root){for(unsigned i=0;p&&i<16;++i){if(!stock_object_valid(p))return false;if(p==root)return true;p=parent(p);}return false;}
#if defined(__aarch64__) && !defined(WMP_NATIVE_TEST)
 static void*pointer(std::uintptr_t a){return *reinterpret_cast<void*volatile*>(a);}
#endif
};
}}
