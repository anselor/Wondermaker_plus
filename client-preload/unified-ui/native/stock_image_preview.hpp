// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "button_caption.hpp"
#include "profile1113.hpp"
#include <algorithm>
#include <functional>
#include <string>
namespace wmp_ui { namespace native {
#ifdef WMP_NATIVE_TEST
void*test_resolve(std::uintptr_t);
#endif
// Enlarges the file source already displayed by the stock preview. No second
// thumbnail fetch, app shell, model mutation or printer command is involved.
class StockImagePreview {
 void*root_=nullptr;void*close_=nullptr;
public:
 std::function<void()>dismissed;
 bool active()const{return valid(root_);}
 void close(){auto*root=root_;root_=nullptr;close_=nullptr;if(valid(root))fn<void(*)(void*)>(lv_obj_del)(root);}
 bool show(void*parent,void*thumbnail)try{
  close();if(!valid(parent)||!valid(thumbnail))return false;
  const auto*source=fn<const void*(*)(void*)>(lv_img_get_src)(thumbnail);
  if(!source||fn<int(*)(const void*)>(lv_img_src_get_type)(source)!=1)return false;
  const auto*path=static_cast<const char*>(source);std::size_t length=0;
  while(length<4096&&path[length])++length;
  if(!length||length==4096)return false;
  const std::string filename(path,length);
  if(filename=="/home/t13dp/TM_T1/access/screen_preview_img.bin")return false;
  std::uint32_t header[2]={0,0};
  if(fn<int(*)(const void*,void*)>(lv_img_decoder_get_info)(filename.c_str(),header)!=1)return false;
  const unsigned iw=(header[0]>>10)&2047,ih=(header[0]>>21)&2047;
  if(!iw||!ih)return false;
  const int w=fn<int(*)(void*)>(lv_obj_get_content_width)(parent),h=fn<int(*)(void*)>(lv_obj_get_content_height)(parent);
  if(w<200||h<160)return false;
  const unsigned zoom=std::min(4096U,std::min(unsigned(w-32)*256/iw,unsigned(h-80)*256/ih));
  if(!zoom)return false;
  root_=fn<void*(*)(void*)>(lv_obj_create)(parent);if(!root_)return false;
  if(!fn<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(root_,&deleted,33,this)){close();return false;}
  style(root_,0x463c8d8);place(root_,0,0,w,h);
  fn<void(*)(void*,unsigned)>(lv_obj_clear_flag)(root_,16); // Do not scroll the unscaled image bounds.
  auto*image=fn<void*(*)(void*)>(lv_img_create)(root_);if(!image){close();return false;}
  fn<void(*)(void*,const void*)>(lv_img_set_src)(image,filename.c_str());
  fn<void(*)(void*,int,int)>(lv_img_set_pivot)(image,0,0);
  fn<void(*)(void*,unsigned)>(lv_img_set_zoom)(image,zoom);
  fn<void(*)(void*,int,int)>(lv_obj_set_pos)(image,(w-int(iw*zoom/256))/2,64+(h-80-int(ih*zoom/256))/2);
  close_=fn<void*(*)(void*)>(lv_btn_create)(root_);if(!close_){close();return false;}
  style(close_,0x463c8e8);place(close_,w-132,8,116,46);
  auto*text=fn<void*(*)(void*)>(lv_label_create)(close_);if(!text){close();return false;}
  caption(text,"CLOSE");center_button_caption(close_,text,"CLOSE");
  if(!fn<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(close_,&pressed,7,this)){close();return false;}
  return true;
 }catch(...){close();return false;}

private:
 template<class F>static F fn(std::uintptr_t address){
#ifdef WMP_NATIVE_TEST
  return reinterpret_cast<F>(test_resolve(address));
#else
  return reinterpret_cast<F>(address);
#endif
 }
 static bool valid(void*p){return p&&fn<bool(*)(void*)>(lv_obj_is_valid)(p);}
 static void place(void*p,int x,int y,int w,int h){fn<void(*)(void*,int,int)>(lv_obj_set_pos)(p,x,y);fn<void(*)(void*,int,int)>(lv_obj_set_size)(p,w,h);}
 static void style(void*p,std::uintptr_t address){fn<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(p,reinterpret_cast<void*>(address),0);}
 static void caption(void*p,const std::string&s){fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(0x26297a0),0);fn<void(*)(void*,const char*)>(lv_label_set_text)(p,s.c_str());}
 static void deleted(void*e)noexcept{try{auto*o=static_cast<StockImagePreview*>(fn<void*(*)(void*)>(lv_event_get_user_data)(e));if(o&&fn<void*(*)(void*)>(lv_event_get_target)(e)==o->root_){o->root_=nullptr;o->close_=nullptr;}}catch(...){} }
 static void pressed(void*e)noexcept{try{
  auto*o=static_cast<StockImagePreview*>(fn<void*(*)(void*)>(lv_event_get_user_data)(e));if(!o||!o->active()||fn<void*(*)(void*)>(lv_event_get_target)(e)!=o->close_)return;
  auto*screen=fn<void*(*)(void*)>(lv_disp_get_scr_act)(fn<void*(*)()>(lv_disp_get_default)());
  auto*p=o->root_;bool visible=false;for(unsigned i=0;p&&i<32;++i){if(!valid(p)||fn<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return;if(p==screen){visible=true;break;}p=fn<void*(*)(void*)>(lv_obj_get_parent)(p);}
  if(!visible)return;
  auto callback=o->dismissed;o->close();if(callback)callback();
 }catch(...){} }
};
}}
