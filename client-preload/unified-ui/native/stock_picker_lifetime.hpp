// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include <list>
#include <cstdint>
namespace wmp_ui { namespace native {
// Captures the stock modal created for an edit, not the mutable vendor global.
class StockPickerLifetime {
public:
 void close(){auto*p=current_;retire();if(stock_object_valid(p))stock_function<void(*)(void*)>(lv_obj_del)(p);}
 void retire(){current_=nullptr;++generation_;}
 // A just-created owned modal must not remain interactive if its lifetime
 // callback cannot be installed. Never use this for unrelated stock dialogs.
 bool bind_owned(void*modal){
  if(bind(modal))return true;
  if(stock_object_valid(modal))stock_function<void(*)(void*)>(lv_obj_del)(modal);
  return false;
 }
 bool bind(void*modal){
  retire();if(!stock_object_valid(modal))return false;
  bindings_.push_back({this,modal,generation_});auto*b=&bindings_.back();
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(modal,&deleted,33,b)){
   bindings_.pop_back();return false;
  }
  current_=modal;return true;
 }
 void* modal()const{return current_;}
 bool accepts(void*target)const{
  if(!stock_object_valid(current_))return false;
  for(unsigned depth=0;target&&depth<16;++depth){
   if(!stock_object_valid(target))return false;
   if(target==current_)return true;
   target=stock_function<void*(*)(void*)>(lv_obj_get_parent)(target);
  }
  return false;
 }
private:
 struct Binding{StockPickerLifetime*owner;void*modal;std::uint64_t generation;};
 std::list<Binding>bindings_;void*current_=nullptr;std::uint64_t generation_=0;
 static void deleted(void*event)noexcept{
  try{auto*b=static_cast<Binding*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(event));if(!b)return;
   auto*owner=b->owner;if(b->generation==owner->generation_&&b->modal==owner->current_)owner->current_=nullptr;
   for(auto it=owner->bindings_.begin();it!=owner->bindings_.end();++it)if(&*it==b){owner->bindings_.erase(it);break;}
  }catch(...){}
 }
};
}}
