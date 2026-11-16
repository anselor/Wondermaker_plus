// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "profile1113.hpp"
#include "button_caption.hpp"
#include <array>
#include <functional>
#include <list>
#include <string>
namespace wmp_ui { namespace native {
#ifdef WMP_NATIVE_TEST
void* test_resolve(std::uintptr_t);
#endif
// Reuse the vendor keypad's actual images and textarea. Its original READY
// handler heats immediately, so all key/textarea callbacks are detached before
// any WM+ entry. Each key is bound to this dialog, never the vendor globals.
class StockTemperatureKeypad {
 struct Dialog;
 struct Key {Dialog*dialog;unsigned index;};
 struct Dialog {StockTemperatureKeypad*owner;void*modal;void*text;void*notice;std::array<Key,13>keys;std::function<bool(int)>commit;};
 std::list<Dialog>dialogs_;Dialog*current_=nullptr;
public:
 bool open(void*parent,int initial,std::function<bool(int)>commit){
#if defined(__aarch64__)
  if(current_||!valid(parent))return false;
  fn<void(*)(void*)>(draw_number_keyboard)(parent);
  auto read=[](std::uintptr_t a){return *reinterpret_cast<void*volatile*>(a);};
  std::array<void*,13>keys;for(unsigned i=0;i<13;++i)keys[i]=read(0x386e9e8+8*i);
  return attach(read(0x386dc68),read(0x386dc70),keys,initial,std::move(commit));
#else
  (void)parent;(void)initial;(void)commit;return false;
#endif
 }
 bool attach(void*modal,void*text,const std::array<void*,13>&keys,int initial,std::function<bool(int)>commit){
  if(current_||!valid(modal))return false;
  // Fail closed: a malformed new keypad must not retain the vendor heating path.
  if(!inside(text,modal)){erase(modal);return false;}
  for(unsigned i=0;i<13;++i){
   if(!inside(keys[i],modal)||keys[i]==text){erase(modal);return false;}
   for(unsigned j=0;j<i;++j)if(keys[i]==keys[j]){erase(modal);return false;}
  }
  bool detached=detach(text,number_text_event);
  for(auto*key:keys)detached=detach(key,number_key_event)&&detached;
  if(!detached){erase(modal);return false;}
  dialogs_.emplace_back();auto*d=&dialogs_.back();d->owner=this;d->modal=modal;d->text=text;d->commit=std::move(commit);
  if(!fn<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(modal,&deleted,33,d)){
   dialogs_.pop_back();erase(modal);return false;
  }
  current_=d;d->notice=fn<void*(*)(void*)>(lv_label_create)(modal);
  if(!d->notice){erase(modal);return false;}
  fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(d->notice,reinterpret_cast<void*>(0x26297a0),0);
  fn<void(*)(void*,int,int)>(lv_obj_set_pos)(d->notice,89,8);
  fn<void(*)(void*,int,int)>(lv_obj_set_size)(d->notice,696,24);
  fn<void(*)(void*,const char*)>(lv_label_set_text)(d->notice,"Target temperature (C)");
  for(unsigned i=0;i<13;++i){d->keys[i]={d,i};
   if(!fn<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(keys[i],&pressed,7,&d->keys[i])){erase(modal);return false;}
  }
  if(!action_caption(keys[10],"CANCEL")||!action_caption(keys[11],"SAVE")){erase(modal);return false;}
  set(text,std::to_string(initial));return true;
 }
 void close(){if(current_&&valid(current_->modal))erase(current_->modal);}
private:
 template<class F>static F fn(std::uintptr_t a){
#ifdef WMP_NATIVE_TEST
  return reinterpret_cast<F>(test_resolve(a));
#else
  return reinterpret_cast<F>(a);
#endif
 }
 // LVGL removes one matching registration per call. The stock textarea
 // registers the same handler for CLICKED and READY; both must be detached.
 static bool detach(void*p,std::uintptr_t handler){
  bool found=false;while(fn<bool(*)(void*,void(*)(void*))>(lv_obj_remove_event_cb)(p,reinterpret_cast<void(*)(void*)>(handler)))found=true;
  return found;
 }
 static bool valid(void*p){return p&&fn<bool(*)(void*)>(lv_obj_is_valid)(p);}
 static bool inside(void*p,void*modal){for(unsigned i=0;p&&i<16;++i){if(!valid(p))return false;if(p==modal)return true;p=fn<void*(*)(void*)>(lv_obj_get_parent)(p);}return false;}
 // Stock action captions are baked into image buttons. Cover only their
 // decoration; keep the already-rebound key as the sole touch target.
 static bool action_caption(void*key,const char*text){
  fn<void(*)(void*)>(lv_obj_update_layout)(key);
  const int w=fn<int(*)(void*)>(lv_obj_get_content_width)(key),h=fn<int(*)(void*)>(lv_obj_get_content_height)(key);
  auto*cover=fn<void*(*)(void*)>(lv_obj_create)(key);if(!cover)return false;
  fn<void(*)(void*,void*,unsigned)>(lv_obj_remove_style)(cover,nullptr,0);
  for(unsigned flag:{2U,16U})fn<void(*)(void*,unsigned)>(lv_obj_clear_flag)(cover,flag);
  fn<void(*)(void*,int,int)>(lv_obj_set_pos)(cover,0,0);
  fn<void(*)(void*,int,int)>(lv_obj_set_size)(cover,w,h);
  fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(cover,0xff5a5b5dU,0);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(cover,255,0);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_radius)(cover,5,0);
  auto*label=fn<void*(*)(void*)>(lv_label_create)(cover);if(!label)return false;
  fn<void(*)(void*,unsigned)>(lv_obj_clear_flag)(label,2);
  fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(label,reinterpret_cast<void*>(0xf84928),0);
  fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(label,0xffeeeeeeU,0);
  fn<void(*)(void*,const char*)>(lv_label_set_text)(label,text);
  center_button_caption(cover,label,text);return true;
 }
 static void erase(void*p){fn<void(*)(void*)>(lv_obj_del)(p);}
 static void set(void*p,const std::string&s){fn<void(*)(void*,const char*)>(lv_textarea_set_text)(p,s.c_str());}
 static void pressed(void*event)noexcept{try{
  auto*k=static_cast<Key*>(fn<void*(*)(void*)>(lv_event_get_user_data)(event));if(!k)return;
  auto*d=k->dialog;if(d->owner->current_!=d||!inside(d->text,d->modal))return;
  auto*target=fn<void*(*)(void*)>(lv_event_get_target)(event);if(!inside(target,d->modal))return;
  const unsigned index=k->index;auto*modal=d->modal;
  if(index==10){erase(modal);return;}
  const char*raw=fn<const char*(*)(void*)>(lv_textarea_get_text)(d->text);std::string value=raw?raw:"";
  if(index==12){if(!value.empty())value.pop_back();set(d->text,value);return;}
  if(index<10){
   // The displayed zero is a value, not a digit the user must erase first.
   if(value=="0")value.clear();
   if(value.size()<3)value+=index==9?'0':char('1'+index);
   set(d->text,value);return;
  }
  if(index!=11||value.empty()||value.size()>3)return;
  int number=0;for(char c:value){if(c<'0'||c>'9')return;number=number*10+c-'0';}
  // Runtime validates the captured head/context and heater limits. A successful
  // commit submits the requested heater target through the typed backend.
  if(d->commit&&d->commit(number)){erase(modal);return;}
  fn<void(*)(void*,const char*)>(lv_label_set_text)(d->notice,"Target not accepted. Check limits or close and reopen.");
 }catch(...){} }
 static void deleted(void*event)noexcept{try{
  auto*d=static_cast<Dialog*>(fn<void*(*)(void*)>(lv_event_get_user_data)(event));if(!d)return;
  auto*o=d->owner;if(o->current_==d)o->current_=nullptr;
  for(auto it=o->dialogs_.begin();it!=o->dialogs_.end();++it)if(&*it==d){o->dialogs_.erase(it);break;}
 }catch(...){} }
};
}}
