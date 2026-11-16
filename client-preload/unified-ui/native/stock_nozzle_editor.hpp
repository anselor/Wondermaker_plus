// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_dialog_backdrop.hpp"
#include "../model.hpp"
#include <functional>
#include <cmath>
#include <stdexcept>
#include <string>
namespace wmp_ui { namespace native {
class StockNozzleEditor {
 void*root_=nullptr,*save_=nullptr,*save_label_=nullptr,*back_label_=nullptr,*material_=nullptr,*diameter_=nullptr,*notice_=nullptr,*armed_=nullptr;
 Json data_=Json::object(),original_=Json::object();std::string head_,session_,revision_,request_;bool terminal_=false;
public:
 std::function<Receipt(const Json&)> submit;
 bool active()const{return valid(root_);}
 void close(){auto*p=root_;root_=nullptr;if(valid(p))fn<void(*)(void*)>(lv_obj_del)(p);reset();}
 void update(const Json&data){
  data_=data;if(!active())return;
  if(!request_.empty()){
   const auto receipt=data.value("receipts",Json::object()).value(request_,Json::object());const auto state=receipt.value("state","");
   if(state=="complete"||state=="failed"||state=="refused"||state=="unknown"){
    caption(notice_,receipt.value("message","Nozzle save outcome unavailable"));request_.clear();terminal_=true;
   }
  }
  if(request_.empty()&&!terminal_){
   const bool changed=data_.value("session","")!=session_||data_.value("nozzle_revision","")!=revision_;
   caption(notice_,changed?"Settings changed. Go back and reopen.":identification_pending()?"Wait for head identification to finish before saving.":!available()?"Waiting for printer status.":original_.value("restart_required",false)?"Saved diameter differs from active diameter. Restart Klipper to apply it.":"");
  }
  // LVGL may create the popup after the READY callback returns.
  for(auto*p:{material_,diameter_})if(valid(p)&&fn<bool(*)(void*)>(lv_dropdown_is_open)(p))list_style(p);
  enable_save();
 }
 bool show(void*parent,unsigned head)try{
  close();head_="h"+std::to_string(head);
  if(!valid(parent)||!viewable()||!data_.value("nozzle_settings",Json::object()).contains(head_))return false;
  original_=data_["nozzle_settings"][head_];session_=data_.value("session","");revision_=data_.value("nozzle_revision","");
  root_=fn<void*(*)(void*)>(lv_obj_create)(parent);if(!root_)return false;
  bind(root_,33);stock_dialog_backdrop(root_);
  fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(root_,0xff3c3e42U,0);style(root_,lv_obj_set_style_bg_opa,255);
  const int w=fn<int(*)(void*)>(lv_obj_get_content_width)(parent),h=fn<int(*)(void*)>(lv_obj_get_content_height)(parent);place(root_,0,0,w,h);
  label(root_,"Head "+std::to_string(head+1)+" - Nozzle",20,10,w-260,28);
  auto*back=header("BACK",w-244,false);back_label_=fn<void*(*)(void*,int)>(lv_obj_get_child)(back,0);save_=header("SAVE",w-124,true);
  auto*rule=fn<void*(*)(void*)>(lv_obj_create)(root_);if(!rule)throw std::runtime_error("Nozzle separator allocation failed");stock_dialog_backdrop(rule);place(rule,20,44,w-40,1);style(rule,lv_obj_set_style_bg_opa,255);fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(rule,0xff55575aU,0);
  label(root_,"Material",20,80,130,28);label(root_,"Diameter",20,148,130,28);
  material_=dropdown("Select material\nHardened steel\nStainless steel",160,66,w-180);
  const auto mat=original_.value("material","");fn<void(*)(void*,unsigned)>(lv_dropdown_set_selected)(material_,mat=="Hardened steel"?1:mat=="Stainless steel"?2:0);
  diameter_=dropdown("Select diameter\n0.2 mm\n0.4 mm\n0.6 mm\n0.8 mm",160,134,w-180);
  const double d=original_.value("diameter",0.0);unsigned selected=0;for(unsigned i=1;i<=4;++i)if(std::abs(d-double(i)/5.0)<0.000001)selected=i;
  fn<void(*)(void*,unsigned)>(lv_dropdown_set_selected)(diameter_,selected);
  notice_=label(root_,original_.value("restart_required",false)?"Saved diameter differs from active diameter. Restart Klipper to apply it.":"",20,214,w-40,80);
  enable_save();return true;
 }catch(...){close();return false;}
private:
 template<class F>static F fn(std::uintptr_t p){return dialog_function<F>(p);}
 static bool valid(void*p){return p&&fn<bool(*)(void*)>(lv_obj_is_valid)(p);}
 static void style(void*p,std::uintptr_t f,int value){fn<void(*)(void*,int,unsigned)>(f)(p,value,0);}
 static void place(void*p,int x,int y,int w,int h){fn<void(*)(void*,int,int)>(lv_obj_set_pos)(p,x,y);fn<void(*)(void*,int,int)>(lv_obj_set_size)(p,w,h);}
 static void caption(void*p,const std::string&s){fn<void(*)(void*,const char*)>(lv_label_set_text)(p,s.c_str());}
 static void*label(void*p,const std::string&s,int x,int y,int w,int h){auto*l=fn<void*(*)(void*)>(lv_label_create)(p);if(!l)throw std::runtime_error("Nozzle label allocation failed");place(l,x,y,w,h);fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(l,reinterpret_cast<void*>(0x26297a0),0);fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(l,0xffeeeeeeU,0);caption(l,s);return l;}
 void bind(void*p,int code){if(!fn<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(p,&event,code,this))throw std::runtime_error("Nozzle event binding failed");}
 void*header(const std::string&s,int x,bool save){auto*p=fn<void*(*)(void*)>(lv_obj_create)(root_);if(!p)throw std::runtime_error("Nozzle control allocation failed");stock_dialog_backdrop(p);place(p,x,8,104,34);auto*l=label(p,s,4,2,96,26);fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(l,reinterpret_cast<void*>(0xf84928),0);style(l,lv_obj_set_style_text_align,2);if(save)save_label_=l;bind(p,7);return p;}
 void*dropdown(const char*options,int x,int y,int width){auto*p=fn<void*(*)(void*)>(lv_dropdown_create)(root_);if(!p)throw std::runtime_error("Nozzle selector allocation failed");place(p,x,y,width,48);fn<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(p,reinterpret_cast<void*>(0x463c8e8),0);fn<void(*)(void*,const char*)>(lv_dropdown_set_options)(p,options);fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(0x2a4b0b0),0);fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(lv_font_montserrat_14),0x20000);style(p,lv_obj_set_style_pad_top,10);fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(p,0xffeeeeeeU,0);bind(p,31);bind(p,28);return p;}
 static void list_style(void*p){auto*l=fn<void*(*)(void*)>(lv_dropdown_get_list)(p);if(!l)return;fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(l,reinterpret_cast<void*>(0x26297a0),0);for(unsigned part:{0U,0x40000U,0x40001U,0x40020U,0x40021U}){fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(l,0xffeeeeeeU,part);fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(l,part?0xffbf4900U:0xff3c3e42U,part);fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(l,255,part);}}
 bool viewable()const{return data_.value("fresh",false)&&data_.value("owner","")=="standalone"&&data_.value("capabilities",Json::object()).value("save_nozzle",false);}
 bool identification_pending()const{const auto state=data_.value("identification",Json::object()).value("state","");return state=="pending"||state=="running";}
 bool available()const{return viewable()&&!identification_pending();}
 Json draft()const{unsigned m=fn<unsigned(*)(void*)>(lv_dropdown_get_selected)(material_),d=fn<unsigned(*)(void*)>(lv_dropdown_get_selected)(diameter_);if(m<1||m>2||d<1||d>4)return Json();return {{"head",head_},{"material",m==1?"Hardened steel":"Stainless steel"},{"diameter",double(d)/5.0},{"expected",revision_}};}
 bool can_save()const{if(!active()||!material_||!diameter_||!available()||terminal_||!request_.empty()||data_.value("session","")!=session_||data_.value("nozzle_revision","")!=revision_)return false;const auto d=draft();return d.is_object()&&(d["material"]!=original_.value("material","")||std::abs(d["diameter"].get<double>()-original_.value("diameter",0.0))>0.000001);}
 void enable_save(){if(!valid(save_))return;if(valid(back_label_))caption(back_label_,terminal_?"DONE":"BACK");bool enabled=can_save();fn<void(*)(void*,unsigned)>(enabled?lv_obj_clear_state:lv_obj_add_state)(save_,128);fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(save_label_,enabled?0xffeeeeeeU:0xff888888U,0);for(auto*p:{material_,diameter_})if(valid(p))fn<void(*)(void*,unsigned)>(request_.empty()&&!terminal_?lv_obj_clear_state:lv_obj_add_state)(p,128);}
 void reset(){root_=save_=save_label_=back_label_=material_=diameter_=notice_=armed_=nullptr;request_.clear();terminal_=false;}
 static void event(void*e)noexcept{try{
  auto*o=static_cast<StockNozzleEditor*>(fn<void*(*)(void*)>(lv_event_get_user_data)(e));if(!o)return;auto*p=fn<void*(*)(void*)>(lv_event_get_target)(e);const int code=fn<int(*)(void*)>(lv_event_get_code)(e);
  if(code==33){if(p==o->root_)o->reset();return;}if(!o->active())return;
  auto*screen=fn<void*(*)(void*)>(lv_disp_get_scr_act)(fn<void*(*)()>(lv_disp_get_default)());bool visible=false;for(auto*n=o->root_;n;n=fn<void*(*)(void*)>(lv_obj_get_parent)(n)){if(!valid(n)||fn<bool(*)(void*,unsigned)>(lv_obj_has_flag)(n,1))return;if(n==screen){visible=true;break;}}if(!visible)return;
  if(code==31){if(!o->request_.empty()||o->terminal_)return;o->armed_=p;list_style(p);return;}
  if(code==28){if(p!=o->armed_)return;o->armed_=nullptr;o->enable_save();return;}
  if(code!=7)return;
  if(p!=o->save_){o->close();return;}
  if(!o->can_save()||!o->submit)return;
  auto receipt=o->submit(o->draft());
  caption(o->notice_,receipt.message);if(!receipt.id.empty())o->request_=receipt.id;else o->terminal_=true;o->enable_save();
 }catch(...){} }
};
}}
