// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "button_caption.hpp"
#include "profile1113.hpp"
#include "../model.hpp"
#include <list>
#include <map>
namespace wmp_ui { namespace native {
#ifdef WMP_NATIVE_TEST
void* test_resolve(std::uintptr_t);
#endif
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
  }
  const int right=width-146;
  const int middle=right-220;
  label("distance","Distance (mm)",208,80,middle,24);
  for(int value:{1,5,10,25,50}){
   int col=value==1?0:value==5?1:value==10?2:value==25?3:4;
   const auto id="step:"+std::to_string(value);
   button(id,std::to_string(value),208+col*(middle/5),104,middle/5-6,36);
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
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_radius)(circle,32,0);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_border_width)(circle,2,0);
  fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_border_color)(circle,0xff999999U,0);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(circle,0,0);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_text_align)(circle,1,0);
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
  fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(edit.second,reinterpret_cast<void*>(lv_font_montserrat_14),0);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_text_align)(edit.second,2,0);
  for(auto property:{lv_obj_set_style_bg_opa,lv_obj_set_style_border_width,lv_obj_set_style_outline_width})
   fn<void(*)(void*,int,unsigned)>(property)(edit.first,0,0);
  edit_allowed_=data.value("fresh",false)&&!ace_managed&&selected.is_object()&&(data.value("owner","")=="standalone"||(!pending&&filament_identity_editable(data,"h"+std::to_string(head))));
  visible("edit-filament",edit_allowed_);enabled("edit-filament",edit_allowed_);
  button("retract",pending&&this_head&&busy_action=="retract"?"Retracting...":"\xef\x81\xb7 Retract\n"+std::to_string(step)+" mm",right,80,134,74);
  button("extrude",pending&&this_head&&busy_action=="extrude"?"Extruding...":"\xef\x81\xb8 Extrude\n"+std::to_string(step)+" mm",right,height-130,134,74);
  for(const auto&id:{"retract","extrude"})fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(objects_.at(id).second,reinterpret_cast<void*>(lv_font_montserrat_14),0);
  for(const auto&id:{"retract","extrude","target","off"})enabled(id,!pending&&data.value("fresh",false));
  if(data.value("owner","")=="standalone")enabled("off",true);
  button("check-filament","Check filament",208,height-44,120,38);
  const bool reviewable=busy.value("reviewable",pending&&(busy_action=="load"||busy_action=="unload"||busy_action=="confirm_filament"));
  visible("check-filament",!ace_managed&&is_empty&&loaded.value("sensor_present",false)&&data.value("capabilities",Json::object()).value("confirm_filament",false));
  enabled("check-filament",!pending&&data.value("fresh",false));
  button("view-operation",busy.value("interrupted",false)?"Recover":"Result",336,height-44,76,38);visible("view-operation",reviewable);
  const auto mounting=mounting_for(data,head);
  button("take-dock",mounting=="Mounted"?"Dock":mounting=="Not mounted"||mounting=="No head mounted"?"Take":"Mount state unknown",12,height-44,180,38);
  const auto tool_state=data.value("toolhead_operation",Json::object()).value("state","");
  enabled("take-dock",take_allowed_=!pending&&data.value("fresh",false)&&data.value("owner","")=="standalone"&&data.value("capabilities",Json::object()).value("toolhead_action",false)&&mounting!="Attachment unknown"&&tool_state!="running"&&(data.value("job",Json::object()).value("state","")=="idle"||data.value("job",Json::object()).value("state","")=="complete"||paused_toolhead_action_available(data,"h"+std::to_string(head),mounting=="Mounted"?"dock":"take")));
  const auto nozzle=selected.is_object()?selected.value("nozzle",Json::object()):Json::object();
  button("nozzle",nozzle.value("diameter","Unknown")+" / "+nozzle.value("material","Unknown")+(nozzle.value("restart_required",false)?"\nRestart required":""),208,height-104,middle,48);
  for(auto property:{lv_obj_set_style_bg_opa,lv_obj_set_style_border_width,lv_obj_set_style_outline_width})fn<void(*)(void*,int,unsigned)>(property)(objects_.at("nozzle").first,0,0);
  enabled("nozzle",nozzle_allowed_=(data.value("owner","")=="standalone"||!pending)&&data.value("fresh",false)&&data.value("capabilities",Json::object()).value("save_nozzle",false));
  button("filaments","Filaments / slots",width-188,height-44,176,38);
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
   fn<void(*)(void*,const void*,unsigned)>(lv_obj_remove_style)(object,reinterpret_cast<void*>(style),0);
  fn<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(object,reinterpret_cast<void*>(selected?0x463c918:0x463c908),0);
 }
 void visible(const std::string&id,bool show){auto it=objects_.find(id);if(it!=objects_.end())fn<void(*)(void*,unsigned)>(show?lv_obj_clear_flag:lv_obj_add_flag)(it->second.first,1);}
 void enabled(const std::string&id,bool enable){enabled_[id]=enable;auto it=objects_.find(id);if(it!=objects_.end())fn<void(*)(void*,unsigned)>(enable?lv_obj_clear_state:lv_obj_add_state)(it->second.first,128);}
 template<class F>static F fn(std::uintptr_t address){
#ifdef WMP_NATIVE_TEST
  return reinterpret_cast<F>(test_resolve(address));
#else
  return reinterpret_cast<F>(address);
#endif
 }
 void control(const std::string&id,const std::string&text,int x,int y,int w,int h,bool clickable){
  auto it=objects_.find(id);
  if(it==objects_.end()){
   void*object=clickable?fn<void*(*)(void*)>(lv_btn_create)(content_):fn<void*(*)(void*)>(lv_label_create)(content_);
   if(!object)return;
   void*caption=object;
   if(clickable){
    fn<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(object,reinterpret_cast<void*>(0x463c8e8),0);
    fn<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(object,reinterpret_cast<void*>(0x463c8f8),0x20);
    caption=fn<void*(*)(void*)>(lv_label_create)(object);
   }
   fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(caption,reinterpret_cast<void*>(0x26297a0),0);fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(caption,0xffeeeeeeU,0);
   bindings_.push_back({this,object,content_,id});auto*b=&bindings_.back();
   fn<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(object,&event,0,b);
   it=objects_.emplace(id,std::make_pair(object,caption)).first;
  }
  auto*object=it->second.first;auto*caption=it->second.second;
  fn<void(*)(void*,int,int)>(lv_obj_set_size)(object,w,h);
  fn<void(*)(void*,int,int,int)>(lv_obj_align)(object,1,x,y);
  fn<void(*)(void*,const char*)>(lv_label_set_text)(caption,text.c_str());
  if(clickable)center_button_caption(object,caption,text);
 }
 void button(const std::string&id,const std::string&t,int x,int y,int w,int h){control(id,t,x,y,w,h,true);}
 void label(const std::string&id,const std::string&t,int x,int y,int w,int h){control(id,t,x,y,w,h,false);}
 static void event(void*e)noexcept{
  try{auto*b=static_cast<Binding*>(fn<void*(*)(void*)>(lv_event_get_user_data)(e));if(!b)return;auto*owner=b->owner;
   int code=fn<int(*)(void*)>(lv_event_get_code)(e);
   if(code==33){
    auto it=owner->objects_.find(b->id);if(it!=owner->objects_.end()&&it->second.first==b->object)owner->objects_.erase(it);
    for(auto it=owner->bindings_.begin();it!=owner->bindings_.end();++it)if(&*it==b){owner->bindings_.erase(it);break;}
   }else if(code==7&&owner->content_==b->content){

    if(owner->enabled_.count(b->id)&&!owner->enabled_.at(b->id))return;
    if(fn<bool(*)(void*,unsigned)>(lv_obj_has_flag)(b->object,1))return;
    if(b->id=="take-dock"&&!owner->take_allowed_)return;
    if(b->id=="nozzle"&&!owner->nozzle_allowed_)return;
    if(b->id=="edit-filament"){
     if(!owner->edit_allowed_)return;
     auto*screen=fn<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);auto*p=b->content;
     for(unsigned depth=0;p&&p!=screen&&depth<32;++depth){
      if(!fn<bool(*)(void*)>(lv_obj_is_valid)(p)||fn<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return;
      p=fn<void*(*)(void*)>(lv_obj_get_parent)(p);
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
