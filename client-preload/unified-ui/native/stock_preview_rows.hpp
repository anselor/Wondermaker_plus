// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include "button_caption.hpp"
#include "stock_preview_widgets.hpp"
#include "stock_palette.hpp"
#include "../model.hpp"
#include <functional>
#include <list>
namespace wmp_ui { namespace native {
// Content extension inside the vendor's existing mapping panel. Reuse its
// first four source/destination colour widgets; only extra rows and missing
// material/destination captions are created. Surrounding preview stays stock.
class StockPreviewRows {
 struct Binding{StockPreviewRows*owner;void*object;std::string row;unsigned generation;};
 struct Row{void*left=nullptr,*right=nullptr,*text=nullptr,*button=nullptr,*caption=nullptr;int slot=-1;};
 std::map<std::string,Row>rows_;
 std::list<Binding>bindings_;std::vector<void*>owned_;
 StockPreviewWidgets widgets_;void*panel_=nullptr;std::string white_,signature_;unsigned generation_=0;bool fresh_=false;
public:
 std::function<void(const std::string&)>select;
 bool mount(const StockPreviewWidgets&w,const std::string&white){
  if(!stock_object_valid(w.content)||!stock_object_valid(w.sources[0])||white.empty())return false;
  auto*panel=parent(w.sources[0]);if(!stock_object_valid(panel)||panel==w.content||parent(panel)!=w.content)return false;
  std::set<void*>seen;
  for(unsigned i=0;i<4;++i)for(auto*p:{w.sources[i],w.destinations[i]})if(!stock_object_valid(p)||parent(p)!=panel||!seen.insert(p).second)return false;
  if(panel_==panel)return true;
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(panel,&panel_deleted,33,this))return false;
  clear();widgets_=w;panel_=panel;white_=white;
  const std::string large="screen_filament_edit_color_re_0.bin";
  if(white_.size()>=large.size()&&white_.compare(white_.size()-large.size(),large.size(),large)==0)
   white_.replace(white_.size()-large.size(),large.size(),"screen_preview_color_0.bin");
  signature_.clear();++generation_;
  stock_function<void(*)(void*,int)>(lv_obj_set_scroll_dir)(panel_,12);
  stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(panel_,16);
  return true;
 }
 void update(const Json&state,int width){
  if(!stock_object_valid(panel_)||width<320)return;
  const auto rows=state.value("rows",Json::array());
  fresh_=state.value("fresh",false)&&state.value("editable",false);if(!rows.is_array()||rows.size()>32){fresh_=false;readiness();return;}
  // Admission changes must not delete the widget under an active touch.
  // Keep callbacks bound to the same row; they also recheck fresh_ on release.
  auto key=rows.dump()+std::to_string(width);if(key==signature_){readiness();return;}
  const auto scroll=stock_function<int(*)(void*)>(lv_obj_get_scroll_y)(panel_);
  std::set<std::string>ids;
  for(const auto&row:rows){const auto id=row.value("id","");if(id.empty()||!ids.insert(id).second){fresh_=false;readiness();return;}}
  for(auto it=rows_.begin();it!=rows_.end();){if(!ids.count(it->first)){retire(it->second);it=rows_.erase(it);}else ++it;}
  signature_=key;
  const auto count=stock_function<unsigned(*)(void*)>(lv_obj_get_child_cnt)(panel_);
  for(unsigned i=0;i<count;++i){auto*p=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(panel_,int(i));
   if(std::find(owned_.begin(),owned_.end(),p)==owned_.end())stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(p,1);
  }
  int next_y=8;
  for(std::size_t i=0;i<rows.size();++i){const auto&row=rows[i];const auto slice=row.value("sliced",Json::object());
   const auto id=row.value("id","");auto&view=rows_[id];
   if(!view.button){
    for(int slot=0;slot<4;++slot){bool used=false;for(const auto&entry:rows_)if(entry.second.slot==slot)used=true;if(!used){view.slot=slot;break;}}
    view.left=view.slot>=0?widgets_.sources[view.slot]:create(lv_img_create,panel_);
    view.right=view.slot>=0?widgets_.destinations[view.slot]:create(lv_img_create,panel_);
    view.text=create(lv_label_create,panel_);view.button=create(lv_btn_create,panel_);view.caption=create(lv_label_create,view.button);
    stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(view.button,reinterpret_cast<void*>(0x463c8e8),0);
    stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(view.button,reinterpret_cast<void*>(0x463c8f8),0x20);
    for(auto address:{lv_obj_set_style_pad_top,lv_obj_set_style_pad_bottom,lv_obj_set_style_pad_left,lv_obj_set_style_pad_right})
     stock_function<void(*)(void*,int,unsigned)>(address)(view.button,0,0);
    bindings_.push_back({this,view.button,id,generation_});
    if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(view.button,&event,0,&bindings_.back())){bindings_.pop_back();fresh_=false;signature_.clear();throw std::runtime_error("Preview row binding failed");}
   }
   const int y=next_y;auto*left=view.left;auto*right=view.right;
   const auto source=row.value("source",Json());const auto route=row.value("route",Json());
   colour(left,identity_display_text(slice,"color","#888888"),8,y+2,view.slot>=0);
   colour(right,source.is_object()?identity_display_text(source.value("identity",Json::object()),"color","#888888"):"#555555",width/2,y+2,false);
   auto text=slice.value("material","Unknown");const auto brand=identity_display_text(slice,"brand","");if(!brand.empty())text+="\n"+brand;
   const auto usage=filament_usage_text(slice);if(!usage.empty())text+="\n"+usage;
   auto destination=route.is_object()?route.value("label","Choose source"):"Choose source";
   // Give route components explicit lines; counting only newlines while LVGL
   // wraps "Head 3 · External" allocates a one-line box and clips the source.
   const std::string separator=" · ";std::size_t split=0;
   while((split=destination.find(separator,split))!=std::string::npos){destination.replace(split,separator.size(),"\n");++split;}
   if(route.is_object()&&!row.value("eligible",false))destination+="\nUnavailable";
   const int caption_height=22*(1+int(std::count(destination.begin(),destination.end(),'\n')));
   const int button_height=std::max(54,caption_height+8);
   const int text_height=(!brand.empty()&&!usage.empty())?72:54;next_y+=std::max(text_height,button_height)+8;
   label(view.text,text,64,y,width/2-72,text_height);
   place(view.button,width/2+56,y,width-width/2-64,button_height);
   label(view.caption,destination,4,3,width-width/2-72,caption_height);
   center_button_caption(view.button,view.caption,destination);
  }
  readiness();
  stock_function<void(*)(void*,int,int)>(lv_obj_scroll_to_y)(panel_,scroll,0);
 }
private:
 void readiness(){
  for(const auto&binding:bindings_)if(binding.generation==generation_&&stock_object_valid(binding.object))
   stock_function<void(*)(void*,unsigned)>(fresh_?lv_obj_clear_state:lv_obj_add_state)(binding.object,128);
 }
 static void*parent(void*p){return stock_function<void*(*)(void*)>(lv_obj_get_parent)(p);}
 void retire(Row&r){
  if(r.slot>=0){for(auto*p:{r.left,r.right})if(stock_object_valid(p))stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(p,1);}
  for(auto*p:{r.caption,r.button,r.text,r.slot<0?r.left:nullptr,r.slot<0?r.right:nullptr})if(p){
   if(stock_object_valid(p))stock_function<void(*)(void*)>(lv_obj_del)(p);
   owned_.erase(std::remove(owned_.begin(),owned_.end(),p),owned_.end());
  }
 }
 void clear(){for(auto*p:owned_)if(stock_object_valid(p))stock_function<void(*)(void*)>(lv_obj_del)(p);owned_.clear();rows_.clear();}
 void*create(std::uintptr_t ctor,void*parent){auto*p=stock_function<void*(*)(void*)>(ctor)(parent);if(!p){fresh_=false;signature_.clear();throw std::runtime_error("Preview widget allocation failed");}owned_.push_back(p);return p;}
 static void place(void*p,int x,int y,int w,int h){stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(p,w,h);stock_function<void(*)(void*,int,int,int)>(lv_obj_align)(p,1,x,y);}
 void label(void*p,const std::string&text,int x,int y,int w,int h){place(p,x,y,w,h);stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(0x26297a0),0);stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(p,0xffeeeeeeU,0);stock_function<void(*)(void*,const char*)>(lv_label_set_text)(p,text.c_str());}
 void colour(void*p,const std::string&hex,int x,int y,bool image_button){
  stock_function<void(*)(void*,unsigned)>(lv_obj_clear_flag)(p,1);stock_function<void(*)(void*,unsigned)>(lv_obj_clear_flag)(p,2);place(p,x,y,50,50);
  if(image_button)for(int state:{0,1})stock_function<void(*)(void*,int,const void*,const void*,const void*)>(lv_imgbtn_set_src)(p,state,nullptr,white_.c_str(),nullptr);
  else stock_function<void(*)(void*,const void*)>(lv_img_set_src)(p,white_.c_str());
  std::uint32_t rgb=0xff888888;stock_rgb(hex,rgb);stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_img_recolor)(p,rgb,0);stock_function<void(*)(void*,unsigned char,unsigned)>(lv_obj_set_style_img_recolor_opa)(p,255,0);
 }
 static void panel_deleted(void*e)noexcept{try{auto*o=static_cast<StockPreviewRows*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(o&&stock_function<void*(*)(void*)>(lv_event_get_target)(e)==o->panel_){o->panel_=nullptr;o->owned_.clear();o->rows_.clear();o->signature_.clear();o->fresh_=false;++o->generation_;}}catch(...){} }
 static void event(void*e)noexcept{try{
  auto*b=static_cast<Binding*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(!b)return;auto*o=b->owner;
  const auto code=stock_function<int(*)(void*)>(lv_event_get_code)(e);
  if(code==33){for(auto it=o->bindings_.begin();it!=o->bindings_.end();++it)if(&*it==b){o->bindings_.erase(it);break;}return;}
  if(code!=7||b->generation!=o->generation_||!o->fresh_)return;
  auto*p=b->object;bool inside=false;auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(stock_function<void*(*)()>(lv_disp_get_default)());
  for(unsigned depth=0;p&&depth<32;++depth){if(!stock_object_valid(p)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return;if(p==o->panel_)inside=true;if(p==screen){if(inside&&o->select)o->select(b->row);return;}p=parent(p);}
 }catch(...){} }
};
}}
