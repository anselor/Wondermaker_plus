// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include "stock_dialog_backdrop.hpp"
#include "button_caption.hpp"
#include "stock_header_action.hpp"
#include "stock_palette.hpp"
#include <algorithm>
#include <array>
#include <string>
#include <functional>
namespace wmp_ui { namespace native {
// RGB-only palette: appearances such as rainbow need a richer identity model.
constexpr unsigned kFilamentSolidColourCount=60;
inline const char* filament_solid_colour(unsigned index){
 static const char* const colours[]={
  "#ffffff","#eeeeee","#cccccc","#97999b","#333333","#0c0809",
  "#fff4d6","#e7ceb5","#d2b48c","#a0522d","#714623","#4b2e20",
  "#ffd6d6","#ff9e9e","#ff5555","#cd001a","#800020","#400010",
  "#ffe0b2","#ffad42","#ff8000","#fe5000","#b35900","#5c2900",
  "#fff9b0","#fce300","#e5c229","#bc991c","#806415","#493c0b",
  "#bdebd0","#88cc44","#00b140","#008060","#265b31","#12331c",
  "#c7f2ec","#80e0cc","#49c5b1","#00cccc","#007878","#003d3d",
  "#cceeff","#8ab8ff","#009cde","#2444aa","#03257e","#001333",
  "#e4d1ff","#d0b5f5","#bb88ee","#9255cc","#5f249f","#2c104d",
  "#f5b6cd","#ef94c8","#dd77bb","#e10098","#a40070","#530039"};
 return index<kFilamentSolidColourCount?colours[index]:nullptr;
}
class SolidColourPicker {
 struct Choice{SolidColourPicker*owner=nullptr;void*node=nullptr;unsigned index=0;};
 void*root_=nullptr,*cancel_=nullptr;std::array<Choice,kFilamentSolidColourCount>choices_;
 std::array<Choice,10>families_;void*shade_title_=nullptr;
 int width_=0,height_=0;std::string selected_;
 static unsigned begin(unsigned family){return family*6;}
 static const char* family_name(unsigned i){static const char* names[]={"Neutral","Brown / beige","Red","Orange","Yellow","Green","Teal","Blue","Violet","Pink / magenta"};return names[i];}
public:
 std::function<void(const std::string&)>chosen;
 std::function<void()>cancelled;
 void*modal()const{return root_;}
 void close(){auto*p=root_;root_=cancel_=nullptr;shade_title_=nullptr;for(auto&c:choices_)c.node=nullptr;if(stock_object_valid(p))stock_function<void(*)(void*)>(lv_obj_del)(p);}
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
  cancel_=stock_header_action(root_,"CANCEL",w-148,8,132,48,40);
  if(!cancel_){close();return false;}
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(cancel_,&pressed,7,this)){close();return false;}
  width_=w;height_=h;selected_=selected;
  auto*hint=stock_function<void*(*)(void*)>(lv_label_create)(root_);
  if(!hint){close();return false;}label(hint,"Choose a colour family");stock_object_place(hint,16,68,w-32,30);
  const int cell=(w-32)/5;
  unsigned initial=0;
  for(unsigned i=0;i<kFilamentSolidColourCount;++i)if(selected==filament_solid_colour(i))for(unsigned j=0;j<families_.size();++j)if(i>=begin(j)&&i<begin(j+1))initial=j;
  for(unsigned i=0;i<families_.size();++i){
   auto&choice=families_[i];choice.owner=this;choice.index=i;
   choice.node=stock_function<void*(*)(void*)>(lv_btn_create)(root_);if(!choice.node){close();return false;}
   stock_dialog_backdrop(choice.node);stock_object_place(choice.node,16+int(i%5)*cell,104+int(i/5)*70,cell-10,64);
   std::uint32_t rgb=0;stock_rgb(filament_solid_colour(begin(i)+2),rgb);
   stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(choice.node,0xff292b2eU,0);
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(choice.node,255,0);
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_border_width)(choice.node,4,0);
   stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_border_color)(choice.node,rgb,0);
   auto*name=stock_function<void*(*)(void*)>(lv_label_create)(choice.node);if(!name){close();return false;}
   const char* caption_text=i==1?"Brown /\nbeige":i==9?"Pink /\nmagenta":family_name(i);
   label(name,caption_text);stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(name,reinterpret_cast<void*>(MyriadPro_Bold_20),0);
   center_button_caption(choice.node,name,caption_text);
   if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(choice.node,&family_picked,7,&choice)){close();return false;}
  }
  shade_title_=stock_function<void*(*)(void*)>(lv_label_create)(root_);if(!shade_title_){close();return false;}
  stock_object_place(shade_title_,16,246,w-32,32);
  if(!show_family(initial)){close();return false;}
  return true;
 }
private:
 bool show_family(unsigned family){
  for(auto&c:choices_){if(stock_object_valid(c.node))stock_function<void(*)(void*)>(lv_obj_del)(c.node);c.node=nullptr;}
  label(shade_title_,("Choose a shade · "+std::string(family_name(family))).c_str());
  const unsigned count=begin(family+1)-begin(family);const int cell=(width_-32)/int(count);
  std::uint32_t current=0;const bool valid=stock_rgb(selected_,current);
  for(unsigned i=begin(family);i<begin(family+1);++i){
   auto&c=choices_[i];c.owner=this;c.index=i;c.node=stock_function<void*(*)(void*)>(lv_btn_create)(root_);if(!c.node)return false;
   stock_dialog_backdrop(c.node);stock_object_place(c.node,16+int(i-begin(family))*cell,288,cell-10,height_-308);
   std::uint32_t rgb=0;stock_rgb(filament_solid_colour(i),rgb);
   stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(c.node,rgb,0);
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(c.node,255,0);
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_radius)(c.node,8,0);
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_border_width)(c.node,valid&&rgb==current?4:0,0);
   stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_border_color)(c.node,0xffff6600U,0);
   if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(c.node,&picked,7,&c))return false;
  }
  return true;
 }
 static void family_picked(void*e)noexcept{try{
  auto*c=static_cast<Choice*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));
  auto*t=stock_function<void*(*)(void*)>(lv_event_get_target)(e);
  if(c&&t==c->node&&c->owner->visible(t))if(!c->owner->show_family(c->index))c->owner->close();
 }catch(...){} }
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
 static void deleted(void*e)noexcept{try{auto*self=static_cast<SolidColourPicker*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(self&&stock_function<void*(*)(void*)>(lv_event_get_target)(e)==self->root_){self->root_=self->cancel_=self->shade_title_=nullptr;for(auto&c:self->choices_)c.node=nullptr;}}catch(...){} }
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
