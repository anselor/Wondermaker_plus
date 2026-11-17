// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "button_caption.hpp"
#include "stock_api.hpp"
#include "../model.hpp"
#include <list>
#include <map>
namespace wmp_ui { namespace native {
// Missing Toolhead controls live directly inside the stock content object.
// The stock page/card objects, navigation and refresh lifecycle remain owners.
class StockToolheadView {
public:
 std::function<void(const std::string&)> action;
 std::function<void(unsigned)> select_head;
 bool edit_allowed()const{return edit_allowed_;}
 void head_count(unsigned count){head_count_=count;}
 void mount(void*content){if(content_!=content){content_=content;objects_.clear();}}
 static std::string mounting_for(const Json&data,unsigned head){
  if(!data.value("fresh",false))return "Attachment unknown";
  unsigned count=0;std::string mounting;
  for(const auto&h:data.value("heads",Json::array()))if(h.value("id","")=="h"+std::to_string(head)){mounting=h.value("mounting","");++count;}
  if(count!=1)return "Attachment unknown";
  for(const auto*state:{"Mounted","Not mounted","No head mounted"})if(mounting==state)return mounting;
  return "Attachment unknown";
 }
 static bool ace_managed(const Json&data,const std::string&head){
  for(const auto&s:data.value("sources",Json::array()))if(s.value("head","")==head&&s.value("kind","")=="ace")return true;
  return false;
 }
 static Json identity_for(const Json&data,unsigned head){
  const auto id="h"+std::to_string(head);
  for(const auto&h:data.value("heads",Json::array()))if(h.value("id","")==id){
   const auto loaded=h.value("loaded",Json::object());
   if(loaded.value("state","")=="loaded")return loaded.value("identity",Json::object());

  }
  return Json::object();
 }
 void update(const Json&data,unsigned head,int step,int /*target*/,int width,int height){
  if(!content_)return;
  for(unsigned i=0;i<head_count_;++i){
   const auto id="head:"+std::to_string(i);
   button(id,"Head "+std::to_string(i+1),12+int(i)*(width-24)/4,32,(width-24)/4-8,40);
   selection(id,i==head);
   stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(
    objects_.at(id).second,mounting_for(data,i)=="Mounted"?0xffff6600U:0xffeeeeeeU,0);
  }
  const int right=width-146;
  const int middle=right-220;
  label("distance","Distance (mm)",208,80,middle,24);
  for(int value:{1,10,25,50}){
   int col=value==1?0:value==10?1:value==25?2:3;
   const auto id="step:"+std::to_string(value);
   button(id,std::to_string(value),208+col*(middle/4),104,middle/4-6,52);
   selection(id,step==value);
  }
  Json selected;
  for(const auto&h:data.value("heads",Json::array()))if(h.value("id","")=="h"+std::to_string(head))selected=h;
  auto loaded=selected.is_object()?selected.value("loaded",Json::object()):Json::object();
  auto identity=identity_for(data,head);
  bool is_loaded=loaded.value("state","")=="loaded";
  const bool is_empty=loaded.value("state","")=="empty";
  const auto colour=identity_display_text(identity,"color","");
  const bool colour_known=colour.size()==7&&colour[0]=='#'&&colour.substr(1).find_first_not_of("0123456789abcdefABCDEF")==std::string::npos;
  label("empty-colour","",36,94,64,64);
  auto*circle=objects_.at("empty-colour").first;
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_radius)(circle,32,0);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_border_width)(circle,2,0);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_border_color)(circle,0xff999999U,0);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(circle,0,0);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_text_align)(circle,1,0);
  visible("empty-colour",is_empty||(is_loaded&&!colour_known));
  label("unknown-colour","?",62,115,16,24);
  visible("unknown-colour",is_loaded&&!colour_known);
  // The original stock colour/material widgets display identity. Add only
  // the missing brand and observed loaded state, without a covering button.
  const auto brand=identity_display_text(identity,"brand","");
  label("brand",is_loaded&&brand.empty()?"Unknown brand":brand,20,height-174,164,22);
  label("material-text",is_loaded?identity.value("material","Unknown"):"",20,height-151,164,22);
  std::string provenance=is_loaded?"Loaded":is_empty?(loaded.value("sensor_present",false)?"Inserted":"Empty"):"Filament unknown";
  bool ace_managed=false;
  for(const auto&source:data.value("sources",Json::array())){
   if(source.value("head","")=="h"+std::to_string(head)&&source.value("kind","")=="ace")ace_managed=true;
   if(is_loaded&&source.value("id","")==loaded.value("source","")&&source.value("kind","")=="ace"){
    std::string unit=source.value("unit","");
    for(const auto&u:data.value("units",Json::array()))if(u.value("id","")==unit)unit=u.value("name",unit);
    provenance=unit+" / Slot "+std::to_string(source.value("slot",-1)+1);
   }
  }
  label("loaded-state",provenance,20,height-128,164,22);
  button("load","Load",12,height-94,180,38);button("unload","Unload",12,height-94,180,38);
  visible("load",is_empty&&!ace_managed);visible("unload",is_loaded);
  const std::string actual=selected.is_object()&&selected.contains("actual")?std::to_string(int(selected["actual"].get<double>())):"?";
  label("actual","Nozzle temperature",208,height-178,middle,22);
  button("target",actual+" / "+std::to_string(selected.is_object()?selected.value("target",0):0)+" C",208,height-154,middle-44,40);
  button("off","X",208+middle-38,height-154,38,40);
  const auto busy=data.value("tool_ui_busy",Json::object());
  const auto operation=data.value("filament_operation",Json::object()).value("state","");
  const auto tool_operation=data.value("toolhead_operation",Json::object()).value("state","");
  const bool pending=busy.value("pending",false)||operation=="running"||operation=="pending"||tool_operation=="running"||tool_operation=="pending"||(data.value("owner","")!="standalone"&&(operation=="unknown"||tool_operation=="unknown"));
  enabled("load",!pending&&data.value("fresh",false));enabled("unload",!pending&&data.value("fresh",false));
  const bool this_head=busy.value("head","")=="h"+std::to_string(head);
  const auto busy_action=busy.value("action","");
  button("edit-filament","\xef\x8c\x84",152,80,40,32); // Stock Montserrat edit symbol.
  auto edit=objects_.at("edit-filament");
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(edit.second,reinterpret_cast<void*>(lv_font_montserrat_14),0);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_text_align)(edit.second,2,0);
  for(auto property:{lv_obj_set_style_bg_opa,lv_obj_set_style_border_width,lv_obj_set_style_outline_width})
   stock_function<void(*)(void*,int,unsigned)>(property)(edit.first,0,0);
  edit_allowed_=data.value("fresh",false)&&!ace_managed&&selected.is_object()&&(data.value("owner","")=="standalone"||(!pending&&filament_identity_editable(data,"h"+std::to_string(head))));
  visible("edit-filament",edit_allowed_);enabled("edit-filament",edit_allowed_);
  feed_button("retract",pending&&this_head&&busy_action=="retract"?"Retracting...":"Retract\n"+std::to_string(step)+" mm",right,80,true);
  feed_button("extrude",pending&&this_head&&busy_action=="extrude"?"Extruding...":"Extrude\n"+std::to_string(step)+" mm",right,height-130,false);
  for(const auto&id:{"retract","extrude","target","off"})enabled(id,!pending&&data.value("fresh",false));
  if(data.value("owner","")=="standalone")enabled("off",true);
  const bool interrupted=busy.value("interrupted",false);
  const bool in_progress=pending&&this_head&&(busy_action=="load"||busy_action=="unload"||busy_action=="take"||busy_action=="dock");
  button("view-operation",interrupted?"Recover":"Progress",336,height-44,76,38);visible("view-operation",interrupted||in_progress);
  const auto mounting=mounting_for(data,head);
  button("take-dock",mounting=="Mounted"?"Dock":mounting=="Not mounted"||mounting=="No head mounted"?"Mount":"Mount state unknown",12,height-44,180,38);
  const auto tool_state=data.value("toolhead_operation",Json::object()).value("state","");
  enabled("take-dock",take_allowed_=!pending&&data.value("fresh",false)&&data.value("owner","")=="standalone"&&data.value("capabilities",Json::object()).value("toolhead_action",false)&&mounting!="Attachment unknown"&&tool_state!="running"&&(data.value("job",Json::object()).value("state","")=="idle"||data.value("job",Json::object()).value("state","")=="complete"||paused_toolhead_action_available(data,"h"+std::to_string(head),mounting=="Mounted"?"dock":"take")));
  const auto nozzle=selected.is_object()?selected.value("nozzle",Json::object()):Json::object();
  button("nozzle",nozzle.value("diameter","Unknown")+" / "+nozzle.value("material","Unknown")+(nozzle.value("apply_pending",false)?"\nApplies when idle":nozzle.value("restart_required",false)?"\nRestart required":""),208,height-104,middle,48);
  for(auto property:{lv_obj_set_style_bg_opa,lv_obj_set_style_border_width,lv_obj_set_style_outline_width})stock_function<void(*)(void*,int,unsigned)>(property)(objects_.at("nozzle").first,0,0);
  enabled("nozzle",nozzle_allowed_=(data.value("owner","")=="standalone"||!pending)&&data.value("fresh",false)&&data.value("capabilities",Json::object()).value("save_nozzle",false));
 }
