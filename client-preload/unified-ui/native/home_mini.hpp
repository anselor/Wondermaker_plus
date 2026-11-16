// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "lvgl_surface.hpp"
namespace wmp_ui { namespace native {
// Covers only the original Home filament button. The root owns navigation so
// legacy image children cannot swallow touches over individual indicators.
class HomeMini {
public:
 std::function<void()> open_filaments;
 void update(const Json&data,void*main,void*first_stock_icon){
  if(!valid(main)||!valid(first_stock_icon)||!descendant(first_stock_icon,main)||!shown(main)){clear();return;}
  auto display=call<void*(*)()>(lv_disp_get_default)();auto screen=display?call<void*(*)(void*)>(lv_disp_get_scr_act)(display):nullptr;
  if(!screen||!descendant(main,screen)){clear();return;}
  auto parent=call<void*(*)(void*)>(lv_obj_get_parent)(first_stock_icon);
  if(!parent||parent==main){clear();return;}
  Area bounds{},content{};call<void(*)(void*,Area*)>(lv_obj_get_coords)(parent,&bounds);call<void(*)(void*,Area*)>(lv_obj_get_content_coords)(parent,&content);
  int width=bounds.x2-bounds.x1+1,height=bounds.y2-bounds.y1+1;if(width<80||height<35||width>300||height>150){clear();return;}
  bool stale=!data.value("fresh",false)||data.value("owner","")=="unknown";
  auto units=data.value("units",Json::array()),sources=data.value("sources",Json::array());
  bool ace=data.value("owner","")=="openace";bool alert=ace&&!data.value("candidates",Json::array()).empty();
  // Temperature/target changes must not delete the touch target mid-gesture.
  Json heads=Json::array();for(const auto&head:data.value("heads",Json::array())){
   const auto loaded=head.value("loaded",Json::object());
   heads.push_back({{"id",head.value("id","")},{"loaded",{{"state",loaded.value("state","unknown")},{"identity",{{"color",identity_display_text(loaded.value("identity",Json::object()),"color","#888888")}}}}}});
  }
  Json signature={{"stale",stale},{"units",units},{"sources",sources},{"heads",heads},{"alert",alert},{"ace",ace},{"width",width},{"height",height}};
  if(root_&&valid(root_)&&parent==parent_&&signature.dump()==signature_)return;
  if(!valid(root_)||parent!=parent_){
   clear();parent_=parent;root_=new_box(parent,bounds.x1-content.x1,bounds.y1-content.y1,width,height,0xff505258);
   call<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(root_,&deleted,33,this);
   call<void(*)(void*,unsigned)>(lv_obj_add_flag)(root_,2);
   call<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(root_,&pressed,7,this);
  }else{
   // Decorative children cannot receive input. Keep their parent touch target
   // alive across freshness, presence and colour updates.
   // Retain decorative objects as well as the parent touch target.
   for(const auto&item:decorations_)if(valid(item.second))call<void(*)(void*,unsigned)>(lv_obj_add_flag)(item.second,1);
   call<void(*)(void*,int,int)>(lv_obj_set_pos)(root_,bounds.x1-content.x1,bounds.y1-content.y1);
   call<void(*)(void*,int,int)>(lv_obj_set_size)(root_,width,height);
  }
  signature_=signature.dump();
  if(stale){label(root_,"status","Status\nunavailable",3,5,width-6,height-10);return;}
  if(ace&&!units.empty()){
   // Up to eight registered ACEs fit as two rows; remaining units have a count.
   unsigned shown_count=std::min<std::size_t>(units.size(),8);int cols=shown_count<=4?int(shown_count):4,rows=shown_count<=4?1:2;
   int cellw=(width-8)/cols,cellh=(height-12)/rows;
   for(unsigned i=0;i<shown_count;++i){const auto&u=units[i];int x=4+int(i%cols)*cellw,y=6+int(i/cols)*cellh;auto outline=box(root_,"unit:"+std::to_string(i),x,y,cellw-3,cellh-3,0xff33373c);style(outline,lv_obj_set_style_border_width,1);color(outline,lv_obj_set_style_border_color,u.value("connected",false)?0xffaaaaaa:0xff777777);
    for(int slot=0;slot<4;++slot){std::string shade="#555555";for(const auto&s:sources)if(s.value("unit","")==u.value("id","")&&s.value("slot",-1)==slot)shade=identity_display_text(s.value("identity",Json::object()),"color",shade);
     int sw=std::max(1,(cellw-9)/4);auto square=box(outline,"slot:"+std::to_string(i)+":"+std::to_string(slot),3+slot*sw,3,std::max(1,sw-1),std::max(2,cellh-9),parse(shade));if(!u.value("connected",false))style(square,lv_obj_set_style_opa,100);
    }
   }
   if(units.size()>8)label(root_,"overflow","+"+std::to_string(units.size()-8),width-30,height-20,30,20);
  }else {
   // Presence and loaded identity come from the same physical-head projection
   // as the filament page. Saved source metadata does not prove presence.
   int n=0;for(int i=0;i<4;++i){
    const auto id="h"+std::to_string(i);bool external=false;
    for(const auto&s:sources)if(s.value("kind","")=="external"&&s.value("head","")==id)external=true;
    if(!external)continue;
    Json loaded=Json::object();for(const auto&h:heads)if(h.value("id","")==id)loaded=h.value("loaded",Json::object());
    const auto state=loaded.value("state","unknown");
    const int cell=(width-10)/4,diameter=std::max(2,std::min(cell-4,height-16));
    const auto shade=identity_display_text(loaded.value("identity",Json::object()),"color","#888888");
    auto circle=box(root_,"head:"+id,5+n*cell+(cell-diameter)/2,(height-diameter)/2,diameter,diameter,parse(shade));
    style(circle,lv_obj_set_style_radius,diameter/2);
    if(state!="loaded"){
     style(circle,lv_obj_set_style_bg_opa,0);style(circle,lv_obj_set_style_border_width,1);
     color(circle,lv_obj_set_style_border_color,0xff888888);
     if(state!="empty")label(circle,"unknown:"+id,"?",0,0,diameter,diameter);
    }
    ++n;
   }
  }
  if(alert){auto badge=box(root_,"alert",width-17,0,17,19,0xffed7900);label(badge,"alert-text","!",0,0,17,19);}
 }
 void clear(){if(root_&&valid(root_))call<void(*)(void*)>(lv_obj_del)(root_);root_=nullptr;parent_=nullptr;signature_.clear();decorations_.clear();}
private:
 struct Area{short x1,y1,x2,y2;};void*root_=nullptr,*parent_=nullptr;std::string signature_;std::map<std::string,void*>decorations_;
 template<class F>static F call(std::uintptr_t p){return LvglSurface::call<F>(p);}
 static bool valid(void*p){return p&&call<bool(*)(void*)>(lv_obj_is_valid)(p);}
 static bool descendant(void*p,void*ancestor){for(int i=0;p&&i<64;++i){if(p==ancestor)return true;p=call<void*(*)(void*)>(lv_obj_get_parent)(p);}return false;}
 static bool shown(void*p){for(int i=0;p&&i<64;++i){if(call<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return false;p=call<void*(*)(void*)>(lv_obj_get_parent)(p);}return !p;}
 static void style(void*p,std::uintptr_t f,int v){call<void(*)(void*,int,int)>(f)(p,v,0);}
 static void color(void*p,std::uintptr_t f,std::uint32_t v){call<void(*)(void*,std::uint32_t,int)>(f)(p,v,0);}
 static std::uint32_t parse(const std::string&s){if(s.size()!=7||s[0]!='#'||s.substr(1).find_first_not_of("0123456789abcdefABCDEF")!=std::string::npos)return 0xff555555;return 0xff000000|std::stoul(s.substr(1),nullptr,16);}
 static void*new_box(void*parent,int x,int y,int w,int h,std::uint32_t shade){auto p=call<void*(*)(void*)>(lv_obj_create)(parent);if(!p)throw std::runtime_error("Home mini allocation failed");
  call<void(*)(void*,void*,unsigned)>(lv_obj_remove_style)(p,nullptr,0);for(unsigned f:{2U,16U})call<void(*)(void*,unsigned)>(lv_obj_clear_flag)(p,f);
  for(auto f:{lv_obj_set_style_pad_top,lv_obj_set_style_pad_bottom,lv_obj_set_style_pad_left,lv_obj_set_style_pad_right})style(p,f,0);
  call<void(*)(void*,int,int)>(lv_obj_set_pos)(p,x,y);call<void(*)(void*,int,int)>(lv_obj_set_size)(p,w,h);color(p,lv_obj_set_style_bg_color,shade);style(p,lv_obj_set_style_bg_opa,255);style(p,lv_obj_set_style_radius,2);return p;}
 void*box(void*parent,const std::string&key,int x,int y,int w,int h,std::uint32_t shade){
  auto&p=decorations_[key];if(!valid(p))p=new_box(parent,x,y,w,h,shade);
  call<void(*)(void*,unsigned)>(lv_obj_clear_flag)(p,1);
  call<void(*)(void*,int,int)>(lv_obj_set_pos)(p,x,y);call<void(*)(void*,int,int)>(lv_obj_set_size)(p,w,h);
  color(p,lv_obj_set_style_bg_color,shade);style(p,lv_obj_set_style_bg_opa,255);style(p,lv_obj_set_style_opa,255);
  style(p,lv_obj_set_style_border_width,0);style(p,lv_obj_set_style_radius,2);return p;
 }
 void label(void*parent,const std::string&key,const std::string&text,int x,int y,int w,int h){
  auto&p=decorations_[key];if(!valid(p))p=call<void*(*)(void*)>(lv_label_create)(parent);
  call<void(*)(void*,unsigned)>(lv_obj_clear_flag)(p,1);call<void(*)(void*,unsigned)>(lv_obj_clear_flag)(p,2);
  call<void(*)(void*,int,int)>(lv_obj_set_pos)(p,x,y);call<void(*)(void*,int,int)>(lv_obj_set_size)(p,w,h);
  color(p,lv_obj_set_style_text_color,0xffffffff);style(p,lv_obj_set_style_text_align,1);call<void(*)(void*,const char*)>(lv_label_set_text)(p,text.c_str());
 }
 static void deleted(void*event)noexcept {auto*self=static_cast<HomeMini*>(call<void*(*)(void*)>(lv_event_get_user_data)(event));if(self){self->root_=nullptr;self->parent_=nullptr;self->decorations_.clear();}}
 static void pressed(void*event)noexcept {try{
  auto*self=static_cast<HomeMini*>(call<void*(*)(void*)>(lv_event_get_user_data)(event));
  if(!self||!valid(self->root_)||!shown(self->root_)||call<void*(*)(void*)>(lv_event_get_target)(event)!=self->root_)return;
  auto*screen=call<void*(*)(void*)>(lv_disp_get_scr_act)(call<void*(*)()>(lv_disp_get_default)());
  if(screen&&descendant(self->root_,screen)&&self->open_filaments)self->open_filaments();
 }catch(...){} }
};
}}
