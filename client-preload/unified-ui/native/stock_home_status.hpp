// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_progress_panel.hpp"
#include "stock_header_action.hpp"
#include <functional>
namespace wmp_ui { namespace native {
// Standalone Home presentation; transport and operation authority stay in Runtime.
class StockHomeStatus {
 void*root_=nullptr,*action_=nullptr;StockProgressPanel progress_;bool done_=false,enabled_=false;int width_=0;std::string rendered_title_,rendered_message_;
 static void deleted(void*e)noexcept{try{
  auto*self=static_cast<StockHomeStatus*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));
  if(self&&stock_function<void*(*)(void*)>(lv_event_get_target)(e)==self->root_)self->root_=self->action_=nullptr;
 }catch(...){} }
 static void pressed(void*e)noexcept{try{
  auto*self=static_cast<StockHomeStatus*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));
  if(!self||!self->visible()||!self->enabled_||stock_function<int(*)(void*)>(lv_event_get_code)(e)!=7
     ||stock_function<void*(*)(void*)>(lv_event_get_target)(e)!=self->action_)return;
  auto*p=self->root_;auto*layer=stock_function<void*(*)(void*)>(lv_disp_get_layer_sys)(nullptr);bool visible=false;
  for(unsigned depth=0;p&&depth<20;++depth){if(!stock_object_valid(p)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return;if(p==layer){visible=true;break;}p=stock_function<void*(*)(void*)>(lv_obj_get_parent)(p);}
  if(!visible||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_state)(self->action_,128))return;
  auto callback=self->done_?self->done:self->cancel;if(callback)callback();
 }catch(...){} }
public:
 std::function<void()>cancel,done;
 bool visible()const{return stock_object_valid(root_);}
 void close(){rendered_title_.clear();rendered_message_.clear();done_=enabled_=false;progress_.close();auto*p=root_;root_=action_=nullptr;if(stock_object_valid(p))stock_function<void(*)(void*)>(lv_obj_del)(p);}
 bool show(void*parent){
  close();if(!stock_object_valid(parent))return false;
  const int w=stock_function<int(*)(void*)>(lv_obj_get_content_width)(parent),h=stock_function<int(*)(void*)>(lv_obj_get_content_height)(parent);
  if(w<360||h<200)return false;
  root_=stock_function<void*(*)(void*)>(lv_obj_create)(parent);if(!root_)return false;
  stock_dialog_backdrop(root_);stock_object_place(root_,0,0,w,h);width_=w;
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(root_,0xff3c3f43U,0);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(root_,255,0);
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(root_,&deleted,33,this)
     ||!progress_.attach(root_,0,0,w,h)){close();return false;}
  action_=stock_header_action(root_,"CANCEL",w-132,0,124);
  if(!action_||!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(action_,&pressed,7,this)){close();return false;}
  return true;
 }
 void update(const std::string&title,const std::string&message,bool terminal,bool cancel_available){
  if(!visible())return;
  if(rendered_title_==title&&rendered_message_==message&&done_==terminal&&enabled_==(terminal||cancel_available))return;
  rendered_title_=title;rendered_message_=message;done_=terminal;enabled_=terminal||cancel_available;
  stock_header_action_caption(action_,terminal?"DONE":"CANCEL",enabled_);
  progress_.update({{"title",title},{"title_width",width_-148},{"instruction",message},{"steps",Json::array()}});
 }
};
// Frozen XYZ screen click ids. Invalid/stale/hidden controls never dispatch.
inline int stock_home_action(void*event){
 if(!event||stock_function<int(*)(void*)>(lv_event_get_code)(event)!=7)return -1;
 const auto action=reinterpret_cast<std::uintptr_t>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(event));
 if(action>15)return -1;
 auto*p=stock_function<void*(*)(void*)>(lv_event_get_target)(event);
 auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);
 for(unsigned depth=0;p&&depth<20;++depth){
  if(!stock_object_valid(p)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_state)(p,128))return -1;
  if(p==screen)return int(action);
  p=stock_function<void*(*)(void*)>(lv_obj_get_parent)(p);
 }
 return -1;
}
}}