private:
 struct Binding{StockToolheadView*owner;void*object;void*content;std::string id;};
 std::list<Binding>bindings_;std::map<std::string,std::pair<void*,void*>>objects_;void*content_=nullptr;unsigned head_count_=4;
 bool edit_allowed_=false,take_allowed_=false,nozzle_allowed_=false;
 std::map<std::string,bool> enabled_;
 // Use the vendor's selected/unselected styles, including its colour and
 // border treatment, rather than decorating selection with mock-only text.
 void selection(const std::string&id,bool selected){
  auto*object=objects_.at(id).first;
  for(auto style:{std::uintptr_t(0x463c908),std::uintptr_t(0x463c918)})
   stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_remove_style)(object,reinterpret_cast<void*>(style),0);
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(object,reinterpret_cast<void*>(selected?0x463c918:0x463c908),0);
 }
 void visible(const std::string&id,bool show){auto it=objects_.find(id);if(it!=objects_.end())stock_function<void(*)(void*,unsigned)>(show?lv_obj_clear_flag:lv_obj_add_flag)(it->second.first,1);}
 void enabled(const std::string&id,bool enable){enabled_[id]=enable;auto it=objects_.find(id);if(it!=objects_.end())stock_function<void(*)(void*,unsigned)>(enable?lv_obj_clear_state:lv_obj_add_state)(it->second.first,128);}
 void control(const std::string&id,const std::string&text,int x,int y,int w,int h,bool clickable){
  auto it=objects_.find(id);
  if(it==objects_.end()){
   void*object=clickable?stock_function<void*(*)(void*)>(lv_btn_create)(content_):stock_function<void*(*)(void*)>(lv_label_create)(content_);
   if(!object)return;
   void*caption=object;
   if(clickable){
    stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(object,reinterpret_cast<void*>(0x463c8e8),0);
    stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(object,reinterpret_cast<void*>(0x463c8f8),0x20);
    caption=stock_function<void*(*)(void*)>(lv_label_create)(object);
   }
   stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(caption,reinterpret_cast<void*>(MyriadPro_Regular_16),0);stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(caption,0xffeeeeeeU,0);
   bindings_.push_back({this,object,content_,id});auto*b=&bindings_.back();
   stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(object,&event,0,b);
   it=objects_.emplace(id,std::make_pair(object,caption)).first;
  }
  auto*object=it->second.first;auto*caption=it->second.second;
  stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(object,w,h);
  stock_function<void(*)(void*,int,int,int)>(lv_obj_align)(object,1,x,y);
  stock_function<void(*)(void*,const char*)>(lv_label_set_text)(caption,text.c_str());
  if(clickable)center_button_caption(object,caption,text);
 }
 // Keep vector chevrons independent of the caption font and centered on the
 // full touch target. Their static points outlive LVGL's retained point pointer.
 void feed_button(const std::string&id,const std::string&text,int x,int y,bool retract){
  button(id,text,x,y,134,74);
  auto widgets=objects_.at(id);auto*object=widgets.first;auto*caption=widgets.second;
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(caption,reinterpret_cast<void*>(MyriadPro_Regular_16),0);
  stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(caption,122,40);
  stock_function<void(*)(void*,int,int,int)>(lv_obj_align)(caption,1,6,retract?27:7);
  auto*chevron=stock_function<int(*)(void*)>(lv_obj_get_child_cnt)(object)>1
   ?stock_function<void*(*)(void*,int)>(lv_obj_get_child)(object,1):nullptr;
  if(!chevron){
   chevron=stock_function<void*(*)(void*)>(lv_line_create)(object);
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_line_width)(chevron,3,0);
   stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_line_color)(chevron,0xffeeeeeeU,0);
  }
  struct Point{std::int16_t x,y;};
  static const Point up[]={{0,10},{16,0},{32,10}},down[]={{0,0},{16,10},{32,0}};
  stock_function<void(*)(void*,const Point*,std::uint16_t)>(lv_line_set_points)(chevron,retract?up:down,3);
  stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(chevron,51,retract?8:56);
 }
 void button(const std::string&id,const std::string&t,int x,int y,int w,int h){control(id,t,x,y,w,h,true);}
 void label(const std::string&id,const std::string&t,int x,int y,int w,int h){control(id,t,x,y,w,h,false);}
 static void event(void*e)noexcept{
  try{auto*b=static_cast<Binding*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(!b)return;auto*owner=b->owner;
   int code=stock_function<int(*)(void*)>(lv_event_get_code)(e);
   if(code==33){
    auto it=owner->objects_.find(b->id);if(it!=owner->objects_.end()&&it->second.first==b->object)owner->objects_.erase(it);
    for(auto it=owner->bindings_.begin();it!=owner->bindings_.end();++it)if(&*it==b){owner->bindings_.erase(it);break;}
   }else if(code==7&&owner->content_==b->content){

    if(owner->enabled_.count(b->id)&&!owner->enabled_.at(b->id))return;
    if(stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(b->object,1))return;
    if(b->id=="take-dock"&&!owner->take_allowed_)return;
    if(b->id=="nozzle"&&!owner->nozzle_allowed_)return;
    if(b->id=="edit-filament"){
     if(!owner->edit_allowed_)return;
     auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);auto*p=b->content;
     for(unsigned depth=0;p&&p!=screen&&depth<32;++depth){
      if(!stock_function<bool(*)(void*)>(lv_obj_is_valid)(p)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return;
      p=stock_function<void*(*)(void*)>(lv_obj_get_parent)(p);
     }
     if(p!=screen)return;
    }
    if(b->id.compare(0,5,"head:")==0){if(owner->select_head)owner->select_head(unsigned(std::stoul(b->id.substr(5))));}
    else if(owner->action)owner->action(b->id);
   }
  }catch(...){}
 }
};
}}
