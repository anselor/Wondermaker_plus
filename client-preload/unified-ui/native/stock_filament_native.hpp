// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_filament_page.hpp"
#include "stock_palette.hpp"
#include "stock_api.hpp"
#include "stock_brand_controls.hpp"
#include "stock_toolhead_view.hpp"
#include "stock_ace_filaments.hpp"
#include "stock_profile_import.hpp"
#include <list>
#include <cstdint>
#include <functional>
#include <string>
#include <cstring>
#include <cmath>
#include <cstdio>
namespace wmp_ui { namespace native {
// Used only after executable + profile window verification in Runtime.
// Reuses stock cards/pickers and adds only missing brand selectors inside cards.
// No replacement root, sidebar or Settings navigation is created here.
class StockFilamentNative : public StockGeometryPort {
public:
 StockFilamentNative(){ace_.focus_head=[this](unsigned head){tool_head_=head;ace_filter_=true;if(select_tool)select_tool(head);};tools_.select_head=[this](unsigned head){
  if(tool_mode_&&!blocked_&&!import_view_.active()&&visible()&&fresh_&&head<count_&&select_tool){message_.clear();select_tool(head);}
 };import_view_.dismissed=[this](){ace_.interaction_blocked(false);};}
 bool import_active()const{return import_view_.active();}
 StockProfileImport& import_controls(){return import_view_;}
 void* content()const{return lifecycle_.active()&&valid(content_)?content_:nullptr;}
 void interaction_blocked(bool value){blocked_=value;}
 void* page()const{return lifecycle_.active()&&valid(page_)?page_:nullptr;}
 StockAceFilaments& ace_controls(){return ace_;}
 void ace_mode(bool enabled,unsigned head=0){ace_mode_=enabled;tool_head_=head;if(enabled){tool_mode_=false;identity_head_=-1;}}
 StockToolheadView& tool_controls(){return tools_;}
 void tool_mode(bool enabled,unsigned head=0){tool_mode_=enabled;ace_mode_=false;tool_head_=head;if(enabled)identity_head_=-1;}
 void identity_head(int head){message_.clear();identity_head_=head;if(head>=0&&head<4)tool_head_=unsigned(head);}
 void tool_data(const Json&data,int step,int target){
  tool_data_=data;tool_step_=step;tool_target_=target;import_view_.update(data);
#ifndef WMP_NATIVE_TEST
  // Read-only display adapter, verified against stock 1.1.13 update_common_status.
  // all_filament_info is four 8-byte records: material byte +2, diameter float +4.
  // Keep command admission on the backend snapshot; these are display values only.
  for(auto&h:tool_data_["heads"]){
   const auto id=h.value("id","");if(id.size()!=2||id[0]!='h'||id[1]<'0'||id[1]>'3')continue;
   unsigned i=id[1]-'0';const auto*record=reinterpret_cast<const unsigned char*>(0x384d078)+8*i;
   float diameter=0;std::memcpy(&diameter,record+4,sizeof(diameter));
   const bool nozzle_owned=data.value("owner","")=="standalone"&&data.value("capabilities",Json::object()).value("save_nozzle",false);
   if(!nozzle_owned&&std::isfinite(diameter)&&diameter>0&&diameter<=2){char text[24];std::snprintf(text,sizeof(text),"%.1f mm",double(diameter));h["nozzle"]["diameter"]=text;}
   if(!nozzle_owned&&record[2]<2){
    const auto&name=reinterpret_cast<const std::string*>(0x386db68)[record[2]];
    h["nozzle"]["material"]=name;
   }
   if(nozzle_owned&&data.value("fresh",false)){
    const auto nozzle=h.value("nozzle",Json::object());const auto material=nozzle.value("material","");const double saved=nozzle.value("saved_diameter",0.0);
    if((material=="Hardened steel"||material=="Stainless steel")&&std::isfinite(saved)&&saved>0&&saved<=2){
     auto*cache=reinterpret_cast<unsigned char*>(0x384d078)+8*i;cache[2]=material=="Hardened steel"?0:1;
     const float value=float(saved);std::memcpy(cache+4,&value,sizeof(value));
    }
   }
   if(data.value("fresh",false)){
    const int actual=reinterpret_cast<const int*>(0xe6453d0)[i],target_value=reinterpret_cast<const int*>(0xe6453e0)[i];
    if(actual>=0&&actual<=500&&target_value>=0&&target_value<=500){h["actual"]=actual;h["target"]=target_value;}
   }
  }
#endif
 }
 std::function<void(unsigned)> select_tool,open_toolheads;
 std::function<void()> finish_setup;
 void onboarding(bool value){onboarding_=value;}
 StockBrandControls& brand_controls(){return brand_controls_;}
 void brands(const std::array<std::string,4>&values,const std::vector<std::string>&catalogue){brands_=values;brand_catalogue_=catalogue;}
 // Return false to withhold entry; true allows the stock picker constructor.
 void material_entry(std::function<bool(unsigned)> callback){material_entry_=std::move(callback);}
 void colour_entry(std::function<bool(unsigned)> callback){colour_entry_=std::move(callback);}
 void message(std::string value){message_=std::move(value);}
 void material_labels(const std::array<std::string,4>&values){materials_=values;}
 void colour_sources(const std::array<const char*,4>&values){colours_=values;}
 // Recolour the stock white circle for arbitrary RGB values, preserving its
 // transparency and shape. Zero means use the stock image without recolouring.
 void colour_tints(const std::array<std::uint32_t,4>&values){tints_=values;}
 bool valid(void*p)const override{return p&&stock_function<bool(*)(void*)>(lv_obj_is_valid)(p);}
 void*parent(void*p)const override{return stock_function<void*(*)(void*)>(lv_obj_get_parent)(p);}
 void place(void*p,StockRect r)override{
  stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(p,r.w,r.h);
  stock_function<void(*)(void*,int,int,int)>(lv_obj_align)(p,1,r.x,r.y); // LV_ALIGN_TOP_LEFT
 }
 void created(void*page){
#if defined(__aarch64__)
  if(!valid(page))return;
  StockFilamentWidgets view;view.content=pointer(0x3862f58);
  const int count=*reinterpret_cast<const volatile int*>(0x385c260);
  if(count<1||count>4||!valid(view.content)||parent(view.content)!=page)return;
  view.count=unsigned(count);
  for(unsigned i=0;i<view.count;++i){auto&s=view.slots[i];s.card=pointer(0x3862b20+8*i);
   s.number=pointer(0x3862b40+8*i);s.colour=pointer(0x3862b60+8*i);
   s.material=pointer(0x3862b80+8*i);s.material_label=pointer(0x3862ba0+8*i);}
  attach(view,page,pointer(0x3862b18),pointer(0x3862b10));
#else
  (void)page;
#endif
 }
 // Separate capture from binding so the same native lifetime/callback path is
 // exercised by the host LVGL harness (not merely the geometry abstraction).
 void attach(const StockFilamentWidgets&view,void*page,void*actions,void*tips){
  if(!valid(page)||!valid(view.content)||parent(view.content)!=page||
     !valid(actions)||parent(actions)!=view.content||
     !valid(tips)||parent(tips)!=view.content)return;
  (void)external_filament_columns(view,*this,670,340); // Whole hierarchy check, no writes.
  import_view_.close();ace_.interaction_blocked(false);brand_controls_.retire();
  const auto generation=lifecycle_.created(view,page);
  // Callback data stays stable until DELETE. A constructor call for a new page
  // may precede deletion of the old page, so never reuse a single mutable token.
  bindings_.push_back({this,generation});auto*binding=&bindings_.back();
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(view.content,&on_delete,33,binding)){
   lifecycle_.deleted(generation);bindings_.pop_back();return;
  }
  page_=page;content_=view.content;actions_=actions;tips_=tips;fresh_=false;slots_=view.slots;count_=view.count;tool_labels_.fill(nullptr);navigation_=nullptr;finish_=nullptr;finish_notice_=nullptr;import_button_=nullptr;navigation_binding_=binding;
  if(tool_head_>=count_)tool_head_=0;
  // Capture the verified first decorative child before vendor layout runs.
  rule_=nullptr;
  if(stock_function<unsigned(*)(void*)>(lv_obj_get_child_cnt)(content_)>0){
   auto*first=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(content_,0);
   if(first!=actions_&&first!=tips_&&stock_function<unsigned(*)(void*)>(lv_obj_get_child_cnt)(first)==0&&
      stock_function<bool(*)(void*,const void*)>(lv_obj_check_type)(first,reinterpret_cast<void*>(0x3636328)))rule_=first;
  }
  // Arm before returning from construction, not on the next status/timer tick.
  stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(actions_,1);
 }
 bool visible()const{
  if(!lifecycle_.active()||!valid(page_)||!valid(content_))return false;
  auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);
  void*ancestor=content_;unsigned depth=0;
  while(ancestor&&ancestor!=screen&&depth++<16){
   if(!valid(ancestor)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(ancestor,1))return false;
   ancestor=parent(ancestor);
  }
  return ancestor==screen;
 }
 void tick(bool fresh,bool standalone){
  ace_.interaction_blocked(import_view_.active());
  fresh_=false;
  if(!visible()){ace_.discard_drafts();return;}
  fresh_=fresh&&standalone;
  // Vendor refresh may show the motion row again after page construction.
  if(valid(actions_)&&parent(actions_)==content_)stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(actions_,1);
  // Check geometry after layout and keep the vendor refresh from restoring it.
  if(valid(rule_)&&parent(rule_)==content_&&stock_function<int(*)(void*)>(lv_obj_get_height)(rule_)<=2&&stock_function<int(*)(void*)>(lv_obj_get_width)(rule_)>400)
   stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(rule_,1);
  const int width=stock_function<int(*)(void*)>(lv_obj_get_content_width)(content_);
  const int height=stock_function<int(*)(void*)>(lv_obj_get_content_height)(content_);
  if(tool_mode_||ace_mode_){
   if(width<640||height<300)return;
   if(!ace_mode_){tools_.mount(content_);tools_.head_count(count_);}
   for(unsigned i=0;i<count_;++i){auto&s=slots_[i];
    if(!valid(s.card)||parent(s.card)!=content_)return;
    if(tool_mode_){
     const bool chosen=i==tool_head_;
     stock_function<void(*)(void*,unsigned)>(chosen?lv_obj_clear_flag:lv_obj_add_flag)(s.card,1);
     if(chosen){
      place(s.card,{12,80,180,height-182});
      place(s.colour,{4,0,83,83});place(s.material,{92,36,80,38});place(s.material_label,{0,5,80,28});
      stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(s.material_label,reinterpret_cast<void*>(0x26297a0),0);
      stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(s.number,1);
      for(auto*child:{s.colour,s.material})stock_function<void(*)(void*,unsigned)>(lv_obj_clear_flag)(child,1);
      if(valid(tool_labels_[i]))stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(tool_labels_[i],1);
      const auto identity=StockToolheadView::identity_for(tool_data_,i);
      bool loaded=false;for(const auto&head:tool_data_.value("heads",Json::array()))if(head.value("id","")=="h"+std::to_string(i))loaded=head.value("loaded",Json::object()).value("state","")=="loaded";
      const auto material=identity.value("material","");
      stock_function<void(*)(void*,const char*)>(lv_label_set_text)(s.material_label,(loaded&&material.empty()?std::string("Unknown"):material).c_str());
      stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(s.material,1);
      std::uint32_t tint=0;const bool known=stock_rgb(identity_display_text(identity,"color",""),tint);
      stock_function<void(*)(void*,unsigned)>(known?lv_obj_clear_flag:lv_obj_add_flag)(s.colour,1);
#if defined(__aarch64__) || defined(WMP_NATIVE_TEST)
      if(known)for(int state=0;state<2;++state){
       const auto*white=stock_white_filament_asset();
       stock_function<void(*)(void*,int,const void*,const void*,const void*)>(lv_imgbtn_set_src)(s.colour,state,nullptr,white,nullptr);
       stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_img_recolor)(s.colour,tint,state?0x20:0);
       stock_function<void(*)(void*,unsigned char,unsigned)>(lv_obj_set_style_img_recolor_opa)(s.colour,255,state?0x20:0);
      }
#endif
     }
     continue;
    }
    place(s.card,{12+int(i)*(width-24)/4,4,(width-24)/4-8,40});
    for(auto style:{std::uintptr_t(0x463c908),std::uintptr_t(0x463c918)})
     stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_remove_style)(s.card,reinterpret_cast<void*>(style),0);
    stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(s.card,reinterpret_cast<void*>(ace_filter_&&i==tool_head_?0x463c918:0x463c908),0);
    for(auto*child:{s.number,s.colour,s.material})if(valid(child))stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(child,1);
    if(!tool_labels_[i]){tool_labels_[i]=stock_function<void*(*)(void*)>(lv_label_create)(s.card);
     stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(tool_labels_[i],reinterpret_cast<void*>(0xf84928),0);}
    const auto title="Head "+std::to_string(i+1);
    stock_function<void(*)(void*,const char*)>(lv_label_set_text)(tool_labels_[i],title.c_str());place(tool_labels_[i],{8,8,(width-24)/4-24,26});center_button_caption(s.card,tool_labels_[i],title);
   }
   if(ace_mode_){
    if(valid(tips_))stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(tips_,1);
    update_navigation(height);ace_.mount(content_);auto data=tool_data_;data["fresh"]=fresh_;
    const bool head_tabs=!data.value("units",Json::array()).empty();data["head_tabs_visible"]=head_tabs;
    ace_.update(data,head_tabs&&ace_filter_?"h"+std::to_string(tool_head_):"",width,height,46);
    // The editor is inset within stock content; hide the overview tabs rather
    // than allowing their selected borders to peek around the modal edges.
    for(unsigned i=0;i<count_;++i)
     stock_function<void(*)(void*,unsigned)>((ace_.modal_active()||!head_tabs)?lv_obj_add_flag:lv_obj_clear_flag)(slots_[i].card,1);
    if(ace_.modal_active())for(auto*p:{navigation_,import_button_,finish_,finish_notice_})if(valid(p))stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(p,1);
    return;
   }
   if(valid(tips_)){
    stock_function<void(*)(void*,unsigned)>(lv_obj_clear_flag)(tips_,1);
    const auto mounting=StockToolheadView::mounting_for(tool_data_,tool_head_);
    const auto title=message_.empty()?"Toolhead management - "+mounting:mounting+" - "+message_;
    place(tips_,{12,0,width-24,28});
    stock_function<void(*)(void*,const char*)>(lv_label_set_text)(tips_,fresh_?title.c_str():"Printer status unavailable");
   }
   tools_.update(tool_data_,tool_head_,tool_step_,tool_target_,width,height);return;
  }
  lifecycle_.apply(*this,page_,width,height,fresh,standalone);
  if(lifecycle_.applied()){
   update_navigation(height);
   if(identity_head_>=0){
    for(unsigned i=0;i<count_;++i){auto&s=slots_[i];const bool chosen=int(i)==identity_head_;
     stock_function<void(*)(void*,unsigned)>(chosen?lv_obj_clear_flag:lv_obj_add_flag)(s.card,1);
     if(chosen){
      place(s.card,{(width-280)/2,40,280,height-88});
      place(s.colour,{98,40,83,83});place(s.material,{8,126,264,38});place(s.material_label,{0,5,264,28});
     }
    }
   }
   for(unsigned i=0;i<count_;++i)if((identity_head_<0||int(i)==identity_head_)&&valid(slots_[i].card)&&parent(slots_[i].card)==content_)
    if(!brands_[i].empty())brand_controls_.update(i,slots_[i].card,brands_[i],brand_catalogue_,fresh_);
   // Hide the actual stock action container; no invisible covering widget.
   // The scoped callback guard below is a second barrier against queued clicks.
   if(valid(actions_)&&parent(actions_)==content_)stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(actions_,1);
   if(valid(tips_)&&parent(tips_)==content_)stock_function<void(*)(void*,const char*)>(lv_label_set_text)(tips_,fresh_?(message_.empty()?(identity_head_>=0?("Head "+std::to_string(identity_head_+1)+" - filament settings").c_str():"Filament settings"):message_.c_str()):"Printer status unavailable");
   if(fresh_)for(unsigned i=0;i<count_;++i){const auto&s=slots_[i];
    if(!materials_[i].empty()&&valid(s.material_label)&&parent(s.material_label)==s.material)
     stock_function<void(*)(void*,const char*)>(lv_label_set_text)(s.material_label,materials_[i].c_str());
    if(colours_[i]&&valid(s.colour)&&parent(s.colour)==s.card){
     for(int state=0;state<2;++state){
      stock_function<void(*)(void*,int,const void*,const void*,const void*)>(lv_imgbtn_set_src)(s.colour,state,nullptr,colours_[i],nullptr);
      const unsigned selector=state?0x20:0; // LV_STATE_PRESSED / default
      stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_img_recolor)(s.colour,tints_[i],selector);
      stock_function<void(*)(void*,unsigned char,unsigned)>(lv_obj_set_style_img_recolor_opa)(s.colour,tints_[i]?255:0,selector);
     }
    }
   }
  }
 }
 bool intercept(void*event){
  if(!event||!lifecycle_.active()||!valid(content_))return false;
  if(stock_function<int(*)(void*)>(lv_event_get_code)(event)!=7)return false;
  auto*object=stock_function<void*(*)(void*)>(lv_event_get_target)(event);
  // Only the migrated page's descendants: no global command or event filter.
  unsigned depth=0;while(object&&object!=content_&&depth++<16){if(!valid(object))return false;object=parent(object);}
  if(object!=content_)return false;
  if(blocked_||import_view_.active())return true;
  const auto action=reinterpret_cast<std::uintptr_t>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(event));
  if(tool_mode_&&action>=8&&action<=15){
   if(fresh_&&visible()&&unsigned((action-8)%4)==tool_head_&&tools_.edit_allowed()&&tools_.action)tools_.action("edit-filament");
   return true;
  }
  if(tool_mode_||ace_mode_){
   if(ace_mode_&&ace_.modal_active())return true;
   if(fresh_&&action>=4&&action<=7&&select_tool){
    const auto head=unsigned(action-4);if(ace_mode_)ace_filter_=head==tool_head_?!ace_filter_:true;
    select_tool(head);
   }return true;
  }
  // Verified callback IDs: 0 load, 1 unload, 2 release, 3 take. These do not
  // belong on Filament settings even if a delayed/programmatic click arrives.
  if(action<=3)return true;
  // Stock 4..7 select, 8..11 colour, 12..15 material. Retain their constructors,
  // capturing a WM+ draft before entry. Never dispatch a stale click as an edit.
  // Modal close (16) is handled separately by the captured-modal bootstrap.
  if(action>=4&&action<=15&&(!fresh_||!lifecycle_.applied()))return true;
  if(identity_head_>=0&&action>=4&&action<=15&&int((action-4)%4)!=identity_head_)return true;
  if(action>=4&&action<=7)tool_head_=unsigned(action-4);
  if(action>=12&&action<=15&&material_entry_)return !material_entry_(unsigned(action-12));
  if(action>=8&&action<=11&&colour_entry_)return !colour_entry_(unsigned(action-8));
  return false;
 }
