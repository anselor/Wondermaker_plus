// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include "stock_dialog_backdrop.hpp"
#include "button_caption.hpp"
#include "stock_palette.hpp"
#include <algorithm>
#include <array>
#include <string>
#include <functional>
namespace wmp_ui { namespace native {
// RGB-only palette: appearances such as rainbow need a richer identity model.
inline const char* filament_solid_colour(unsigned index){
 static const char* const colours[]={
  "#ffffff","#e7ceb5","#714623","#97999b","#0c0809","#49c5b1","#009cde","#03257e",
  "#00b140","#265b31","#fce300","#fe5000","#f5b6cd","#e10098","#cd001a","#5f249f",
  "#eeeeee","#cccccc","#666666","#333333","#fff4d6","#d2b48c","#a0522d","#4b2e20",
  "#ffd6d6","#ff9e9e","#ff5555","#800020","#ffe0b2","#ffad42","#ff8000","#b35900",
  "#fff9b0","#d4ed65","#88cc44","#008060","#bdebd0","#80e0cc","#00cccc","#007878",
  "#cceeff","#8ab8ff","#4488ff","#2444aa","#e4d1ff","#bb88ee","#dd77bb","#993366"};
 return index<48?colours[index]:nullptr;
}
class SolidColourPicker {
 struct Choice{SolidColourPicker*owner=nullptr;void*node=nullptr;unsigned index=0;};
 void*root_=nullptr,*cancel_=nullptr;std::array<Choice,48>choices_;
public:
 std::function<void(const std::string&)>chosen;
 std::function<void()>cancelled;
 void*modal()const{return root_;}
 void close(){auto*p=root_;root_=cancel_=nullptr;if(stock_object_valid(p))stock_function<void(*)(void*)>(lv_obj_del)(p);}
 bool show(void*parent,const std::string&selected){
  close();if(!stock_object_valid(parent))return false;
  const int w=stock_function<int(*)(void*)>(lv_obj_get_content_width)(parent),h=stock_function<int(*)(void*)>(lv_obj_get_content_height)(parent);
  if(w<400||h<340)return false;
  root_=stock_function<void*(*)(void*)>(lv_obj_create)(parent);if(!root_)return false;
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(root_,&deleted,33,this)){close();return false;}
  stock_dialog_backdrop(root_);stock_object_place(root_,0,0,w,h);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(root_,0xff3c3f43U,0);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(root_,255,0);
  auto*title=stock_function<void*(*)(void*)>(lv_label_create)(root_);if(!title){close();return false;}
  label(title,"Filament colour");stock_object_place(title,16,12,w-180,40);
  cancel_=stock_function<void*(*)(void*)>(lv_btn_create)(root_);if(!cancel_){close();return false;}
  stock_dialog_backdrop(cancel_);stock_object_place(cancel_,w-148,8,132,48);
  auto*caption=stock_function<void*(*)(void*)>(lv_label_create)(cancel_);if(!caption){close();return false;}
  label(caption,"CANCEL");
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(caption,reinterpret_cast<void*>(MyriadPro_Bold_20),0);
  center_button_caption(cancel_,caption,"CANCEL");
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(cancel_,&pressed,7,this)){close();return false;}
  const int size=std::min((w-32)/8,(h-84)/6),gap=8,left=(w-size*8)/2;
  std::uint32_t current=0;const bool valid=stock_rgb(selected,current);
  for(unsigned i=0;i<choices_.size();++i){
   auto&choice=choices_[i];choice.owner=this;choice.index=i;
   choice.node=stock_function<void*(*)(void*)>(lv_btn_create)(root_);if(!choice.node){close();return false;}
   stock_dialog_backdrop(choice.node);stock_object_place(choice.node,left+int(i%8)*size,68+int(i/8)*size,size-gap,size-gap);
   std::uint32_t rgb=0;stock_rgb(filament_solid_colour(i),rgb);
   stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(choice.node,rgb,0);
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(choice.node,255,0);
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_radius)(choice.node,8,0);
   if(valid&&rgb==current){
    stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_border_width)(choice.node,4,0);
    stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_border_color)(choice.node,0xffff6600U,0);
   }
   if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(choice.node,&picked,7,&choice)){close();return false;}
  }
  return true;
 }
private:
 static void label(void*p,const char*text){
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(MyriadPro_Bold_24),0);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(p,0xffeeeeeeU,0);
  stock_function<void(*)(void*,const char*)>(lv_label_set_text)(p,text);
 }
 bool visible(void*target)const{
  if(!stock_object_valid(root_))return false;
  bool inside=false;
  auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(stock_function<void*(*)()>(lv_disp_get_default)());
  auto*top=stock_function<void*(*)(void*)>(lv_disp_get_layer_top)(nullptr);
  auto*system=stock_function<void*(*)(void*)>(lv_disp_get_layer_sys)(nullptr);
  for(unsigned n=0;target&&n<32;++n){
   if(!stock_object_valid(target)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(target,1))return false;
   if(target==root_)inside=true;
   if(target==screen||target==top||target==system)return inside;
   target=stock_function<void*(*)(void*)>(lv_obj_get_parent)(target);
  }
  return false;
 }
 static void deleted(void*e)noexcept{try{auto*self=static_cast<SolidColourPicker*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(self&&stock_function<void*(*)(void*)>(lv_event_get_target)(e)==self->root_)self->root_=self->cancel_=nullptr;}catch(...){} }
 static void pressed(void*e)noexcept{try{
  auto*self=static_cast<SolidColourPicker*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));
  auto*target=stock_function<void*(*)(void*)>(lv_event_get_target)(e);
  if(!self||target!=self->cancel_||!self->visible(target))return;
  auto callback=self->cancelled;self->close();if(callback)callback();
 }catch(...){} }
 static void picked(void*e)noexcept{try{
  auto*choice=static_cast<Choice*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));
  auto*target=stock_function<void*(*)(void*)>(lv_event_get_target)(e);
  if(!choice||target!=choice->node||!choice->owner->visible(target))return;
  auto*self=choice->owner;const std::string colour=filament_solid_colour(choice->index);
  auto callback=self->chosen;self->close();if(callback)callback(colour);
 }catch(...){} }
};
}}
