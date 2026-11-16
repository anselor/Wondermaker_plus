// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "button_caption.hpp"
#include "stock_api.hpp"
#include "../model.hpp"
#include "stock_dialog_backdrop.hpp"
#include <algorithm>
#include <functional>
#include <string>
#include <vector>
#include <stdexcept>
namespace wmp_ui { namespace native {
// USB profile review in stock content; only Save persists the reviewed records.
class StockProfileImport {
 void*root_=nullptr;void*close_=nullptr;void*panel_=nullptr;
 struct Choice{void*object;int action;std::string value;};std::vector<Choice>choices_;
 int width_=0,height_=0;Json data_,result_;std::string signature_,pending_,pending_action_;
public:
 std::function<void()>dismissed;
 std::function<Receipt(const std::string&,const std::string&)>requested;
 void update(const Json&data){
  data_=data;const auto result=data.value("profile_import",Json::object());
  if(!pending_.empty()){
   const auto receipt=data.value("receipts",Json::object()).value(pending_,Json::object());
   if(receipt.value("state","")=="refused"||receipt.value("state","")=="failed"||receipt.value("state","")=="unknown"){
    result_={{"state","error"},{"message",receipt.value("message","Import failed")}};pending_.clear();
   }else if(result.value("id","")==pending_&&result.value("state","")!="busy"){result_=result;pending_.clear();}
  }
  if(active()){auto signature=result_.dump()+pending_+(ready()?"ready":"unavailable");if(signature!=signature_){signature_=signature;render();}}
 }
 bool ready()const{return data_.is_object()&&data_.value("fresh",false)&&data_.value("owner","")=="standalone"&&data_.value("capabilities",Json::object()).value("profile_import",false);}
 void send(const std::string&action,const std::string&value=""){
  if(!pending_.empty()||!ready()||!requested)return;
  const auto receipt=requested(action,value);
  if(receipt.id.empty())result_={{"state","error"},{"message",receipt.message}};
  else {pending_=receipt.id;pending_action_=action;result_={{"state","busy"}};}
  signature_.clear();if(active())render();
 }

