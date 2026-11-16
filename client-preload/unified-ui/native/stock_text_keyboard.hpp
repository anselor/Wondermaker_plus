// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include <functional>
#include <list>
#include <set>
#include <string>
#include <vector>
namespace wmp_ui { namespace native {
// Adopts the original stock text-keyboard objects, replacing every Wi-Fi key
// callback. Enter commits a local draft through the caller; no command is sent.
class StockTextKeyboard {
public:
 struct Widget{void*object;std::string value;};
private:
 struct Key{StockTextKeyboard*owner;void*object;void*modal;unsigned generation;std::string value;};
 std::list<Key>keys_;void*modal_=nullptr;void*text_=nullptr;unsigned generation_=0;
 std::function<bool(const std::string&)>commit_;
 std::function<bool(const std::string&)>layout_;
public:
 bool active()const{return stock_object_valid(modal_);}
 void close(){auto*modal=modal_;modal_=nullptr;text_=nullptr;++generation_;if(stock_object_valid(modal))stock_function<void(*)(void*)>(lv_obj_del)(modal);}
 bool attach(void*modal,void*text,const std::vector<Widget>&keys,const std::string&initial,
             std::function<bool(const std::string&)>commit,std::function<bool(const std::string&)>layout)try{
  close();
  // Caller supplies the just-created owned modal, never the active screen or
  // shared layer. Even failed adoption must not expose its Wi-Fi callbacks.
  if(!stock_object_valid(modal)||!stock_object_valid(stock_function<void*(*)(void*)>(lv_obj_get_parent)(modal)))return false;
  if(text==modal||!inside(text,modal)||initial.size()>64){stock_function<void(*)(void*)>(lv_obj_del)(modal);return false;}
  modal_=modal;text_=text;commit_=std::move(commit);layout_=std::move(layout);++generation_;
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(modal_,&deleted,33,this)){close();return false;}
  if(!replace_keys(keys)){close();return false;}
  stock_function<void(*)(void*,const char*)>(lv_textarea_set_text)(text_,initial.c_str());return true;
 }catch(...){close();return false;}
 // Called after the original key-layout builder creates a new alphabet/symbol
 // set. Its newly registered vendor handlers must also be removed completely.
 bool replace_keys(const std::vector<Widget>&widgets)try{
  if(!active()||widgets.empty()||widgets.size()>64){close();return false;}
  std::set<void*>seen;bool enter=false,back=false;
  for(const auto&w:widgets){
   if(w.object==text_||!inside(w.object,modal_)||!seen.insert(w.object).second||w.value.empty()||w.value.size()>16){close();return false;}
   enter=enter||w.value=="enter";back=back||w.value=="back";
  }
  if(!enter||!back){close();return false;}
  for(const auto&w:widgets){bool detached=false;
   while(stock_function<bool(*)(void*,void(*)(void*))>(lv_obj_remove_event_cb)(w.object,reinterpret_cast<void(*)(void*)>(text_key_event)))detached=true;
   if(!detached){close();return false;}
  }
  // A partial key inventory must not leave an omitted vendor key callable.
  std::vector<void*>pending{modal_};bool unexpected=false;
  for(std::size_t i=0;i<pending.size();++i){
   auto*object=pending[i];if(!stock_object_valid(object)){close();return false;}
   while(stock_function<bool(*)(void*,void(*)(void*))>(lv_obj_remove_event_cb)(object,reinterpret_cast<void(*)(void*)>(text_key_event)))unexpected=true;
   const auto count=stock_function<unsigned(*)(void*)>(lv_obj_get_child_cnt)(object);
   if(count>256||pending.size()+count>256){close();return false;}
   for(unsigned j=0;j<count;++j)pending.push_back(stock_function<void*(*)(void*,int)>(lv_obj_get_child)(object,int(j)));
  }
  if(unexpected){close();return false;}
  ++generation_;
  for(const auto&w:widgets){
   keys_.push_back({this,w.object,modal_,generation_,w.value});auto*k=&keys_.back();
   if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(w.object,&pressed,0,k)){keys_.pop_back();close();return false;}
   // The vendor disables Enter for short Wi-Fi passwords. Unit-name validity
   // is checked by the draft owner instead and is not an eight-character rule.
   stock_function<void(*)(void*,unsigned)>(lv_obj_clear_state)(w.object,128);
  }
  return true;
 }catch(...){close();return false;}
private:
 static bool inside(void*p,void*root){for(unsigned i=0;p&&i<32;++i){if(!stock_object_valid(p))return false;if(p==root)return true;p=stock_function<void*(*)(void*)>(lv_obj_get_parent)(p);}return false;}
 bool visible()const{
  auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(stock_function<void*(*)()>(lv_disp_get_default)());
  for(void*p=modal_;p;p=stock_function<void*(*)(void*)>(lv_obj_get_parent)(p)){if(!stock_object_valid(p)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return false;if(p==screen)return true;}return false;
 }
 static void deleted(void*e)noexcept{try{auto*o=static_cast<StockTextKeyboard*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(o&&stock_function<void*(*)(void*)>(lv_event_get_target)(e)==o->modal_){o->modal_=nullptr;o->text_=nullptr;++o->generation_;}}catch(...){} }
 static void pressed(void*e)noexcept{StockTextKeyboard*owner=nullptr;try{
  auto*k=static_cast<Key*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(!k)return;auto*o=k->owner;
  owner=o;
  const int code=stock_function<int(*)(void*)>(lv_event_get_code)(e);
  if(code==33){for(auto it=o->keys_.begin();it!=o->keys_.end();++it)if(&*it==k){o->keys_.erase(it);break;}return;}
  if(code!=7||k->modal!=o->modal_||k->generation!=o->generation_||stock_function<void*(*)(void*)>(lv_event_get_target)(e)!=k->object||!o->visible()||!inside(o->text_,o->modal_))return;
  const auto value=k->value; // callbacks may rebuild/delete this key
  if(value=="back"){o->close();return;}
  if(value=="enter"){
   const char*raw=stock_function<const char*(*)(void*)>(lv_textarea_get_text)(o->text_);const std::string text=raw?raw:"";
   if(!text.empty()&&text.size()<=64){auto commit=o->commit_;if(commit&&commit(text))o->close();}return;
  }
  if(value=="大写"||value=="小写"||value=="123"||value=="ABC"||value=="pre"||value=="next"){
   auto change=o->layout_;if(!change||!change(value))o->close();return;
  }
  if(value=="del"){stock_function<void(*)(void*)>(lv_textarea_del_char)(o->text_);return;}
  const auto insertion=value=="space"?std::string(" "):value;
  for(unsigned char c:insertion)if(c<32||c==127)return;
  const char*raw=stock_function<const char*(*)(void*)>(lv_textarea_get_text)(o->text_);
  if(std::string(raw?raw:"").size()+insertion.size()<=64)stock_function<void(*)(void*,const char*)>(lv_textarea_add_text)(o->text_,insertion.c_str());
 }catch(...){try{if(owner)owner->close();}catch(...){}} }
};
}}
