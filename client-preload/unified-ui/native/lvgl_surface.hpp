// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "button_caption.hpp"
#include "../native_renderer.hpp"
#include "profile1113.hpp"
#include "../../openace-compat/screen1113/source/client/native1113_port.hpp"
#include <list>
#include <cstring>
#include <stdexcept>
namespace wmp_ui { namespace native {
#ifdef WMP_NATIVE_TEST
void* test_resolve(std::uintptr_t);
#endif
// Calls the statically linked LVGL in the verified WM executable. No browser,
// framebuffer painting, network calls or secondary LVGL instance.
class LvglSurface : public Surface {
public:
 bool initialize() {
#if defined(WMP_NATIVE_TEST)
  verified_=true;return true;
#elif defined(__aarch64__)
  if(!wmp_openace::Native1113Port::profile_file_matches("/proc/self/exe"))return false;
  for(const auto&w:windows)if(std::memcmp(reinterpret_cast<void*>(w.address),w.bytes,32))return false;
  verified_=true;return true;
#else
  return false;
#endif
 }
 bool owns_page()const override{return verified_&&root_&&live(root_)&&screen_==active_screen()&&!foreign();}
 bool open() {
  if(!verified_)return false;
  if(root_deleted_||(root_&&!live(root_))){root_=nullptr;objects_.clear();bindings_.clear();scroll_positions_.clear();pending_.clear();root_deleted_=false;++generation_;}
  auto screen=active_screen();if(!screen)return false;
  if(root_&&screen_!=screen)close();
  screen_=screen;
  if(foreign())return false;
  if(!root_) {
   // Stock keeps its shared top layer hidden on Home. An owned child there
   // cannot be made visible without changing the vendor parent's flags.
   // Append the page to the active screen instead; stock top/system modals
   // remain above it and foreign() still makes our page yield to them.
   root_=call<void*(*)(void*)>(lv_obj_create)(screen_);if(!root_)return false;
   reset_style(root_);flag(root_,16,false); // root fixed; only list panes scroll
   Area area{};call<void(*)(void*,Area*)>(lv_obj_get_coords)(screen_,&area);
   width_=area.x2-area.x1+1;height_=area.y2-area.y1+1;
   if(width_<640||height_<400){close();return false;}
   place(root_,0,0,width_,height_);style_color(root_,lv_obj_set_style_bg_color,0xff272b30);style(root_,lv_obj_set_style_bg_opa,255);
   ++generation_;bind(root_,"@root",false);
  }
  flag(root_,1,false);return true;
 }
 void hide(){if(root_&&live(root_))flag(root_,1,true);pending_.clear();}
 void close(){pending_.clear();if(root_&&live(root_))call<void(*)(void*)>(lv_obj_del)(root_);root_=nullptr;objects_.clear();bindings_.clear();scroll_positions_.clear();root_deleted_=false;++generation_;}
 void clear()override {
  if(!owns_page())throw std::runtime_error("Native page ownership changed");
  for(const auto&row:objects_)if(!reset_scroll_&&row.second.kind=="scroll"&&live(row.second.object))scroll_positions_[scroll_context_+":"+row.first]=call<int(*)(void*)>(lv_obj_get_scroll_y)(row.second.object);
  scroll_context_=next_scroll_context_;reset_scroll_=false;rebuilding_=true;call<void(*)(void*)>(lv_obj_clean)(root_);rebuilding_=false;
  // Root binding remains alive; child DELETE callbacks have already returned.
  objects_.clear();for(auto it=bindings_.begin();it!=bindings_.end();){if(it->object!=root_)it=bindings_.erase(it);else ++it;}pending_.clear();++generation_;
 }
 void draw(const Widget&w)override {
  if(w.id=="background")return; // root is the native full-page background
  if(widgets_count_++>1000)throw std::runtime_error("Screen widget limit exceeded");
  void*parent=root_;int px=0,py=0;
  if(!w.parent.empty()) {auto it=objects_.find(w.parent);if(it==objects_.end())throw std::runtime_error("Missing scroll parent");parent=it->second.object;px=it->second.x;py=it->second.y;}
  auto kind=w.kind;
  auto address=kind=="button"?lv_btn_create:kind=="label"||kind=="heading"||kind=="notice"||kind=="bar"?lv_label_create:lv_obj_create;
  auto obj=call<void*(*)(void*)>(address)(parent);if(!obj)throw std::runtime_error("LVGL allocation failed");
  reset_style(obj);flag(obj,16,kind=="scroll");
  // A genuine scrolling parent handles touch dragging and clips its children.
  if(kind=="scroll") {
   call<void(*)(void*,int)>(lv_obj_set_scroll_dir)(obj,12); // LV_DIR_VER: TOP|BOTTOM
   call<void(*)(void*,int)>(lv_obj_set_scrollbar_mode)(obj,3); // AUTO
  }
  const int x=w.id=="topbar"?84:w.x,ww=w.id=="topbar"?w.w-84:w.w;
  place(obj,sx(x-px),sy(w.y-py),sx(ww),sy(w.h));
  objects_[w.id]={obj,w.x,w.y,kind};
  if(kind=="button") {
   style_color(obj,lv_obj_set_style_bg_color,w.selected?0xffb84d06:parse_color(w.color,0xff353d46));style(obj,lv_obj_set_style_bg_opa,255);
   style(obj,lv_obj_set_style_radius,6);style(obj,lv_obj_set_style_border_width,1);style_color(obj,lv_obj_set_style_border_color,w.selected?0xfffb8b3e:0xff59636e);
   // Unavailable controls stay non-actionable but remain tappable for help.
   // The separate @reason route never enters the command renderer.
   if(!w.enabled)style_color(obj,lv_obj_set_style_bg_color,0xff505258);
   if(w.image_path.empty()){
   auto label=call<void*(*)(void*)>(lv_label_create)(obj);reset_style(label);flag(label,16,false);flag(label,2,false);
   place(label,sx(5),sy(5),sx(ww-10),sy(w.h-10));const auto caption=(w.enabled?std::string():std::string("? "))+(w.busy?std::string("Working...\n"):std::string())+w.text;text(label,caption,true);center_button_caption(obj,label,caption);
   }
   bind(obj,w.enabled?w.id:"@reason:"+w.id,true);
  }else if(kind=="label"||kind=="heading"||kind=="notice"||kind=="bar") {
   flag(obj,2,false);text(obj,w.text,false);
   if(kind=="notice"||kind=="bar"){style_color(obj,lv_obj_set_style_bg_color,kind=="bar"?0xff171b20:0xff684a19);style(obj,lv_obj_set_style_bg_opa,255);}
  }else {
   flag(obj,2,kind=="scroll");style_color(obj,lv_obj_set_style_bg_color,parse_color(w.color,kind=="card"?0xff303740:0xff272b30));style(obj,lv_obj_set_style_bg_opa,255);style(obj,lv_obj_set_style_radius,6);
   if(!w.text.empty()){
    auto label=call<void*(*)(void*)>(lv_label_create)(obj);reset_style(label);flag(label,16,false);flag(label,2,false);
    place(label,sx(5),sy(5),sx(ww-10),sy(w.h-10));text(label,w.text,false);
   }
  }
  if(!w.image_path.empty()&&w.image_path.compare(0,18,"/tmp/wmp-ui-thumb-")==0&&w.image_width>0&&w.image_height>0&&w.image_width<=800&&w.image_height<=800){
   auto img=call<void*(*)(void*)>(lv_img_create)(obj);flag(img,2,false);flag(img,16,false);
   call<void(*)(void*,const void*)>(lv_img_set_src)(img,w.image_path.c_str());
   int aw=std::max(1,sx(ww)-8),ah=std::max(1,sy(w.h)-8);
   int zoom=std::max(1,std::min(aw*256/w.image_width,ah*256/w.image_height));
   call<void(*)(void*,int,int)>(lv_img_set_pivot)(img,0,0);
   call<void(*)(void*,unsigned)>(lv_img_set_zoom)(img,unsigned(zoom));
   call<void(*)(void*,int,int)>(lv_obj_set_pos)(img,(sx(ww)-w.image_width*zoom/256)/2,(sy(w.h)-w.image_height*zoom/256)/2);
  }
  if(w.faded)style(obj,lv_obj_set_style_opa,100);
 }
 void finish()override {
  widgets_count_=0;
  for(const auto&row:objects_)if(row.second.kind=="scroll") {
   call<void(*)(void*)>(lv_obj_update_layout)(row.second.object);
   call<void(*)(void*,int,int)>(lv_obj_scroll_to_y)(row.second.object,scroll_positions_[scroll_context_+":"+row.first],0);
  }
  // Always reachable, including inside WM+ modals: return to the untouched
  // stock controls (including its Stop button). Never routed through backend.
  Widget escape;escape.id="@stock";escape.text="Back";escape.kind="button";escape.x=3;escape.y=2;escape.w=76;escape.h=32;draw(escape);
 }
 std::string take_input(){auto value=pending_;pending_.clear();return value;}
 bool is_open()const{return root_!=nullptr;}
 void scroll_context(const std::string&context){next_scroll_context_=context;}
 void clear_scroll(){scroll_positions_.clear();reset_scroll_=true;}
 bool verified()const{return verified_;}
 std::uint64_t generation()const{return generation_;}
 template<class Function>static Function call(std::uintptr_t address){
#ifdef WMP_NATIVE_TEST
 return reinterpret_cast<Function>(test_resolve(address));
#else
 return reinterpret_cast<Function>(address);
#endif
 }
private:
 struct Area{short x1,y1,x2,y2;};
 struct Object{void*object;int x,y;std::string kind;};
 struct Binding{LvglSurface*self;void*object;std::string id;bool enabled;std::uint64_t generation;};
 bool verified_=false,rebuilding_=false,reset_scroll_=false,root_deleted_=false;void*root_=nullptr,*screen_=nullptr;int width_=800,height_=480;unsigned widgets_count_=0;
 std::uint64_t generation_=1;std::string pending_,scroll_context_,next_scroll_context_;std::list<Binding>bindings_;std::map<std::string,Object>objects_;std::map<std::string,int>scroll_positions_;
 int sx(int x)const{return x*width_/800;}int sy(int y)const{return y*height_/480;}
 static bool live(void*p){return p&&call<bool(*)(void*)>(lv_obj_is_valid)(p);}
 static void*display(){return call<void*(*)()>(lv_disp_get_default)();}
 static void*layer(){auto d=display();return d?call<void*(*)(void*)>(lv_disp_get_layer_top)(d):nullptr;}
 static void*active_screen(){auto d=display();return d?call<void*(*)(void*)>(lv_disp_get_scr_act)(d):nullptr;}
 bool foreign()const {
  auto d=display();if(!d)return true;
  for(auto layer_address:{lv_disp_get_layer_top,lv_disp_get_layer_sys}) {
   auto l=call<void*(*)(void*)>(layer_address)(d);if(!l)continue;
   // Children of a hidden stock layer cannot cover or receive input over us.
   if(call<bool(*)(void*,unsigned)>(lv_obj_has_flag)(l,1))continue;
   auto count=call<unsigned(*)(void*)>(lv_obj_get_child_cnt)(l);if(count>512)return true;
   for(unsigned i=0;i<count;++i){auto child=call<void*(*)(void*,int)>(lv_obj_get_child)(l,int(i));if(child==root_)continue;
    if(child&&!call<bool(*)(void*,unsigned)>(lv_obj_has_flag)(child,1))return true;}
  }return false;
 }
 static void flag(void*o,unsigned f,bool yes){call<void(*)(void*,unsigned)>(yes?lv_obj_add_flag:lv_obj_clear_flag)(o,f);}
 static void style(void*o,std::uintptr_t f,int value){call<void(*)(void*,int,int)>(f)(o,value,0);}
 static void style_color(void*o,std::uintptr_t f,std::uint32_t value){call<void(*)(void*,std::uint32_t,int)>(f)(o,value,0);}
 static void reset_style(void*o){call<void(*)(void*,void*,unsigned)>(lv_obj_remove_style)(o,nullptr,0);for(auto f:{lv_obj_set_style_pad_top,lv_obj_set_style_pad_bottom,lv_obj_set_style_pad_left,lv_obj_set_style_pad_right,lv_obj_set_style_border_width,lv_obj_set_style_outline_width})style(o,f,0);}
 static void place(void*o,int x,int y,int w,int h){call<void(*)(void*,int,int)>(lv_obj_set_pos)(o,x,y);call<void(*)(void*,int,int)>(lv_obj_set_size)(o,w,h);}
 static std::uint32_t parse_color(const std::string&s,std::uint32_t fallback){if(s.size()!=7||s[0]!='#')return fallback;try{return 0xff000000U|std::stoul(s.substr(1),nullptr,16);}catch(...){return fallback;}}
 static void text(void*o,const std::string&s,bool centered){
  style_color(o,lv_obj_set_style_text_color,0xfff0f2f4);style(o,lv_obj_set_style_text_opa,255);style(o,lv_obj_set_style_text_align,centered?2:1);
  call<void(*)(void*,int)>(lv_label_set_long_mode)(o,0); // WRAP
  // The vendor's default font lacks these UI punctuation/arrow glyphs.
  // Keep user text otherwise intact and use legible directional fallbacks.
  std::string visible=s;
  for(const auto&replacement:std::vector<std::pair<std::string,std::string>>{{"↑","^"},{"↓","v"},{"→",">"},{"·","-"},{"✎","(edit)"},{"▾","v"},{"✓","*"},{"…","..."},{"⌫","Backspace"}}){
   std::size_t at=0;while((at=visible.find(replacement.first,at))!=std::string::npos){visible.replace(at,replacement.first.size(),replacement.second);at+=replacement.second.size();}
  }
  call<void(*)(void*,const char*)>(lv_label_set_text)(o,visible.c_str());
 }
 void bind(void*obj,const std::string&id,bool enabled){bindings_.push_back({this,obj,id,enabled,generation_});auto*b=&bindings_.back();for(int code:{7,33})if(!call<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(obj,&event,code,b))throw std::runtime_error("LVGL event registration failed");}
 static void event(void*e)noexcept {
  try {
   auto*b=static_cast<Binding*>(call<void*(*)(void*)>(lv_event_get_user_data)(e));if(!b)return;
   auto code=call<int(*)(void*)>(lv_event_get_code)(e);auto*self=b->self;
   if(code==33){if(b->id=="@root"){self->root_=nullptr;self->root_deleted_=true;++self->generation_;}b->enabled=false;return;}
   if(code!=7||!b->enabled||self->rebuilding_||b->generation!=self->generation_||!self->owns_page())return;
   auto indev=call<void*(*)()>(lv_indev_get_act)();if(indev&&call<void*(*)(void*)>(lv_indev_get_scroll_obj)(indev))return;
   if(self->pending_.empty())self->pending_=b->id; // one immutable deferred action
  }catch(...){}
 }
};
}}
