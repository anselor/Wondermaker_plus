// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_text_keyboard.hpp"
#include <array>
namespace wmp_ui { namespace native {
struct StockTextKeyboardState {
 void*modal=nullptr;void*background=nullptr;void*text=nullptr;
 const void*layout=nullptr;const void*widths=nullptr;
 int count=0,edit_type=0;unsigned char wifi=0;
 std::array<void*,50>keys{}; // verified btn_array ELF symbol size: 0x190
};
#ifdef WMP_NATIVE_TEST
StockTextKeyboardState&test_text_keyboard_state();
#endif
// Construct the real keyboard and retain its geometry/assets. Its shared
// globals are borrowed only during synchronous GUI-thread construction, then
// restored. Owned key callbacks subsequently use captured widgets exclusively.
class StockTextKeyboardHost {
 StockTextKeyboard keyboard_;void*modal_=nullptr;void*background_=nullptr;void*text_=nullptr;unsigned layout_=0;
 static StockTextKeyboardState read(){
#ifdef WMP_NATIVE_TEST
  return test_text_keyboard_state();
#elif defined(__aarch64__)
  StockTextKeyboardState s;s.modal=*reinterpret_cast<void**>(0x4635b58);s.background=*reinterpret_cast<void**>(0x463c100);s.text=*reinterpret_cast<void**>(0x463c108);
  s.layout=*reinterpret_cast<const void**>(0x384fdd8);s.widths=*reinterpret_cast<const void**>(0x384fde0);
  s.count=*reinterpret_cast<int*>(0x463c0f0);s.edit_type=*reinterpret_cast<int*>(0x463c8d0);s.wifi=*reinterpret_cast<unsigned char*>(0x463c110);
  for(unsigned i=0;i<50;++i)s.keys[i]=reinterpret_cast<void**>(0x4635b60)[i];
  return s;
#else
  return {};
#endif
 }
 static void write(const StockTextKeyboardState&s){
#ifdef WMP_NATIVE_TEST
  test_text_keyboard_state()=s;
#elif defined(__aarch64__)
  *reinterpret_cast<void**>(0x4635b58)=s.modal;*reinterpret_cast<void**>(0x463c100)=s.background;*reinterpret_cast<void**>(0x463c108)=s.text;
  *reinterpret_cast<const void**>(0x384fdd8)=s.layout;*reinterpret_cast<const void**>(0x384fde0)=s.widths;
  *reinterpret_cast<int*>(0x463c0f0)=s.count;*reinterpret_cast<int*>(0x463c8d0)=s.edit_type;*reinterpret_cast<unsigned char*>(0x463c110)=s.wifi;
  for(unsigned i=0;i<50;++i)reinterpret_cast<void**>(0x4635b60)[i]=s.keys[i];
#else
  (void)s;
#endif
 }
 struct Restore {StockTextKeyboardState state;Restore():state(read()){}~Restore(){write(state);}};
 struct ModalGuard {void*root;explicit ModalGuard(void*p):root(p){}~ModalGuard(){if(valid(root))fn<void(*)(void*)>(lv_obj_del)(root);}};
 static void select_layout(StockTextKeyboardState&s,unsigned index){
  static const std::uintptr_t layouts[]={0x384f7b8,0x384f8d8,0x384f9f8,0x384faf0,0x384fbe8,0x384fce0};
  s.layout=reinterpret_cast<const void*>(layouts[index]);s.widths=reinterpret_cast<const void*>(index==0?0x8820d8:index==1?0x882168:0x8821f8);
 }
 static bool capture(const StockTextKeyboardState&s,std::vector<StockTextKeyboard::Widget>&keys){
  if(s.count<1||s.count>50)return false;
  for(int i=0;i<s.count;++i){auto*object=s.keys[i];if(!valid(object)||!inside(object,s.background))return false;
   const auto*value=static_cast<const char*>(fn<void*(*)(void*)>(text_key_user_data)(object));if(!value)return false;
   std::size_t size=0;while(size<17&&value[size])++size;if(!size||size>16)return false;
   keys.push_back({object,std::string(value,size)});
  }
  return true;
 }
public:
 bool active()const{return keyboard_.active();}
 void close(){keyboard_.close();modal_=background_=text_=nullptr;}
 bool open(void*parent,const std::string&initial,std::function<bool(const std::string&)>commit)try{
  close();if(!valid(parent)||initial.size()>64)return false;
  StockTextKeyboardState created;bool constructed=false;void*previous_modal=nullptr;
  {
   Restore restore;if(restore.state.wifi)return false; // never displace a stock Wi-Fi keyboard
   previous_modal=restore.state.modal;
   auto temp=restore.state;temp.edit_type=0;select_layout(temp,0);write(temp);
   try{fn<void(*)(void*)>(draw_text_keyboard)(parent);created=read();constructed=true;}
   catch(...){created=read();}
  }
  const bool owned=created.modal!=previous_modal&&valid(created.modal)&&fn<void*(*)(void*)>(lv_obj_get_parent)(created.modal)==parent;
  ModalGuard cleanup(owned?created.modal:nullptr);
  if(!constructed||!owned||!inside(created.text,created.modal)||!inside(created.background,created.modal)){
   return false;
  }
  std::vector<StockTextKeyboard::Widget>keys;
  if(!capture(created,keys))return false;
  modal_=created.modal;background_=created.background;text_=created.text;layout_=0;
  if(!keyboard_.attach(modal_,text_,keys,initial,std::move(commit),[this](const std::string&key){return change_layout(key);})){close();return false;}
  cleanup.root=nullptr;return true;
 }catch(...){close();return false;}
private:
 bool change_layout(const std::string&key){
  if(!active()||!inside(background_,modal_)||!inside(text_,modal_))return false;
  unsigned next=layout_;
  if(key=="大写")next=1;else if(key=="小写"||key=="ABC")next=0;else if(key=="123")next=2;
  else if(key=="pre")next=layout_>2?layout_-1:2;else if(key=="next")next=layout_<5?layout_+1:5;else return false;
  StockTextKeyboardState created;
  {
   Restore restore;auto temp=restore.state;temp.edit_type=0;temp.modal=modal_;temp.text=text_;temp.background=background_;select_layout(temp,next);write(temp);
   fn<void(*)(void*)>(lv_obj_clean)(background_);fn<void(*)(void*)>(create_text_keys)(background_);created=read();
  }
  std::vector<StockTextKeyboard::Widget>keys;if(!capture(created,keys)||!keyboard_.replace_keys(keys))return false;
  layout_=next;return true;
 }
 template<class F>static F fn(std::uintptr_t address){
#ifdef WMP_NATIVE_TEST
  return reinterpret_cast<F>(test_resolve(address));
#else
  return reinterpret_cast<F>(address);
#endif
 }
 static bool valid(void*p){return p&&fn<bool(*)(void*)>(lv_obj_is_valid)(p);}
 static bool inside(void*p,void*root){if(!valid(root)||p==root)return false;for(unsigned i=0;p&&i<32;++i){if(!valid(p))return false;if(p==root)return true;p=fn<void*(*)(void*)>(lv_obj_get_parent)(p);}return false;}
};
}}
