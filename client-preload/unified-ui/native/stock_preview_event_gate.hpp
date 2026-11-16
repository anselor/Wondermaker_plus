// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include <list>
#include <mutex>
namespace wmp_ui { namespace native {
// Guards the original preview callback before widget adoption. Each stock
// content root retains its own ownership, so a later USB preview cannot enable
// delayed events from an earlier WM+-owned preview.
class StockPreviewEventGate {
public:
 struct MetadataOrigin{void*content;std::uint64_t ticket;};
private:
 struct Entry{StockPreviewEventGate*owner;void*content;bool managed;std::uint64_t generation;};
 std::list<Entry>entries_;void*parent_=nullptr;
 bool constructing_=false,managed_=false,managed_seen_=false;
 std::uint64_t generation_=0;
 mutable std::mutex metadata_mutex_;MetadataOrigin metadata_origin_{nullptr,0};
 void publish_metadata(void*content,std::uint64_t ticket){std::lock_guard<std::mutex>lock(metadata_mutex_);metadata_origin_={content,ticket};}
public:
 void begin(void*parent,bool managed){publish_metadata(nullptr,0);++generation_;parent_=parent;managed_=managed;constructing_=true;managed_seen_=managed_seen_||managed;}
 bool finish(void*content){
  constructing_=false;
  if(!stock_object_valid(parent_)||!stock_object_valid(content)||stock_function<void*(*)(void*)>(lv_obj_get_parent)(content)!=parent_)return false;
  entries_.push_back({this,content,managed_,generation_});auto*entry=&entries_.back();
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(content,&deleted,33,entry)){entries_.pop_back();return false;}
  if(!managed_)publish_metadata(content,generation_);
  return true;
 }
 // USB destination chooser is a sibling modal beneath the page, not a
 // child of preview content. Permit only a new modal from a captured USB
 // trigger; never infer its ownership from the current global USB flag.
 bool usb_modal(void*trigger,void*modal){
  if(!stock_object_valid(modal))return false;
  for(unsigned depth=0;trigger&&depth<32;++depth){
   if(!stock_object_valid(trigger))return false;
   for(const auto&entry:entries_)if(entry.content==trigger){
    if(entry.managed||stock_function<void*(*)(void*)>(lv_obj_get_parent)(modal)!=stock_function<void*(*)(void*)>(lv_obj_get_parent)(trigger))return false;
    for(const auto&existing:entries_)if(existing.content==modal)return !existing.managed;
    entries_.push_back({this,modal,false,generation_});auto*created=&entries_.back();
    if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(modal,&deleted,33,created)){entries_.pop_back();return false;}
    return true;
   }
   trigger=stock_function<void*(*)(void*)>(lv_obj_get_parent)(trigger);
  }
  return false;
 }
 bool consume(void*target,int code)const{
  if(code!=7)return false;
  if(constructing_)return managed_||managed_seen_;
  for(unsigned depth=0;target&&depth<32;++depth){
   if(!stock_object_valid(target))return managed_seen_;
   for(const auto&entry:entries_)if(entry.content==target)return entry.managed;
   target=stock_function<void*(*)(void*)>(lv_obj_get_parent)(target);
  }
  // A failed capture never falls back to vendor Start or mapping writes.
  return managed_seen_;
 }
 // Metadata callbacks are asynchronous. Capture ownership at scheduling and
 // require the same root and generation at execution, even if memory is reused.
 // The scheduler can run on a vendor worker. It reads only this synchronized
 // immutable snapshot; LVGL and the entry list are inspected on the GUI thread.
 MetadataOrigin scheduled_origin()const{std::lock_guard<std::mutex>lock(metadata_mutex_);return metadata_origin_;}
 std::uint64_t metadata_ticket(void*content)const{
  if(constructing_||!stock_object_valid(content))return 0;
  for(const auto&e:entries_)if(e.content==content&&!e.managed&&e.generation==generation_)return e.generation;
  return 0;
 }
 bool metadata_allowed(void*origin,void*current,std::uint64_t ticket)const{
  return ticket&&origin==current&&metadata_ticket(origin)==ticket;
 }
private:
 static void deleted(void*event)noexcept{try{
  auto*entry=static_cast<Entry*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(event));if(!entry)return;
  auto*owner=entry->owner;
  {std::lock_guard<std::mutex>lock(owner->metadata_mutex_);if(owner->metadata_origin_.content==entry->content&&owner->metadata_origin_.ticket==entry->generation)owner->metadata_origin_={nullptr,0};}
  for(auto it=owner->entries_.begin();it!=owner->entries_.end();++it)if(&*it==entry){owner->entries_.erase(it);break;}
 }catch(...){} }
};
}}