private:
 void*rule_=nullptr;bool blocked_=false;int identity_head_=-1;
 StockAceFilaments ace_;bool ace_mode_=false;bool ace_filter_=true;StockToolheadView tools_;bool tool_mode_=false;unsigned tool_head_=0;int tool_step_=10,tool_target_=220;Json tool_data_;
 std::array<void*,4>tool_labels_{{nullptr,nullptr,nullptr,nullptr}};
 StockBrandControls brand_controls_;std::array<std::string,4> brands_;std::vector<std::string>brand_catalogue_;
 struct Binding{StockFilamentNative*owner;std::uint64_t generation;};
 std::function<bool(unsigned)> material_entry_,colour_entry_;std::string message_;
 std::array<std::string,4> materials_;std::array<StockSlotWidgets,4> slots_;unsigned count_=0;
 std::array<const char*,4> colours_{{nullptr,nullptr,nullptr,nullptr}};
 std::array<std::uint32_t,4> tints_{{0,0,0,0}};
 StockProfileImport import_view_;void*import_button_=nullptr;
 void*navigation_=nullptr,*finish_=nullptr,*finish_notice_=nullptr;bool onboarding_=false;Binding*navigation_binding_=nullptr;
 void update_navigation(int height){
  if(onboarding_&&!finish_){
   finish_=stock_function<void*(*)(void*)>(lv_btn_create)(content_);
   if(finish_){
    stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(finish_,reinterpret_cast<void*>(0x463c8e8),0);
    auto*label=stock_function<void*(*)(void*)>(lv_label_create)(finish_);
    stock_function<void(*)(void*,const char*)>(lv_label_set_text)(label,"FINISH");
    stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(label,reinterpret_cast<void*>(0x26297a0),0);
    place(finish_,{12,height-44,176,38});center_button_caption(finish_,label,"FINISH");
    stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(finish_,&finish_setup_event,7,navigation_binding_);
   }
  }
  if(valid(finish_)){
   stock_function<void(*)(void*,unsigned)>(onboarding_?lv_obj_clear_flag:lv_obj_add_flag)(finish_,1);
   place(finish_,{12,height-44,176,38});
   stock_function<void(*)(void*,unsigned)>(fresh_&&!blocked_?lv_obj_clear_state:lv_obj_add_state)(finish_,128);
  }
  if(onboarding_&&!message_.empty()&&!finish_notice_)finish_notice_=stock_function<void*(*)(void*)>(lv_label_create)(content_);
  if(valid(finish_notice_)){
   place(finish_notice_,{198,height-44,270,38});
   stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(finish_notice_,reinterpret_cast<void*>(lv_font_montserrat_14),0);
   stock_function<void(*)(void*,const char*)>(lv_label_set_text)(finish_notice_,message_.c_str());
   stock_function<void(*)(void*,unsigned)>(onboarding_&&!message_.empty()?lv_obj_clear_flag:lv_obj_add_flag)(finish_notice_,1);
  }
  if(!navigation_){
   navigation_=stock_function<void*(*)(void*)>(lv_btn_create)(content_);
   if(!navigation_)return;
   if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(navigation_,&navigate,7,navigation_binding_)){
    stock_function<void(*)(void*)>(lv_obj_del)(navigation_);navigation_=nullptr;return;
   }
   stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(navigation_,reinterpret_cast<void*>(0x463c8e8),0);
   stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(navigation_,reinterpret_cast<void*>(0x463c8f8),0x20);
   auto*label=stock_function<void*(*)(void*)>(lv_label_create)(navigation_);
   stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(label,reinterpret_cast<void*>(0x26297a0),0);
   stock_function<void(*)(void*,const char*)>(lv_label_set_text)(label,"Toolheads");
   place(label,{6,8,164,22});
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_text_align)(label,2,0);
  }
  // USB profile importing is deferred; keep its implementation for a later release.
  const int width=stock_function<int(*)(void*)>(lv_obj_get_content_width)(content_);
  place(navigation_,{width-188,height-44,176,38});
  for(auto*p:{navigation_,import_button_})if(valid(p))stock_function<void(*)(void*,unsigned)>(lv_obj_clear_flag)(p,1);
  stock_function<void(*)(void*,unsigned)>(fresh_?lv_obj_clear_state:lv_obj_add_state)(navigation_,128);
 }
 static void finish_setup_event(void*event)noexcept{try{
  auto*b=static_cast<Binding*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(event));if(!b)return;auto*o=b->owner;
  if(!o->lifecycle_.active()||b->generation!=o->lifecycle_.generation()||!o->visible()||!o->onboarding_||!o->fresh_||o->blocked_||o->ace_.modal_active()||o->import_view_.active())return;
  if(stock_function<void*(*)(void*)>(lv_event_get_target)(event)!=o->finish_)return;
  if(o->finish_setup)o->finish_setup();
 }catch(...){} }
 static void import_pressed(void*event)noexcept{try{
  auto*b=static_cast<Binding*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(event));if(!b)return;auto*o=b->owner;
  if(!o->lifecycle_.active()||b->generation!=o->lifecycle_.generation()||!o->visible()||o->tool_mode_||o->import_view_.active()||stock_function<void*(*)(void*)>(lv_event_get_target)(event)!=o->import_button_)return;
  if(o->import_view_.show(o->content_))o->ace_.interaction_blocked(true);
 }catch(...){} }
 static void navigate(void*event)noexcept{
  try{auto*b=static_cast<Binding*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(event));if(!b)return;
   auto*o=b->owner;
   if(!o->lifecycle_.active()||b->generation!=o->lifecycle_.generation()||o->tool_mode_||o->blocked_||o->import_view_.active())return;
   // Recheck visibility and freshness, including queued clicks after navigation.
   const bool fresh=o->fresh_;o->tick(fresh,true);
   if(!o->fresh_||!o->valid(o->navigation_)||o->tool_head_>=o->count_)return;
   unsigned head=o->tool_head_;
   for(const auto&h:o->tool_data_.is_object()?o->tool_data_.value("heads",Json::array()):Json::array()){const auto id=h.value("id","");if(h.value("mounting","")=="Mounted"&&id.size()==2&&id[0]=='h'&&id[1]>='0'&&id[1]<'0'+int(o->count_))head=unsigned(id[1]-'0');}
   if(o->open_toolheads)o->open_toolheads(head);
  }catch(...){}
 }
 std::list<Binding>bindings_;StockFilamentPage lifecycle_;void*page_=nullptr,*content_=nullptr,*actions_=nullptr,*tips_=nullptr;bool fresh_=false;
 static void*pointer(std::uintptr_t address){return *reinterpret_cast<void*volatile*>(address);}
 static void on_delete(void*event)noexcept{
  try{auto*b=static_cast<Binding*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(event));if(!b)return;
   auto*owner=b->owner;owner->lifecycle_.deleted(b->generation);
   for(auto it=owner->bindings_.begin();it!=owner->bindings_.end();++it)if(&*it==b){owner->bindings_.erase(it);break;}
  }catch(...){}
 }
};
}}
