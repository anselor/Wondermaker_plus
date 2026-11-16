// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "profile1113.hpp"
#include <list>
#include <cstdint>
namespace wmp_ui { namespace native {
#ifdef WMP_NATIVE_TEST
void* test_resolve(std::uintptr_t);
#endif
// Captures the stock modal created for an edit, not the mutable vendor global.
class StockPickerLifetime {
public:
 void close(){auto*p=current_;retire();if(valid(p))fn<void(*)(void*)>(lv_obj_del)(p);}
 void retire(){current_=nullptr;++generation_;}
 // A just-created owned modal must not remain interactive if its lifetime
 // callback cannot be installed. Never use this for unrelated stock dialogs.
 bool bind_owned(void*modal){
  if(bind(modal))return true;
  if(valid(modal))fn<void(*)(void*)>(lv_obj_del)(modal);
  return false;
 }
 bool bind(void*modal){
  retire();if(!valid(modal))return false;
  bindings_.push_back({this,modal,generation_});auto*b=&bindings_.back();
  if(!fn<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(modal,&deleted,33,b)){
   bindings_.pop_back();return false;
  }
  current_=modal;return true;
 }
 void* modal()const{return current_;}
 bool accepts(void*target)const{
  if(!valid(current_))return false;
  for(unsigned depth=0;target&&depth<16;++depth){
   if(!valid(target))return false;
   if(target==current_)return true;
   target=fn<void*(*)(void*)>(lv_obj_get_parent)(target);
  }
  return false;
 }
private:
 struct Binding{StockPickerLifetime*owner;void*modal;std::uint64_t generation;};
 std::list<Binding>bindings_;void*current_=nullptr;std::uint64_t generation_=0;
 template<class F>static F fn(std::uintptr_t address){
#ifdef WMP_NATIVE_TEST
  return reinterpret_cast<F>(test_resolve(address));
#else
  return reinterpret_cast<F>(address);
#endif
 }
 static bool valid(void*p){return p&&fn<bool(*)(void*)>(lv_obj_is_valid)(p);}
 static void deleted(void*event)noexcept{
  try{auto*b=static_cast<Binding*>(fn<void*(*)(void*)>(lv_event_get_user_data)(event));if(!b)return;
   auto*owner=b->owner;if(b->generation==owner->generation_&&b->modal==owner->current_)owner->current_=nullptr;
   for(auto it=owner->bindings_.begin();it!=owner->bindings_.end();++it)if(&*it==b){owner->bindings_.erase(it);break;}
  }catch(...){}
 }
};
}}