 bool active()const{return stock_object_valid(root_);}
 void close(){auto*root=root_;root_=nullptr;close_=nullptr;panel_=nullptr;choices_.clear();if(stock_object_valid(root))stock_function<void(*)(void*)>(lv_obj_del)(root);}
 bool show(void*parent)try{
  close();if(!stock_object_valid(parent))return false;
  root_=stock_function<void*(*)(void*)>(lv_obj_create)(parent);if(!root_)return false;
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(root_,&deleted,33,this)){close();return false;}
  const int w=stock_function<int(*)(void*)>(lv_obj_get_content_width)(parent),h=stock_function<int(*)(void*)>(lv_obj_get_content_height)(parent);
  if(w<400||h<280){close();return false;}
  style(root_,0x463c8d8);stock_dialog_backdrop(root_);stock_object_place(root_,0,0,w,h);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(root_,0xff3c3e42U,0);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(root_,255,0);
  panel_=stock_function<void*(*)(void*)>(lv_obj_create)(root_);if(!panel_){close();return false;}
  width_=w-16;height_=h-16;
  style(panel_,0x463c8f8);stock_dialog_backdrop(panel_);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(panel_,0xff3c3e42U,0);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(panel_,255,0);
  stock_object_place(panel_,8,8,width_,height_);pending_.clear();result_=Json::object();render();send("scan");
  return true;
 }catch(...){close();return false;}
private:
 static void style(void*p,std::uintptr_t address){stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(p,reinterpret_cast<void*>(address),0);}
 static void caption(void*p,const std::string&s){stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(MyriadPro_Regular_16),0);stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(p,0xffeeeeeeU,0);stock_function<void(*)(void*,const char*)>(lv_label_set_text)(p,s.c_str());}
 void label(void*parent,const std::string&text,int x,int y,int w,int h){
  auto*node=stock_function<void*(*)(void*)>(lv_label_create)(parent);if(!node)throw std::runtime_error("Import label allocation failed");caption(node,text);stock_object_place(node,x,y,w,h);
 }
 void button(void*parent,const std::string&text,int action,int x,int y,int w,int h,bool enabled=true,const std::string&value="",bool header=false){
  auto*node=stock_function<void*(*)(void*)>(header?lv_obj_create:lv_btn_create)(parent);if(!node)throw std::runtime_error("Import button allocation failed");
  if(header){stock_dialog_backdrop(node);stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(node,0,0);stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_border_width)(node,0,0);}
  else {style(node,0x463c8e8);}
  stock_object_place(node,x,y,w,h);label(node,text,header?4:8,header?2:8,w-(header?8:16),h-(header?8:12));
  center_button_caption(node,stock_function<void*(*)(void*,int)>(lv_obj_get_child)(node,0),text);
  if(header){
   auto*caption=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(node,0);
   stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(caption,reinterpret_cast<void*>(MyriadPro_Bold_20),0);
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_text_align)(caption,2,0);
   if(!enabled)stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(caption,0xff888888U,0);
  }
  if(!enabled)stock_function<void(*)(void*,unsigned)>(lv_obj_add_state)(node,128);
  choices_.push_back({node,enabled?action:-1,value});
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(node,&pressed,7,this))throw std::runtime_error("Import event allocation failed");
 }
 void render(){
  choices_.clear();stock_function<void(*)(void*)>(lv_obj_clean)(panel_);
  const auto state=result_.value("state","");const bool busy=!pending_.empty();
  label(panel_,"Import from USB",12,4,width_-260,28);
  button(panel_,state=="saved"?"DONE":"BACK",8,width_-240,0,116,32,true,"",true);close_=choices_.back().object;
  if(state=="review")button(panel_,"SAVE",3,width_-124,0,112,32,ready()&&!busy&&!result_.value("profiles",Json::array()).empty(),result_.value("token",""),true);
  else button(panel_,"REFRESH",1,width_-124,0,112,32,ready()&&!busy,"",true);
  auto*rule=stock_function<void*(*)(void*)>(lv_obj_create)(panel_);if(!rule)throw std::runtime_error("Import separator allocation failed");
  stock_dialog_backdrop(rule);stock_object_place(rule,12,35,width_-24,1);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(rule,0xff55575aU,0);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(rule,255,0);
  auto*body=stock_function<void*(*)(void*)>(lv_obj_create)(panel_);if(!body)throw std::runtime_error("Import body allocation failed");
  stock_dialog_backdrop(body);stock_object_place(body,8,40,width_-16,height_-48);stock_function<void(*)(void*,int)>(lv_obj_set_scroll_dir)(body,12);
  int y=4;
  if(!ready()){label(body,"USB profile import requires standalone WM+ support.",8,y,width_-48,52);return;}
  if(busy){label(body,pending_action_=="save"?"Saving profiles...":"Reading USB profiles...",8,y,width_-48,28);return;}
  if(state=="files"){
   for(const auto&file:result_.value("files",Json::array())){button(body,file.value("name",""),2,8,y,width_-48,44,true,file.value("id",""));y+=50;}
   if(y==4)label(body,result_.value("message","No profile files found"),8,y,width_-48,48);
  }else if(state=="review"){
   label(body,result_.value("name",""),8,y,width_-48,44);y+=48;
   for(const auto&profile:result_.value("profiles",Json::array())){
    const auto identity=profile.value("identity",Json::object());
    label(body,profile.value("name","")+"\n"+identity_display_text(identity,"brand","")+" / "+identity.value("material","")+" / "+std::to_string(int(identity.value("nozzle_temp",0.0)))+" C",8,y,width_-48,66);y+=70;
   }
   for(const auto*key:{"warnings","errors"})for(const auto&message:result_.value(key,Json::array())){label(body,message.get<std::string>(),8,y,width_-48,70);y+=74;}
  }else if(state=="saved")label(body,"Saved "+std::to_string(result_.value("count",0))+" profiles",8,y,width_-48,40);
  else label(body,result_.value("message","Choose a USB profile file"),8,y,width_-48,80);
 }
 static void deleted(void*e)noexcept{try{auto*o=static_cast<StockProfileImport*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(o&&stock_function<void*(*)(void*)>(lv_event_get_target)(e)==o->root_){o->root_=nullptr;o->close_=nullptr;o->panel_=nullptr;o->choices_.clear();}}catch(...){} }
 static void pressed(void*e)noexcept{try{
  auto*o=static_cast<StockProfileImport*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(!o||!o->active())return;
  auto*target=stock_function<void*(*)(void*)>(lv_event_get_target)(e);int action=-1;std::string value;
  for(const auto&choice:o->choices_)if(choice.object==target){action=choice.action;value=choice.value;}
  if(action<0)return;
  auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(stock_function<void*(*)()>(lv_disp_get_default)());
  auto*p=o->root_;bool visible=false;for(unsigned i=0;p&&i<32;++i){if(!stock_object_valid(p)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return;if(p==screen){visible=true;break;}p=stock_function<void*(*)(void*)>(lv_obj_get_parent)(p);}
  if(!visible)return;
  if(action==8){auto callback=o->dismissed;o->close();if(callback)callback();return;}
  o->send(action==1?"scan":action==2?"review":"save",value);

 }catch(...){} }
};
}}
