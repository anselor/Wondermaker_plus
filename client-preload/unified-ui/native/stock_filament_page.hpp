// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_filament_layout.hpp"
#include <cstdint>
namespace wmp_ui { namespace native {
// GUI-thread lifecycle. A page-constructor callback captures a fresh generation;
// deletion retires it. No ownership is inferred from a reused pointer address.
class StockFilamentPage {
public:
 std::uint64_t created(const StockFilamentWidgets& view,void* page){
  view_=view;page_=page;applied_=false;active_=true;return ++generation_;
 }
 void deleted(std::uint64_t generation){if(generation==generation_){active_=false;page_=nullptr;view_=StockFilamentWidgets();applied_=false;}}
 bool active()const{return active_;}
 bool applied()const{return applied_;}
 std::uint64_t generation()const{return generation_;}
 bool apply(StockGeometryPort& port,void* current_page,int width,int height,
            bool fresh,bool standalone){
  if(!active_||applied_||!fresh||!standalone||current_page!=page_)return false;
  if(!page_||!port.valid(page_)||!port.valid(view_.content)||port.parent(view_.content)!=page_){deleted(generation_);return false;}
  auto plan=external_filament_columns(view_,port,width,height);
  apply_stock_geometry(plan,port);applied_=true;return true;
 }
private:
 StockFilamentWidgets view_;void*page_=nullptr;bool active_=false,applied_=false;std::uint64_t generation_=0;
};
}}
