// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../model.hpp"
#include <mutex>
namespace wmp_ui { namespace native {
// Worker-side byte flags, as used by stock start_print_prepare. No LVGL or
// std::string access here. Only bind after exact firmware verification.
class PrintContext {
public:
 void bind(volatile unsigned char*screen,volatile unsigned char*selected,volatile unsigned char*available){std::lock_guard<std::mutex>lock(mutex_);screen_=screen;selected_=selected;available_=available;}
 bool prepare(const Json&options){
  std::lock_guard<std::mutex>lock(mutex_);
  if(armed_||!screen_||!selected_||!available_)return false;
  bool selected=options.at("timelapse").get<bool>();
  if(selected&&!*available_)return false;
  // An outstanding stock screen submission must not be overwritten.
  if(*screen_)return false;
  old_screen_=*screen_;old_selected_=*selected_;chosen_=selected;
  armed_=true;*selected_=chosen_;*screen_=1;return true;
 }
 void settle(const std::string&state){
  std::lock_guard<std::mutex>lock(mutex_);
  if(!armed_)return;
  if(state=="refused"||state=="retired"){
   // A terminal receipt or explicit new attempt retires our reservation. Restore only flags still
   // owned by this request; prepare() independently checks any stock hold.
   if(*screen_==1&&*selected_==chosen_){*screen_=old_screen_;*selected_=old_selected_;}
   armed_=false;
  }else if(state=="complete")armed_=false;
  // Keep unknown history until readback or an explicit new admitted attempt.
 }
 bool armed()const{std::lock_guard<std::mutex>lock(mutex_);return armed_;}
private:
 mutable std::mutex mutex_;
 volatile unsigned char*screen_=nullptr,*selected_=nullptr,*available_=nullptr;
 unsigned char old_screen_=0,old_selected_=0,chosen_=0;bool armed_=false;
};
}}
