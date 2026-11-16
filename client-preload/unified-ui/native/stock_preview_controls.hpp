// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include "stock_preview_widgets.hpp"
#include <functional>
#include <list>
namespace wmp_ui { namespace native {
// Rebind the original preview controls; their geometry, images, fonts and
// parentage remain stock. Runtime supplies admission readiness separately from
// edit readiness. The stock Start callback must never run beside WM+ submission.
class StockPreviewControls {
 struct Page;
 struct Control {Page*page;void*object;unsigned action;};
 struct Page {StockPreviewControls*owner;StockPreviewWidgets widgets;std::list<Control>controls;std::function<void(unsigned)>dispatch;bool editable=false,start_ready=false,start_pending=false,copy_only=false;};
 std::list<Page>pages_;Page*current_=nullptr;
public:
 bool attach(StockPreviewWidgets widgets,std::function<void(unsigned)>dispatch){
  retire();
  if(!StockPreviewInventory::resolve(widgets)){
   // Only the content captured beneath this constructor's page is ours to
   // close. An invalid root cannot be adopted; Runtime must not fall back to
   // vendor Start when no trusted subtree is available.
   if(stock_object_valid(widgets.page)&&stock_object_valid(widgets.content)&&stock_function<void*(*)(void*)>(lv_obj_get_parent)(widgets.content)==widgets.page)return fail(widgets.content);
   return false;
  }
  std::vector<void*>nodes{widgets.content};
  for(std::size_t i=0;i<nodes.size();++i){
   const auto count=stock_function<unsigned(*)(void*)>(lv_obj_get_child_cnt)(nodes[i]);
   if(count>256||nodes.size()+count>256)return fail(widgets.content);
   for(unsigned j=0;j<count;++j)nodes.push_back(stock_function<void*(*)(void*,int)>(lv_obj_get_child)(nodes[i],int(j)));
  }
  pages_.emplace_back();auto*p=&pages_.back();p->owner=this;p->widgets=widgets;p->dispatch=std::move(dispatch);
  // Collect before mutation. The option with action zero is explicit because
  // the vendor accessor returns null both for zero and for no matching handler.
  for(auto*object:nodes){
   const auto id=reinterpret_cast<std::uintptr_t>(stock_function<void*(*)(void*,void(*)(void*))>(lv_obj_get_event_user_data)(object,reinterpret_cast<void(*)(void*)>(preview_event)));
   if(id>12){pages_.pop_back();return fail(widgets.content);}
   if(id||object==widgets.options[0])p->controls.push_back({p,object,unsigned(id)});
  }
  bool options_ok=true;
  for(unsigned i=0;i<3;++i){if(!widgets.options[i])continue;bool found=false;for(const auto&c:p->controls)if(c.object==widgets.options[i]&&c.action==i)found=true;options_ok=options_ok&&found;}
  if(!options_ok){pages_.pop_back();return fail(widgets.content);}
  bool removed_refresh=detach(widgets.content,preview_refresh_event);
  bool removed_controls=true;
  for(const auto&c:p->controls)removed_controls=detach(c.object,preview_event)&&removed_controls;
  if(!removed_refresh||!removed_controls){pages_.pop_back();return fail(widgets.content);}
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(widgets.content,&deleted,33,p)){
   pages_.pop_back();return fail(widgets.content);
  }
  current_=p;
  for(auto&c:p->controls)if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(c.object,&pressed,7,&c))return fail(widgets.content);
  readiness(false,false);return true;
 }
 void readiness(bool editable,bool start_ready,bool copy_only=false){
  if(!current_)return;
  current_->copy_only=copy_only;current_->editable=editable;current_->start_ready=editable&&start_ready&&!current_->start_pending;
  for(const auto&c:current_->controls){
   const bool enabled=c.action==3||(!copy_only&&c.action==1)||(c.action==4?current_->start_ready:!copy_only&&editable);
   stock_function<void(*)(void*,unsigned)>(enabled?lv_obj_clear_state:lv_obj_add_state)(c.object,128);
   // Stock header captions have their own color and do not inherit disabled
   // state from the parent action. Keep their appearance in sync with admission.
   if((c.action==3||c.action==4)&&stock_function<unsigned(*)(void*)>(lv_obj_get_child_cnt)(c.object)==1){
    auto*caption=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(c.object,0);
    stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(caption,enabled?0xffeeeeeeU:0xff888888U,0);
   }
  }
 }
 // Only a reconciled terminal admission outcome may clear the click latch;
 // ordinary metadata/status refreshes cannot rearm a submitted Start.
 void admission_settled(){if(current_)current_->start_pending=false;}
 void retire(){if(current_)readiness(false,false);current_=nullptr;}
 bool active()const{return current_!=nullptr;}
private:
 static bool fail(void*content){if(stock_object_valid(content))stock_function<void(*)(void*)>(lv_obj_del)(content);return false;}
 static bool detach(void*object,std::uintptr_t handler){bool removed=false;while(stock_function<bool(*)(void*,void(*)(void*))>(lv_obj_remove_event_cb)(object,reinterpret_cast<void(*)(void*)>(handler)))removed=true;return removed;}
 static bool visible(void*object,void*content){
  bool contained=false;
  auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(stock_function<void*(*)()>(lv_disp_get_default)());
  for(unsigned depth=0;object&&depth<32;++depth){
   if(!stock_object_valid(object)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(object,1))return false;
   if(object==content)contained=true;
   if(object==screen)return contained;
   object=stock_function<void*(*)(void*)>(lv_obj_get_parent)(object);
  }
  return false;
 }
 static void pressed(void*event)noexcept{try{
  auto*c=static_cast<Control*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(event));if(!c)return;
  auto*p=c->page;
  if(p->owner->current_!=p||stock_function<void*(*)(void*)>(lv_event_get_target)(event)!=c->object||!visible(c->object,p->widgets.content))return;
  if(p->copy_only&&c->action!=3&&c->action!=4)return;
  if(c->action!=1&&c->action!=3&&(!p->editable||(c->action==4&&!p->start_ready)))return;
  auto dispatch=p->dispatch;const auto action=c->action;
  if(action==4){p->start_pending=true;p->owner->readiness(false,false);} // one request until readback
  if(dispatch)dispatch(action);
 }catch(...){} }
 static void deleted(void*event)noexcept{try{
  auto*p=static_cast<Page*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(event));if(!p)return;
  auto*o=p->owner;if(o->current_==p)o->current_=nullptr;
  for(auto it=o->pages_.begin();it!=o->pages_.end();++it)if(&*it==p){o->pages_.erase(it);break;}
 }catch(...){} }
};
}}
