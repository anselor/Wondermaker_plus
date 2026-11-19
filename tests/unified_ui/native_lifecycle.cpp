// SPDX-License-Identifier: GPL-3.0-or-later
#define WMP_NATIVE_TEST 1
#include "native/stock_progress_panel.hpp"
#include "native/bootstrap.cpp"
#include "native/stock_usb_preview.hpp"
#include "native/stock_preview_widgets.hpp"
#include "native/stock_recovery_progress.hpp"
#include "native/stock_preview_controls.hpp"
#include "native/stock_preview_rows.hpp"
#include "native/stock_preview_page.hpp"
#include "native/stock_preview_loading.hpp"
#include "native/stock_async.hpp"
#include "native/stock_service_event.hpp"
#include "native/stock_text_keyboard.hpp"
#include "native/stock_preview_event_gate.hpp"
#include "native/stock_ace_filaments.hpp"
#include "native/stock_probe_editor.hpp"
#include "native/setup_completion.hpp"
#include <cstdlib>
#include <cassert>
#include <array>
#include <fstream>
#include <memory>
#include <iostream>
using namespace wmp_ui;using namespace wmp_ui::native;
namespace fake {
void*async_data=nullptr;void(*async_callback)(void*)=nullptr;
int async_success(void(*callback)(void*),void*data){async_data=data;async_callback=callback;return 1;}
int async_failure(void(*)(void*),void*){return 0;}
struct Event;
struct Callback {void(*fn)(void*);int code;void*data;};
struct Node {std::string text,image,options;unsigned layout_updates=0;bool height_fixed=false;bool pending_layout=false,open=false,is_image=false,is_label=false;unsigned selected=0,state=0,zoom_factor=256,disable_writes=0;int text_alignment=0,label_long_mode=-1;std::uintptr_t font_address=0;std::uint32_t text_color=0,background_color=0;int opacity=255,background_opacity=255;std::vector<std::uintptr_t>styles;std::uint32_t tint[2]={0,0};unsigned tint_opa[2]={0,0};Node*parent=nullptr;std::vector<Node*>children;std::vector<Callback>callbacks;bool live=true;unsigned flags=0;int x=0,y=0,w=800,h=480,scroll=0,dir=0,inset_x=0,inset_y=0;unsigned line_point_count=0;std::uint32_t line_color=0;};
unsigned char menu_selection=255;
unsigned style_resets=0;
void clear_styles(void*p){++style_resets;static_cast<Node*>(p)->styles.clear();}
void menu(void*,unsigned char selected){menu_selection=selected;}
void page_route(const char*){}
std::string video_translation="Video";
const char*translate(const char*text){return std::string(text)=="Video"?video_translation.c_str():text;}
void line_points(void*p,const void*,std::uint16_t n){static_cast<Node*>(p)->line_point_count=n;}
struct Event {Node*node;int code;void*data;};
std::vector<std::unique_ptr<Node>>nodes;std::function<void(Node*)>layout_hook;
Node* make(void*p){nodes.emplace_back(new Node);auto*n=nodes.back().get();n->parent=static_cast<Node*>(p);if(p)n->parent->children.push_back(n);return n;}
void*make_label(void*p){auto*n=make(p);n->is_label=true;return n;}
Node*screen=make(nullptr),*top=make(nullptr),*sys=make(nullptr);Node*scrolling=nullptr;
bool check_type(void*p,const void*type){if(type==reinterpret_cast<const void*>(lv_label_class))return static_cast<Node*>(p)->is_label;if(type==reinterpret_cast<const void*>(0x3636328))return !static_cast<Node*>(p)->is_image;assert(type==reinterpret_cast<const void*>(lv_img_class));return static_cast<Node*>(p)->is_image;}
void label_mode(void*p,int mode){static_cast<Node*>(p)->label_long_mode=mode;}
void set_width(void*p,int w){static_cast<Node*>(p)->w=w;}
int outer_width(void*p){auto*n=static_cast<Node*>(p);return n->pending_layout?0:n->w;}int outer_height(void*p){auto*n=static_cast<Node*>(p);return n->pending_layout?0:n->h;}
void*display(){return reinterpret_cast<void*>(1);}void*active(void*){return screen;}void*top_layer(void*){return top;}void*sys_layer(void*){return sys;}
bool live(void*p){return p&&static_cast<Node*>(p)->live;}
void flag(void*p,unsigned f){static_cast<Node*>(p)->flags|=f;}void unflag(void*p,unsigned f){static_cast<Node*>(p)->flags&=~f;}bool has(void*p,unsigned f){return (static_cast<Node*>(p)->flags&f)!=0;}
bool defer_sizes=false;
struct DeferredSizes {DeferredSizes(){defer_sizes=true;}~DeferredSizes(){defer_sizes=false;}};
void pos(void*p,int x,int y){auto*n=static_cast<Node*>(p);n->x=x;n->y=y;}void size(void*p,int w,int h){auto*n=static_cast<Node*>(p);n->w=w;n->h=h;n->height_fixed=true;if(defer_sizes)n->pending_layout=true;}
void align(void*p,int anchor,int x,int y){assert(anchor==1);pos(p,x,y);}
int width(void*p){auto*n=static_cast<Node*>(p);return n->pending_layout?0:n->w-n->inset_x;}int height(void*p){auto*n=static_cast<Node*>(p);return n->pending_layout?0:n->h-n->inset_y;}
void coords(void*p,void*out){auto*n=static_cast<Node*>(p);auto*a=static_cast<short*>(out);a[0]=n->x;a[1]=n->y;a[2]=n->x+n->w-1;a[3]=n->y+n->h-1;}
unsigned count(void*p){return static_cast<Node*>(p)->children.size();}void*child(void*p,int i){return static_cast<Node*>(p)->children.at(i);}void*parent(void*p){return static_cast<Node*>(p)->parent;}
void send(Node*n,int code){auto callbacks=n->callbacks;for(auto cb:callbacks)if(cb.code==code||cb.code==0){Event e{n,code,cb.data};cb.fn(&e);}}
int event_send(void*p,int code,void*){assert(static_cast<Node*>(p)->live);send(static_cast<Node*>(p),code);return 1;}
// Vendor maintenance bytes read by the nozzle scrub (nozzle_scrub_vendor.hpp).
unsigned char vendor_rapid_mode=1,vendor_selected[4]={0,0,0,0},vendor_pairing_failed=0;std::uint32_t vendor_heads=4;
// lv_disp_get_inactive_time: milliseconds since the last touch. 0 is a touch now.
std::uint32_t inactive_ms=3600000;std::uint32_t inactive(void*){return inactive_ms;}
void del(void*p){auto*n=static_cast<Node*>(p);assert(n->live);send(n,33);auto children=n->children;for(auto*c:children)del(c);n->live=false;n->callbacks.clear();if(n->parent){auto&v=n->parent->children;v.erase(std::remove(v.begin(),v.end(),n),v.end());}}
void clean(void*p){auto children=static_cast<Node*>(p)->children;for(auto*c:children)del(c);}
bool unbind(void*p,void(*fn)(void*)){auto&v=static_cast<Node*>(p)->callbacks;for(auto it=v.begin();it!=v.end();++it)if(it->fn==fn){v.erase(it);return true;}return false;}
const char*get_text(void*p){return static_cast<Node*>(p)->text.c_str();}
void append_text(void*p,const char*s){static_cast<Node*>(p)->text+=s;}
void erase_text_char(void*p){auto&s=static_cast<Node*>(p)->text;if(s.empty())return;auto i=s.size()-1;while(i>0&&(static_cast<unsigned char>(s[i])&0xc0)==0x80)--i;s.erase(i);}
void*bind(void*,void(*)(void*),int,void*);
bool text_constructor_fails=false;
void*key_value(void*p){return const_cast<char*>(static_cast<Node*>(p)->options.c_str());}
void make_text_keys(void*parent){
 auto&s=wmp_ui::native::test_text_keyboard_state();s.count=0;
 for(const auto*key:{"a","A","space","del","enter","back","大写","小写","123","ABC","next","pre"}){
  auto*n=make(parent);n->options=key;s.keys[s.count++]=n;bind(n,reinterpret_cast<void(*)(void*)>(text_key_event),7,nullptr);
 }
}
void make_text_keyboard(void*parent){
 auto&s=wmp_ui::native::test_text_keyboard_state();assert(s.edit_type==0);
 s.wifi=1;s.modal=make(parent);s.text=make(s.modal);s.background=make(s.modal);
 if(text_constructor_fails)throw std::runtime_error("Stock constructor failed");
 make_text_keys(s.background);
}
bool fail_binding=false;
void*bind(void*p,void(*fn)(void*),int code,void*data){if(fail_binding)return nullptr;static_cast<Node*>(p)->callbacks.push_back({fn,code,data});return p;}
void*callback_data(void*p,void(*fn)(void*)){for(const auto&cb:static_cast<Node*>(p)->callbacks)if(cb.fn==fn)return cb.data;return nullptr;}
int code(void*e){return static_cast<Event*>(e)->code;}void*userdata(void*e){return static_cast<Event*>(e)->data;}void*target(void*e){return static_cast<Event*>(e)->node;}
void*indev(){return reinterpret_cast<void*>(2);}void*scroll_obj(void*){return scrolling;}
void background_colour(void*p,std::uint32_t v,int){static_cast<Node*>(p)->background_color=v;}
void text_alignment(void*p,int v,unsigned){static_cast<Node*>(p)->text_alignment=v;}
void text_colour(void*p,std::uint32_t v,int){static_cast<Node*>(p)->text_color=v;}
unsigned text_writes=0;
void remove_style(void*,void*,unsigned){}void style(void*,int,int){}void color(void*p,std::uint32_t v,int){static_cast<Node*>(p)->line_color=v;}void one_int(void*,int){}void text(void*p,const char*value){++text_writes;static_cast<Node*>(p)->text=value;}void update(void*p){auto*n=static_cast<Node*>(p);++n->layout_updates;n->pending_layout=false;for(auto*c:n->children)update(c);if(layout_hook)layout_hook(n);}
const void*image_source(void*p){return static_cast<Node*>(p)->image.c_str();}
int image_type(const void*p){return p&&*static_cast<const char*>(p)?1:3;}
bool decoder_fails=false;
int image_info(const void*,void*header){if(decoder_fails)return 0;*static_cast<std::uint32_t*>(header)=(400U<<10)|(200U<<21);return 1;}
void image_src(void*p,const void*path){static_cast<Node*>(p)->image=static_cast<const char*>(path);}
void image_button_src(void*p,int state,const void*left,const void*middle,const void*right){assert(state==0||state==1);assert(!left&&!right);image_src(p,middle);}
void tint(void*p,std::uint32_t value,unsigned selector){assert(selector==0||selector==0x20);static_cast<Node*>(p)->tint[selector?1:0]=value;}
void tint_opacity(void*p,unsigned char value,unsigned selector){assert(selector==0||selector==0x20);static_cast<Node*>(p)->tint_opa[selector?1:0]=value;}
void add_style(void*p,const void*value,unsigned){static_cast<Node*>(p)->styles.push_back(reinterpret_cast<std::uintptr_t>(value));}
void font(void*p,const void*f,unsigned){static_cast<Node*>(p)->font_address=reinterpret_cast<std::uintptr_t>(f);}
void options(void*p,const char*text){static_cast<Node*>(p)->options=text;}
void selected(void*p,unsigned value){static_cast<Node*>(p)->selected=value;}
unsigned get_selected(void*p){return static_cast<Node*>(p)->selected;}
bool is_open(void*p){return static_cast<Node*>(p)->open;}
void close_dropdown(void*p){static_cast<Node*>(p)->open=false;send(static_cast<Node*>(p),32);}
Node*popup_owner=nullptr,*popup_list=nullptr;
void*list(void*p){return p==popup_owner?popup_list:p;}
bool has_state(void*p,unsigned state){return (static_cast<Node*>(p)->state&state)==state;}
void add_state(void*p,unsigned state){auto*n=static_cast<Node*>(p);if(state&128)++n->disable_writes;n->state|=state;}
void clear_state(void*p,unsigned state){static_cast<Node*>(p)->state&=~state;}
void background_opacity(void*p,int value,unsigned){static_cast<Node*>(p)->background_opacity=value;}
void opacity(void*p,int value,unsigned){static_cast<Node*>(p)->opacity=value;}
void zoom(void*p,unsigned value){static_cast<Node*>(p)->zoom_factor=value;}
void set_dir(void*p,int d){static_cast<Node*>(p)->dir=d;}int get_scroll(void*p){return static_cast<Node*>(p)->scroll;}void set_scroll(void*p,int y,int){static_cast<Node*>(p)->scroll=y;}
}
namespace wmp_ui {namespace native {
StockTextKeyboardState&test_text_keyboard_state(){static StockTextKeyboardState state;return state;}
// Inject worker observations at the GUI boundary, without issuing printer RPCs.
struct RuntimeReceiptTest {
 static std::string calibration_request(const Runtime&r){return r.calibration_binding_.request;}
 static void close_maintenance_notice(Runtime&r){r.maintenance_notice_.close();}
 static int requested(const Runtime&r){return r.requested_.load();}
 static std::string finish_preview(Runtime&r){r.preview_worker_.reset();std::lock_guard<std::mutex>lock(r.mutex_);return r.metadata_path_;}
 static void details_demand(Runtime&r,bool needed){r.filament_details_needed_.store(needed);}
 static bool nozzle_active(const Runtime&r){return r.nozzle_editor_.active();}
 static void usb_status(Runtime&r,const Json&data){r.normalized_=data;++r.status_publication_;r.at_=r.ui_.now_ms();r.usb_worker_->observe(data);}
 static Json usb_result(Runtime&r){return r.usb_worker_->result(r.usb_origin_);}
 static void usb_tick(Runtime&r){r.update_usb_preview();}
 static Json ace_source(Runtime&r){return r.stock_filament_.ace_controls().selected_source();}
 static void ace_colour_draft(Runtime&r,const Json&data,const std::string&id){
  assert(r.stock_identity_.begin_source(data,id,"color"));r.stock_ace_edit_=true;r.stock_material_owned_=true;r.stock_edit_field_="color";
 }
 static bool identity_active(const Runtime&r){return r.stock_identity_.active();}
 static void saved_load(Runtime&r,const Json&origin,const Json&current){
  auto data=current;r.normalized_=data;++r.status_publication_;r.at_=r.ui_.now_ms();r.standalone_.observe(data);
  r.ace_mode_active_=true;r.stock_ace_edit_=true;r.stock_edit_receipt_="saved-edit";
  r.stock_edit_operation_={{"id","saved-edit"},{"state","complete"},{"owner",origin["owner"]},{"session",origin["session"]},
   {"action","save_identity"},{"arguments",{{"draft",origin["sources"][0]}}},{"load_after_save",true},
   {"load_context",{{"job",origin["job"]},{"paused_filament",origin["paused_filament"]}}}};
  r.normalized_["receipts"]["saved-edit"]={{"state","complete"},{"message","Saved"}};
  r.update_stock_edit();
 }
 static void pending_edit(Runtime&r,const Json&origin,const std::string&action){
  r.stock_ace_edit_=true;r.stock_edit_receipt_="old-edit";
  r.stock_edit_operation_={{"id","old-edit"},{"state","unknown"},{"owner",origin["owner"]},{"session",origin["session"]},
   {"action",action},{"arguments",{{"draft",Json::object()}}},{"load_after_save",true}};
 }
 static void edit_state(Runtime&r,const char*state){r.stock_edit_operation_["state"]=state;}
 static Json edit_operation(const Runtime&r){return r.stock_edit_operation_;}
 static void submit_identity(Runtime&r,Json data,const Json&draft,wmp_openace::HttpPort&wire){
  r.filament_settings_.observe(data);
  const auto receipt=r.filament_settings_.submit({"save_identity",data.at("revision"),"standalone",{{"draft",draft}}});
  assert(receipt.state=="pending");
  r.stock_ace_edit_=true;r.stock_edit_receipt_=receipt.id;
  r.stock_edit_operation_={{"id",receipt.id},{"state","pending"},{"owner",data["owner"]},{"session",data["session"]},
   {"action","save_identity"},{"arguments",{{"draft",draft}}},{"load_after_save",true}};
  // A queued settings transaction must not occupy the physical-command slot.
  auto physical=data;physical["heater_limits"]={{"h0",{{"min",0},{"max",300}}}};
  r.standalone_.observe(physical);
  const auto heater=r.standalone_.submit({"temperature",data.at("revision"),"standalone",{{"head","h0"},{"target",0}}});
  assert(heater.state=="pending"&&heater.id!=receipt.id);
  // Retire the synthetic heater before checking metadata-only admission.
  // A real queued heater must block calibration, even without a view receipt.
  r.standalone_.invalidate();r.standalone_.deliver(wire);
  r.filament_settings_.deliver(wire);
  // The RPC may fail, or succeed without matching subsequent readback.
  for(int i=0;i<4;++i)r.filament_settings_.observe(data);
  r.normalized_=data;++r.status_publication_;r.at_=r.ui_.now_ms();
 }

 static void update_identity(Runtime&r){r.update_stock_edit();}
 static bool rename(Runtime&r,const std::string&name){return r.stock_filament_.ace_controls().rename_draft(name);}
 static Json unit_draft(Runtime&r){return r.stock_filament_.ace_controls().unit_draft();}
 static Json preview(const Runtime&r){return r.app_.preview_state();}
 static bool preview_session(const Runtime&r){return r.native_preview_session_;}
 static void preview_tick(Runtime&r){r.update_stock_preview();}
 static void picker(Runtime&r,void*modal){assert(r.stock_picker_.bind(modal));}
 static void attach(Runtime&r,const StockFilamentWidgets&w,void*p,void*a,void*t){r.stock_filament_.attach(w,p,a,t);}

 static void adoption_status(Runtime&r,const Json&normalized,const Json&raw,std::int64_t at){r.normalized_=normalized;++r.status_publication_;r.normalized_["preview_generation"]=r.preview_generation_;r.raw_=raw;r.at_=at;}
 static Receipt adopt(Runtime&r,const Json&candidate,const Json&context){return r.submit_adoption(candidate,context);}

 static void tool_context(Runtime&r,Json data,std::int64_t at){r.tool_mode_active_=true;r.tool_head_=2;r.standalone_.observe(data);r.normalized_=data;++r.status_publication_;r.at_=at;}
 static bool temperature(Runtime&r,const Json&context,int value){return r.apply_tool_temperature(context,2,value);}
 static void tool_action(Runtime&r,const std::string&action){r.tool_action(action);}
 static void slot_load(Runtime&r,const std::string&id){r.tool_mode_active_=false;r.ace_mode_active_=true;r.stock_filament_.ace_controls().action("load-source:"+id);}
 static void slot_action(Runtime&r,const std::string&action){r.tool_mode_active_=false;r.ace_mode_active_=true;r.stock_filament_.ace_controls().action(action);}
 static bool filament_notice(const Runtime&r){return r.filament_refusal_notice_.active();}
 static void clear_filament_notice(Runtime&r){r.filament_refusal_notice_.close();}
 static Json status(Runtime&r){return r.stock_snapshot();}
 static bool heater_off(Runtime&r,unsigned head){return r.send_physical_off(head);}
 static void pending_app(Runtime&r,const Json&data){r.app_.update(data);const_cast<Json&>(r.app_.operation())={{"id","previous-start"},{"action","start_print"},{"owner","standalone"},{"session",data.value("session","")},{"state","pending"}};}
 static Json app_operation(Runtime&r){return r.app_.operation();}
 static Json app_preview(Runtime&r){return r.app_.preview_state();}
 static void preview_back(Runtime&r){r.app_.event("back");r.stock_preview_.close();r.update_stock_preview();}
 static Receipt queue_temperature(Runtime&r){auto s=r.stock_snapshot();return r.standalone_.submit({"temperature",s.at("revision"),"standalone",{{"head","h0"},{"target",200}}});}
 static bool procedure_active(const Runtime&r){return r.filament_procedure_.active();}
 static std::string tool_receipt(const Runtime&r){return r.tool_receipt_;}
 static void update_tool(Runtime&r){r.update_tool_view();}
 static void draft_nozzle(Runtime&r,void*page,const Json&data){r.nozzle_editor_.update(data);assert(r.nozzle_editor_.show(page,0));}
 static void close_nozzle(Runtime&r){r.nozzle_editor_.close();}
 static void terminal_cancel(Runtime&r,void*page){assert(r.cancel_progress_.open(page,{{"id","done"},{"kind","print_cancel"},{"state","complete"},{"fresh",true},{"receipt",{{"state","complete"}}}}));}
 static void close_cancel(Runtime&r){r.cancel_progress_.close();}
 static Json cancel_result(Runtime&r){return r.cancel_worker_->result();}
 static bool cancel_tracks(Runtime&r,const std::string&id){return r.cancel_progress_.tracks(id);}
 static void cancel_observe(Runtime&r,const Json&helper,const Json&stats,bool resolution_fresh){
  r.cancel_worker_->observe(helper,stats,true);r.cancel_resolution_worker_->observe(helper,resolution_fresh);
 }
 static void pending(Runtime&r,bool tool,const std::string&id){if(tool)r.tool_receipt_=id;else r.stock_edit_receipt_=id;}
 static bool pending(const Runtime&r,bool tool){return !(tool?r.tool_receipt_:r.stock_edit_receipt_).empty();}
 static void observe(Runtime&r,const std::string&id){++r.status_publication_;r.normalized_["receipts"]={{id,{{"state","complete"},{"message","Confirmed"}}}};}
 static void scrub_vendor(Runtime&,unsigned char rapid,std::array<unsigned char,4>selected,unsigned heads){
  fake::vendor_rapid_mode=rapid;for(unsigned i=0;i<4;++i)fake::vendor_selected[i]=selected[i];fake::vendor_heads=heads;}
 static unsigned char scrub_rapid(const Runtime&){return fake::vendor_rapid_mode;}
 static void scrub_status(Runtime&r,const Json&data){std::lock_guard<std::mutex>lock(r.mutex_);r.normalized_=data;r.at_=r.ui_.now_ms();}
 static void scrub_advance(Runtime&r,std::int64_t&clock,std::int64_t ms){std::lock_guard<std::mutex>lock(r.mutex_);clock+=ms;}
 static ScrubView scrub_flow_view(Runtime&r){std::lock_guard<std::mutex>lock(r.mutex_);return nozzle_scrub_view(r.scrub_.flow_.facts());}
 static ScrubOutcome scrub_outcome(Runtime&r){std::lock_guard<std::mutex>lock(r.mutex_);return r.scrub_.flow_.outcome();}
 static void scrub_failed_byte(Runtime&r,unsigned char value){std::lock_guard<std::mutex>lock(r.mutex_);fake::vendor_pairing_failed=value;}
 static unsigned char scrub_failed_byte(Runtime&r){std::lock_guard<std::mutex>lock(r.mutex_);return fake::vendor_pairing_failed;}
 static void scrub_failure_wait(Runtime&r,int ms){std::lock_guard<std::mutex>lock(r.mutex_);r.scrub_.failure_wait_ms_=ms;}
 static void scrub_shutdown(Runtime&r){r.scrub_.shutdown();}
 static Json scrub_result(Runtime&r){std::lock_guard<std::mutex>lock(r.mutex_);
  return {{"flagged",r.scrub_.result_flagged_heads_locked()},{"saved_anyway",r.scrub_.result_saved_anyway_locked()},
   {"cancelled",r.scrub_.result_cancelled_locked()},{"restore_failed",r.scrub_.result_restore_failed_locked()}};}
};
void*test_stock_colour_picker(void*parent,int selected){assert(selected>=-1&&selected<16);return fake::make(parent);}
void*test_resolve(std::uintptr_t a){
if(a==0x38626e8){static const std::string asset("stock-white-filament.bin");return const_cast<std::string*>(&asset);}
 if(a==is_rapid_mode)return &fake::vendor_rapid_mode;
 if(a==auto_check_selected)return fake::vendor_selected;
 if(a==current_thr_number)return &fake::vendor_heads;
 if(a==knife_pairing_failed)return &fake::vendor_pairing_failed;
 #define MAP(name,fn) if(a==name)return reinterpret_cast<void*>(&fake::fn)
 MAP(lv_obj_set_width,set_width);MAP(lv_obj_check_type,check_type);MAP(lv_obj_get_width,outer_width);MAP(lv_obj_get_height,outer_height);
 MAP(lv_obj_get_event_user_data,callback_data);
 MAP(lv_obj_set_style_opa,opacity);
 MAP(lv_obj_remove_event_cb,unbind);MAP(lv_textarea_set_text,text);MAP(lv_textarea_get_text,get_text);
 MAP(lv_textarea_add_text,append_text);MAP(lv_textarea_del_char,erase_text_char);
 MAP(text_key_user_data,key_value);MAP(draw_text_keyboard,make_text_keyboard);MAP(create_text_keys,make_text_keys);
 MAP(lv_dropdown_create,make);MAP(lv_dropdown_set_options,options);MAP(lv_dropdown_set_selected,selected);MAP(lv_dropdown_get_selected,get_selected);MAP(lv_dropdown_is_open,is_open);MAP(lv_dropdown_close,close_dropdown);MAP(lv_dropdown_get_list,list);MAP(lv_obj_add_style,add_style);MAP(lv_obj_set_style_text_font,font);MAP(lv_obj_clear_state,clear_state);MAP(lv_obj_add_state,add_state);
 MAP(lv_img_get_src,image_source);MAP(lv_img_src_get_type,image_type);MAP(lv_img_decoder_get_info,image_info);
 MAP(lv_img_create,make);MAP(lv_img_set_src,image_src);MAP(lv_img_set_zoom,zoom);MAP(lv_img_set_pivot,pos);
 MAP(lv_imgbtn_set_src,image_button_src);MAP(lv_obj_set_style_img_recolor,tint);MAP(lv_obj_set_style_img_recolor_opa,tint_opacity);
 MAP(stock_remove_all_styles,clear_styles);MAP(lv_i18n_get_text,translate);
 MAP(lv_line_create,make);MAP(lv_line_set_points,line_points);MAP(lv_obj_set_style_line_width,style);MAP(lv_obj_set_style_line_color,color);
 MAP(lv_obj_create,make);MAP(lv_btn_create,make);MAP(lv_label_create,make_label);MAP(lv_label_get_text,get_text);MAP(lv_disp_get_default,display);MAP(lv_disp_get_scr_act,active);MAP(lv_disp_get_layer_top,top_layer);MAP(lv_disp_get_layer_sys,sys_layer);MAP(lv_disp_get_inactive_time,inactive);
 MAP(lv_obj_is_valid,live);MAP(lv_obj_get_parent,parent);MAP(lv_obj_get_child,child);MAP(lv_obj_get_child_cnt,count);MAP(lv_obj_get_coords,coords);MAP(lv_obj_get_content_coords,coords);
 MAP(lv_obj_add_flag,flag);MAP(lv_obj_clear_flag,unflag);MAP(lv_obj_has_flag,has);MAP(lv_obj_has_state,has_state);MAP(lv_obj_set_pos,pos);MAP(lv_obj_set_size,size);MAP(lv_obj_del,del);MAP(lv_obj_clean,clean);MAP(lv_obj_add_event_cb,bind);
 MAP(lv_obj_align,align);MAP(lv_obj_get_content_width,width);MAP(lv_obj_get_content_height,height);
 MAP(lv_event_send,event_send);
 MAP(lv_event_get_code,code);MAP(lv_event_get_user_data,userdata);MAP(lv_event_get_target,target);MAP(lv_indev_get_act,indev);MAP(lv_indev_get_scroll_obj,scroll_obj);
 MAP(lv_obj_set_style_bg_opa,background_opacity);
 MAP(lv_obj_remove_style,remove_style);MAP(lv_label_set_text,text);MAP(lv_label_set_long_mode,label_mode);MAP(lv_obj_move_to_index,one_int);MAP(lv_obj_add_state,one_int);
 MAP(lv_obj_set_scroll_dir,set_dir);MAP(lv_obj_set_scrollbar_mode,one_int);MAP(lv_obj_get_scroll_y,get_scroll);MAP(lv_obj_scroll_to_y,set_scroll);MAP(lv_obj_update_layout,update);
 MAP(lv_obj_set_style_text_color,text_colour);MAP(lv_obj_set_style_text_align,text_alignment);
 MAP(lv_obj_set_style_bg_color,background_colour);
 for(auto f:{lv_obj_set_style_border_color})if(a==f)return reinterpret_cast<void*>(&fake::color);
 for(auto f:{lv_obj_set_style_pad_top,lv_obj_set_style_pad_bottom,lv_obj_set_style_pad_left,lv_obj_set_style_pad_right,lv_obj_set_style_border_width,lv_obj_set_style_outline_width,lv_obj_set_style_bg_opa,lv_obj_set_style_radius,lv_obj_set_style_text_align,lv_obj_set_style_text_opa,lv_obj_set_style_opa})if(a==f)return reinterpret_cast<void*>(&fake::style);
 throw std::runtime_error("unhandled fake LVGL address");
#undef MAP
}
}}
struct Port : wmp_openace::NativeUi {
 std::int64_t now=1000;
 bool profile1113()const override{return true;}bool frame(wmp_openace::Frame&,void*)override{return false;}
 void*create(void*,Kind,Event,void*,std::uint64_t)override{return nullptr;}void erase(void*)override{}
 void rect(void*,wmp_openace::Rect)override{}void literal_text(void*,const std::string&)override{}void hidden(void*,bool)override{}void behind_stock(void*)override{}
 std::uint64_t enqueue(const std::string&)override{return 0;}std::int64_t now_ms()const override{return now;}
};
struct Http : wmp_openace::HttpPort {
 Json ace;std::vector<std::string>queries;bool ace_present=true;std::function<void(const std::string&)>on_get;
 Json extra_status=Json::object(),filament_details=Json::object();std::function<void()>on_post;
 std::string get(const std::string&path)override {
  queries.push_back(path);if(on_get)on_get(path);
  if(path=="/printer/wmp/filament/details")return Json{{"result",filament_details}}.dump();
  if(path.compare(0,23,"/server/files/metadata?")==0)return Json{{"result",{{"filename","folder/part.gcode"},{"filament_type",Json::array({"PLA","PETG"})},{"preset_colours",Json::array({"#123456","#aabbcc"})},{"size",1000},{"modified",1}}}}.dump();
  if(path=="/printer/objects/list")return Json{{"result",{{"objects",ace_present?Json::array({"print_stats","extruder","openace"}):Json::array({"print_stats","extruder"})}}}}.dump();
  auto response=Json{{"result",{{"status",{{"webhooks",{{"state","ready"}}},{"openace",ace},{"print_stats",{{"state","standby"},{"filename",""}}},{"extruder",{{"temperature",28.0},{"target",0.0}}}}}}}};response["result"]["status"].update(extra_status);return response.dump();
 }
 std::string post(const std::string&,const std::string&)override{assert(on_post);on_post();return "{\"result\":\"ok\"}";}
};
#include "progress_ui_contract.hpp"
#include "nozzle_scrub_lifecycle.hpp"
int main(int argc,char**argv){
 if(argc==3&&std::string(argv[1])=="--progress-fit")return progress_ui_contract(argv[2]);
 {auto*button=fake::make(nullptr);auto*caption=fake::make(button);button->w=130;button->h=54;button->pending_layout=true;
 wmp_ui::native::center_button_caption(button,caption,"Choose source");
 assert(!button->pending_layout&&caption->w>0&&caption->h==MyriadPro_Bold_20_line_height);
 button->h=64;center_button_caption(button,caption,"Confirm",40);
 assert(caption->h==25&&caption->y==(40-25)/2);
 }

 {
  // Stock page_to schedules construction: sidebar selection must survive
  // beyond the navigation callback, until the actual menu builder runs.
  wmp_openace::original_page.store(&fake::page_route);
  wmp_openace::original_sidebar.store(&fake::menu);
  wmp_openace::unified_page_to("camera_page");
  wmp_openace::unified_sidebar(nullptr,2);assert(fake::menu_selection==1);
  wmp_openace::unified_page_to("move_page");
  wmp_openace::unified_sidebar(nullptr,2);assert(fake::menu_selection==2);
  wmp_openace::original_page.store(nullptr);wmp_openace::original_sidebar.store(nullptr);
  StockNavigationTabs tabs;unsigned tools=0,videos=0;
  tabs.tools=[&]{++tools;};tabs.video=[&]{++videos;};
  auto*page=fake::make(fake::screen);std::array<void*,5>buttons{};
  for(auto&button:buttons){button=fake::make(page);fake::make_label(button);
   fake::bind(button,reinterpret_cast<void(*)(void*)>(stock_menu_event),1,nullptr);}
  tabs.settings(buttons);tabs.settings(buttons);
  auto*tool=static_cast<fake::Node*>(buttons[2]);
  assert(tool->children[0]->text=="Tools"&&tool->callbacks.size()==1);
  assert(static_cast<fake::Node*>(buttons[1])->callbacks.size()==1);
  fake::send(tool,1);assert(tools==0); // Original pressed handler was removed.
  fake::send(tool,7);assert(tools==1);
  tool->state|=128;fake::send(tool,7);assert(tools==1);tool->state&=~128U;
  page->flags|=1;fake::send(tool,7);assert(tools==1);page->flags&=~1U;
  auto*files=fake::make(fake::screen);std::array<void*,3>file_buttons{};
  for(auto&button:file_buttons)button=fake::make(files);
  static_cast<fake::Node*>(file_buttons[1])->flags|=1;
  fake::video_translation="Vidéo";tabs.files(file_buttons,false);
  auto*video=files->children.back();assert(video->x==280&&video->w==135&&video->h==45);
  assert(video->children[0]->text=="Vidéo"&&fake::style_resets==1);fake::video_translation="Video";
  fake::send(video,7);assert(videos==1);
  const auto allocations=fake::nodes.size();tabs.refresh();assert(fake::nodes.size()==allocations);
  static_cast<fake::Node*>(file_buttons[1])->flags&=~1U;tabs.refresh();assert(video->x==420);
  static_cast<fake::Node*>(file_buttons[1])->flags|=1;tabs.refresh();assert(video->x==280);
  auto*camera=fake::make(fake::screen);for(auto&button:file_buttons)button=fake::make(camera);
  tabs.files(file_buttons,true);auto*selected=camera->children.back();assert(selected->state&128);
  fake::send(selected,7);assert(videos==1);
  fake::del(files);fake::del(camera);fake::del(page);tabs.refresh();
 }
 assert(argc==3);std::ifstream input(argv[1]);Json data;input>>data;StubBackend backend;App app(backend);app.update(data);app.event("nav:filaments");
 {
  StockTextKeyboardHost host;
  auto&state=test_text_keyboard_state();
  state.modal=fake::make(fake::screen);state.background=fake::make(state.modal);state.text=fake::make(state.modal);
  state.edit_type=9;state.count=1;state.keys[0]=fake::make(state.background);
  state.layout=reinterpret_cast<void*>(123);state.widths=reinterpret_cast<void*>(456);
  const auto original=state;
  auto restored=[&](){assert(state.modal==original.modal&&state.background==original.background&&state.text==original.text);
   assert(state.edit_type==original.edit_type&&state.count==original.count&&state.keys==original.keys);
   assert(state.layout==original.layout&&state.widths==original.widths&&state.wifi==0);};
  std::string saved;
  assert(host.open(fake::screen,"ACE",[&](const std::string&name){saved=name;return true;}));restored();
  auto*modal=fake::screen->children.back();auto*text=modal->children[0];auto*keys=modal->children[1];
  auto press=[&](const std::string&value){for(auto*n:keys->children)if(n->options==value){fake::send(n,7);return;}assert(false);};
  press("space");press("a");assert(text->text=="ACE a");
  press("大写");restored();assert(text->text=="ACE a");
  press("A");press("123");restored();press("next");restored();
  press("enter");assert(saved=="ACE aA"&&!host.active()&&!modal->live);restored();
  const auto children=fake::screen->children.size();
  state.wifi=1;assert(!host.open(fake::screen,"ACE",{}));assert(fake::screen->children.size()==children);state.wifi=0;
  fake::text_constructor_fails=true;assert(!host.open(fake::screen,"ACE",{}));fake::text_constructor_fails=false;
  restored();assert(fake::screen->children.size()==children);
  fake::del(original.modal);state=StockTextKeyboardState();
 }
 {
  StockTextKeyboard keyboard;auto*modal=fake::make(fake::screen);auto*text=fake::make(modal);
  std::vector<StockTextKeyboard::Widget>keys;
  auto make_keys=[&](){keys.clear();for(const auto*value:{"A","2","space","del","enter","back","大写","é"}){
   auto*key=fake::make(modal);fake::bind(key,reinterpret_cast<void(*)(void*)>(text_key_event),7,nullptr);
   fake::bind(key,reinterpret_cast<void(*)(void*)>(text_key_event),31,nullptr);keys.push_back({key,value});
  }};
  make_keys();unsigned commits=0,layouts=0;std::string submitted;bool accept=false;
  auto commit=[&](const std::string&name){++commits;submitted=name;return accept;};
  auto layout=[&](const std::string&name){assert(name=="大写");++layouts;auto old=keys;for(const auto&key:old)fake::del(static_cast<fake::Node*>(key.object));make_keys();return keyboard.replace_keys(keys);};
  assert(keyboard.attach(modal,text,keys,"ACE",commit,layout));
  auto keypress=[&](const std::string&value){for(const auto&key:keys)if(key.value==value){fake::send(static_cast<fake::Node*>(key.object),7);return;}assert(false);};
  for(const auto&key:keys)for(const auto&binding:static_cast<fake::Node*>(key.object)->callbacks)assert(binding.fn!=reinterpret_cast<void(*)(void*)>(text_key_event));
  keypress("space");keypress("2");keypress("é");keypress("del");assert(text->text=="ACE 2");
  modal->flags|=1;keypress("A");assert(text->text=="ACE 2");modal->flags&=~1U;
  keypress("大写");assert(layouts==1&&text->text=="ACE 2");
  keypress("enter");assert(commits==1&&submitted=="ACE 2"&&keyboard.active());
  accept=true;keypress("enter");assert(commits==2&&!keyboard.active()&&!modal->live);
  modal=fake::make(fake::screen);text=fake::make(modal);make_keys();
  assert(keyboard.attach(modal,text,keys,"Original",commit,layout));keypress("A");keypress("back");assert(commits==2&&!keyboard.active());
  modal=fake::make(fake::screen);text=fake::make(modal);make_keys();
  assert(keyboard.attach(modal,text,keys,"Original",commit,layout));fake::del(modal);assert(!keyboard.active());
  modal=fake::make(fake::screen);text=fake::make(modal);make_keys();fake::fail_binding=true;
  assert(!keyboard.attach(modal,text,keys,"Original",commit,layout));fake::fail_binding=false;assert(!modal->live&&!keyboard.active());
  modal=fake::make(fake::screen);text=fake::make(modal);make_keys();
  assert(!keyboard.attach(modal,text,keys,std::string(65,'x'),commit,layout));assert(!modal->live);
  modal=fake::make(fake::screen);text=fake::make(modal);make_keys();
  auto partial=keys;partial.erase(partial.begin()); // omitted key still has a vendor handler
  assert(!keyboard.attach(modal,text,partial,"Original",commit,layout));assert(!modal->live&&!keyboard.active());
  modal=fake::make(fake::screen);text=fake::make(modal);make_keys();
  assert(keyboard.attach(modal,text,keys,"Original",commit,[](const std::string&)->bool{throw std::runtime_error("Rebuild failed");}));
  keypress("大写");assert(!keyboard.active()&&!modal->live);
  modal=fake::make(fake::screen);text=fake::make(modal);make_keys();
  assert(keyboard.attach(modal,text,keys,"Original",commit,layout));
  assert(!keyboard.replace_keys({})&&!keyboard.active()&&!modal->live);
 }
 // Reproduce stock Home: the shared top layer is hidden. Never unhide it
 // just to display our own page. The page belongs to the active screen.
 fake::top->flags|=1;const auto stock_layer_flags=fake::top->flags;
 auto hidden_layer_child=fake::make(fake::top);
 auto stock_content=fake::make(fake::screen);
 LvglSurface surface;assert(surface.initialize());assert(surface.open());Renderer renderer(app,surface);renderer.paint();
 auto root=fake::screen->children.back();assert(root->parent==fake::screen);assert(!(root->flags&1));assert(fake::top->flags==stock_layer_flags);
 assert(fake::screen->children.front()==stock_content&&stock_content->live);fake::del(stock_content);
 // Keypad/current-value cards must render their text, not just a background.
 Widget value;value.id="key-text";value.kind="card";value.text="220";value.x=100;value.y=94;value.w=660;value.h=40;surface.draw(value);
 auto card=root->children.back();assert(card->children.size()==1);assert(card->children[0]->text=="220");assert(!(card->children[0]->flags&2));
 fake::Node*scroll=nullptr;for(auto*n:root->children)if(n->dir==12)scroll=n;assert(scroll);assert(scroll->flags&16);assert(scroll->children.size()>8);
 scroll->scroll=170;renderer.paint();scroll=nullptr;for(auto*n:root->children)if(n->dir==12)scroll=n;assert(scroll&&scroll->scroll==170);
 // The same source-scroll widget has independent offsets in page/modal contexts.
 surface.scroll_context("preview/sources");renderer.paint();scroll=nullptr;for(auto*n:root->children)if(n->dir==12)scroll=n;assert(scroll&&scroll->scroll==0);scroll->scroll=42;
 surface.scroll_context("");renderer.paint();scroll=nullptr;for(auto*n:root->children)if(n->dir==12)scroll=n;assert(scroll&&scroll->scroll==170);
 surface.scroll_context("preview/sources");renderer.paint();scroll=nullptr;for(auto*n:root->children)if(n->dir==12)scroll=n;assert(scroll&&scroll->scroll==42);
 surface.scroll_context("");renderer.paint();
 // External stock screen deletion calls root DELETE before child DELETE.
 auto generation=surface.generation();fake::del(root);assert(!surface.is_open());assert(surface.open());assert(surface.generation()!=generation);renderer.paint();
 // Deleting the replacement root used to dereference freed binding userdata.
 fake::del(fake::screen->children.front());assert(surface.open());renderer.paint();
 // Foreign stock modal disowns our page and no owned touch can dispatch.
 assert(surface.owns_page());fake::top->flags&=~1U;assert(!surface.owns_page());
 surface.hide();assert(surface.take_input().empty());fake::del(hidden_layer_child);
 assert(surface.open());renderer.paint();
 auto modal=fake::make(fake::sys);assert(!surface.owns_page());surface.hide();assert(surface.take_input().empty());fake::del(modal);assert(surface.open());renderer.paint();
 // Actual screen replacement recreates its native content root.
 generation=surface.generation();fake::screen=fake::make(nullptr);assert(surface.open());assert(surface.generation()!=generation);renderer.paint();
 for(int i=0;i<4;++i){surface.close();assert(surface.open());renderer.paint();}
 // Native thumbnail widgets use stock LVGL images and remain inside buttons.
 data["files"]=Json::array({{{"id","image.gcode"},{"name","image.gcode"},{"sliced",Json::array()},{"thumbnail",{{"path","/tmp/wmp-ui-thumb-test.png"},{"width",320},{"height",240}}}}});
 app.update(data);app.event("file:image.gcode");renderer.paint();bool preview_image=false;for(const auto&node:fake::nodes)if(node->live&&node->image=="/tmp/wmp-ui-thumb-test.png")preview_image=true;assert(preview_image);
 renderer.click("thumbnail",renderer.generation());auto expanded=renderer.paint();assert(expanded["modal"]=="thumbnail");bool expanded_image=false;for(const auto&w:expanded["widgets"])if(w["id"]=="expanded-thumbnail")expanded_image=w["kind"]=="image";assert(expanded_image);
 renderer.click("close",renderer.generation());assert(renderer.paint()["modal"]=="");
 surface.close();assert(fake::screen->children.empty());
 // Construction-time guard distinguishes each local/USB content lifetime.
 StockPreviewEventGate preview_gate;auto*gate_page=fake::make(fake::screen);
 auto*local_content=fake::make(gate_page);auto*local_start=fake::make(local_content);
 assert(!preview_gate.consume(local_start,7));
 preview_gate.begin(gate_page,true);assert(preview_gate.consume(local_start,7));
 assert(preview_gate.finish(local_content));assert(preview_gate.consume(local_start,7));
 assert(preview_gate.metadata_ticket(local_content)==0);
 assert(preview_gate.scheduled_origin().ticket==0);
 assert(!preview_gate.consume(local_start,33));
 auto*usb_content=fake::make(gate_page);auto*usb_start=fake::make(usb_content);
 preview_gate.begin(gate_page,false);assert(preview_gate.finish(usb_content));
 const auto usb_ticket=preview_gate.metadata_ticket(usb_content);assert(usb_ticket);
 assert(preview_gate.scheduled_origin().content==usb_content&&preview_gate.scheduled_origin().ticket==usb_ticket);
 assert(preview_gate.metadata_allowed(usb_content,usb_content,usb_ticket));
 assert(!preview_gate.metadata_allowed(usb_content,local_content,usb_ticket));
 assert(!preview_gate.metadata_allowed(local_content,usb_content,0));
 assert(!preview_gate.consume(usb_start,7)&&preview_gate.consume(local_start,7));
 auto*usb_modal=fake::make(gate_page);auto*usb_choice=fake::make(usb_modal);
 assert(preview_gate.consume(usb_choice,7));
 assert(!preview_gate.usb_modal(local_start,usb_modal));
 assert(preview_gate.usb_modal(usb_start,usb_modal)&&!preview_gate.consume(usb_choice,7));
 fake::del(usb_modal);assert(preview_gate.consume(usb_choice,7));
 // Failed capture is still protected, even after a successful USB preview.
 auto*failed_content=fake::make(gate_page);auto*failed_start=fake::make(failed_content);
 preview_gate.begin(gate_page,true);assert(!preview_gate.finish(nullptr));
 assert(!preview_gate.metadata_allowed(usb_content,usb_content,usb_ticket));
 assert(preview_gate.scheduled_origin().ticket==0);
 assert(preview_gate.consume(failed_start,7)&&!preview_gate.consume(usb_start,7));
 fake::del(local_content);assert(preview_gate.consume(local_start,7));
 auto*failed_usb=fake::make(gate_page);preview_gate.begin(gate_page,false);
 fake::fail_binding=true;assert(!preview_gate.finish(failed_usb));fake::fail_binding=false;
 assert(preview_gate.consume(failed_usb,7));fake::del(gate_page);
 // Stock preview identity comes from captured objects and callback/action pairs,
 // never translated button text or geometry. Inventory is read-only.
 StockPreviewWidgets preview_widgets;preview_widgets.page=fake::make(fake::screen);
 preview_widgets.content=fake::make(preview_widgets.page);preview_widgets.title=fake::make(preview_widgets.content);
 for(unsigned i=0;i<3;++i){preview_widgets.options[i]=fake::make(preview_widgets.content);fake::bind(preview_widgets.options[i],reinterpret_cast<void(*)(void*)>(preview_event),7,reinterpret_cast<void*>(i));}
 for(auto&source:preview_widgets.sources)source=fake::make(preview_widgets.content);
 for(auto&destination:preview_widgets.destinations)destination=fake::make(preview_widgets.content);
 auto*stock_footer=fake::make(preview_widgets.content);auto*stock_start=fake::make(stock_footer);auto*stock_cancel=fake::make(stock_footer);
 fake::bind(stock_start,reinterpret_cast<void(*)(void*)>(preview_event),7,reinterpret_cast<void*>(4));
 fake::bind(stock_cancel,reinterpret_cast<void(*)(void*)>(preview_event),7,reinterpret_cast<void*>(3));
 auto*thumbnail_panel=fake::make(preview_widgets.content);thumbnail_panel->w=thumbnail_panel->h=149;
 auto*thumbnail=fake::make(thumbnail_panel);thumbnail->is_image=true;
 assert(StockPreviewInventory::find_thumbnail(preview_widgets.content)==thumbnail);
 thumbnail->is_image=false;assert(!StockPreviewInventory::find_thumbnail(preview_widgets.content));thumbnail->is_image=true;
 auto*ambiguous_panel=fake::make(preview_widgets.content);ambiguous_panel->w=ambiguous_panel->h=149;
 auto*ambiguous_image=fake::make(ambiguous_panel);ambiguous_image->is_image=true;
 assert(!StockPreviewInventory::find_thumbnail(preview_widgets.content));fake::del(ambiguous_panel);
 auto*extra_child=fake::make(thumbnail_panel);assert(!StockPreviewInventory::find_thumbnail(preview_widgets.content));fake::del(extra_child);
 const auto inventory_allocations=fake::nodes.size();
 assert(StockPreviewInventory::resolve(preview_widgets));
 assert(preview_widgets.start==stock_start&&preview_widgets.cancel==stock_cancel&&preview_widgets.thumbnail==thumbnail);
 assert(fake::nodes.size()==inventory_allocations&&stock_start->callbacks.size()==1);
 auto broken_preview=preview_widgets;broken_preview.sources[1]=broken_preview.sources[0];
 assert(!StockPreviewInventory::resolve(broken_preview)&&!broken_preview.start);
 auto*outsider=fake::make(fake::screen);broken_preview=preview_widgets;broken_preview.title=outsider;
 assert(!StockPreviewInventory::resolve(broken_preview));fake::del(outsider);
 auto*duplicate_start=fake::make(stock_footer);fake::bind(duplicate_start,reinterpret_cast<void(*)(void*)>(preview_event),7,reinterpret_cast<void*>(4));
 assert(!StockPreviewInventory::resolve(preview_widgets)&&!preview_widgets.start);fake::del(duplicate_start);
 assert(StockPreviewInventory::resolve(preview_widgets));
 fake::bind(preview_widgets.content,reinterpret_cast<void(*)(void*)>(preview_refresh_event),30,nullptr);
 fake::bind(stock_start,reinterpret_cast<void(*)(void*)>(preview_event),31,reinterpret_cast<void*>(4));
 auto*start_caption=fake::make(stock_start);start_caption->text="PRINT";
 auto*cancel_caption=fake::make(stock_cancel);cancel_caption->text="CANCEL";
 StockPreviewControls preview_controls;std::vector<unsigned>preview_actions;
 assert(preview_controls.attach(preview_widgets,[&](unsigned action){preview_actions.push_back(action);}));
 assert(preview_controls.active()&&(stock_start->state&128));
 assert(start_caption->text_color==0xff888888U&&cancel_caption->text_color==0xffeeeeeeU);
 for(const auto&cb:stock_start->callbacks)assert(cb.fn!=reinterpret_cast<void(*)(void*)>(preview_event));
 fake::send(stock_start,7);assert(preview_actions.empty());
 preview_controls.readiness(true,false);fake::send(static_cast<fake::Node*>(preview_widgets.options[0]),7);assert(preview_actions==std::vector<unsigned>{0});
 fake::send(stock_start,7);assert(preview_actions.size()==1);
 preview_controls.readiness(true,true);assert(start_caption->text_color==0xffeeeeeeU);static_cast<fake::Node*>(preview_widgets.page)->flags|=1;
 fake::send(stock_start,7);assert(preview_actions.size()==1);
 static_cast<fake::Node*>(preview_widgets.page)->flags&=~1U;
 fake::send(stock_start,7);fake::send(stock_start,7);assert(preview_actions==std::vector<unsigned>({0,4}));
 assert(start_caption->text_color==0xff888888U);
 preview_controls.readiness(true,true);fake::send(stock_start,7);assert(preview_actions.size()==2); // refresh cannot rearm admission
 fake::send(stock_cancel,7);assert(preview_actions.back()==3); // escape stays usable while waiting
 preview_controls.retire();fake::send(stock_cancel,7);assert(preview_actions.size()==3);
 fake::del(preview_widgets.page);assert(!preview_controls.active());
 assert(!StockPreviewInventory::resolve(preview_widgets));
 // Failure after inventory must close only the newly owned preview content.
 auto make_preview=[](){
  StockPreviewWidgets w;w.page=fake::make(fake::screen);w.content=fake::make(w.page);w.title=fake::make(w.content);
  for(unsigned i=0;i<3;++i){w.options[i]=fake::make(w.content);fake::bind(w.options[i],reinterpret_cast<void(*)(void*)>(preview_event),7,reinterpret_cast<void*>(i));}
  for(auto&source:w.sources)source=fake::make(w.content);
  for(auto&destination:w.destinations)destination=fake::make(w.content);
  auto*start=fake::make(w.content);auto*cancel=fake::make(w.content);
  fake::bind(start,reinterpret_cast<void(*)(void*)>(preview_event),7,reinterpret_cast<void*>(4));
  fake::bind(cancel,reinterpret_cast<void(*)(void*)>(preview_event),7,reinterpret_cast<void*>(3));
  return w;
 };
 auto invalid_inventory=make_preview();invalid_inventory.sources[1]=invalid_inventory.sources[0];
 assert(!preview_controls.attach(invalid_inventory,{}));assert(!fake::live(invalid_inventory.content)&&fake::live(invalid_inventory.page));fake::del(invalid_inventory.page);
 auto no_refresh=make_preview();
 assert(!preview_controls.attach(no_refresh,{}));assert(!fake::live(no_refresh.content)&&fake::live(no_refresh.page));fake::del(no_refresh.page);
 auto binding_failure=make_preview();fake::bind(binding_failure.content,reinterpret_cast<void(*)(void*)>(preview_refresh_event),30,nullptr);
 fake::fail_binding=true;assert(!preview_controls.attach(binding_failure,{}));fake::fail_binding=false;
 assert(!fake::live(binding_failure.content)&&fake::live(binding_failure.page)&&!preview_controls.active());fake::del(binding_failure.page);
 // Optional stock controls may be absent or retain globals from an old page.
 for(unsigned missing:{1U,2U,3U}){
  auto optional=make_preview();
  fake::bind(optional.content,reinterpret_cast<void(*)(void*)>(preview_refresh_event),30,nullptr);
  auto*stale=fake::make(fake::screen);
  for(unsigned i=1;i<3;++i)if(missing&(1U<<(i-1))){fake::del(optional.options[i]);optional.options[i]=stale;optional.option_icons[i]=stale;}
  assert(StockPreviewInventory::resolve(optional));
  for(unsigned i=1;i<3;++i)if(missing&(1U<<(i-1)))assert(!optional.options[i]&&!optional.option_icons[i]);
  unsigned sent=0;StockPreviewControls controls;
  assert(controls.attach(optional,[&](unsigned){++sent;}));
  fake::send(static_cast<fake::Node*>(optional.start),7);assert(sent==0);
  controls.readiness(true,true);fake::send(static_cast<fake::Node*>(optional.start),7);assert(sent==1);
  fake::del(optional.page);fake::del(stale);
 }
 // Replacing a page retires its callbacks even before the old stock page dies.
 auto old_preview=make_preview();auto new_preview=make_preview();
 fake::bind(old_preview.content,reinterpret_cast<void(*)(void*)>(preview_refresh_event),30,nullptr);
 fake::bind(new_preview.content,reinterpret_cast<void(*)(void*)>(preview_refresh_event),30,nullptr);
 assert(StockPreviewInventory::resolve(old_preview)&&StockPreviewInventory::resolve(new_preview));
 unsigned preview_dispatches=0;
 assert(preview_controls.attach(old_preview,[&](unsigned){++preview_dispatches;}));preview_controls.readiness(true,true);
 assert(preview_controls.attach(new_preview,[&](unsigned){++preview_dispatches;}));preview_controls.readiness(true,true);
 fake::send(static_cast<fake::Node*>(old_preview.start),7);assert(preview_dispatches==0);
 fake::del(old_preview.page);assert(preview_controls.active());
 fake::send(static_cast<fake::Node*>(new_preview.start),7);assert(preview_dispatches==1);
 fake::del(new_preview.page);assert(!preview_controls.active());
 // USB copy uses the stock footer; it cannot dispatch print/options/mapping.
 {
  auto usb_widgets=make_preview();
  fake::bind(usb_widgets.content,reinterpret_cast<void(*)(void*)>(preview_refresh_event),30,nullptr);
  assert(StockPreviewInventory::resolve(usb_widgets));
  auto*start=static_cast<fake::Node*>(usb_widgets.start);auto*cancel=static_cast<fake::Node*>(usb_widgets.cancel);
  fake::make(start)->text="Start";fake::make(cancel)->text="Cancel";
  StockUsbPreview usb;unsigned copies=0,reviews=0;std::string reviewed;
  usb.copy=[&]{++copies;};usb.review=[&](const std::string&path){++reviews;reviewed=path;};
  assert(usb.attach(usb_widgets));usb.update(Json::object(),true);
  assert(start->children[0]->text=="COPY");
  for(auto*option:usb_widgets.options){assert(static_cast<fake::Node*>(option)->state&128);fake::send(static_cast<fake::Node*>(option),7);}
  assert(copies==0&&reviews==0);
  fake::send(start,7);fake::send(start,7);assert(copies==1&&start->children[0]->text=="COPYING");
  const Json receipt={{"state","copied"},{"destination","WM_USB_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/part.gcode"}};
  usb.update(receipt,false);fake::send(start,7);assert(reviews==0);
  usb.update(receipt,true);assert(start->children[0]->text=="OPEN FILE");
  for(const auto&node:fake::nodes)if(node->live&&node->parent==fake::parent(usb_widgets.sources[0]))
   assert(node->text.find("1. Check USB file")==std::string::npos&&node->text.find("2. Copy to printer")==std::string::npos);
  fake::send(start,7);fake::send(start,7);assert(reviews==1&&reviewed==receipt["destination"]&&copies==1);
  const std::string long_destination="WM_USB_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/"+std::string(240,'x')+".gcode";
  usb.update({{"state","unknown"},{"destination",long_destination},{"message","Copy result unconfirmed."}},false);
  bool locator=false;for(const auto&node:fake::nodes)if(node->live&&node->text.find(long_destination)!=std::string::npos){
   locator=true;assert(node->parent==fake::parent(usb_widgets.sources[0])&&node->parent->dir==12&&(node->parent->flags&16));
  }
  assert(locator);fake::send(start,7);assert(copies==1&&reviews==1);
  fake::send(cancel,7);assert(!usb.active()&&fake::live(usb_widgets.page));fake::del(usb_widgets.page);
 }
 // Mapping extension uses the existing panel and first four colour pairs.
 auto*rows_page=fake::make(fake::screen);auto*rows_content=fake::make(rows_page);auto*rows_panel=fake::make(rows_content);
 StockPreviewWidgets row_widgets;row_widgets.page=rows_page;row_widgets.content=rows_content;
 for(auto&source:row_widgets.sources)source=fake::make(rows_panel);
 for(auto&destination:row_widgets.destinations)destination=fake::make(rows_panel);
 auto*stock_filename=fake::make(rows_content);stock_filename->text="part.gcode";
 StockPreviewRows mapping_rows;assert(mapping_rows.mount(row_widgets,"stock-white.bin"));
 Json mapping_state={{"fresh",true},{"editable",true},{"rows",Json::array()}};
 for(unsigned i=0;i<6;++i)mapping_state["rows"].push_back({{"id",std::to_string(i)},{"sliced",{{"color","#123456"},{"material","PLA"},{"brand","Generic"}}},{"route",nullptr},{"source",nullptr}});
 mapping_state["rows"][0]["sliced"]["filament_used_g"]=49.31;
 std::string selected_row;mapping_rows.select=[&](const std::string&id){selected_row=id;};
 mapping_rows.update(mapping_state,389);assert(rows_panel->dir==12&&stock_filename->text=="part.gcode");
 bool usage_visible=false;for(const auto&n:fake::nodes)if(n->live&&n->parent==rows_panel&&n->text=="T0: PLA\nGeneric\n49.31 g"){usage_visible=true;assert(n->h>=66);}assert(usage_visible);
 assert(fake::live(row_widgets.sources[0])&&fake::parent(row_widgets.sources[0])==rows_panel);
 assert(static_cast<fake::Node*>(row_widgets.sources[0])->tint[0]==0xff123456);
 rows_panel->scroll=84;auto row_allocations=fake::nodes.size();mapping_rows.update(mapping_state,389);
 assert(fake::nodes.size()==row_allocations&&rows_panel->scroll==84);
 fake::Node*last_destination=nullptr;unsigned destination_count=0;
 for(const auto&n:fake::nodes)if(n->live&&n->text=="Choose source"&&n->parent->parent==rows_panel){last_destination=n->parent;++destination_count;}
 assert(destination_count==6&&last_destination);
 mapping_state["revision"]="status-refresh";mapping_rows.update(mapping_state,389);
 assert(fake::nodes.size()==row_allocations&&last_destination->live);
 fake::send(last_destination,7);assert(selected_row=="5");
 mapping_state["fresh"]=false;mapping_rows.update(mapping_state,389);selected_row.clear();
 assert(fake::nodes.size()==row_allocations&&last_destination->live&&(last_destination->state&128));
 for(const auto&n:fake::nodes)if(n->live&&n->text=="Choose source"&&n->parent->parent==rows_panel)fake::send(n->parent,7);
 assert(selected_row.empty()&&rows_panel->scroll==84);
 mapping_state["fresh"]=true;mapping_rows.update(mapping_state,389);
 assert(fake::nodes.size()==row_allocations&&last_destination->live&&!(last_destination->state&128));
 fake::send(last_destination,7);assert(selected_row=="5");selected_row.clear();
 mapping_state["editable"]=false;mapping_rows.update(mapping_state,389);
 assert(fake::nodes.size()==row_allocations&&last_destination->live&&(last_destination->state&128));
 fake::send(last_destination,7);assert(selected_row.empty());
 mapping_state["fresh"]=true;mapping_state["editable"]=true;
 mapping_state["rows"][0]["route"]={{"label","Head 3 · External"}};mapping_state["rows"][0]["eligible"]=true;
 mapping_rows.update(mapping_state,389);bool route_caption_visible=false;
 for(const auto&n:fake::nodes)if(n->live&&n->parent&&n->parent->parent==rows_panel&&n->text=="Head 3\nExternal"){
  route_caption_visible=true;assert(n->h>=44&&n->parent->h>=54);assert(n->y>=0&&n->y+n->h<=n->parent->h);
 }
 assert(route_caption_visible);
 assert(fake::nodes.size()==row_allocations&&last_destination->live);
 mapping_state["rows"][5]["sliced"]["color"]="#abcdef";
 mapping_state["rows"][5]["sliced"]["filament_used_g"]=12.5;
 mapping_rows.update(mapping_state,410);
 assert(fake::nodes.size()==row_allocations&&last_destination->live&&rows_panel->scroll==84);
 std::reverse(mapping_state["rows"].begin(),mapping_state["rows"].end());mapping_rows.update(mapping_state,410);
 assert(fake::nodes.size()==row_allocations&&last_destination->live&&last_destination->y==8);
 selected_row.clear();fake::send(last_destination,7);assert(selected_row=="5");selected_row.clear();
 // Reordering does not rebind a retained button to the item at its old position.
 std::reverse(mapping_state["rows"].begin(),mapping_state["rows"].end());
 mapping_state["rows"].erase(mapping_state["rows"].begin());mapping_rows.update(mapping_state,410);
 assert(fake::nodes.size()==row_allocations&&last_destination->live);
 mapping_state["rows"].insert(mapping_state["rows"].begin(),Json{{"id","new-row"},{"sliced",{{"material","PLA"},{"color","#123456"}}},{"route",{{"label","Head 3 · External"}}},{"source",nullptr},{"eligible",true}});
 mapping_rows.update(mapping_state,389);assert(fake::nodes.size()==row_allocations+3&&last_destination->live);
 mapping_state["rows"][0]["eligible"]=false;mapping_rows.update(mapping_state,389);bool unavailable_caption_visible=false;
 for(const auto&n:fake::nodes)if(n->live&&n->parent&&n->parent->parent==rows_panel&&n->text=="Head 3\nExternal\nUnavailable"){
  unavailable_caption_visible=true;assert(n->h>=66&&n->parent->h>=74);assert(n->y+n->h<=n->parent->h);
 }
 assert(unavailable_caption_visible);
 mapping_state["fresh"]=true;mapping_state["editable"]=false;
 mapping_state["rows"][0]["route"]={{"label","T0 - ACE 1 - Slot 1"}};mapping_state["rows"][0]["eligible"]=false;
 mapping_rows.update(mapping_state,389);bool invalid_mapping_visible=false;
 for(const auto&n:fake::nodes)if(n->live&&n->parent&&n->parent->parent==rows_panel&&n->text.find("Unavailable")!=std::string::npos){invalid_mapping_visible=true;fake::send(n->parent,7);}
 assert(invalid_mapping_visible&&selected_row.empty());
 // Exercise metadata -> native row rendering, retaining sparse sliced IDs.
 // Missing weight must show length rather than an invented gram estimate.
 for(unsigned scenario=0;scenario<3;++scenario){
  Json metadata={{"filament_type","PLA;PETG;PLA;ABS"},
   {"preset_colours",Json::array({"#FF0000","#00FF00","#0000FF","#FFFF00"})},
   {"filament_used_mm",Json::array({0,125,0,250})}};
  if(scenario==0)metadata["filament_used_g"]=Json::array({0,0.38,0,0.75});
  if(scenario==2)metadata.erase("filament_used_mm");
  const auto parsed=preview_file("usage.gcode",metadata,"");
  Json rendered={{"fresh",true},{"editable",true},{"rows",Json::array()}};
  for(const auto&row:parsed["sliced"])rendered["rows"].push_back({{"id",row["id"]},{"sliced",row},{"route",nullptr},{"source",nullptr}});
  mapping_rows.update(rendered,389);
  std::vector<std::string>captions;std::vector<fake::Node*>buttons;
  for(const auto&node:fake::nodes)if(node->live){
   if(node->parent==rows_panel&&!node->text.empty())captions.push_back(node->text);
   if(node->text=="Choose source"&&node->parent&&node->parent->parent==rows_panel)buttons.push_back(node->parent);
  }
  const std::vector<std::string>expected=scenario==0?std::vector<std::string>{"T1: PETG\n0.38 g","T3: ABS\n0.75 g"}:
   scenario==1?std::vector<std::string>{"T1: PETG\n125.00 mm","T3: ABS\n250.00 mm"}:
   std::vector<std::string>{"T0: PLA","T1: PETG","T2: PLA","T3: ABS"};
  std::vector<fake::Node*>row_labels;
  for(const auto&node:fake::nodes)if(node->live&&node->parent==rows_panel&&!node->text.empty())row_labels.push_back(node.get());
  std::sort(row_labels.begin(),row_labels.end(),[](fake::Node*a,fake::Node*b){return a->y<b->y;});
  captions.clear();for(auto*node:row_labels)captions.push_back(node->text);
  std::sort(buttons.begin(),buttons.end(),[](fake::Node*a,fake::Node*b){return a->y<b->y;});
  assert(captions==expected&&buttons.size()==expected.size());
  for(std::size_t i=0;i<buttons.size();++i){selected_row.clear();fake::send(buttons[i],7);assert(selected_row==parsed["sliced"][i]["id"]);}
 }
 fake::del(rows_page);mapping_rows.update(mapping_state,389);
 // Loading suppression is scoped, including nested USB construction and unwinding.
 assert(!StockPreviewLoadingScope::suppress());
 // The real LVGL ABI returns 1 for success, 0 for failure. Successfully
 // queued data must survive the wrapper and be freed by the callback only.
 struct AsyncProbe{bool*destroyed;~AsyncProbe(){*destroyed=true;}};
 bool async_destroyed=false;
 auto consume_async=[](void*p){delete static_cast<AsyncProbe*>(p);};
 assert(queue_stock_async(fake::async_success,consume_async,std::unique_ptr<AsyncProbe>(new AsyncProbe{&async_destroyed})));
 assert(!async_destroyed&&fake::async_data&&fake::async_callback);
 fake::async_callback(fake::async_data);fake::async_data=nullptr;fake::async_callback=nullptr;assert(async_destroyed);
 async_destroyed=false;
 assert(!queue_stock_async(fake::async_failure,consume_async,std::unique_ptr<AsyncProbe>(new AsyncProbe{&async_destroyed})));
 assert(async_destroyed&&!fake::async_data&&!fake::async_callback);
 try {StockPreviewLoadingScope managed(true);assert(StockPreviewLoadingScope::suppress());
  {StockPreviewLoadingScope usb(false);assert(!StockPreviewLoadingScope::suppress());}
  assert(StockPreviewLoadingScope::suppress());throw 1;
 }catch(int){}
 assert(!StockPreviewLoadingScope::suppress());
 // Integrated page adapter: stock controls + reused rows + source chooser
 // submit through the shared controller, without constructing a screen shell.
 struct AdmissionBackend:Backend{unsigned submissions=0;Request request;std::string unavailable(const std::string&)const override{return "";}Receipt submit(const Request&r)override{++submissions;request=r;return {"admission-test","pending","Queued"};}} admission_backend;
 Json preview_fixture;std::ifstream preview_input(argv[1]);preview_input>>preview_fixture;preview_fixture["capabilities"]["start_print"]=true;
 App preview_app(admission_backend);preview_app.print_options(true,false,true);preview_app.update(preview_fixture);preview_app.event("file:demo-file");
 auto*page_parent=fake::make(fake::screen);auto*preserved_sidebar=fake::make(page_parent);
 StockPreviewWidgets combined;combined.page=page_parent;combined.content=fake::make(page_parent);
 static_cast<fake::Node*>(combined.content)->w=670;static_cast<fake::Node*>(combined.content)->h=400;
 combined.title=fake::make(combined.content);static_cast<fake::Node*>(combined.title)->text="Original filename";
 auto*combined_panel=fake::make(combined.content);combined_panel->w=389;
 for(auto&source:combined.sources)source=fake::make(combined_panel);
 for(auto&destination:combined.destinations)destination=fake::make(combined_panel);
 for(unsigned i=0;i<3;++i){combined.options[i]=fake::make(combined.content);fake::bind(combined.options[i],reinterpret_cast<void(*)(void*)>(preview_event),7,reinterpret_cast<void*>(i));}
 for(unsigned i=0;i<3;++i)combined.option_icons[i]=fake::make(combined.options[i]);
 auto*combined_start=fake::make(combined.content);auto*combined_cancel=fake::make(combined.content);
 auto*combined_cancel_label=fake::make(combined_cancel);combined_cancel_label->text="Cancel";
 fake::bind(combined_start,reinterpret_cast<void(*)(void*)>(preview_event),7,reinterpret_cast<void*>(4));fake::bind(combined_cancel,reinterpret_cast<void(*)(void*)>(preview_event),7,reinterpret_cast<void*>(3));
 fake::bind(combined.content,reinterpret_cast<void(*)(void*)>(preview_refresh_event),30,nullptr);
 auto*combined_thumbnail_panel=fake::make(combined.content);combined_thumbnail_panel->w=combined_thumbnail_panel->h=149;
 auto*combined_thumbnail=fake::make(combined_thumbnail_panel);combined_thumbnail->is_image=true;combined_thumbnail->image="/tmp/part-thumbnail.png";
 StockPreviewPage preview_page(preview_app);assert(preview_page.attach(combined,"stock-white.bin"));
 assert(page_parent->children.size()==2&&preserved_sidebar->live&&static_cast<fake::Node*>(combined.title)->text=="Original filename");
 fake::send(static_cast<fake::Node*>(combined.options[0]),7);
 assert(static_cast<fake::Node*>(combined.option_icons[0])->image.find("no_select.bin")!=std::string::npos);
 auto combined_tap=[&](const std::string&text){fake::Node*target=nullptr;for(const auto&node:fake::nodes)if(node->live&&node->text==text){for(auto*p=node->parent;p;p=p->parent)if(p==combined.content){target=node->parent;break;}if(target)break;}assert(target);fake::send(target,7);};
 // Enlarging the actual thumbnail preserves the original widget and selections.
 const auto before_image=preview_app.preview_state();
 fake::send(combined_thumbnail,7);
 fake::Node*stock_expanded_image=nullptr;
 for(const auto&node:fake::nodes)if(node->live&&node.get()!=combined_thumbnail&&node->image==combined_thumbnail->image)stock_expanded_image=node.get();
 assert(stock_expanded_image&&stock_expanded_image->parent->parent==combined.content);
 assert(stock_expanded_image->zoom_factor==408&&stock_expanded_image->x==16&&stock_expanded_image->y==65);
 assert(combined_thumbnail->parent==combined_thumbnail_panel&&preserved_sidebar->live);
 fake::send(static_cast<fake::Node*>(combined.options[0]),7);combined_tap("Choose source");fake::send(combined_start,7);
 assert(admission_backend.submissions==0&&preview_app.preview_state()["options"]==before_image["options"]&&!preview_app.source_picker_state().value("picker_open",false));
 combined_tap("CLOSE");assert(!stock_expanded_image->live&&combined_thumbnail->live&&preview_page.active());
 combined_thumbnail->image="/home/t13dp/TM_T1/access/screen_preview_img.bin";
 fake::send(combined_thumbnail,7);combined_tap("CLOSE");assert(combined_thumbnail->live);
 combined_thumbnail->image="/tmp/part-thumbnail.png";
 fake::decoder_fails=true;fake::send(combined_thumbnail,7);combined_tap("CLOSE");fake::decoder_fails=false;
 // The original knife control explains its backend gap without dispatching.
 const auto before_explanation=preview_app.preview_state()["options"];
 fake::send(static_cast<fake::Node*>(combined.options[1]),7);
 bool explanation_visible=false;for(const auto&node:fake::nodes)if(node->live&&node->text.find("Knife pairing is not available")!=std::string::npos)explanation_visible=true;
 assert(explanation_visible&&admission_backend.submissions==0&&preserved_sidebar->live);
 fake::send(static_cast<fake::Node*>(combined.options[0]),7);combined_tap("Choose source");
 assert(preview_app.preview_state()["options"]==before_explanation&&!preview_app.source_picker_state().value("picker_open",false));
 assert(static_cast<fake::Node*>(combined.option_icons[1])->image.find("no_select.bin")!=std::string::npos);
 combined_tap("CLOSE");
 assert(preview_page.active()&&admission_backend.submissions==0);
 // Native source picker uses the same uppercase header action and cancels
 // without changing the selected routes or dispatching a print.
 const auto before_picker_cancel=preview_app.preview_state();
 combined_tap("Choose source");assert(preview_app.source_picker_state()["picker_open"]==true);
 fake::Node*picker_cancel=nullptr;
 for(const auto&node:fake::nodes)if(node->live&&node->text=="CANCEL"&&node->parent!=combined_cancel){
  for(auto*p=node->parent;p;p=p->parent)if(p==combined.content){picker_cancel=node->parent;break;}
 }
 assert(picker_cancel);fake::send(picker_cancel,7);assert(preview_app.source_picker_state()["picker_open"]==false);
 assert(preview_app.preview_state()==before_picker_cancel&&admission_backend.submissions==0);
 for(unsigned i=0;i<6;++i){combined_tap("Choose source");assert(preview_app.source_picker_state()["picker_open"]==true);combined_tap("Slot 1");assert(preview_app.source_picker_state()["picker_open"]==false);}
 assert(preview_app.preview_state()["can_start"]==true&&!(combined_start->state&128));
 fake::send(combined_start,7);preview_page.tick();fake::send(combined_start,7);
 assert(admission_backend.submissions==1&&admission_backend.request.action=="start_print");
 assert(admission_backend.request.arguments["routes"].size()==6);
 assert(combined_start->state&128);assert(combined_cancel_label->text=="CANCEL");
 // A second stock decoration must not turn standalone Back into a print lock.
 fake::make(combined_cancel);preview_page.tick();assert(combined_cancel->state&128);
 preview_fixture["owner"]="standalone";preview_app.update(preview_fixture);preview_page.tick();
 assert(!(combined_cancel->state&128));const auto retained_start=preview_app.operation().at("id");fake::send(combined_cancel,7);
 assert(preview_app.operation().at("id")==retained_start);
 assert(!preview_page.active()&&preserved_sidebar->live);fake::del(page_parent);
 // A stock-scoped explanation must retire on parent deletion and must not
 // leave an input-blocking object behind if its callback binding fails.
 StockImagePreview detached_image;auto*image_parent=fake::make(fake::screen);auto*image_thumb=fake::make(image_parent);image_thumb->image="/tmp/file.png";
 assert(detached_image.show(image_parent,image_thumb));fake::del(image_parent);assert(!detached_image.active());detached_image.close();
 image_parent=fake::make(fake::screen);image_thumb=fake::make(image_parent);image_thumb->image="/tmp/file.png";
 fake::fail_binding=true;assert(!detached_image.show(image_parent,image_thumb));fake::fail_binding=false;
 assert(image_parent->children.size()==1&&image_thumb->live);fake::del(image_parent);
 StockNotice notice;auto*notice_parent=fake::make(fake::screen);
 auto*retained_widget=fake::make(notice_parent);retained_widget->text="Stock page";
 assert(notice.show(notice_parent,"Unavailable"));assert(notice.active());
 auto*backdrop=notice_parent->children.back();
 assert(backdrop->background_opacity==0&&(backdrop->flags&2)&&!(backdrop->flags&16));
 assert(retained_widget->live&&retained_widget->text=="Stock page");
 assert(backdrop->children.size()==1&&backdrop->children[0]->background_opacity==255);
 fake::del(notice_parent);assert(!notice.active());
 notice_parent=fake::make(fake::screen);fake::fail_binding=true;
 assert(!notice.show(notice_parent,"Unavailable"));fake::fail_binding=false;
 assert(!notice.active()&&notice_parent->children.empty());fake::del(notice_parent);
 // Confirmation is a separate explicit click; dismissal never executes it.
 {
  auto*parent=fake::make(fake::screen);parent->w=670;parent->h=400;
  fake::DeferredSizes deferred_layout;
  StockNotice confirm;int accepted=0,dismissed=0;confirm.confirmed=[&]{++accepted;};confirm.dismissed=[&]{++dismissed;};
  auto tap=[&](const char*text){fake::Node*button=nullptr;for(const auto&n:fake::nodes)if(n->live&&n->text==text)for(auto*p=n->parent;p;p=p->parent)if(p==parent)button=n->parent;assert(button);fake::send(button,7);};
  assert(confirm.show(parent,"Verify selected filament.","PRINT"));
  auto*overlay=parent->children.back();auto*card=overlay->children[0];
  assert(overlay->w==670&&overlay->h==400&&(overlay->flags&2)&&overlay->background_opacity==0);
  assert(card->w==560&&card->h==280&&card->x==55&&card->y==60);
  auto*body=card->children[0];assert(body->flags&16);
  assert(body->children[0]->font_address==MyriadPro_Regular_22&&body->children[0]->text=="Verify selected filament.");
  for(auto*button:card->children)if(button!=body){assert(button->h==56&&button->children[0]->h==40&&button->children[0]->font_address==MyriadPro_Bold_24);}
  tap("CANCEL");assert(accepted==0&&dismissed==1&&!confirm.active());
  assert(confirm.show(parent,"Verify selected filament.","PRINT"));tap("PRINT");assert(accepted==1&&dismissed==1&&!confirm.active());
  fake::del(parent);
 }
 {auto*parent=fake::make(fake::screen);auto*child=fake::make(parent);
  assert(stock_object_visible(child));fake::flag(parent,1);assert(!stock_object_visible(child));fake::unflag(parent,1);
  auto*inactive=fake::make(nullptr);auto*hidden_page=fake::make(inactive);assert(!stock_object_visible(hidden_page));
  fake::del(parent);assert(!stock_object_visible(child));fake::del(inactive);
 }
 // The Home mini owns one navigation target confined to the original button.
 auto main=fake::make(fake::screen);auto mini_button=fake::make(main);auto stock_icon=fake::make(mini_button);mini_button->w=126;mini_button->h=57;
 HomeMini mini;int home_opens=0;mini.open_filaments=[&](){++home_opens;};auto home_data=data;home_data["fresh"]=true;home_data["owner"]="openace";home_data["candidates"]=Json::array({{{"id","new"}}});
 mini.update(home_data,main,stock_icon);assert(mini_button->children.size()==2);auto mini_root=mini_button->children.back();assert(mini_root->w==126&&mini_root->h==57);assert((mini_root->flags&2)&&!(mini_root->flags&16));
 fake::send(mini_root,7);assert(home_opens==1);fake::flag(main,1);fake::send(mini_root,7);assert(home_opens==1);fake::unflag(main,1);
 auto child_count=mini_root->children.size();assert(child_count>=home_data["units"].size());mini.update(home_data,main,stock_icon);assert(mini_button->children.back()==mini_root);
 home_data["fresh"]=false;mini.update(home_data,main,stock_icon);assert(mini_button->children.size()==2&&stock_icon->live&&mini_root->live&&mini_button->children.back()==mini_root);bool stale_label=false;for(const auto&node:fake::nodes)if(node->live&&node->text=="Status\nunavailable")stale_label=true;assert(stale_label);
 home_data["fresh"]=true;mini.update(home_data,main,stock_icon);fake::del(main);mini.clear(); // stock deletion must clear owned pointers safely
 auto second=fake::make(fake::screen);auto button2=fake::make(second);auto icon2=fake::make(button2);button2->w=126;button2->h=57;mini.update(home_data,second,icon2);assert(button2->children.size()==2);mini.clear();assert(button2->children.size()==1);fake::del(second);
 // Polling survives missing/malformed procedure prose and receipt messages;
 // physical fields and the current operation state remain untouched.
 for(const auto&description:{Json(),Json(3),Json::object()}){
  Http wire;wire.ace_present=false;Port clock;wmp_openace::UiChannel channel;
  wire.extra_status["wm_material"]={{"session_id","text-session"},{"filament_sequence_protocol",1},
   {"filament_procedures",Json::array({{{"head","h0"},{"action","load"},{"source","external:h0"},{"token",std::string(64,'a')},{"description",description},{"target",220}}})},
   {"toolhead_operation",{{"id","old"},{"head","h0"},{"action","take"},{"state","failed"},{"message",Json::object()}}}};
  wire.extra_status["wm_material"]["recovery_restore_error"]=Json::object();
  wire.extra_status["wmp_recovery"]["calibration_failed"]=Json::object();
  Runtime polling(wire,clock,channel);assert(polling.initialize());polling.worker_step(clock.now);
  auto view=RuntimeReceiptTest::status(polling);assert(view.value("fresh",false));
  assert(view["procedures"][0]["description"]==""&&view["procedures"][0]["target_temperature"]=="220");
  assert(view["toolhead_operation"]["id"]=="old"&&view["toolhead_operation"]["state"]=="failed");
  assert(view["toolhead_operation"]["message"]=="toolhead_operation message text unavailable.");
  assert(!view["calibration_failed"].get<std::string>().empty()); // never pretend successful calibration
  assert(!view["recovery_restore_error"].get<std::string>().empty());
  assert(!view.value("managed_operation_hold",true));
  StubBackend sink;App ui(sink);ui.update(view);assert(ui.data().value("fresh",false));ui.render();
 }
 // Filament details are fetched only on foreground demand, and never merged
 // across a changed backend context. Older helpers retain their normal path.
 {
  Http wire;wire.ace_present=false;Port clock;wmp_openace::UiChannel channel;
  wire.extra_status["wm_material"]={{"session_id","detail-session"},{"command_generation",0},{"filament_details_protocol",1},{"filament_sequence_protocol",1},{"filament_procedures",Json::array()}};
  wire.filament_details=wire.extra_status["wm_material"];
  wire.filament_details["filament_details_ready"]=true;
  wire.filament_details["filament_procedures"]=Json::array({{{"head","h0"},{"action","load"},{"source","external:h0"},{"token",std::string(64,'a')}}});
  auto count=[&]{return std::count(wire.queries.begin(),wire.queries.end(),"/printer/wmp/filament/details");};
  Runtime r(wire,clock,channel);assert(r.initialize());r.worker_step(clock.now);
  assert(count()==0&&RuntimeReceiptTest::status(r)["procedures"].empty());
  RuntimeReceiptTest::details_demand(r,true);clock.now+=700;r.worker_step(clock.now);
  assert(count()==1&&RuntimeReceiptTest::status(r)["procedures"].size()==1);
  RuntimeReceiptTest::details_demand(r,false);clock.now+=700;r.worker_step(clock.now);
  assert(count()==1&&RuntimeReceiptTest::status(r)["procedures"].empty());
  RuntimeReceiptTest::details_demand(r,true);wire.filament_details["session_id"]="another-session";
  clock.now+=700;r.worker_step(clock.now);assert(!RuntimeReceiptTest::status(r).value("fresh",false));
 }
 // Unknown metadata must not reveal legacy stock colors. Presence transitions
 // repaint even when configured source metadata is unchanged, in head order.
 auto manual=fake::make(fake::screen);auto manual_button=fake::make(manual);auto legacy_icon=fake::make(manual_button);manual_button->w=126;manual_button->h=57;
 home_data["owner"]="standalone";home_data["sources"]=Json::array();home_data["heads"]=Json::array();
 for(int i=3;i>=0;--i){
  const auto id="h"+std::to_string(i);
  home_data["sources"].push_back({{"kind","external"},{"head",id},{"identity",{{"material","Unknown"},{"color","#ff0000"}}}});
  home_data["heads"].push_back({{"id",id},{"loaded",{{"state",i==2?"empty":i==3?"unknown":"loaded"},{"identity",Json::object()}}}});
 }
 mini.update(home_data,manual,legacy_icon);auto*manual_root=manual_button->children.back();
 assert(manual_button->children.size()==2&&manual_root!=legacy_icon&&manual_root->children.size()==4);
 for(auto*circle:manual_root->children)assert(!(circle->flags&2));
 fake::send(manual_root,7);assert(home_opens==2);
 home_data["heads"][0]["actual"]=29;home_data["heads"][0]["target"]=220;
 mini.update(home_data,manual,legacy_icon);assert(manual_button->children.back()==manual_root&&manual_root->live);
 assert(manual_root->children[0]->background_opacity==255&&manual_root->children[1]->background_opacity==255);
 assert(manual_root->children[0]->background_color==0xff888888); // Never cached red source/stock color.
 assert(manual_root->children[2]->background_opacity==0&&manual_root->children[2]->children.empty());
 assert(manual_root->children[3]->background_opacity==0&&manual_root->children[3]->children[0]->text=="?");
 auto home_children=manual_root->children;auto home_allocations=fake::nodes.size();
 home_data["heads"][1]["loaded"]["identity"]={{"color","#12ab34"}};
 home_data["heads"][1]["loaded"]["state"]="loaded"; // Head 3, reversed input order.
 mini.update(home_data,manual,legacy_icon);assert(manual_root->live&&manual_button->children.back()==manual_root);
 assert(manual_button->children.back()->children[2]->background_opacity==255);
 assert(manual_button->children.back()->children[2]->background_color==0xff12ab34);
 assert(manual_root->children==home_children&&fake::nodes.size()==home_allocations);
 home_data["fresh"]=false;mini.update(home_data,manual,legacy_icon);auto stale_allocations=fake::nodes.size();
 home_data["fresh"]=true;mini.update(home_data,manual,legacy_icon);
 assert(fake::nodes.size()==stale_allocations);for(auto*child:home_children)assert(child->live&&!(child->flags&1));
 home_data["fresh"]=false;mini.update(home_data,manual,legacy_icon);
 assert(fake::nodes.size()==stale_allocations);
 home_data["fresh"]=true;mini.update(home_data,manual,legacy_icon);

 fake::del(manual);mini.clear();

 // The overlay suppresses covered native animation widgets, owns no original
 // objects, and restores their visibility even when one is deleted first.
 {
  auto*host=fake::make(fake::screen);auto*button=fake::make(host);button->w=126;button->h=57;
  auto*original=fake::make(button);auto*already_hidden=fake::make(button);already_hidden->flags|=1;
  HomeMini overlay;overlay.update(home_data,host,original);
  assert((original->flags&1)&&(already_hidden->flags&1));
  auto*owned=button->children.back();auto allocations=fake::nodes.size();
  for(int i=0;i<100;++i)overlay.update(home_data,host,original,false);
  assert(fake::nodes.size()==allocations&&button->children.back()==owned);
  fake::unflag(original,1);overlay.update(home_data,host,original,false);assert(original->flags&1);
  fake::del(already_hidden);overlay.clear();
  assert(original->live&&!(original->flags&1)&&original->callbacks.empty());
  overlay.update(home_data,host,original);assert(original->flags&1);
  fake::del(button->children.back());assert(!(original->flags&1)&&original->callbacks.empty());
  overlay.update(home_data,host,original);fake::del(host);overlay.clear();
 }
 // Runtime production navigation must retain the stock page hierarchy.
 Port port;Http http;std::ifstream raw_input(argv[2]);raw_input>>http.ace;
 // Reset refusal queues only presentation, retains its modal during sync, and
 // never unhides the stock top layer or reaches a backend command transport.
 {
  struct NoCommands: wmp_openace::HttpPort {
   std::string get(const std::string&)override{assert(false);return "";}
   std::string post(const std::string&,const std::string&)override{assert(false);return "";}
  }no_commands;
  wmp_openace::UiChannel channel;Runtime runtime(no_commands,port,channel);
  const auto original_flags=fake::top->flags;fake::top->flags|=1;
  const auto before=fake::sys->children.size();runtime.request_factory_reset_refusal();
  assert(fake::sys->children.size()==before);runtime.gui_step();
  assert(fake::sys->children.size()==before+1);auto*root=fake::sys->children.back();
  auto*panel=root->children[0];auto*close=panel->children[1];
  assert(panel->children[0]->text.find("first uninstall WM+ with the installer")!=std::string::npos);
  assert(close->children[0]->text=="CLOSE");
  assert(panel->background_opacity==255&&panel->background_color==0xff3c3f43U);
  assert(close->y==6&&close->background_opacity==0&&panel->children[0]->y>close->y+close->h);
  runtime.request_factory_reset_refusal();runtime.gui_step();
  assert(fake::sys->children.back()==root&&fake::sys->children.size()==before+1);
  assert(fake::top->flags&1);fake::send(close,7);assert(!root->live);
  runtime.gui_step();assert(fake::sys->children.size()==before);
  runtime.request_factory_command_refusal();assert(fake::sys->children.size()==before);
  runtime.gui_step();root=fake::sys->children.back();panel=root->children[0];close=panel->children[1];
  assert(panel->children[0]->text.find("No trigger command was sent")!=std::string::npos);
  assert(fake::top->flags&1);fake::send(close,7);assert(!root->live);
  fake::top->flags=original_flags;
 }
 // Runtime binds the real worker to retained USB widgets; review is explicit.
 {
  struct CopyPort: wmp_openace::HttpPort {
   unsigned requests=0;
   std::string get(const std::string&)override{assert(false);return "";}
   std::string post(const std::string&path,const std::string&body)override{
    const bool dir=path=="/server/files/directory";assert(dir||path=="/server/files/copy");++requests;
    auto args=Json::parse(body);
    return Json{{"result",{{"action",dir?"create_dir":"create_file"},{"item",{{"root","gcodes"},{"path",args.at(dir?"path":"dest").get<std::string>().substr(7)},{"size",12}}}}}}.dump();
   }
  }copy_http;
  char directory[]="/tmp/wmp-native-usb-XXXXXX";assert(::mkdtemp(directory));
  {std::ofstream file(std::string(directory)+"/part.gcode");file<<"G1 X1\nG1 X2\n";}
  wmp_openace::UiChannel channel;Runtime runtime(http,port,channel);runtime.enable_usb(copy_http,directory);
  auto ready=data;ready["fresh"]=true;ready["owner"]="standalone";ready["job"]={{"state","idle"}};
  ready["fresh"]=false;ready["job"]={{"state","printing"}};ready["revision"]="";
  RuntimeReceiptTest::usb_status(runtime,ready);
  unsigned reviews=0;runtime.set_local_preview([&](void*,const std::string&path){++reviews;assert(path.find("WM_USB_")==0);});
  assert(runtime.prepare_usb_preview("part.gcode"));
  auto usb=make_preview();fake::bind(usb.content,reinterpret_cast<void(*)(void*)>(preview_refresh_event),30,nullptr);
  assert(StockPreviewInventory::resolve(usb));auto*start=static_cast<fake::Node*>(usb.start);auto*cancel=static_cast<fake::Node*>(usb.cancel);
  fake::make(start)->text="Start";fake::make(cancel)->text="Cancel";assert(runtime.usb_preview_created(usb));
  auto wait_state=[&](const std::string&state){auto until=std::chrono::steady_clock::now()+std::chrono::seconds(3);
   while(std::chrono::steady_clock::now()<until){if(RuntimeReceiptTest::usb_result(runtime).value("state","")==state)return;std::this_thread::yield();}assert(false);};
  wait_state("ready");RuntimeReceiptTest::usb_tick(runtime);assert(!(start->state&128));
  fake::send(start,7);wait_state("copied");RuntimeReceiptTest::usb_tick(runtime);assert(copy_http.requests==2&&reviews==0);
  fake::send(start,7);assert(reviews==1);fake::send(cancel,7);assert(!runtime.active());
  RuntimeReceiptTest::usb_tick(runtime);assert(reviews==1);fake::del(usb.page);
  ::unlink((std::string(directory)+"/part.gcode").c_str());::rmdir(directory);
 }
 // Exercise the production stock-preview handoff through Runtime. Metadata
 // arrives after attachment; it must populate the retained content without
 // allocating a replacement shell or navigating back after the user leaves.
 {
  wmp_openace::UiChannel native_channel;Runtime native_runtime(http,port,native_channel);
  assert(native_runtime.initialize());
  const std::string native_path="folder/native.gcode";
  assert(native_runtime.prepare_stock_preview(native_path,false,true,true));
  auto*stock_page=fake::make(fake::screen);auto*sidebar=fake::make(stock_page);
  StockPreviewWidgets native_widgets;native_widgets.page=stock_page;native_widgets.content=fake::make(stock_page);
  auto*content=static_cast<fake::Node*>(native_widgets.content);content->w=670;content->h=400;
  native_widgets.title=fake::make(content);static_cast<fake::Node*>(native_widgets.title)->text=native_path;
  auto*panel=fake::make(content);panel->w=389;
  for(auto&source:native_widgets.sources)source=fake::make(panel);
  for(auto&destination:native_widgets.destinations)destination=fake::make(panel);
  for(unsigned i=0;i<3;++i){native_widgets.options[i]=fake::make(content);fake::bind(native_widgets.options[i],reinterpret_cast<void(*)(void*)>(preview_event),7,reinterpret_cast<void*>(i));}
  auto*start=fake::make(content);auto*cancel=fake::make(content);fake::make(cancel)->text="Cancel";
  fake::bind(start,reinterpret_cast<void(*)(void*)>(preview_event),7,reinterpret_cast<void*>(4));
  fake::bind(cancel,reinterpret_cast<void(*)(void*)>(preview_event),7,reinterpret_cast<void*>(3));
  fake::bind(content,reinterpret_cast<void(*)(void*)>(preview_refresh_event),30,nullptr);
  assert(native_runtime.stock_preview_created(native_widgets,"stock-white.bin"));
  assert(native_runtime.active());
  bool inline_loading=false;for(const auto&node:fake::nodes)if(node->live&&node->parent==content&&node->text=="Loading file information...")inline_loading=true;
  assert(inline_loading);
  auto native_data=preview_fixture;native_data["files"][0]["id"]=native_path;
  auto loading=native_data;loading["revision"]="initial-metadata-loading";
  loading["files"][0]["metadata_loading"]=true;loading["files"][0]["sliced"]=Json::array();
  RuntimeReceiptTest::adoption_status(native_runtime,loading,http.ace,port.now);
  native_runtime.gui_step();
  bool still_loading=false;for(const auto&node:fake::nodes)if(node->live&&node->parent==content&&node->text=="Loading file information...")still_loading=true;
  assert(still_loading);
  RuntimeReceiptTest::adoption_status(native_runtime,native_data,http.ace,port.now);
  native_runtime.gui_step();
  assert(stock_page->children.size()==2&&sidebar->live&&content->live);
  auto preview_state=RuntimeReceiptTest::preview(native_runtime);
  assert(preview_state["rows"].size()==6);
  assert(preview_state.value("reason","").find("Configuration changed")==std::string::npos);
  assert(preview_state["options"]["leveling"]==false&&preview_state["options"]["timelapse"]==true);
  assert(fake::screen->children.size()==1); // only the original stock page
  fake::send(cancel,7);assert(!native_runtime.active()&&sidebar->live&&!content->live);
  native_runtime.gui_step();assert(!native_runtime.active()&&stock_page->children.size()==1);
  assert(!RuntimeReceiptTest::preview_session(native_runtime));
  fake::del(stock_page);
 }
 wmp_openace::UiChannel channel;Runtime runtime(http,port,channel);assert(runtime.initialize());runtime.worker_step(1000);
 assert(http.queries.size()==2);
 assert(http.queries[0]=="/printer/objects/list");
 for(const auto*field:{"material_change_prompt","manual_flow","unit_discovery","unit_settings"})assert(http.queries[1].find(field)!=std::string::npos);
 std::vector<std::string> handoffs;runtime.set_stock_navigation([&](const char*name){handoffs.push_back(name);});
 // Retired preview ID and malformed IDs must neither allocate an opaque shell
 // nor hand off to a guessed stock page. They cannot overwrite a valid request.
 const auto no_shell_allocations=fake::nodes.size();
 for(int request:{8,5,6,13,99,-2}){runtime.request(request);runtime.gui_step();assert(!runtime.active());}
 assert(fake::nodes.size()==no_shell_allocations&&handoffs.empty());
 runtime.request(7);runtime.request(8);runtime.gui_step();assert(handoffs.size()==1&&handoffs.back()=="filament_page");
 // Both Home tool entries and ACE Filament navigation hand off to stock pages.
 runtime.request(1);runtime.gui_step();assert(!runtime.active()&&handoffs.back()=="filament_page");
 const auto before_ace_navigation=handoffs.size();runtime.request(7);runtime.gui_step();
 assert(!runtime.active()&&handoffs.size()==before_ace_navigation+1&&fake::screen->children.empty());

 // Reopening the same pathname must fetch again inside the normal five-second
 // cache window. A lookup completed for an earlier review cannot seed the next.
 {
  Http wire;wire.ace=http.ace;Port clock;wmp_openace::UiChannel c;
  Runtime r(wire,clock,c);assert(r.initialize());
  auto count_metadata=[&](){unsigned count=0;for(const auto&q:wire.queries)if(q.find("/server/files/metadata?")==0)++count;return count;};
  assert(r.prepare_stock_preview("folder/part.gcode",false,false,true));
  r.worker_step(clock.now);assert(count_metadata()==1);
  clock.now+=700;r.worker_step(clock.now);
  assert(!RuntimeReceiptTest::status(r)["files"][0].value("metadata_loading",true));
  assert(r.prepare_stock_preview("folder/part.gcode",false,false,true));
  clock.now+=700;r.worker_step(clock.now);assert(count_metadata()==2);
  assert(RuntimeReceiptTest::status(r)["files"][0].value("metadata_loading",false));
  clock.now+=700;r.worker_step(clock.now);
  assert(!RuntimeReceiptTest::status(r)["files"][0].value("metadata_loading",true));
  // Simulate navigation during a metadata response, on the same pathname.
  assert(r.prepare_stock_preview("folder/part.gcode",false,false,true));
  wire.on_get=[&](const std::string&q){if(q.find("/server/files/metadata?")==0){assert(r.prepare_stock_preview("folder/part.gcode",false,false,true));}};
  clock.now+=700;r.worker_step(clock.now);assert(count_metadata()==3);
  wire.on_get=nullptr;
  clock.now+=700;r.worker_step(clock.now);assert(count_metadata()==4);
  assert(RuntimeReceiptTest::status(r)["files"][0].value("metadata_loading",false));
  clock.now+=700;r.worker_step(clock.now);
  assert(!RuntimeReceiptTest::status(r)["files"][0].value("metadata_loading",true));
 }

 // Standalone Filament must call the real page constructor path, not create
 // another opaque replacement root. This test also rejects command dispatch.
 Http standalone_http;standalone_http.ace_present=false;
 wmp_openace::UiChannel standalone_channel;
 Runtime standalone_runtime(standalone_http,port,standalone_channel);
 assert(standalone_runtime.initialize());unsigned stock_calls=0;
 auto retained=fake::make(fake::screen);retained->text="stock sidebar";
 const auto initial_children=fake::screen->children.size();
 standalone_runtime.set_stock_navigation([&](const char*name){assert(std::string(name)=="filament_page");++stock_calls;});
 const auto stale_navigation_before=wmp_openace::screen_diagnostics().navigation_stale.load();
 const auto navigation_before=wmp_openace::screen_diagnostics().navigation_requests.load();
 standalone_runtime.request(7);standalone_runtime.gui_step(); // no ownership observation yet
 assert(stock_calls==0&&!standalone_runtime.active()&&fake::screen->children.size()==initial_children);
 assert(wmp_openace::screen_diagnostics().navigation_stale.load()==stale_navigation_before+1);
 assert(wmp_openace::screen_diagnostics().navigation_requests.load()==navigation_before+1);
 assert(wmp_openace::screen_diagnostics().navigation_page.load()==7);
 assert(wmp_openace::screen_diagnostics().navigation_at.load()==port.now);
 standalone_runtime.gui_step();RuntimeReceiptTest::close_maintenance_notice(standalone_runtime);
 port.now=4200;standalone_runtime.worker_step(4200);
 assert(standalone_http.queries.size()==2);
 for(const auto&q:standalone_http.queries){
  assert(q.find("openace=")==std::string::npos);
  assert(q.find("configfile")==std::string::npos&&q.find("save_variables")==std::string::npos);
 }
 standalone_runtime.request(7);standalone_runtime.gui_step();
 assert(stock_calls==1&&!standalone_runtime.active());
 assert(fake::screen->children.size()==initial_children&&retained->live);
 // A new status reply is fresh even when earlier polling work was slow.
 // It must still expire two seconds after receipt, and failed queries fail closed.
 {
  Http slow;slow.ace_present=false;Port clock;clock.now=10000;
  wmp_openace::UiChannel c;Runtime r(slow,clock,c);
  slow.on_get=[&](const std::string&){clock.now+=800;};
  r.worker_step(10000);assert(clock.now==11600);
  assert(RuntimeReceiptTest::status(r).value("fresh",false));
  clock.now+=2001;assert(!RuntimeReceiptTest::status(r).value("fresh",false));
  const auto queued=c.enqueue("OPENACE_CONFIRM_CHANGE TOOL=0 CONFIRM=1 EXPECT_CONTEXT="+std::string(64,'a'));assert(queued);
  const auto failures=wmp_openace::screen_diagnostics().status_failures.load();
  slow.on_get=[&](const std::string&){clock.now+=1000;throw wmp_openace::HttpFailure(wmp_openace::HttpFailureKind::Deadline,"private diagnostic detail");};
  r.worker_step(clock.now);assert(!RuntimeReceiptTest::status(r).value("fresh",false));
  assert(c.latest()->delivery.ticket==queued&&c.latest()->delivery.outcome==wmp_openace::Delivery::NotSent);
  assert(wmp_openace::screen_diagnostics().status_failures.load()==failures+1);
  assert(wmp_openace::screen_diagnostics().status_failure_stage.load()==2);
  assert(wmp_openace::screen_diagnostics().status_failure_kind.load()==1);
  assert(wmp_openace::screen_diagnostics().status_failure_poll_ms.load()==1000);
  slow.queries.clear();clock.now+=1000;slow.on_get={};r.worker_step(clock.now);
  assert(RuntimeReceiptTest::status(r).value("fresh",false));
  assert(slow.queries.size()==1&&slow.queries.front().find("/printer/objects/query?")==0);
 }

 // Without a ready helper session, periodic discovery still finds a newly
 // installed helper even if its brief restart state was not sampled.
 {
  Http wire;wire.ace_present=false;Port clock;clock.now=10000;
  wmp_openace::UiChannel c;Runtime r(wire,clock,c);r.worker_step(clock.now);
  assert(wire.queries.size()==2);wire.queries.clear();
  clock.now+=700;r.worker_step(clock.now);assert(wire.queries.size()==1);
  wire.queries.clear();clock.now+=30000;r.worker_step(clock.now);
  assert(wire.queries.size()==2&&wire.queries[0]=="/printer/objects/list");
 }
 // Cache configuration discovery only. Every poll still requests live status,
 // and errors/session/owner changes must invalidate discovery before dispatch.
 {
  Http wire;wire.ace_present=false;Port clock;clock.now=10000;
  wire.extra_status={{"wm_material",{{"session_id","first"},{"afc_metadata",{{"owner","standalone"}}}}}};
  wmp_openace::UiChannel c;Runtime r(wire,clock,c);r.worker_step(clock.now);
  assert(wire.queries.size()==2);wire.queries.clear();
  clock.now+=700;r.worker_step(clock.now);
  assert(wire.queries.size()==1&&wire.queries[0].find("/printer/objects/query?")==0);
  assert(RuntimeReceiptTest::status(r).value("fresh",false));
  for(auto kind:{wmp_openace::HttpFailureKind::Deadline,wmp_openace::HttpFailureKind::Connection,wmp_openace::HttpFailureKind::Io}){
   wire.on_get=[kind](const std::string&){throw wmp_openace::HttpFailure(kind,"transport unavailable");};
   clock.now+=700;r.worker_step(clock.now);assert(!RuntimeReceiptTest::status(r).value("fresh",false));
   wire.on_get={};wire.queries.clear();clock.now+=700;r.worker_step(clock.now);
   assert(wire.queries.size()==1&&wire.queries[0].find("/printer/objects/query?")==0);
   assert(RuntimeReceiptTest::status(r).value("fresh",false));
  }
  wire.queries.clear();clock.now+=30000;r.worker_step(clock.now);
  assert(wire.queries.size()==1&&wire.queries[0].find("/printer/objects/query?")==0);
  wire.queries.clear();clock.now+=300000;r.worker_step(clock.now);
  assert(wire.queries.size()==1&&RuntimeReceiptTest::status(r).value("fresh",false));
  wire.extra_status["wm_material"]["session_id"]="restarted";
  wire.queries.clear();clock.now+=700;r.worker_step(clock.now);
  assert(RuntimeReceiptTest::status(r).value("fresh",false));
  assert(wire.queries.size()==3&&wire.queries[1]=="/printer/objects/list");
  assert(RuntimeReceiptTest::status(r).value("session","")=="restarted");
  wire.queries.clear();clock.now+=700;r.worker_step(clock.now);
  assert(wire.queries.size()==1&&RuntimeReceiptTest::status(r).value("fresh",false));
  // A failed rediscovery still invalidates current status; no retry loop.
  wire.extra_status["wm_material"]["session_id"]="again";
  wire.on_get=[](const std::string&path){if(path=="/printer/objects/list")throw std::runtime_error("discovery failed");};
  wire.queries.clear();clock.now+=700;r.worker_step(clock.now);
  assert(!RuntimeReceiptTest::status(r).value("fresh",false)&&wire.queries.size()==2);
  wire.on_get={};wire.queries.clear();clock.now+=700;r.worker_step(clock.now);
  assert(wire.queries.size()==2&&RuntimeReceiptTest::status(r).value("fresh",false));
  wire.extra_status["wm_material"]["afc_metadata"]["owner"]="openace";
  wire.queries.clear();clock.now+=700;r.worker_step(clock.now);
  assert(!RuntimeReceiptTest::status(r).value("fresh",false));
  wire.ace_present=true;wire.ace={{"session_id",42}};wire.queries.clear();clock.now+=700;r.worker_step(clock.now);
  assert(wire.queries.size()==2&&wire.queries[1].find("openace=")!=std::string::npos);
  assert(RuntimeReceiptTest::status(r).value("fresh",false));
  wire.ace_present=false;wire.extra_status["wm_material"]["afc_metadata"]["owner"]="standalone";
  wire.queries.clear();clock.now+=700;r.worker_step(clock.now);
  assert(!RuntimeReceiptTest::status(r).value("fresh",false));
  wire.queries.clear();clock.now+=700;r.worker_step(clock.now);
  assert(wire.queries.size()==2&&wire.queries[1].find("openace=")==std::string::npos);
  assert(RuntimeReceiptTest::status(r).value("fresh",false));
  wire.on_get=[](const std::string&){throw std::runtime_error("status transport failed");};
  clock.now+=700;r.worker_step(clock.now);
  assert(!RuntimeReceiptTest::status(r).value("fresh",false));
  wire.on_get={};wire.queries.clear();clock.now+=700;r.worker_step(clock.now);
  assert(wire.queries.size()==2&&RuntimeReceiptTest::status(r).value("fresh",false));
  wire.extra_status["webhooks"]={{"state","startup"}};
  clock.now+=700;r.worker_step(clock.now);
  wire.extra_status["webhooks"]={{"state","ready"}};
  wire.queries.clear();clock.now+=700;r.worker_step(clock.now);
  assert(wire.queries.size()==2&&RuntimeReceiptTest::status(r).value("fresh",false));
 }

 // Leaving a preview must stop its periodic metadata/roots requests. Hidden
 // file work must not consume the printer-status freshness budget forever.
 {
  Http wire;wire.ace_present=false;Port clock;clock.now=10000;
  wmp_openace::UiChannel c;Runtime r(wire,clock,c);
  assert(r.prepare_stock_preview("folder/part.gcode",false,false,true));
  r.worker_step(clock.now);
  bool metadata=false;for(const auto&q:wire.queries)if(q.find("/server/files/metadata?")==0)metadata=true;
  assert(metadata);
  RuntimeReceiptTest::preview_tick(r); // closed page, no outstanding submission
  assert(!RuntimeReceiptTest::preview_session(r));
  wire.queries.clear();clock.now+=6000;r.worker_step(clock.now);
  for(const auto&q:wire.queries)assert(q.find("/server/files/")!=0);
  assert(RuntimeReceiptTest::status(r).value("fresh",false));
 }

 // Preview I/O must follow status publication, including the first lookup.
 // Cached metadata becomes visible on the next poll without renewing the age
 // of printer evidence when a file request takes too long.
 {
  Http wire;wire.ace_present=false;Port clock;clock.now=10000;
  wmp_openace::UiChannel c;Runtime r(wire,clock,c);r.worker_step(clock.now);
  assert(r.prepare_stock_preview("folder/part.gcode",false,false,true));
  clock.now+=2001;bool looked_up=false;
  wire.on_get=[&](const std::string&q){if(q.find("/server/files/metadata?")!=0)return;
   looked_up=true;assert(RuntimeReceiptTest::status(r).value("fresh",false));
   clock.now+=2001;assert(!RuntimeReceiptTest::status(r).value("fresh",false));
  };
  r.worker_step(clock.now);assert(looked_up);
  assert(!RuntimeReceiptTest::status(r).value("fresh",false));
  wire.on_get={};r.worker_step(clock.now);
  auto current=RuntimeReceiptTest::status(r);assert(current.value("fresh",false));
  assert(current.at("files").at(0).at("sliced").size()==2);
  clock.now+=5000;wire.on_get=[&](const std::string&q){if(q.find("/server/files/metadata?")!=0)return;
   const auto during=RuntimeReceiptTest::status(r);assert(during.value("fresh",false));
   assert(during.at("files").at(0).at("sliced").size()==2);
   throw std::runtime_error("file lookup timeout");
  };
  r.worker_step(clock.now);assert(RuntimeReceiptTest::status(r).value("fresh",false));
  clock.now+=700;wire.on_get={};r.worker_step(clock.now);
  current=RuntimeReceiptTest::status(r);assert(current.value("fresh",false));
  assert(!current.at("files").at(0).value("metadata_error","").empty());
 }

 // Missing metadata is recoverable through read-only file inspection.
 {
  struct Missing:Http{std::string root;std::string get(const std::string&path)override{
   if(path.find("/server/files/metadata?")==0)throw std::runtime_error("No slicer metadata");
   if(path=="/server/files/roots")return Json{{"result",Json::array({{{"name","gcodes"},{"path",root}}})}}.dump();
   return Http::get(path);
  }} wire;wire.ace_present=false;wire.extra_status={{"wm_material",{{"print_material_confirmation_protocol",1}}}};
  char directory[]="/tmp/wmp-native-inspect-XXXXXX";assert(::mkdtemp(directory));wire.root=directory;
  const auto path=wire.root+"/no-metadata.gcode";{std::ofstream file(path);file<<"START_PRINT INITIAL_TOOL=0\nG1 X10\n";}
  Port clock;clock.now=10000;wmp_openace::UiChannel c;Runtime r(wire,clock,c);
  assert(r.prepare_stock_preview("no-metadata.gcode",false,false,true));r.worker_step(clock.now);clock.now+=700;r.worker_step(clock.now);
  const auto file=RuntimeReceiptTest::status(r).at("files").at(0);assert(file.value("metadata_error","").empty());
  assert(file.at("sliced").size()==1&&file["sliced"][0]["id"]=="0"&&file["sliced"][0]["material"]=="Unknown");
  assert(file["file_identity"]["size"].get<int>()>0);::unlink(path.c_str());::rmdir(directory);
 }

 // Worker shutdown cancels queued work, rejects new work, and joins the one
 // already executing task without dropping its completion.
 {
  std::mutex gate;std::condition_variable wake;bool entered=false,release=false;int finished=0,queued=0;
  {BoundedWorker worker;assert(worker.submit(0,[&]{std::unique_lock<std::mutex>lock(gate);entered=true;wake.notify_all();wake.wait(lock,[&]{return release;});++finished;}));
   {std::unique_lock<std::mutex>lock(gate);assert(wake.wait_for(lock,std::chrono::seconds(3),[&]{return entered;}));}
   assert(worker.submit(1,[&]{++queued;}));assert(worker.submit(2,[&]{++queued;}));worker.request_stop();assert(!worker.submit(0,[&]{++queued;}));
   {std::lock_guard<std::mutex>lock(gate);release=true;}wake.notify_all();
  }
  assert(finished==1&&queued==0);
 }

 // Production background transports isolate blocked command and preview work.
 {
  struct Delayed:Http{
   std::mutex gate;std::condition_variable changed;bool entered=false,released=false,block_get=false;std::vector<std::string>scripts;
   std::string post(const std::string&,const std::string&body)override{
    std::unique_lock<std::mutex>lock(gate);scripts.push_back(Json::parse(body).at("script"));entered=true;changed.notify_all();changed.wait(lock,[&]{return released;});return "{\"result\":\"ok\"}";
   }
   std::string get(const std::string&path)override{if(block_get&&path.find("/server/files/metadata?")==0){std::unique_lock<std::mutex>lock(gate);entered=true;changed.notify_all();changed.wait(lock,[&]{return released;});}return Http::get(path);}
   void wait(){std::unique_lock<std::mutex>lock(gate);assert(changed.wait_for(lock,std::chrono::seconds(3),[&]{return entered;}));}
   void release(){std::lock_guard<std::mutex>lock(gate);released=true;changed.notify_all();}
  } commands,preview,off;
  preview.block_get=true;off.released=true;
  Http status;status.ace_present=false;Port clock;clock.now=10000;
  status.extra_status={{"wm_material",{{"session_id","before"},{"heater_settings",{{"extruder",{{"min_temp",0},{"max_temp",290}}}}}}}};
  wmp_openace::UiChannel c;Runtime r(status,clock,c);r.worker_step(clock.now);
  clock.now+=2855;assert(RuntimeReceiptTest::status(r).value("status_age_ms",0)==2855);assert(!RuntimeReceiptTest::status(r).value("fresh",true));assert(RuntimeReceiptTest::status(r).value("display_fresh",false));
  clock.now+=1146;assert(!RuntimeReceiptTest::status(r).value("display_fresh",true));r.worker_step(clock.now);
  r.enable_background(commands,preview,off);
  assert(RuntimeReceiptTest::queue_temperature(r).state=="pending");
  clock.now+=700;r.worker_step(clock.now);commands.wait();
  assert(r.prepare_stock_preview("folder/first.gcode",false,false,true));clock.now+=700;r.worker_step(clock.now);preview.wait();
  for(int i=0;i<5;++i){clock.now+=700;r.worker_step(clock.now);assert(RuntimeReceiptTest::status(r).value("fresh",false));}
  assert(commands.scripts.size()==1);
  // Old status/history and an occupied command connection never prevent Off.
  clock.now+=5000;assert(!RuntimeReceiptTest::status(r).value("fresh",false));
  assert(RuntimeReceiptTest::heater_off(r,2));off.wait();assert(off.scripts[0]=="SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=0");
  auto context=RuntimeReceiptTest::status(r);context["fresh"]=true;RuntimeReceiptTest::pending_app(r,context);
  assert(r.prepare_stock_preview("folder/second.gcode",false,false,true));
  assert(RuntimeReceiptTest::app_operation(r)["id"]=="previous-start");
  status.extra_status["wm_material"]["session_id"]="after";clock.now+=700;r.worker_step(clock.now);
  assert(!RuntimeReceiptTest::app_preview(r).value("can_start",true));RuntimeReceiptTest::preview_back(r);
  assert(r.prepare_stock_preview("folder/third.gcode",false,false,true));
  assert(RuntimeReceiptTest::app_operation(r)["id"]=="previous-start");
  commands.release();preview.release();assert(RuntimeReceiptTest::finish_preview(r)!="folder/first.gcode");
 }

 // Publish received status before waiting on a command RPC. A blocked command
 // must not conceal a fresh observation, nor extend its two-second lifetime.
 {
  Http wire;wire.ace_present=false;Port clock;clock.now=10000;
  wire.extra_status={{"wm_material",{{"heater_settings",{{"extruder",{{"min_temp",0},{"max_temp",290}}}}}}}};
  wmp_openace::UiChannel c;Runtime r(wire,clock,c);r.worker_step(clock.now);
  assert(RuntimeReceiptTest::queue_temperature(r).state=="pending");
  clock.now+=2001;wire.on_get=[&](const std::string&){clock.now+=100;};
  bool posted=false;wire.on_post=[&]{posted=true;
   assert(RuntimeReceiptTest::status(r).value("fresh",false));
   clock.now+=2001;assert(!RuntimeReceiptTest::status(r).value("fresh",false));
  };
  r.worker_step(clock.now);assert(posted);
  assert(!RuntimeReceiptTest::status(r).value("fresh",false));
 }

 // Opening a local draft leaves the hidden Toolhead receipt intact. Saving
 // is still serialized by the backend; exercise the reverse direction too.
 RuntimeReceiptTest::pending(standalone_runtime,true,"step-old");
 // Backend completion not yet published: the old pending ID must prevent
 // the opposite screen from starting an edit despite an otherwise idle view.
 assert(standalone_runtime.begin_stock_edit(0,"brand"));
 assert(RuntimeReceiptTest::pending(standalone_runtime,true));
 RuntimeReceiptTest::observe(standalone_runtime,"step-old");
 standalone_runtime.request(7);standalone_runtime.gui_step();
 assert(!RuntimeReceiptTest::pending(standalone_runtime,true));
 RuntimeReceiptTest::pending(standalone_runtime,false,"identity-new");
 RuntimeReceiptTest::observe(standalone_runtime,"identity-new");
 standalone_runtime.request(1);standalone_runtime.gui_step();
 assert(!RuntimeReceiptTest::pending(standalone_runtime,false));
 RuntimeReceiptTest::pending(standalone_runtime,true,"step-new");
 RuntimeReceiptTest::observe(standalone_runtime,"step-new");
 standalone_runtime.request(7);standalone_runtime.gui_step();
 assert(!RuntimeReceiptTest::pending(standalone_runtime,true));
 const auto before_identity_page=stock_calls;
 standalone_runtime.request(11);standalone_runtime.gui_step();
 assert(stock_calls==before_identity_page); // fixture has only physical h0
 standalone_runtime.request(9);standalone_runtime.gui_step();
 assert(stock_calls==before_identity_page+1&&!standalone_runtime.active());
 assert(fake::screen->children.size()==initial_children);
 const auto calls_before_stale=stock_calls;
 port.now=7201;standalone_runtime.request(7);standalone_runtime.gui_step(); // stale observation
 assert(stock_calls==calls_before_stale+1&&!standalone_runtime.active()&&fake::screen->children.size()==initial_children); // Read-only known-owner page remains reachable.

 // Explicit routing fixture for adoption/identity checks below. This used
 // to be initialized incidentally by the removed prototype-preview test.
 http.ace["management"]["units"]={{"ace0",Json::object()}};
 http.ace["management"]["source_settings"]={{"ace0:0",Json::object()}};
 http.ace["default_tool_map"]={{"0",{{"head","h0"},{"unit","ace0"},{"slot",0}}}};
 // Native adoption confirmation reaches the typed backend queue, never HTTP.
 Http adoption_http;adoption_http.ace=http.ace;
 const auto device_context=std::string(64,'c');
 adoption_http.ace["management"]["capabilities"]["unit_add_expect_context"]=1;
 adoption_http.ace["management"]["add_candidates"]=Json::array({{{"expect_context",device_context},{"usb_serial","native-test-device"}}});
 wmp_openace::UiChannel adoption_channel;Runtime adoption_runtime(adoption_http,port,adoption_channel);
 auto adoption_status=project(Json{{"webhooks",{{"state","ready"}}},{"print_stats",{{"state","standby"}}}},adoption_http.ace,true,"wm-screen-process");
 assert(adoption_status["capabilities"]["adopt"]==true);const auto candidate=adoption_status["candidates"][0];
 RuntimeReceiptTest::adoption_status(adoption_runtime,adoption_status,adoption_http.ace,port.now);
 assert(RuntimeReceiptTest::adopt(adoption_runtime,candidate,adoption_status).state=="pending");
 auto adoption_request=adoption_channel.take();assert(adoption_request.request["action"]=="unit_add");
 assert(adoption_request.command.find("EXPECT_CONTEXT="+device_context)!=std::string::npos);adoption_channel.settle(adoption_request.ticket);
 auto changed_adoption=adoption_status;changed_adoption["job"]["state"]="paused";
 RuntimeReceiptTest::adoption_status(adoption_runtime,changed_adoption,adoption_http.ace,port.now);
 assert(RuntimeReceiptTest::adopt(adoption_runtime,candidate,adoption_status).state=="refused");
 changed_adoption=adoption_status;changed_adoption["revision"]="different";
 RuntimeReceiptTest::adoption_status(adoption_runtime,changed_adoption,adoption_http.ace,port.now);
 assert(RuntimeReceiptTest::adopt(adoption_runtime,candidate,adoption_status).state=="refused");

 // Exercise the production save/readback-to-Load continuation with actual
 // runtime/backend admission. No worker runs, so no printer RPC is issued.
 for(const auto*scenario:{"unchanged","cancelled","new_pause","file_position","session","identity_not_read_back","calibration","recovery_hold"}){
  Http load_http;wmp_openace::UiChannel load_channel;Runtime load_runtime(load_http,port,load_channel);
  auto*page=fake::make(fake::screen);auto*content=fake::make(page);content->w=670;content->h=340;
  StockFilamentWidgets widgets;widgets.content=content;widgets.count=4;
  for(auto&slot:widgets.slots){slot.card=fake::make(content);slot.number=fake::make(slot.card);slot.colour=fake::make(slot.card);slot.material=fake::make(slot.card);slot.material_label=fake::make(slot.material);}
  RuntimeReceiptTest::attach(load_runtime,widgets,page,fake::make(content),fake::make(content));
  Json origin={{"fresh",true},{"owner","standalone"},{"session","paused-test"},{"revision","rev"},
   {"job",{{"state","paused"}}},{"capabilities",{{"load",true}}},
   {"heads",Json::array({{{"id","h2"},{"loaded",{{"state","empty"}}}}})},
   {"sources",Json::array({{{"id","external:h2"},{"kind","external"},{"head","h2"},{"available",true},
    {"identity",{{"brand","Sunlu"},{"material","PLA"},{"color","#ffaaaa"}}}}})},
   {"procedures",Json::array({{{"head","h2"},{"source","external:h2"},{"action","load"},{"revision","rev"},{"token",std::string(64,'a')},{"description","Load and purge Head 3"}}})},
   {"paused_filament",{{"available",true},{"head","h2"},{"origin",{{"head","h2"},{"session","paused-test"},{"id",std::string(32,'a')},{"file_position",120}}}}}};
  auto current=origin;const std::string scenario_name=scenario;
  if(scenario_name=="cancelled")current["job"]["state"]="idle";
  if(scenario_name=="new_pause")current["paused_filament"]["origin"]["id"]=std::string(32,'b');
  if(scenario_name=="file_position")current["paused_filament"]["origin"]["file_position"]=121;
  if(scenario_name=="session")current["session"]="restarted";
  if(scenario_name=="identity_not_read_back")current["sources"][0]["identity"]["color"]="#aaaaaa";
  if(scenario_name=="calibration")current["calibration_active"]=true;
  if(scenario_name=="recovery_hold")current["managed_operation_hold"]=true;
  RuntimeReceiptTest::saved_load(load_runtime,origin,current);
  if(scenario_name=="unchanged"){
   assert(RuntimeReceiptTest::procedure_active(load_runtime));
   const auto receipt=RuntimeReceiptTest::tool_receipt(load_runtime);assert(receipt.empty()); // Review only, no automatic Load.
   RuntimeReceiptTest::update_identity(load_runtime);assert(RuntimeReceiptTest::tool_receipt(load_runtime)==receipt);
  }else{
   assert(!RuntimeReceiptTest::procedure_active(load_runtime));
   assert(RuntimeReceiptTest::tool_receipt(load_runtime).empty());
  }
  fake::del(page);
 }

 // Standalone saves use the shared source editor too: an unknown metadata
 // result must not leave the printer globally busy after the editor is closed.
 for(bool lost_reply:{false,true}){
  Http wire;wire.on_post=[&]{if(lost_reply)throw std::runtime_error("lost settings response");};
  wmp_openace::UiChannel channel;Runtime r(wire,port,channel);
  Json current={{"fresh",true},{"owner","standalone"},{"session","same-session"},{"revision","rev"},
   {"identity_revision",std::string(64,'a')},{"job",{{"state","idle"}}},
   {"capabilities",{{"save_identity",true}}},
   {"heads",Json::array({{{"id","h0"},{"loaded",{{"state","empty"}}}}})},
   {"sources",Json::array({{{"id","external:h0"},{"kind","external"},{"head","h0"},{"available",true},
    {"identity",{{"brand","Generic"},{"material","PLA"},{"color","#ffffff"}}}}})}};
  auto draft=current["sources"][0];draft["identity"]["color"]="#123456";
  RuntimeReceiptTest::submit_identity(r,current,draft,wire);
  assert(RuntimeReceiptTest::pending(r,false));
  assert(r.stock_maintenance_allowed()); // Metadata receipt is not a machine lock.
  RuntimeReceiptTest::update_identity(r);
  assert(!RuntimeReceiptTest::pending(r,false));
  assert(RuntimeReceiptTest::edit_operation(r)["state"]=="unknown");
  assert(RuntimeReceiptTest::edit_operation(r)["load_after_save"]==false);
  assert(r.stock_maintenance_allowed());
  assert(!RuntimeReceiptTest::procedure_active(r)&&RuntimeReceiptTest::tool_receipt(r).empty());
 }

 // A prior-session settings save must neither block maintenance forever nor
 // resume a deferred Load, even when no old receipt survives in fresh status.
 for(const auto*owner:{"standalone","openace"})for(const auto*action:{"save_identity","save_unit"}){
  Http wire;wmp_openace::UiChannel channel;Runtime r(wire,port,channel);
  Json origin={{"fresh",true},{"owner",owner},{"session","old-session"},{"job",{{"state","idle"}}}};
  RuntimeReceiptTest::pending_edit(r,origin,action);
  RuntimeReceiptTest::adoption_status(r,origin,Json::object(),port.now);
  RuntimeReceiptTest::update_identity(r);assert(r.stock_maintenance_allowed());
  auto changed=origin;changed["session"]="new-session";
  RuntimeReceiptTest::adoption_status(r,changed,Json::object(),port.now-3000);
  RuntimeReceiptTest::update_identity(r);assert(RuntimeReceiptTest::pending(r,false)); // stale evidence cannot release it
  auto unknown=changed;unknown["owner"]="unknown";
  RuntimeReceiptTest::adoption_status(r,unknown,Json::object(),port.now);
  RuntimeReceiptTest::update_identity(r);assert(RuntimeReceiptTest::pending(r,false));
  RuntimeReceiptTest::adoption_status(r,changed,Json::object(),port.now);
  RuntimeReceiptTest::update_identity(r);
  assert(!RuntimeReceiptTest::pending(r,false)&&r.stock_maintenance_allowed());
  assert(RuntimeReceiptTest::edit_operation(r)["state"]=="unknown");
  assert(RuntimeReceiptTest::edit_operation(r)["load_after_save"]==false);
  assert(!RuntimeReceiptTest::procedure_active(r)&&RuntimeReceiptTest::tool_receipt(r).empty());
  // Ownership changes are also a boundary, even if the session text matches.
  RuntimeReceiptTest::pending_edit(r,origin,action);
  changed=origin;changed["owner"]=std::string(owner)=="openace"?"standalone":"openace";
  RuntimeReceiptTest::adoption_status(r,changed,Json::object(),port.now);
  RuntimeReceiptTest::update_identity(r);assert(!RuntimeReceiptTest::pending(r,false));
  assert(RuntimeReceiptTest::edit_operation(r)["load_after_save"]==false);
  // Genuine current calibration holds still refuse maintenance.
  changed["calibration_active"]=true;
  RuntimeReceiptTest::adoption_status(r,changed,Json::object(),port.now);assert(!r.stock_maintenance_allowed());
 }

 // Closing the original stock colour picker leaves an ACE draft saveable;
 // neither cancel nor choosing an unsupported swatch dispatches a request.
 const auto colour_source=adoption_status.at("sources").at(0).at("id").get<std::string>();
 RuntimeReceiptTest::ace_colour_draft(adoption_runtime,adoption_status,colour_source);
 auto*colour_modal=fake::make(fake::screen);RuntimeReceiptTest::picker(adoption_runtime,colour_modal);
 adoption_runtime.stock_picker_cancel();
 assert(RuntimeReceiptTest::identity_active(adoption_runtime));
 assert(adoption_runtime.stock_picker_modal()==nullptr);
 adoption_runtime.stock_colour_pick(20);
 assert(RuntimeReceiptTest::identity_active(adoption_runtime));
 fake::del(colour_modal);

 // Old probe pages/actions open review only; malformed and stale taps do nothing.
 {
  assert(stock_probe_page("probe_calibrate_page"));
  assert(!stock_probe_page(nullptr)&&!stock_probe_page("maintenance_page"));
  auto*page=fake::make(fake::screen);auto*button=fake::make(page);
  for(unsigned id=0;id<14;++id){fake::Event e{button,7,reinterpret_cast<void*>(std::uintptr_t(id))};assert(stock_probe_editor_event(&e));}
  fake::Event e{button,7,reinterpret_cast<void*>(14)};assert(!stock_probe_editor_event(&e));
  e.data=nullptr;e.code=6;assert(!stock_probe_editor_event(&e));e.code=7;
  for(auto*n:{button,page}){n->state|=128;assert(!stock_probe_editor_event(&e));n->state&=~128U;}
  page->flags|=1;assert(!stock_probe_editor_event(&e));page->flags&=~1U;
  auto*detached=fake::make(nullptr);e.node=detached;assert(!stock_probe_editor_event(&e));
  e.node=button;fake::del(page);assert(!stock_probe_editor_event(&e));fake::del(detached);
  assert(!stock_probe_editor_event(nullptr));
 }
 // Independent password-success sender cannot bypass admission or touch GUI.
 {
  unsigned checks=0,notices=0;bool allow=false;
  auto admitted=[&]{++checks;return allow;};auto notice=[&]{++notices;};
  assert(!refuse_factory_confirmation(0x4c415c,admitted,notice)&&checks==0&&notices==0);
  assert(refuse_factory_confirmation(0x4c4160,admitted,notice)&&checks==1&&notices==1);
  allow=true;assert(!refuse_factory_confirmation(0x4c4160,admitted,notice)&&checks==2&&notices==1);
  assert(refuse_factory_confirmation(0x4c4160,{},{}));
 }
 // Factory machine actions must not delegate without positive admission.
 {
  auto*page=fake::make(fake::screen);auto*button=fake::make(page);
  for(unsigned id:{8U,9U,10U,13U,14U}){
   fake::Event event{button,7,reinterpret_cast<void*>(std::uintptr_t(id))};
   assert(stock_factory_probe_event(&event)==2);
   unsigned calls=0;auto admitted=[&]{++calls;return true;};
   assert(stock_factory_probe_event(&event,[]{return false;})==2);
   assert(stock_factory_probe_event(&event,admitted)==0&&calls==1);
   for(auto*n:{button,page}){n->state|=128;assert(stock_factory_probe_event(&event,admitted)==1&&calls==1);n->state&=~128U;}
   page->flags|=1;assert(stock_factory_probe_event(&event,admitted)==1&&calls==1);page->flags&=~1U;
  }
  fake::del(page);
 }
 // Factory probe review/navigation stay usable even when machine admission refuses.
 {
  auto*page=fake::make(fake::screen);auto*button=fake::make(page);
  for(unsigned id=0;id<16;++id){fake::Event event{button,7,reinterpret_cast<void*>(std::uintptr_t(id))};
   const bool machine=id==8||id==9||id==10||id==13||id==14;
   assert(stock_factory_probe_event(&event,[]{return false;})==(id==12?3:id==11?1:machine?2:0));}
  fake::Event probe{button,7,reinterpret_cast<void*>(12)};
  for(auto*n:{button,page}){n->state|=128;assert(stock_factory_probe_event(&probe)==1);n->state&=~128U;}
  page->flags|=1;assert(stock_factory_probe_event(&probe)==1);page->flags&=~1U;
  probe.code=6;assert(stock_factory_probe_event(&probe)==1);probe.code=7;
  auto*detached=fake::make(nullptr);probe.node=detached;assert(stock_factory_probe_event(&probe)==1);
  probe.node=button;fake::del(page);assert(stock_factory_probe_event(&probe)==1);
  assert(stock_factory_probe_event(nullptr)==1);fake::del(detached);
 }
 // Knife jog/save refuse before display mutation; distance and Close remain usable.
 {
  auto*page=fake::make(fake::screen);auto*button=fake::make(page);unsigned calls=0;
  for(unsigned id=0;id<10;++id){
   fake::Event event{button,7,reinterpret_cast<void*>(std::uintptr_t(id))};
   const bool machine=id==6||id==7||id==9;
   assert(stock_knife_event(&event)==(machine?2:0));
   auto allowed=[&]{++calls;return true;};const auto before=calls;
   assert(stock_knife_event(&event,allowed)==0&&calls==before+unsigned(machine));
   for(auto*n:{button,page}){n->state|=128;assert(stock_knife_event(&event,allowed)==1&&calls==before+unsigned(machine));n->state&=~128U;}
   page->flags|=1;assert(stock_knife_event(&event,allowed)==1);page->flags&=~1U;
   event.code=6;assert(stock_knife_event(&event,allowed)==1);
  }
  fake::Event invalid{button,7,reinterpret_cast<void*>(10)};assert(stock_knife_event(&invalid)==1);
  fake::del(page);assert(stock_knife_event(&invalid)==1);
  assert(stock_knife_event(nullptr)==1);
 }
 // Maintenance admission precedes vendor preparation; navigation stays usable.
 {
  auto*page=fake::make(fake::screen);auto*button=fake::make(page);unsigned calls=0;bool allow=false;
  auto admitted=[&]{++calls;return allow;};
  fake::Event start{button,7,nullptr};
  assert(stock_maintenance_event(&start,admitted)==2);allow=true;
  assert(stock_maintenance_event(&start,admitted)==0);allow=false;
  fake::Event probe{button,7,reinterpret_cast<void*>(8)};
  assert(stock_maintenance_event(&probe,admitted)==3&&calls==2); // review only; no preparation
  for(unsigned id=1;id<8;++id){fake::Event e{button,7,reinterpret_cast<void*>(std::uintptr_t(id))};assert(stock_maintenance_event(&e,admitted)==0);}
  for(auto*n:{button,page}){n->state|=128;assert(stock_maintenance_event(&start,admitted)==1);assert(stock_maintenance_event(&probe,admitted)==1);assert(calls==2);n->state&=~128U;}
  page->flags|=1;assert(stock_maintenance_event(&probe,admitted)==1);
  fake::del(page);assert(stock_maintenance_event(&probe,admitted)==1&&calls==2);
  assert(stock_maintenance_event(nullptr,admitted)==1);
 }
 {
  wmp_openace::UiChannel ch;Runtime maintenance(http,port,ch);
  auto ready=data;ready["fresh"]=true;ready["owner"]="standalone";ready["job"]={{"state","idle"}};
  for(auto key:{"filament_operation","toolhead_operation","operation"})ready.erase(key);
  RuntimeReceiptTest::adoption_status(maintenance,ready,Json::object(),port.now);
  assert(maintenance.stock_maintenance_allowed());
  // UI drafts and terminal results do not reserve the printer. A genuinely
  // queued physical request still does, before any backend receipt arrives.
  {
   auto draft_status=ready;draft_status["nozzle_settings"]={{"h0",{{"material","Hardened steel"},{"diameter",0.4}}}};
   draft_status["nozzle_revision"]=std::string(64,'a');draft_status["capabilities"]["save_nozzle"]=true;
   auto*page=fake::make(fake::screen);page->w=670;page->h=340;
   RuntimeReceiptTest::draft_nozzle(maintenance,page,draft_status);
   assert(maintenance.active()&&maintenance.stock_maintenance_allowed());
   RuntimeReceiptTest::close_nozzle(maintenance);
   RuntimeReceiptTest::terminal_cancel(maintenance,page);
   assert(maintenance.active()&&maintenance.stock_maintenance_allowed());
   RuntimeReceiptTest::close_cancel(maintenance);fake::del(page);
  }
  // Metadata receipts never own the machine, regardless of their lifecycle.
  for(const auto*owner:{"standalone","openace"})for(const auto*action:{"save_identity","save_unit","save_nozzle","profile_import"})for(const auto*state:{"pending","unknown","failed","complete"}){
   auto current=ready;current["owner"]=owner;current["session"]="editor-test";
   RuntimeReceiptTest::pending_edit(maintenance,current,action);
   RuntimeReceiptTest::edit_state(maintenance,state);
   current["operation"]={{"action",action},{"state",state}};
   RuntimeReceiptTest::adoption_status(maintenance,current,Json::object(),port.now);
   assert(maintenance.stock_maintenance_allowed());
   current["calibration_active"]=true;
   RuntimeReceiptTest::adoption_status(maintenance,current,Json::object(),port.now);
   assert(!maintenance.stock_maintenance_allowed());
  }
  // Release the synthetic receipt before the unrelated admission cases.
  auto next=ready;next["session"]="next-session";
  RuntimeReceiptTest::adoption_status(maintenance,next,Json::object(),port.now);
  RuntimeReceiptTest::update_identity(maintenance);
  // Factory-reset report: standby, completed dock/unload, no calibration latch.
  Json reported={{"webhooks",{{"state","ready"}}},{"print_stats",{{"state","standby"}}},
   {"pause_resume",{{"is_paused",false}}},
   {"wm_material",{{"available",true},{"session_id",std::string(32,'a')},
    {"afc_metadata",{{"owner","standalone"}}},
    {"toolhead_operation",{{"state","complete"},{"action","dock"},{"phase","verifying"}}},
    {"filament_operation",{{"state","complete"},{"action","unload"},{"phase","finishing"}}}}},
   {"wmp_recovery",{{"z_reference_valid",false},{"homing",false},
    {"calibration_failed",""},{"calibration_active",false}}}};
  reported["wmp_recovery"]["calibration_session"]=std::string(32,'b');
  reported["wmp_recovery"]["probe_editor"]={{"protocol",1},{"session",std::string(32,'b')},
   {"request",""},{"state","idle"},{"error",""},{"sequence",-1},
   {"stop_requested",false},{"stop_protocol",1},{"action_refused",false},
   {"save_review_required",false},{"save_review_protocol",2},{"save_review_sequence",0},
   {"save_retain_protocol",1},{"save_review_confirmable",false},{"binding_valid",true},{"z_position",nullptr}};
  // Persisted review is editor state, not execution or a global machine hold.
  for(const auto*state:{"save_review","saved","unknown"}){
   auto review=reported;review["wmp_recovery"]["probe_editor"]["state"]=state;
   review["wmp_recovery"]["probe_editor"]["save_review_required"]=true;
   const auto projected_review=project(review,Json::object(),false,"review-only");
   RuntimeReceiptTest::adoption_status(maintenance,projected_review,Json::object(),port.now);
   assert(maintenance.stock_maintenance_allowed());
   ProbeEditorFlow editor;assert(editor.begin(projected_review,std::string(32,'c'),true).empty());
   review["wmp_recovery"]["calibration_active"]=true;
   RuntimeReceiptTest::adoption_status(maintenance,project(review,Json::object(),false,"running"),Json::object(),port.now);
   assert(!maintenance.stock_maintenance_allowed());
  }
  const auto projected=project(reported,Json::object(),false,"maintenance-report");
  ProbeEditorFlow reported_probe;
  assert(!reported_probe.begin(projected,std::string(32,'c'),true).empty());
  RuntimeReceiptTest::adoption_status(maintenance,projected,Json::object(),port.now);
  assert(maintenance.stock_maintenance_allowed()&&maintenance.stock_maintenance_reason().empty());
  auto review=projected;review["probe_editor"]["state"]="save_review";review["probe_editor"]["save_review_required"]=true;
  review["calibration_failed"]="Previous attempt failed";review["calibration_active"]=false;
  RuntimeReceiptTest::adoption_status(maintenance,review,Json::object(),port.now);assert(maintenance.stock_maintenance_allowed());
  review["calibration_active"]=true;RuntimeReceiptTest::adoption_status(maintenance,review,Json::object(),port.now);assert(!maintenance.stock_maintenance_allowed());
  RuntimeReceiptTest::adoption_status(maintenance,ready,Json::object(),port.now-3000);
  assert(maintenance.stock_maintenance_reason().find("stale")!=std::string::npos);
  maintenance.request_maintenance_refusal();
  // Capture the reason at rejection, even if the next poll is healthy.
  RuntimeReceiptTest::adoption_status(maintenance,ready,Json::object(),port.now);
  maintenance.gui_step();assert(std::any_of(fake::nodes.begin(),fake::nodes.end(),[](const std::unique_ptr<fake::Node>&node){return node->live&&node->text=="Printer status is unavailable or stale. Wait for the printer to reconnect.";}));
  RuntimeReceiptTest::close_maintenance_notice(maintenance);
  for(const auto&failure:{Json{{"calibration_failed","PID failed"}},Json{{"calibration_active",true}}}){
   auto state=ready;state.update(failure);RuntimeReceiptTest::adoption_status(maintenance,state,Json::object(),port.now);assert(maintenance.stock_maintenance_allowed()==!failure.value("calibration_active",false));}
  for(auto job:{"printing","paused","unknown"}){auto state=ready;state["job"]["state"]=job;
   RuntimeReceiptTest::adoption_status(maintenance,state,Json::object(),port.now);assert(!maintenance.stock_maintenance_allowed());}
  RuntimeReceiptTest::adoption_status(maintenance,ready,Json::object(),port.now-3000);assert(!maintenance.stock_maintenance_allowed());
  for(auto key:{"filament_operation","toolhead_operation","operation"})for(auto status:{"pending","running","unknown","failed"}){
   auto state=ready;state[key]={{"state",status}};RuntimeReceiptTest::adoption_status(maintenance,state,Json::object(),port.now);assert(maintenance.stock_maintenance_allowed()==(std::string(status)=="unknown"||std::string(status)=="failed"));}
  // A terminal pre-start refusal is not a machine hold. Independent physical
  // faults and pause state still apply to the same normalized receipt.
  {auto state=ready;state["operation"]={{"action","start_print"},{"state","refused"},{"message","Print was not started; settings may have changed."}};
   RuntimeReceiptTest::adoption_status(maintenance,state,Json::object(),port.now);assert(maintenance.stock_maintenance_allowed());
   state["job"]["state"]="paused";RuntimeReceiptTest::adoption_status(maintenance,state,Json::object(),port.now);assert(!maintenance.stock_maintenance_allowed());
   state["job"]["state"]="idle";state["toolhead_operation"]={{"state","failed"}};
   RuntimeReceiptTest::adoption_status(maintenance,state,Json::object(),port.now);assert(maintenance.stock_maintenance_allowed());}
  // Exercise the real Runtime admission through all factory ingress guards,
  // including the password-success sender that bypasses the event callback.
  auto*page=fake::make(fake::screen);auto*button=fake::make(page);
  auto admission=[&]{return maintenance.stock_maintenance_allowed();};
  unsigned notices=0;
  for(bool held:{true,false}){
   auto snapshot=ready;snapshot["managed_operation_hold"]=held;
   RuntimeReceiptTest::adoption_status(maintenance,snapshot,Json::object(),port.now);
   for(unsigned id:{8U,9U,10U,13U,14U}){
    fake::Event event{button,7,reinterpret_cast<void*>(std::uintptr_t(id))};
    assert(stock_factory_probe_event(&event,admission)==(held?2:0));
   }
   for(unsigned id:{6U,7U,9U}){
    fake::Event event{button,7,reinterpret_cast<void*>(std::uintptr_t(id))};
    assert(stock_knife_event(&event,admission)==(held?2:0));
   }
   assert(refuse_factory_confirmation(0x4c4160,admission,[&]{++notices;})==held);
   // Probe opens read-only review; navigation does not become machine work.
   fake::Event probe{button,7,reinterpret_cast<void*>(12)};
   assert(stock_factory_probe_event(&probe,admission)==3);
  }
  assert(notices==1);fake::del(page);
  ready["owner"]="openace";RuntimeReceiptTest::adoption_status(maintenance,ready,Json::object(),port.now);assert(maintenance.stock_maintenance_allowed());
  ready["owner"]="unknown";RuntimeReceiptTest::adoption_status(maintenance,ready,Json::object(),port.now);assert(!maintenance.stock_maintenance_allowed());
 }
 // Every legacy Nozzle Flow service click is consumed before vendor commands.
 {
  assert(stock_filament_service_page("nozzle_flow_page"));
  assert(!stock_filament_service_page(nullptr)&&!stock_filament_service_page("nozzle_setting_page")&&!stock_filament_service_page("auto_check_prepare_page"));
  auto*page=fake::make(fake::screen);auto*button=fake::make(page);
  unsigned calls=0,head=99;bool load=false;
  auto open=[&](unsigned h,bool l){++calls;head=h;load=l;};
  for(unsigned id=1;id<=8;++id){fake::Event e{button,7,reinterpret_cast<void*>(std::uintptr_t(id))};assert(stock_service_event(&e,open));assert(calls==id&&head==(id-1)%4&&load==(id<=4));}
  fake::Event back{button,7,nullptr};assert(!stock_service_event(&back,open)&&calls==8);
  fake::Event disabled{button,7,reinterpret_cast<void*>(1)};
  for(auto*n:{button,page}){n->state|=128;assert(stock_service_event(&disabled,open)&&calls==8);assert(stock_service_event(&back,open));n->state&=~128U;}
  fake::Event invalid{button,7,reinterpret_cast<void*>(9)};assert(stock_service_event(&invalid,open)&&calls==8);
  fake::Event nonclick{button,1,reinterpret_cast<void*>(1)};assert(stock_service_event(&nonclick,open)&&calls==8);
  page->flags|=1;fake::Event hidden{button,7,reinterpret_cast<void*>(1)};assert(stock_service_event(&hidden,open)&&calls==8);assert(stock_service_event(&back,open));
  fake::del(page);assert(stock_service_event(&hidden,open)&&calls==8);
 }
 // Probe editor updates retained widgets and only forwards explicit enabled taps.
 {
  StockProbeEditor view;auto*page=fake::make(fake::screen);unsigned closes=0;
  std::vector<std::string> actions;
  view.close=[&]{++closes;};view.submit=[&](const std::string&a,const std::string&z){actions.push_back(a+":"+z);};view.created(page);
  auto text=[&](const std::string&value){for(auto&n:fake::nodes)if(n->live&&n->text==value)for(auto*p=n->parent;p;p=p->parent)if(p==page)return n.get();return static_cast<fake::Node*>(nullptr);};
  Json state={{"fresh",true},{"invalidated",false},{"editor",{{"available",true},{"state","editing"},{"z_position",1.5}}},
              {"actions",{{"JOG",true},{"ACCEPT",true},{"ABORT",true},{"SAVE",false},{"DISCARD",false}}}};
  view.update(state);auto count=fake::nodes.size();auto*jog=text("-0.1")->parent;
  assert(text("Probe calibration")->parent->background_opacity==255);



  for(const auto*name:{"CLOSE","ABORT","ACCEPT","DISCARD","SAVE"})assert(text(name)->parent->y==0);
  view.update(state);state["editor"]["z_position"]=1.4;view.update(state);
  state["editor"]["z_position"]=4.5018749949008825;view.update(state);
  assert(text("Adjust Z until paper drags lightly, then ACCEPT.\nZ: 4.502 mm"));
  assert(!text("1. Prepare")&&!text("Status: editing"));
  assert(fake::nodes.size()==count&&text("-0.1")->parent==jog&&actions.empty());
  fake::send(jog,7);assert(actions==std::vector<std::string>{"JOG:-0.1"});
  fake::send(text("SAVE")->parent,7);assert(actions.size()==1);
  page->flags|=1;fake::send(jog,7);assert(actions.size()==1);page->flags&=~1U;
  state["fresh"]=false;view.update(state);fake::send(jog,7);assert(actions.size()==1);

  fake::send(text("CLOSE")->parent,7);assert(closes==1);
  state["fresh"]=true;state["actions"]["JOG"]=false;state["actions"]["ACCEPT"]=false;
  state["actions"]["SAVE"]=true;state["editor"]["state"]="accepted";view.update(state);
  fake::send(jog,7);fake::send(text("SAVE")->parent,7);assert(actions.back()=="SAVE:"&&actions.size()==2);
  state["invalidated"]=true;view.update(state);fake::send(text("SAVE")->parent,7);assert(actions.size()==2);
  state["invalidated"]=false;state["editor"]["state"]="preparing";state["actions"]={{"STOP",true}};view.update(state);
  fake::send(text("STOP")->parent,7);assert(actions.back()=="STOP:"&&actions.size()==3);
  state["actions"]["STOP"]=false;view.update(state);fake::send(text("STOP")->parent,7);assert(actions.size()==3);
  state["editor"]["state"]="accepted";state["actions"]={{"KEEP",true}};
  state["editor"]["config_conflict"]={{"accepted_offset","1.5"},{"current_offset","2.0"},{"review",std::string(64,'d')}};
  view.update(state);assert(fake::nodes.size()==count&&text("KEEP")&&!text("DISCARD"));
  fake::send(text("KEEP")->parent,7);assert(actions.back()=="KEEP:"+std::string(64,'d')&&actions.size()==4);
  state["fresh"]=false;view.update(state);fake::send(text("KEEP")->parent,7);assert(actions.size()==4);
  state["fresh"]=true;state["invalidated"]=true;state["editor"].erase("config_conflict");
  state["editor"]["state"]="save_review";state["editor"]["save_review_required"]=true;
  state["editor"]["save_review"]={{"token",std::string(64,'e')},{"offset","1.5"},{"configuration_matches",true}};
  state["actions"]={{"START",true},{"REVIEW",true},{"ACK",false}};view.update(state);
  assert(fake::nodes.size()==count&&text("START")&&!text("REVIEW")&&text("CONFIRM"));
  assert(jog->flags&1); // Review uses the full body, not disabled jog rows.
  fake::Node*review_body=nullptr;
  for(auto&n:fake::nodes)if(n->live&&n->text.find("Recorded offset: 1.5 mm")!=std::string::npos)review_body=n.get();
  assert(review_body&&review_body->parent->flags&16&&review_body->parent->dir==12);
  assert(review_body->parent->y==52&&review_body->parent->h==page->h-64);

  review_body->parent->scroll=73;state["editor"]["error"]=std::string(512,'x');view.update(state);
  assert(review_body->parent->scroll==73&&fake::nodes.size()==count);

  fake::send(text("CONFIRM")->parent,7);assert(actions.size()==4);
  state["invalidated"]=false;state["actions"]["ACK"]=true;view.update(state);
  fake::send(text("CONFIRM")->parent,7);assert(actions.back()=="ACK:"+std::string(64,'e')&&actions.size()==5);
  state["editor"]["save_retain_protocol"]=1;
  state["editor"]["save_review"]["configuration_matches"]=false;
  state["editor"]["save_review"]["retainable"]=true;
  state["editor"]["save_review"]["loaded_offset"]="2.0";
  state["editor"]["save_review"]["differences"]=Json::array({{{"section","probe"},{"key","z_offset"},{"recorded","1.5"},{"disk","2.0"},{"loaded","2.0"}}});
  state["editor"]["save_review"]["difference_count"]=3;
  state["actions"]={{"REVIEW",true},{"RETAIN",true}};view.update(state);
  assert(review_body->text.find("Current offset: 2.0 mm")!=std::string::npos);
  assert(review_body->text.find("Settings that differ: 3")!=std::string::npos);
  assert(text("KEEP")&&!text("CONFIRM")&&fake::nodes.size()==count);
  fake::send(text("KEEP")->parent,7);assert(actions.back()=="RETAIN:"+std::string(64,'e')&&actions.size()==6);
  fake::del(page);view.update(state);fake::send(jog,7);assert(actions.size()==6);
 }
 // Opening/reopening the managed panel never starts preparation; START is explicit.
 {
  StockProbeEditor view;auto*page=fake::make(fake::screen);unsigned starts=0;
  view.close=[&]{view.dismiss();};view.submit=[&](const std::string&a,const std::string&){assert(a=="START");++starts;};
  auto text=[&](const std::string&value){for(auto&n:fake::nodes)if(n->live&&n->text==value)for(auto*p=n->parent;p;p=p->parent)if(p==page)return n.get();return static_cast<fake::Node*>(nullptr);};
  Json state={{"fresh",true},{"invalidated",false},{"editor",{{"available",true},{"state","idle"}}},{"actions",{{"START",true}}}};
  view.created(page);view.update(state);assert(starts==0&&text("START"));
  fake::send(text("START")->parent,7);assert(starts==1);
  state["editor"]["state"]="preparing";state["actions"]={{"STOP",true}};view.update(state);
  fake::send(text("CLOSE")->parent,7);view.update(state);assert(!text("Probe calibration")&&starts==1);
  view.created(page);view.update(state);assert(text("STOP")&&!text("START")&&starts==1);
  state["editor"]["state"]="aborted";state["actions"]={{"START",true}};view.update(state);
  assert(text("START")&&starts==1);fake::del(page);
 }
 // Identification stages retain nodes, use the agreed colors and block stale taps.
 {
  StockIdentification view;auto*page=fake::make(fake::screen);unsigned submits=0,backs=0;
  view.submit=[&]{++submits;};view.back=[&]{++backs;};view.created(page);
  auto text=[&](const std::string&value){for(auto&n:fake::nodes)if(n->live&&n->text==value)for(auto*p=n->parent;p;p=p->parent)if(p==page)return n.get();return static_cast<fake::Node*>(nullptr);};
  Json state={{"fresh",true},{"identification",{{"steps",Json::array({{{"label","Prepare printer"},{"state","complete"}},{{"label","Identify Head 1"},{"state","active"}},{{"label","Dock head"},{"state","pending"}}})}}}};
  view.update(state,"Identifying heads",false,false);
  assert(!text("1. Prepare printer"));
  assert(text("Identify Head 1")->text_color==0xffd24b00U);
  assert(!text("3. Dock head")&&!text("Dock head"));
  assert(text("Extruder Setup")->parent->background_opacity==255);
  assert(text("Extruder Setup")->parent->y==55&&text("Extruder Setup")->parent->background_color==0xff3c3f41U);
  assert(text("START")->text_color==0xffffffffU&&text("BACK")->text_color==0xffffffffU);
  auto count=fake::nodes.size();view.update(state,"Identifying heads",false,false);assert(fake::nodes.size()==count);
  fake::send(text("START")->parent,7);assert(submits==0);
  view.update(state,"Complete",true,true);fake::send(text("RESTART")->parent,7);assert(submits==1);
  page->flags|=1;fake::send(text("RESTART")->parent,7);assert(submits==1);page->flags&=~1U;
  state["fresh"]=false;view.update(state,"Status unavailable",false,false);
  assert(text("Identify Head 1")->text_color==0xffffffffU);
  fake::send(text("START")->parent,7);assert(submits==1);
  fake::send(text("BACK")->parent,7);assert(backs==1);
  view.update(state,"Awaiting restart",false,false,false);assert(text("BACK")->parent->flags&1);
  fake::send(text("BACK")->parent,7);assert(backs==1);
  StockIdentificationFlow external;
  state["fresh"]=true;state["owner"]="standalone";state["calibration_session"]="other-session";
  state["identification"]["state"]="running";state["identification"]["protocol"]=2;
  view.update(state,external.message(state),external.can_start(state,true),false,!external.blocks_navigation(state));
  assert(!(text("BACK")->parent->flags&1));fake::send(text("BACK")->parent,7);assert(backs==2);
  fake::send(text("START")->parent,7);assert(submits==1);
  fake::del(page);view.update(state,"Unavailable",false,false);
 }
 nozzle_scrub_lifecycle(data);
 // Calibration failure remains visible through stale updates and cannot expose
 // stock success ticks by dismissal. DONE only navigates; it sends no commands.
 {
  StockCalibrationStatus view;auto*page=fake::make(fake::screen);unsigned backs=0;
  view.back=[&]{++backs;};view.created(page);
  auto text=[&](const std::string&prefix){for(auto&n:fake::nodes)if(n->live&&n->text.find(prefix)==0)for(auto*p=n->parent;p;p=p->parent)if(p==page)return n.get();return static_cast<fake::Node*>(nullptr);};
  Json state={{"fresh",true},{"calibration_session","cal-one"},{"calibration_failed",""}};
  view.update(state);assert(page->children.empty());
  state["calibration_failed"]="PID failed";view.update(state);
  assert(text("Calibration stopped.")&&text("DONE"));auto*panel=text("Calibration stopped.")->parent;
  assert(panel->background_opacity==255&&panel->x==90&&panel->y==55&&panel->w==700&&panel->h==415
    &&panel->background_color==0xff3c3f43U);
  auto count=fake::nodes.size();view.update(state);assert(fake::nodes.size()==count);
  fake::send(text("DONE")->parent,7);assert(backs==1&&text("Calibration stopped."));
  state["fresh"]=false;state["calibration_failed"]="";view.update(state);assert(text("Calibration stopped."));
  state["fresh"]=true;state["session"]="different-owner-session";view.update(state);assert(text("Calibration stopped."));
  state["calibration_session"]="cal-two";view.update(state);assert(text("Printer restarted. Calibration result could not be confirmed."));
  assert(text("Printer restarted. Calibration result could not be confirmed.")->text.find("Previous error: PID failed")!=std::string::npos);
  state["fresh"]=false;view.update(state);assert(text("Printer restarted. Calibration result could not be confirmed."));
  auto*old=text("DONE")->parent;auto*screen=fake::screen;fake::screen=fake::make(nullptr);
  fake::send(old,7);assert(backs==1);view.update(state);assert(page->children.empty());fake::screen=screen;
  state["fresh"]=true;view.update(state);assert(text("Printer restarted. Calibration result could not be confirmed."));
  state["calibration_session"]="";view.update(state);assert(text("Printer restarted. Calibration result could not be confirmed."));
  fake::del(page);view.update(state); // parent deletion clears references
  page=fake::make(fake::screen);view.created(page);state["calibration_session"]="cal-three";
  view.update(state);assert(page->children.empty()); // deliberate new page retires old result
  state["calibration_failed"]="Another failure";view.update(state);assert(text("Calibration stopped."));
  fake::del(page);
 }
 // A normal SAVE_CONFIG restart is not proof of failure or success. Keep a
 // neutral result barrier on the old page; a recreated page starts clean.
 {
  StockCalibrationStatus view;auto*page=fake::make(fake::screen);view.created(page);
  Json state={{"fresh",true},{"calibration_session","save-before"},{"calibration_active",true},{"calibration_failed",""}};
  view.update(state);assert(page->children.empty());
  state["fresh"]=false;view.update(state);assert(!page->children.empty());
  state["fresh"]=true;state["calibration_session"]="save-after";state["calibration_active"]=false;
  view.update(state);
  bool unconfirmed=false,failed=false;
  for(auto&n:fake::nodes)if(n->live&&n->parent&&n->parent->parent==page){
   unconfirmed|=n->text.find("Printer restarted. Calibration result could not be confirmed.")==0;
   failed|=n->text.find("Calibration stopped.")==0;
  }
  assert(unconfirmed&&!failed);
  view.update(state);assert(!page->children.empty());
  view.created(page);view.update(state);assert(page->children.empty());
  fake::del(page);view.update(state);
 }
 // A durable save receipt confirms only this page's saved values, after a
 // new backend session, and never overrides a previously observed failure.
 {
  const std::string origin(32,'a'),next(32,'b'),request(32,'c');
  StockCalibrationStatus view;auto*page=fake::make(fake::screen);view.created(page);view.begin(origin,request);
  auto has=[&](const std::string&prefix){for(auto&n:fake::nodes)if(n->live&&n->text.find(prefix)==0)for(auto*p=n->parent;p;p=p->parent)if(p==page)return true;return false;};
  Json receipt={{"protocol",1},{"session",origin},{"request",request},{"state","confirmed"},{"error",""}};
  Json state={{"fresh",true},{"calibration_session",origin},{"calibration_failed",""},{"maintenance_save_requested",true},{"calibration_save_result",receipt}};
  view.update(state);assert(has("Saving calibration settings...\nRestarting Klipper...")); // old session cannot confirm
  state["fresh"]=false;state["maintenance_save_requested"]=false;view.update(state);
  assert(has("Saving calibration settings...\nRestarting Klipper..."));
  assert(!has("Restarting Klipper... Done."));
  state["fresh"]=true;state["calibration_session"]=next;view.update(state);assert(has("Restarting Klipper... Done.\nCalibration settings saved."));
  assert(has("DONE")&&!has("BACK"));
  for(const auto&value:{"pending","saved","unconfirmed"}){state["calibration_save_result"]["state"]=value;view.update(state);assert(has("Restarting Klipper... Done.\nSaved calibration settings could not be verified."));}
  state["calibration_save_result"]=receipt;state["calibration_save_result"]["request"]=std::string(32,'d');view.update(state);assert(has("Restarting Klipper... Done.\nSaved calibration settings could not be verified."));
  state["calibration_save_result"]=receipt;state["calibration_save_result"]["session"]=next;view.update(state);assert(has("Restarting Klipper... Done.\nSaved calibration settings could not be verified."));
  state["calibration_save_result"]=receipt;state["fresh"]=false;view.update(state);assert(has("Restarting Klipper... Done.\nSaved calibration settings could not be verified."));
  state["fresh"]=true;state["calibration_session"]=origin;state["calibration_failed"]="Earlier PID failure";
  state["calibration_attempt"]={{"session",origin},{"request",request},{"state","failed"},{"error","Earlier PID failure"}};view.update(state);
  state["calibration_session"]=next;state["calibration_failed"]="";view.update(state);assert(has("Restarting Klipper... Done.\nSaved calibration settings could not be verified.")&&!has("Restarting Klipper... Done.\nCalibration settings saved."));
  // Deliberate START resets the same retained page, without a constructor.
  view.begin(next,std::string(32,'e'));state["maintenance_save_requested"]=false;view.update(state);assert(page->children.empty());
  // Old global errors and unrelated attempts cannot poison an explicit retry.
  state["calibration_failed"]="Earlier PID failure";view.update(state);assert(page->children.empty());
  state["calibration_attempt"]={{"session",next},{"request",std::string(32,'e')},{"state","running"},{"error",""}};
  view.update(state);assert(page->children.empty());
  state["calibration_save_result"]={{"protocol",1},{"session",next},{"request",std::string(32,'e')},{"state","confirmed"}};
  state["calibration_session"]=std::string(32,'f');view.update(state);assert(has("Restarting Klipper... Done.\nCalibration settings saved."));
  assert(has("DONE")&&!has("BACK"));
  assert(calibration_save_result(receipt)==receipt);
  for(const auto&bad:{Json{{"protocol",1}},Json{{"protocol",true}},Json{{"protocol",2}}})assert(calibration_save_result(bad).empty());
  auto malformed=receipt;malformed["request"]="invalid token";assert(calibration_save_result(malformed).empty());
  malformed=receipt;malformed["state"]="complete";assert(calibration_save_result(malformed).empty());
  fake::del(page);
 }
 // Queued/running work owns the reservation across Klipper restarts. A pooled
 // worker gets an invocation binding, not whatever a later page displays.
 {
  Http wire;Port clock;wmp_openace::UiChannel ch;Runtime r(wire,clock,ch);
  auto ready=data;ready["fresh"]=true;ready["owner"]="standalone";ready["job"]={{"state","idle"}};ready["calibration_session"]=std::string(32,'a');ready["calibration_failed"]="";ready["calibration_active"]=false;
  for(auto key:{"filament_operation","toolhead_operation","operation"})ready.erase(key);
  ready["calibration_attempt_protocol"]=1;
  RuntimeReceiptTest::adoption_status(r,ready,Json::object(),clock.now);
  assert(r.begin_stock_calibration());const auto first=RuntimeReceiptTest::calibration_request(r);
  auto*page=fake::make(fake::screen);r.stock_calibration_created(page);
  r.stock_calibration_enqueued();r.finish_stock_calibration_start();assert(r.stock_calibration_reserved());
  assert(!r.begin_stock_calibration()); // old job has not entered the pool yet
  std::string old_save;
  r.run_stock_calibration_worker([&]{
   const auto home=r.stock_calibration_command_for_worker(0x4b7a1c,"G28");
   assert(home.find(" SESSION="+std::string(32,'a')+" REQUEST="+first+" SEQUENCE=0")!=std::string::npos);
   assert(r.stock_calibration_command_for_worker(0x12345,"G28")=="G28");
   const auto tool=r.stock_calibration_command_for_worker(0x4b7cb8,"T2");
   assert(tool.find(" SEQUENCE=1")!=std::string::npos);

   ready["calibration_session"]=std::string(32,'b');RuntimeReceiptTest::adoption_status(r,ready,Json::object(),clock.now);
   assert(!r.begin_stock_calibration()); // backend restart does not release worker
   old_save=r.stock_calibration_command_for_worker(0x4b869c,"SAVE_CONFIG");
   assert(old_save.find(" SESSION="+std::string(32,'a')+" REQUEST="+first+" SEQUENCE=2")!=std::string::npos);
   assert(r.stock_calibration_command_for_worker(0x50b134,"SAVE_CONFIG").find(" REQUEST=")==std::string::npos);
   r.update_stock_calibration();assert(!page->children.empty());
  });
  assert(!r.stock_calibration_reserved());
  assert(r.stock_calibration_command_for_worker(0x4b869c,"SAVE_CONFIG").find(" REQUEST=")==std::string::npos); // TLS retired
  assert(r.begin_stock_calibration());const auto second=RuntimeReceiptTest::calibration_request(r);assert(second!=first&&page->children.empty());
  r.stock_calibration_enqueued();r.finish_stock_calibration_start();
  try{r.run_stock_calibration_worker([&]{
   const auto save=r.stock_calibration_command_for_worker(0x4b869c,"SAVE_CONFIG");
   assert(save.find(" SESSION="+std::string(32,'b')+" REQUEST="+second+" SEQUENCE=0")!=std::string::npos);
   unsigned sequence=1;
   for(auto caller:calibration_senders){
    const auto wrapped=r.stock_calibration_command_for_worker(caller,caller==0x4b7cb8?"T2":"M400");
    if(caller>=0x4b7558&&caller<=0x4b869c)
     assert(wrapped.find(" SESSION="+std::string(32,'b')+" REQUEST="+second+" SEQUENCE="+std::to_string(sequence++))!=std::string::npos);
    else assert(wrapped.find(" REQUEST=")==std::string::npos);
   }
   assert(sequence==17); // All sixteen verified Maintenance send sites.
   throw std::runtime_error("worker failed");
  });assert(false);}catch(const std::runtime_error&){}
  assert(!r.stock_calibration_reserved());
  assert(r.begin_stock_calibration());r.finish_stock_calibration_start();assert(!r.stock_calibration_reserved()); // declined/no selection
  assert(r.begin_stock_calibration());r.stock_calibration_enqueued();r.stock_calibration_enqueue_failed();assert(!r.stock_calibration_reserved());
  bool duplicate=false;r.run_stock_calibration_worker([&]{duplicate=true;});assert(!duplicate);
  fake::del(page);
 }
 // Maintenance tickets are captured at explicit START, never re-read by an
 // old pooled worker after status advances or the backend restarts.
 {
  Http wire;Port clock;wmp_openace::UiChannel ch;Runtime r(wire,clock,ch);
  auto ready=data;ready["fresh"]=true;ready["owner"]="standalone";ready["job"]={{"state","idle"}};
  ready["calibration_session"]=std::string(32,'a');ready["calibration_failed"]="";ready["calibration_active"]=false;
  for(auto key:{"filament_operation","toolhead_operation","operation"})ready.erase(key);
  ready["calibration_attempt_protocol"]=1;ready["calibration_ticket_protocol"]=1;ready["calibration_next_ticket"]="1025";
  RuntimeReceiptTest::adoption_status(r,ready,Json::object(),clock.now);
  assert(r.begin_stock_calibration());r.stock_calibration_enqueued();r.finish_stock_calibration_start();
  r.run_stock_calibration_worker([&]{
   assert(r.stock_calibration_command_for_worker(0x4b7a1c,"G28").find(" SEQUENCE=0 TICKET=1025")!=std::string::npos);
   ready["calibration_next_ticket"]="1026";ready["calibration_session"]=std::string(32,'b');
   RuntimeReceiptTest::adoption_status(r,ready,Json::object(),clock.now);
   const auto save=r.stock_calibration_command_for_worker(0x4b869c,"SAVE_CONFIG");
   assert(save.find(" SEQUENCE=1 TICKET=1025")!=std::string::npos&&save.find(" SESSION="+std::string(32,'a'))!=std::string::npos);
  });
  assert(r.begin_stock_calibration());r.stock_calibration_enqueued();r.finish_stock_calibration_start();
  r.run_stock_calibration_worker([&]{
   assert(r.stock_calibration_command_for_worker(0x4b7a1c,"G28").find(" SEQUENCE=0 TICKET=1026")!=std::string::npos);
  });
  ready["calibration_next_ticket"]="";RuntimeReceiptTest::adoption_status(r,ready,Json::object(),clock.now);
  assert(!r.begin_stock_calibration()&&!r.stock_calibration_reserved());
  Json raw={{"wmp_recovery",{{"calibration_ticket_protocol",1},{"calibration_next_ticket","12345678901234567890"}}}};
  auto projected=project(raw,Json::object(),false,"test");
  assert(projected["calibration_ticket_protocol"]==1&&projected["calibration_next_ticket"]=="12345678901234567890");
  raw["wmp_recovery"]["calibration_ticket_protocol"]=true;raw["wmp_recovery"]["calibration_next_ticket"]=123;
  projected=project(raw,Json::object(),false,"test");
  assert(projected["calibration_ticket_protocol"]==0&&projected["calibration_next_ticket"]=="");
 }
 // A clean, matching refusal explains this attempt without inventing a
 // physical failure or claiming that a different run was cancelled.
 {
  StockCalibrationStatus view;auto*page=fake::make(fake::screen);view.created(page);
  const std::string session(32,'a'),request(32,'b');view.begin(session,request);
  Json receipt={{"protocol",1},{"session",session},{"request",request},{"state","refused"},{"error","Calibration requires an idle printer"}};
  Json state={{"fresh",true},{"calibration_session",session},{"calibration_failed",""},{"calibration_attempt",receipt}};
  view.update(state);bool shown=false;
  for(auto&n:fake::nodes)if(n->live&&n->text.find("Calibration did not start.")==0){shown=true;assert(n->text.find("restart Klipper")==std::string::npos);}
  assert(shown&&calibration_attempt_result(receipt)==receipt);
  view.begin(session,std::string(32,'c'));view.update(state);assert(page->children.empty());
  for(const auto&bad:{Json{{"protocol",true}},Json{{"protocol",2}},Json{{"protocol","1"}}})assert(calibration_attempt_result(bad).empty());
  for(const auto&protocol:{Json(),Json(true),Json("1"),Json::object(),Json::array(),Json(2)}){
   Json raw={{"wmp_recovery",{{"calibration_attempt_protocol",protocol},{"calibration_attempt",receipt}}}};
   const auto projected=project(raw,Json::object(),false,"test");
   assert(projected["calibration_attempt_protocol"]==0&&projected["calibration_attempt"]==receipt);
  }
  fake::del(page);
 }
 // First-run overlays can leave a failed result without claiming completion.
 {
  StockCalibrationStatus view;auto*page=fake::make(fake::screen);view.created(page,true);
  Json state={{"fresh",true},{"calibration_session","guide"}};
  view.update(state,"Setup checkpoint pending");
  fake::Node*body=nullptr;for(auto&n:fake::nodes)if(n->live&&n->text=="Setup checkpoint pending")body=n.get();
  auto*overlay=page->children.front();
  assert(body&&body->font_address==MyriadPro_Regular_22&&overlay->x==0&&overlay->y==0&&overlay->background_opacity==255);
  unsigned backs=0;view.back=[&]{++backs;};fake::Node*back=nullptr;
  for(auto*child:overlay->children)for(auto*label:child->children)if(label->text=="BACK")back=child;
  assert(back);fake::send(back,7);assert(backs==1);
  auto count=fake::nodes.size();view.update(state,"Setup checkpoint pending");assert(fake::nodes.size()==count);
  view.update(state);assert(page->children.empty());fake::del(page);
 }
 // First-run identification covers the full screen and has no bypass action.
 {
  StockIdentification view;auto*page=fake::make(fake::screen);view.created(page,true);
  view.update(Json::object(),"Seat every head",false,false);
  fake::Node*title=nullptr;for(auto&n:fake::nodes)if(n->live&&n->text=="Extruder Setup")title=n.get();
  assert(title&&title->parent->x==0&&title->parent->y==0&&title->parent->w==fake::screen->w);
  for(auto*child:title->parent->children)for(auto*caption:child->children)assert(caption->text!="BACK");
  fake::del(page);
 }
 // A completed identification must not permit restarting an active print.
 {
  wmp_openace::UiChannel ch;Runtime setup(http,port,ch);std::vector<std::string>commands;
  setup.set_calibration_sender([&](const std::string&s){commands.push_back(s);return true;});
  auto state=data;state["owner"]="standalone";state["fresh"]=true;state["job"]={{"state","printing"}};
  state["calibration_session"]="identify-session";state["identification"]={{"protocol",2},{"state","complete"},{"restart_required",true}};
  RuntimeReceiptTest::adoption_status(setup,state,Json::object(),port.now);
  setup.submit_identification();assert(commands.empty());
  state["job"]["state"]="idle";state["managed_operation_hold"]=true;
  RuntimeReceiptTest::adoption_status(setup,state,Json::object(),port.now);
  setup.submit_identification();assert(commands.empty());
  state["managed_operation_hold"]=false;RuntimeReceiptTest::adoption_status(setup,state,Json::object(),port.now);
  setup.submit_identification();assert(commands==std::vector<std::string>{"FIRMWARE_RESTART"});
  setup.submit_identification();assert(commands.size()==1);
 }
 // Identification sends request identity through the runtime sender and settles only its receipt.
 {
  wmp_openace::UiChannel ch;Runtime setup(http,port,ch);std::vector<std::string>commands;
  setup.set_calibration_sender([&](const std::string&s){commands.push_back(s);return true;});
  auto state=data;state["owner"]="standalone";state["fresh"]=true;state["job"]={{"state","idle"}};
  state["calibration_session"]="identify-runtime";state["identification"]={{"protocol",2},{"state","idle"}};
  RuntimeReceiptTest::adoption_status(setup,state,Json::object(),port.now);
  setup.submit_identification();assert(commands.size()==1);
  assert(commands[0].find("_WMP_IDENTIFY_HEADS SESSION=identify-runtime REQUEST=")==0);
  auto request=commands[0].substr(commands[0].find("REQUEST=")+8);assert(request.size()==32);
  setup.submit_identification();assert(commands.size()==1&&setup.identification_blocks_navigation());
  state["identification"]["request_result"]={{"session","identify-runtime"},{"request",request},{"state","refused"},{"error","Resolve probe editor"}};
  RuntimeReceiptTest::adoption_status(setup,state,Json::object(),port.now);
  assert(!setup.identification_blocks_navigation());assert(commands.size()==1);
  setup.submit_identification();assert(commands.size()==2&&commands[1]!=commands[0]);
  assert(setup.identification_blocks_navigation());
  // A completed status without this attempt's receipt cannot dispatch RESTART.
  state["identification"]["state"]="complete";state["identification"]["restart_required"]=true;
  RuntimeReceiptTest::adoption_status(setup,state,Json::object(),port.now);
  setup.submit_identification();assert(commands.size()==2);
  state["identification"]["request_result"]["request"]=commands[1].substr(commands[1].find("REQUEST=")+8);
  state["identification"]["request_result"]["state"]="complete";
  RuntimeReceiptTest::adoption_status(setup,state,Json::object(),port.now);
  setup.submit_identification();assert(commands.size()==3&&commands.back()=="FIRMWARE_RESTART");
 }
 // First-run navigation waits for a newly issued, matching backend checkpoint.
 {
  wmp_openace::UiChannel ch;Runtime setup(http,port,ch);std::vector<std::string>commands,pages;
  setup.set_calibration_sender([&](const std::string&s){commands.push_back(s);return true;});
  setup.set_stock_navigation([&](const char*s){pages.push_back(s);});
  auto idle=data;idle["owner"]="standalone";idle["fresh"]=true;idle["job"]={{"state","idle"}};
  idle["calibration_session"]="guide-session";idle["calibration_checkpoint"]="old";
  assert(!setup.calibration_navigation("main_page"));
  assert(setup.calibration_navigation("guide_calibrating_page"));setup.gui_step();assert(commands.empty()&&pages.empty());
  RuntimeReceiptTest::adoption_status(setup,idle,Json::object(),port.now);setup.gui_step();assert(commands.size()==1&&pages.empty());
  setup.gui_step();assert(commands.size()==1&&pages.empty());
  idle["calibration_checkpoint"]=commands.back().substr(commands.back().find("TOKEN=")+6);
  RuntimeReceiptTest::adoption_status(setup,idle,Json::object(),port.now);setup.gui_step();assert(pages==std::vector<std::string>{"guide_calibrating_page"});
  setup.calibration_navigation("guide_filament_page");setup.gui_step();assert(commands.size()==2&&pages.size()==1);
  idle["calibration_failed"]="PID failed";RuntimeReceiptTest::adoption_status(setup,idle,Json::object(),port.now);setup.gui_step();
  idle["calibration_checkpoint"]=commands.back().substr(commands.back().find("TOKEN=")+6);
  idle["calibration_failed"]="";idle["calibration_session"]="restarted";
  RuntimeReceiptTest::adoption_status(setup,idle,Json::object(),port.now);setup.gui_step();assert(pages.size()==1);
  setup.calibration_navigation("guide_filament_page");setup.gui_step();assert(commands.size()==2&&pages.size()==1);
 }
 // Runtime observes raw helper status and queues native selection off the GUI.
 {
  struct ReviewHttp: wmp_openace::HttpPort {
   std::atomic<unsigned>posts{0};
   std::string get(const std::string&)override{assert(false);return {};}
   std::string post(const std::string&path,const std::string&)override{
    assert(path=="/printer/wmp/recovery/review");++posts;return "{\"error\":\"Review refused\"}";
   }
  } review,stop;
  Http status;status.ace_present=false;Port clock;wmp_openace::UiChannel c;
  Runtime r(status,clock,c);r.enable_recovery(review,stop,stop);
  auto select=[&]{return r.select_recovery(1,"part.gcode","plr_dataB.ini",std::string(16,'a'),std::string(16,'b'));};
  assert(!select());
  status.extra_status["wm_material"]={{"session_id","native-session"},{"afc_metadata",{{"owner","standalone"}}},
   {"recovery_review_protocol",1},{"recovery_continue_protocol",1},{"recovery_stop_protocol",1},{"recovery_retirement_protocol",1}};
  r.worker_step(clock.now);assert(select());
  // Native callback touches no GUI objects; presentation belongs to gui_step.
  assert(!r.active());r.gui_step();assert(r.active());
  auto*root=fake::top->children.back();
  assert(select());r.gui_step();root=fake::top->children.back();assert(r.active());
  fake::Node*close=nullptr;for(auto*b:root->children)for(auto*l:b->children)if(l->text=="CLOSE"||l->text=="BACK")close=b;
  assert(close);fake::send(close,7);assert(!r.active());r.gui_step();assert(!r.active());
  assert(select());r.gui_step();assert(r.active()); // explicit new read-only review
  const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
  while(!review.posts.load()&&std::chrono::steady_clock::now()<deadline)std::this_thread::yield();
  assert(review.posts>=1&&review.posts<=3&&stop.posts==0);
  fake::Node*back=nullptr;bool reason=false;
  while(!back&&std::chrono::steady_clock::now()<deadline){
   r.gui_step();root=fake::top->children.back();
   for(auto*b:root->children)if(!(b->flags&1))for(auto*l:b->children){
    if(l->text=="BACK")back=b;
    assert(l->text!="DISCARD"&&l->text!="REVIEW");
   }
   for(const auto&n:fake::nodes)if(n->live&&n->text=="PLR could not start.\nReview refused")reason=true;
   std::this_thread::yield();
  }
  assert(back&&reason&&stop.posts==0&&root->children.front()->text=="Power Loss Recovery (PLR)");
  root=fake::top->children.back();fake::del(root);assert(!r.active());
  clock.now+=1000;status.on_get=[](const std::string&){throw std::runtime_error("Disconnected");};
  r.worker_step(clock.now);assert(!r.select_recovery(1,"other.gcode","plr_dataB.ini",std::string(16,'a'),std::string(16,'b')));
 }
 // A refused Continue keeps its native offer; only a fresh matching-worker
 // completed continuation dismisses it, without deleting the result panel.
 {
  Http status;Port clock;wmp_openace::UiChannel c;Runtime r(status,clock,c);
  auto*offer=fake::make(fake::top);auto*inner=fake::make(offer);auto*button=fake::make(inner);
  auto*other=fake::make(fake::top);unsigned dismissed=0;
  r.native_continue_started([&]{++dismissed;assert(wmp_openace::hide_recovery_offer(button,fake::top));});
  Json result={{"id","new-selection"},{"fresh",true},{"state","refused"}};
  r.finish_native_continue(result,"new-selection");assert(dismissed==0&&!(offer->flags&1));
  result["state"]="pending";result["receipt"]={{"state","running"}};
  r.finish_native_continue(result,"new-selection");assert(dismissed==0);
  result["receipt"]={{"state","complete"},{"continuation",{{"state","scheduled"}}}};
  r.finish_native_continue(result,"new-selection");assert(dismissed==0);
  result["receipt"]["continuation"]["state"]="started";result["fresh"]=false;
  r.finish_native_continue(result,"new-selection");assert(dismissed==0);
  result["fresh"]=true;r.finish_native_continue(result,"unrelated-selection");assert(dismissed==0);
  r.finish_native_continue(result,"new-selection");
  assert(dismissed==1&&(offer->flags&1)&&!(other->flags&1)&&!(fake::top->flags&1));
  r.finish_native_continue(result,"new-selection");assert(dismissed==1);
  fake::del(offer);assert(!wmp_openace::hide_recovery_offer(button,fake::top));fake::del(other);
 }
 // A restored hold must survive startup before the overlay has dimensions,
 // and the stock transition from its initializing screen to the main screen.
 {
  struct ReadOnlyResolutionHttp:Http {
   std::atomic<unsigned>reads{0},commands{0};
   std::string post(const std::string&path,const std::string&body)override{
    if(path=="/printer/gcode/script"){++commands;assert(false);}
    assert(path=="/printer/wmp/recovery/resolve_review");++reads;
    auto ticket=Json::parse(body);ticket["version"]=1;ticket["journal_sha256"]=std::string(64,'a');ticket["execution_hash"]=std::string(16,'c');
    return Json{{"result",{{"request",ticket}}}}.dump();
   }
  } wire;wire.ace_present=false;Port clock;wmp_openace::UiChannel c;
  Runtime r(wire,clock,c);r.enable_recovery(wire,wire,wire);
  auto&posts=wire.commands;
  wire.extra_status["wm_material"]={{"session_id","startup"},{"afc_metadata",{{"owner","standalone"}}},
   {"recovery_resolution_protocol",1},{"recovery_attempt",{{"state","unknown"},
    {"request",{{"id","interrupted"},{"session","previous"}}},
    {"continuation",{{"state","interrupted"}}},{"stages",Json::array()}}}};
  fake::top->pending_layout=true;r.worker_step(clock.now);r.gui_step();
  assert(!r.active()&&posts==0);
  fake::top->pending_layout=false;r.gui_step();assert(r.active()&&posts==0);
  auto*old_screen=fake::screen;fake::screen=fake::make(nullptr);
  r.gui_step();r.gui_step();assert(r.active()&&posts==0);
  fake::clean(fake::top); // stock warning construction clears this shared layer
  r.gui_step();assert(r.active()&&posts==0);
  auto*root=fake::top->children.back();
  fake::Node*close=nullptr;
  for(auto*b:root->children)for(auto*l:b->children)if(l->text=="CLOSE")close=b;
  assert(close);fake::send(close,7);
  r.gui_step();assert(!r.active()&&posts==0); // deliberate Close stays closed
  fake::screen=old_screen;
 }
 // A restored hold is shown once without submitting any command, and remains
 // truthful through disconnection and a terminal resolution result.
 {
  struct ReadOnlyResolutionHttp:Http {
   std::atomic<unsigned>reads{0},commands{0};
   std::string post(const std::string&path,const std::string&body)override{
    if(path=="/printer/gcode/script"){++commands;assert(false);}
    assert(path=="/printer/wmp/recovery/resolve_review");++reads;
    auto ticket=Json::parse(body);ticket["version"]=1;ticket["journal_sha256"]=std::string(64,'a');ticket["execution_hash"]=std::string(16,'c');
    return Json{{"result",{{"request",ticket}}}}.dump();
   }
  } wire;wire.ace_present=false;Port clock;wmp_openace::UiChannel c;
  Runtime r(wire,clock,c);r.enable_recovery(wire,wire,wire);
  auto&posts=wire.commands;
  Json attempt={{"request",{{"id","restored"},{"session","old"},{"file","part.gcode"},{"execution_hash",std::string(16,'c')}}},
   {"state","stopped"},{"stages",Json::array()},{"error","Interrupted"}};
  wire.extra_status["wm_material"]={{"session_id","new"},{"afc_metadata",{{"owner","standalone"}}},
   {"recovery_resolution_protocol",1},{"recovery_attempt",attempt}};
  r.worker_step(clock.now);r.gui_step();assert(r.active()&&posts==0);
  assert(r.stock_maintenance_allowed());
  auto*root=fake::top->children.back();const auto count=fake::nodes.size();
  auto caption=[&](const std::string&text){for(auto*b:root->children)for(auto*l:b->children)if(l->text==text)return b;return static_cast<fake::Node*>(nullptr);};
  auto wait_choice=[&]{auto until=std::chrono::steady_clock::now()+std::chrono::seconds(3);while((!caption("DISCARD")||(caption("DISCARD")->flags&1))&&std::chrono::steady_clock::now()<until){r.gui_step();std::this_thread::yield();}};
  wait_choice();assert(caption("DISCARD")&&!(caption("DISCARD")->flags&1)&&wire.reads>=1);r.gui_step();assert(fake::nodes.size()==count);
  clock.now+=1000;wire.on_get=[](const std::string&){throw std::runtime_error("offline");};r.worker_step(clock.now);r.gui_step();
  assert(r.active()&&posts==0&&fake::nodes.size()==count);
  for(const auto*name:{"STOP","DISCARD","USE SAVED"})if(auto*action=caption(name))assert((action->flags&1)||(action->state&128));
  wire.on_get={};
  for(const auto&transition:std::vector<std::pair<std::string,std::string>>{{"scheduled","pending"},{"started","printing"},{"paused","paused"},{"started","printing"},{"unknown","unknown"}}){
   auto&current=wire.extra_status["wm_material"]["recovery_attempt"];
   current["state"]="complete";current["continuation"]={{"state",transition.first}};
   clock.now+=1000;r.worker_step(clock.now);r.gui_step();
   bool shown=false;for(const auto&n:fake::nodes)if(n->live&&n->text.find(transition.second=="unknown"?"PLR stopped.":transition.second=="paused"?"Print paused.":transition.second=="printing"?"Print resumed.":"Power Loss Recovery in progress...")!=std::string::npos)shown=true;
   assert(shown&&fake::nodes.size()==count&&posts==0);
  }
  clock.now+=1000;wire.extra_status["wm_material"]["recovery_attempt"]["state"]="abandoned";
  r.worker_step(clock.now);r.gui_step();assert(r.active()&&posts==0&&!caption("DISCARD"));
  bool abandoned=false;for(const auto&n:fake::nodes)if(n->live&&n->text.find("Saved PLR discarded.")!=std::string::npos)abandoned=true;assert(abandoned);
  // A delayed pre-resolution snapshot must not restore DISCARD or replace the
  // terminal result for the same restored attempt and backend session.
  clock.now+=1000;wire.extra_status["wm_material"]["recovery_attempt"]=attempt;
  r.worker_step(clock.now);r.gui_step();
  assert(!caption("DISCARD")&&posts==0&&fake::nodes.size()==count);
  abandoned=false;for(const auto&n:fake::nodes)if(n->live&&n->text.find("Saved PLR discarded.")!=std::string::npos)abandoned=true;assert(abandoned);
  // A new backend session is a new review context, not frozen old authority.
  clock.now+=1000;wire.extra_status["wm_material"]["session_id"]="newer";
  r.worker_step(clock.now);r.gui_step(); // new session is rediscovered within this poll
  assert(posts==0);
  clock.now+=1000;r.worker_step(clock.now);r.gui_step();root=fake::top->children.back();
  wait_choice();assert(caption("DISCARD")&&!(caption("DISCARD")->flags&1)&&posts==0);
  fake::send(caption("CLOSE"),7);r.gui_step();assert(!r.active()&&posts==0);
  assert(r.stock_maintenance_allowed());
  // Resolving a closed receipt releases maintenance without reopening the
  // result, replaying recovery or requiring a process restart.
  wire.extra_status["wm_material"]["recovery_attempt"]["state"]="abandoned";
  clock.now+=1000;r.worker_step(clock.now);r.gui_step();
  assert(!r.active()&&r.stock_maintenance_allowed()&&posts==0);
 }
 // Resolution is an explicit two-step interaction; updates do not confirm.
 {
  Http wire;wire.ace_present=false;Port clock;wmp_openace::UiChannel c;
  Runtime r(wire,clock,c);r.enable_recovery(wire,wire,wire);
  std::atomic<unsigned>posts{0};wire.on_post=[&]{++posts;};
  assert(!r.request_recovery_review(2));
  wire.extra_status["wm_material"]={{"session_id","legacy-session"},{"afc_metadata",{{"owner","standalone"}}},
   {"recovery_retirement_protocol",1}};
  r.worker_step(clock.now);assert(!r.request_recovery_review(99));assert(r.request_recovery_review(2));
  assert(!r.active()&&posts==0);r.gui_step();assert(r.active()&&posts<=1);
  auto*root=fake::top->children.back();const auto count=fake::nodes.size();
  auto caption=[&](const std::string&text){for(auto*b:root->children)if(!(b->flags&1))for(auto*l:b->children)if(l->text==text)return b;return static_cast<fake::Node*>(nullptr);};
  assert(!caption("REVIEW"));
  r.gui_step();assert(fake::nodes.size()==count&&posts<=1);
  clock.now+=1000;wire.on_get=[](const std::string&){throw std::runtime_error("offline");};r.worker_step(clock.now);r.gui_step();
  assert(!caption("REVIEW")&&posts<=1&&!r.request_recovery_review(2));
  fake::send(caption("BACK"),7);assert(!r.active());r.gui_step();assert(!r.active());
 }
 // Resolution is an explicit two-step interaction; updates do not confirm.
 for(bool native_cancel:{false,true}){
  struct DiscardHttp:wmp_openace::HttpPort {
   std::atomic<unsigned>reviews{0},commands{0},reads{0};std::atomic<bool>release{false};Json request;
   std::string get(const std::string&)override{assert(false);return {};}
   std::string post(const std::string&path,const std::string&body)override{
    auto args=Json::parse(body);
    if(path=="/printer/wmp/recovery/retire_review"){
     ++reviews;request=args;request["version"]=1;
     request["evidence"]={{"manifest",Json::object()},{"receipt",Json::object()},{"fingerprint",std::string(64,'a')}};
     return Json{{"result",{{"request",request}}}}.dump();
    }
    if(path=="/printer/gcode/script"){++commands;while(!release.load())std::this_thread::yield();assert(args.at("script")==recovery_retirement_script(request,request));return "{\"result\":\"ok\"}";}
    assert(path=="/printer/wmp/recovery/retire_result");++reads;
    return Json{{"result",{{"session",args.at("session")},{"result",{{"id",args.at("id")},{"session",request.at("session")},
     {"state","complete"},{"archive",std::string(64,'b')},{"fingerprint",std::string(64,'a')}}}}}}.dump();
   }
  } control;
  Http status;status.ace_present=false;Port clock;wmp_openace::UiChannel c;Runtime r(status,clock,c);
  r.enable_recovery(control,control,control);
  status.extra_status["wm_material"]={{"session_id","invalid-session"},{"afc_metadata",{{"owner","standalone"}}},
    {"recovery_retirement_protocol",1},{"recovery_restore_error","Saved recovery requires review: invalid journal"}};
  unsigned dismissed=0;
  if(native_cancel){status.extra_status["wm_material"]["recovery_restore_error"]="";
   assert(r.request_native_discard([&]{++dismissed;}));assert(r.native_discard_active());}
  r.worker_step(clock.now);r.gui_step();assert(r.active()&&control.commands==0&&control.reviews<=1);
  auto*root=fake::top->children.back();auto count=fake::nodes.size();
  auto caption=[&](const std::string&text){for(auto*b:root->children)if(!(b->flags&1))for(auto*l:b->children)if(l->text==text)return b;return static_cast<fake::Node*>(nullptr);};
  assert(!caption("REVIEW"));
  if(!native_cancel){
   assert(caption("BACK")&&!caption("DISCARD")&&control.reviews==0&&control.commands==0);
   fake::send(caption("BACK"),7);assert(!r.active());continue;
  }
  auto end=std::chrono::steady_clock::now()+std::chrono::seconds(3);
  while(!caption(native_cancel?"CANCEL":"CLOSE")||!caption("DISCARD")){
   assert(std::chrono::steady_clock::now()<end);r.gui_step();std::this_thread::yield();
  }
  assert(caption(native_cancel?"CANCEL":"CLOSE")&&caption("DISCARD")&&control.commands==0&&control.reviews==1);
  if(native_cancel){
   fake::send(caption("CANCEL"),7);r.gui_step();
   assert(!r.active()&&!r.native_discard_active()&&dismissed==0&&control.commands==0);
   assert(r.request_native_discard([&]{++dismissed;}));r.gui_step();root=fake::top->children.back();count=fake::nodes.size();
   assert(!caption("REVIEW"));
   end=std::chrono::steady_clock::now()+std::chrono::seconds(3);
   while(!caption("CANCEL")&&std::chrono::steady_clock::now()<end){r.gui_step();std::this_thread::yield();}
   assert(caption("CANCEL")&&control.reviews==2);
  }
  auto*action=caption("DISCARD");fake::send(action,7);fake::send(action,7);
  if(native_cancel){
   r.gui_step();assert(caption("CLOSE"));fake::send(caption("CLOSE"),7);
   assert(!r.active()&&!r.native_discard_active()&&dismissed==0);
   control.release=true;
   end=std::chrono::steady_clock::now()+std::chrono::seconds(3);
   while(control.reads.load()==0&&std::chrono::steady_clock::now()<end){r.gui_step();std::this_thread::yield();}
   r.gui_step();assert(!r.active()&&dismissed==0&&control.commands==1&&control.reads==1);
   continue; // Closing did not acknowledge, repeat, or cancel the dispatched request.
  }
  control.release=true;
  end=std::chrono::steady_clock::now()+std::chrono::seconds(3);bool done=false;
  while(!done&&std::chrono::steady_clock::now()<end){r.gui_step();for(const auto&n:fake::nodes)if(n->live&&n->text.find("Saved print discarded.")!=std::string::npos)done=true;std::this_thread::yield();}
  assert(dismissed==(native_cancel?1u:0u)&&!r.native_discard_active());
  assert(done&&control.commands==1&&control.reads==1&&fake::nodes.size()==count);
  status.extra_status["wm_material"]["recovery_restore_error"]="";clock.now+=1000;r.worker_step(clock.now);r.gui_step();
  assert(fake::nodes.size()==count&&control.commands==1);fake::send(caption("CLOSE"),7);r.gui_step();assert(!r.active());
 }
 // Automatic reads expose action-bound choices; only the selected button mutates.
 for(const auto&selected:std::vector<std::pair<std::string,std::string>>{{"DISCARD","discard-ticket"},{"USE SAVED","saved-ticket"}}){
  StockRecoveryProgress panel;unsigned reviews=0,confirms=0;
  panel.review_resolution=[&](const std::string&){++reviews;return true;};
  panel.confirm_resolution=[&](const std::string&id){assert(id==selected.second);++confirms;return true;};
  auto*parent=fake::make(fake::screen);
  Json result={{"id","held"},{"fresh",true},{"state","stopped"},{"resolution_available",true},
   {"receipt",{{"state","stopped"},{"stages",Json::array()}}}};
  assert(panel.open(parent,result));auto*root=parent->children.back();
  auto caption=[&](const std::string&text){for(auto*b:root->children)if(!(b->flags&1))for(auto*l:b->children)if(l->text==text)return b;return static_cast<fake::Node*>(nullptr);};
  assert(!caption("REVIEW")&&!caption("DISCARD")&&!caption("USE SAVED")&&reviews==0&&confirms==0);
  result["resolution"]["choices"]={{"abandon",{{"id","discard-ticket"},{"state","reviewed"},{"fresh",true}}},
   {"reconcile",{{"id","saved-ticket"},{"state","reviewed"},{"fresh",true}}}};
  panel.update(result);assert(caption("DISCARD")&&caption("USE SAVED")&&confirms==0&&reviews==0);
  auto*action=caption(selected.first);
  result["fresh"]=false;panel.update(result);fake::send(action,7);assert(confirms==0);
  result["fresh"]=true;panel.update(result);fake::send(action,7);fake::send(action,7);assert(confirms==1&&reviews==0);
  fake::send(caption("CLOSE"),7);assert(!panel.active()&&confirms==1);fake::del(parent);
 }
 // The stock Cancel route submits independently and reopens the same receipt.
 {
  fake::DeferredSizes deferred_layout;
  StockRecoveryProgress panel;unsigned reviews=0,confirms=0,refreshes=0,results=0;
  panel.review_retirement=[&]{++reviews;return true;};
  panel.confirm_retirement=[&](const std::string&id){assert(id=="discard-1");++confirms;return true;};
  panel.refresh_retirement=[&]{++refreshes;return true;};
  panel.show_retirement_result=[&]{++results;};
  auto*parent=fake::make(fake::screen);
  Json result={{"id","invalid-record"},{"fresh",true},{"state","review"},{"retirement_mode",true},
               {"retirement",{{"available",true}}}};
  assert(panel.open(parent,result));auto*root=parent->children.back();const auto count=fake::nodes.size();
  auto caption=[&](const std::string&text){for(auto*b:root->children)if(!(b->flags&1))for(auto*l:b->children)if(l->text==text)return b;return static_cast<fake::Node*>(nullptr);};
  auto*card=root->children.front();auto*title=root->children.at(1);assert(title->text=="Discard PLR");
  assert(root->w==800&&root->h==480&&(root->flags&2));
  assert(card->w==704&&card->h==260&&card->x==48&&card->y==110);
  assert(caption("CLOSE")->w==160&&caption("CLOSE")->h==56);
  auto*large_caption=caption("CLOSE")->children.front();
  assert(large_caption->font_address==MyriadPro_Bold_24&&large_caption->h==40);
  assert(title->font_address==MyriadPro_Regular_22&&root->background_opacity==0);
  assert(caption("CLOSE")->y+56<=card->y+card->h);
  auto stage_colour=[&](const std::string&text){
   for(const auto&node:fake::nodes)if(node->live&&!(node->flags&1)&&node->text==text)return node->text_color;
   return std::uint32_t(0);
  };
  assert(stage_colour("Checking saved print...")!=0U); // Current summary, not a numbered stage.
  assert(stage_colour("Discard saved PLR")==0U);
  assert(stage_colour("Verify archived result")==0U);
  result["retirement_mode"]=false;panel.update(result);assert(title->text=="Power Loss Recovery (PLR)");
  result["retirement_mode"]=true;panel.update(result);assert(title->text=="Discard PLR"&&fake::nodes.size()==count);
  result["retirement_previous"]=true;panel.update(result);assert(!caption("RESULT")&&!caption("REVIEW"));
  assert(results==0&&reviews==0&&confirms==0&&refreshes==0);
  result["retirement_previous"]=false;panel.update(result);
  assert(!caption("REVIEW")&&reviews==0&&confirms==0);
  result["retirement"]={{"id","discard-1"},{"available",true},{"fresh",true},{"state","reviewed"},{"request",Json::object()},
                         {"message","Discard recovery for this saved print?"}};
  panel.update(result);panel.update(result);assert(fake::nodes.size()==count&&confirms==0);
  result["state"]="refused";result["message"]="Checkpoint hash changed: selected A does not match.";
  panel.update(result);assert(title->text=="Power Loss Recovery (PLR)"&&caption("DISCARD")&&caption("CLOSE")&&!caption("CANCEL"));
  bool refusal_visible=false;for(const auto&node:fake::nodes)if(node->live&&node->text.find("Checkpoint hash changed: selected A does not match.")!=std::string::npos)refusal_visible=true;
  assert(refusal_visible&&confirms==0);
  result["state"]="review";result.erase("message");panel.update(result);
  auto*action=caption("DISCARD");assert(action&&caption("CANCEL"));
  assert(stage_colour("Checking saved print...")==0U);
  assert(stage_colour("Discard saved PLR")==0U);
  result["retirement"]["available"]=false;panel.update(result);fake::send(action,7);assert(confirms==0);
  result["retirement"]["available"]=true;panel.update(result);fake::send(action,7);fake::send(action,7);assert(confirms==1);
  result["retirement"]["state"]="unknown";panel.update(result);assert(!caption("REFRESH"));
  assert(stage_colour("Verify archived result")==0U); // Compact confirmation has no bookkeeping stages.
  assert(refreshes==0&&confirms==1);
  result["message"]="Closing this review keeps the saved print.";
  result["retirement"]["state"]="complete";panel.update(result);assert(action->state&128);
  for(const auto*name:{"Checking saved print...","Discard saved PLR","Verify archived result"})
   assert(stage_colour(name)==0U);
  for(const auto&node:fake::nodes)if(node->live)assert(node->text.find("Closing this review keeps the saved print.")==std::string::npos);
  fake::send(action,7);assert(confirms==1&&refreshes==0);
  fake::send(caption("CLOSE"),7);assert(!panel.active());fake::del(parent);
 }
 // The stock Cancel route submits independently and reopens the same receipt.
 {
  struct CancelHttp:wmp_openace::HttpPort {
   std::atomic<unsigned>posts{0};
   std::string get(const std::string&)override{assert(false);return {};}
   std::string post(const std::string&path,const std::string&body)override{
    auto request=Json::parse(body);++posts;
    if(path=="/printer/wmp/print/cancel_review"){request["token"]=std::string(32,'a');return Json{{"result",{{"request",request}}}}.dump();}
    assert(path=="/printer/wmp/print/cancel");request.erase("token");request["state"]="pending";return Json{{"result",request}}.dump();
   }
  } control;
  Http status;status.ace_present=false;Port clock;wmp_openace::UiChannel c;Runtime r(status,clock,c);r.enable_print_cancel(control);
  status.extra_status["wm_material"]={{"session_id","cancel-session"},{"afc_metadata",{{"owner","standalone"}}},{"print_cancel_protocol",1}};
  status.extra_status["print_stats"]={{"filename","cancel.gcode"},{"state","paused"}};
  r.worker_step(clock.now);assert(r.route_print_cancel());assert(!r.active());r.gui_step();assert(r.active());
  auto*root=fake::top->children.back();const auto count=fake::nodes.size();assert(r.route_print_cancel());r.gui_step();assert(fake::nodes.size()==count);
  auto end=std::chrono::steady_clock::now()+std::chrono::seconds(3);
  while(control.posts.load()<2&&std::chrono::steady_clock::now()<end)std::this_thread::yield();
  assert(control.posts==2);
  fake::Node*close=nullptr;for(auto*b:root->children)for(auto*l:b->children)if(l->text=="CLOSE")close=b;
  assert(close);fake::send(close,7);assert(!r.active());r.gui_step();assert(!r.active());
  assert(r.route_print_cancel());r.gui_step();assert(r.active()&&control.posts==2);fake::del(fake::top->children.back());
 }
 // A new Stop must supersede an older unknown result even when the old
 // resolution snapshot is stale. Later completion updates the NEW panel.
 for(bool stale_resolution:{false,true})for(bool close_old:{false,true}){
  struct CancelHistoryHttp:wmp_openace::HttpPort{
   std::string get(const std::string&)override{assert(false);return {};}
   std::string post(const std::string&path,const std::string&body)override{
    auto request=Json::parse(body);
    if(path=="/printer/wmp/print/cancel_resolve_review")throw std::runtime_error("old review unavailable");
    if(path=="/printer/wmp/print/cancel_review"){request["token"]=std::string(32,'a');return Json{{"result",{{"request",request}}}}.dump();}
    assert(path=="/printer/wmp/print/cancel");request.erase("token");request["state"]="pending";return Json{{"result",request}}.dump();
   }
  } control;
  Http status;Port clock;wmp_openace::UiChannel channel;Runtime runtime(status,clock,channel);
  runtime.enable_print_cancel(control);runtime.enable_print_cancel_resolution(control);
  Json helper={{"session_id","current"},{"afc_metadata",{{"owner","standalone"}}},{"print_cancel_protocol",1},{"print_cancel_resolution_protocol",1},
   {"print_cancel",{{"id","old-cancel"},{"session","old-session"},{"file","old.gcode"},{"state","unknown"},{"message","old SD cancellation was not confirmed"}}}};
  RuntimeReceiptTest::cancel_observe(runtime,helper,{{"state","cancelled"},{"filename","old.gcode"}},true);
  runtime.gui_step();assert(RuntimeReceiptTest::cancel_tracks(runtime,"old-cancel"));
  if(close_old)RuntimeReceiptTest::close_cancel(runtime);
  const Json printing={{"state","printing"},{"filename","new.gcode"}};
  RuntimeReceiptTest::cancel_observe(runtime,helper,printing,!stale_resolution);
  assert(runtime.route_print_cancel());const auto id=RuntimeReceiptTest::cancel_result(runtime).value("id","");assert(!id.empty()&&id!="old-cancel");
  runtime.gui_step();assert(RuntimeReceiptTest::cancel_tracks(runtime,id));
  // Old history stays ignored on subsequent ticks, not only the opening tick.
  runtime.gui_step();assert(RuntimeReceiptTest::cancel_tracks(runtime,id));
  auto end=std::chrono::steady_clock::now()+std::chrono::seconds(3);
  while(RuntimeReceiptTest::cancel_result(runtime).value("delivery_pending",false)&&std::chrono::steady_clock::now()<end)std::this_thread::yield();
  auto completed=RuntimeReceiptTest::cancel_result(runtime);completed["state"]="complete";completed["message"]="Print cancelled";
  helper["print_cancel"]=completed;
  RuntimeReceiptTest::cancel_observe(runtime,helper,{{"state","cancelled"},{"filename","new.gcode"}},true);
  runtime.gui_step();assert(RuntimeReceiptTest::cancel_tracks(runtime,id));
  bool done=false,old=false;for(const auto&node:fake::nodes)if(node->live){
   if(node->text.find("Print cancelled.")!=std::string::npos)done=true;
   if(node->text.find("old SD cancellation was not confirmed")!=std::string::npos)old=true;
  }
  assert(done&&!old);RuntimeReceiptTest::close_cancel(runtime);
 }
 // Restored cancellation holds open once without delivery; review and confirmation
 // are separate actions, and completion updates the retained panel in place.
 {
  struct ResolutionHttp:wmp_openace::HttpPort {
   std::atomic<unsigned>reviews{0},commands{0},intents{0};Json request;
   std::string get(const std::string&)override{assert(false);return {};}
   std::string post(const std::string&path,const std::string&body)override{
    if(path=="/printer/wmp/print/cancel_resolve_review"){
     request=Json::parse(body);request["token"]=std::string(32,'a');request["action"]="discard_saved_job";request["job_id"]="saved-job";
     ++reviews;return Json{{"result",{{"request",request},{"file","held.gcode"},{"message","Discard the reviewed saved job"}}}}.dump();
    }
    assert(path=="/printer/gcode/script");if(Json::parse(body).value("script","")=="CANCEL_PRINT"){++intents;return "{}";}++commands;return "{}";
   }
  } resolution;
  Http status;status.ace_present=false;Port clock;wmp_openace::UiChannel c;Runtime r(status,clock,c);
  r.enable_print_cancel(resolution);r.enable_print_cancel_resolution(resolution);
  auto record=Json{{"id","held-cancel"},{"session","old-session"},{"file","held.gcode"},{"state","unknown"},{"stages",Json::array()}};
  status.extra_status["wm_material"]={{"session_id","current"},{"afc_metadata",{{"owner","standalone"}}},
   {"print_cancel_protocol",1},{"print_cancel_resolution_protocol",1},{"print_cancel",record}};
  fake::top->pending_layout=true;r.worker_step(clock.now);r.gui_step();assert(!r.active());
  fake::top->pending_layout=false;r.gui_step();assert(r.active()&&resolution.commands==0);
  auto*root=fake::top->children.back();const auto count=fake::nodes.size();
  auto caption=[&](const std::string&text){for(auto*b:root->children)for(auto*l:b->children)if(l->text==text)return b;return static_cast<fake::Node*>(nullptr);};
  assert(!caption("REVIEW"));
  auto end=std::chrono::steady_clock::now()+std::chrono::seconds(3);
  while(!caption("DISCARD")&&std::chrono::steady_clock::now()<end){r.gui_step();std::this_thread::yield();}
  assert(caption("DISCARD")&&resolution.reviews==1&&resolution.commands==0&&fake::nodes.size()==count);
  // A visible reviewed action loses authority on disconnect, even when its
  // retained button receives a queued click. Reconnection updates in place.
  auto*reviewed_button=caption("DISCARD");
  status.extra_status["webhooks"]={{"state","shutdown"}};
  clock.now+=1000;r.worker_step(clock.now);r.gui_step();
  assert(fake::nodes.size()==count&&r.active());
  fake::send(reviewed_button,7);assert(resolution.commands==0&&resolution.reviews==1);
  status.extra_status["webhooks"]={{"state","ready"}};
  clock.now+=1000;r.worker_step(clock.now);r.gui_step();
  assert(caption("DISCARD")==reviewed_button&&fake::nodes.size()==count);
  // CLOSE dismisses the panel, not the durable hold. Status must not reopen
  // it; explicit reopening retains the read-only review without resubmission.
  fake::send(caption("CLOSE"),7);r.gui_step();assert(!r.active());
  clock.now+=1000;r.worker_step(clock.now);r.gui_step();assert(!r.active());
  assert(r.route_print_cancel());r.gui_step();assert(r.active());
  root=fake::top->children.back();const auto reopened_count=fake::nodes.size();
  assert(caption("DISCARD")&&resolution.reviews==1&&resolution.commands==0);
  auto*confirm=caption("DISCARD");fake::send(confirm,7);fake::send(confirm,7);
  while(resolution.commands==0&&std::chrono::steady_clock::now()<end)std::this_thread::yield();
  assert(resolution.commands==1);
  auto receipt=resolution.request;receipt["state"]="complete";receipt["message"]="Print cancellation resolved";
  status.extra_status["wm_material"]["print_cancel_resolution"]=receipt;
  status.extra_status["wm_material"]["print_cancel"]["state"]="complete";
  clock.now+=1000;r.worker_step(clock.now);r.gui_step();assert(fake::nodes.size()==reopened_count);
  bool complete=false;for(const auto&n:fake::nodes)if(n->live&&n->text.find("Print cancelled.")!=std::string::npos)complete=true;
  assert(complete);
  // An older hold must not undo completed cleanup in the retained view.
  status.extra_status["wm_material"]["print_cancel"]=record;
  clock.now+=1000;r.worker_step(clock.now);r.gui_step();
  complete=false;for(const auto&n:fake::nodes)if(n->live&&n->text.find("Print cancelled.")!=std::string::npos)complete=true;
  assert(complete&&fake::nodes.size()==reopened_count&&resolution.commands==1);
  // A new backend session must re-evaluate the durable record instead.
  status.extra_status["wm_material"]["session_id"]="replacement";
  clock.now+=1000;r.worker_step(clock.now);r.gui_step();
  clock.now+=1000;r.worker_step(clock.now);r.gui_step();
  bool unknown=false;for(const auto&n:fake::nodes)if(n->live&&n->text.find("Cancellation could not be confirmed.")!=std::string::npos)unknown=true;
  assert(unknown&&resolution.commands==1);
  fake::send(caption("CLOSE"),7);r.gui_step();assert(!r.active()&&resolution.commands==1);
 }
 // Cancellation states use plain outcomes, preserve details, and never offer a
 // manual read-only Review. An observed stopped file is not completed docking.
 {
  StockRecoveryProgress panel;auto*parent=fake::make(fake::screen);
  Json receipt={{"state","unknown"},{"stages",Json::array({{{"name","draining"},{"state","failed"}},{{"name","cooling"},{"state","complete"}},{{"name","cancelling"},{"state","pending"}}})}};
  Json result={{"kind","print_cancel"},{"id","cancel-1"},{"state","unknown"},{"fresh",true},{"receipt",receipt},{"message","Original failure"}};
  assert(panel.open(parent,result));auto*root=parent->children.back();
  auto contains=[&](const std::string&value){for(const auto&n:fake::nodes)if(n->live&&n->parent&&n->text.find(value)!=std::string::npos)return n.get();return static_cast<fake::Node*>(nullptr);};
  auto*summary=contains("Cancellation could not be confirmed.");assert(summary);
  assert(summary->text.find("Original failure")!=std::string::npos);
  assert(!contains("Waiting for movement to stop..."));
  const auto count=fake::nodes.size();const auto writes=fake::text_writes;summary->parent->scroll=60;
  for(int i=0;i<100;++i)panel.update(result);
  assert(fake::text_writes==writes&&fake::nodes.size()==count&&summary->parent->scroll==60);
  result["fresh"]=false;panel.update(result);assert(contains("Waiting for printer status...")&& !contains("Printer status unavailable"));
  result["fresh"]=true;result["receipt"]["stages"][2]["state"]="complete";panel.update(result);
  assert(contains("Cancellation could not be confirmed."));
  result["state"]="running";panel.update(result);
  auto*running=contains("Cancelling...");assert(running&&running->text=="Cancelling...");
  result["state"]="complete";panel.update(result);assert(contains("Print cancelled."));
  // The stop point extends the existing summary label; it adds no widget and
  // is written once. Non-string or empty labels are ignored.
  {
   auto stopped=[&](const Json&point){result["receipt"]["stop_point"]=point;panel.update(result);return contains("Stopped at:");};
   assert(!stopped(5)&&!stopped({{"phase","homed"},{"label",5}})&&!stopped({{"phase","homed"},{"label",""}}));
   assert(!stopped({{"phase","homed"},{"label",std::string(161,'x')}}));
   const auto nodes=fake::nodes.size();
   auto*line=stopped({{"phase","homed"},{"label","after homing"},{"state","x"}});
   assert(line&&line==summary&&line->text.find("Stopped at: after homing")!=std::string::npos);
   assert(line->text.find("Print cancelled.")!=std::string::npos&&fake::nodes.size()==nodes);
   const auto stable=fake::text_writes;for(int i=0;i<100;++i)panel.update(result);
   assert(fake::text_writes==stable);
   result["receipt"].erase("stop_point");panel.update(result);assert(!contains("Stopped at:"));
  }
  fake::Node*close=nullptr;for(auto*b:root->children)for(auto*l:b->children)if(l->text=="DONE")close=b;
  assert(close);fake::send(close,7);assert(!panel.active());panel.update(result);assert(!panel.active());fake::del(parent);
 }
 // Terminal recovery/discard history survives stale status without enabling actions.
 {
  StockRecoveryProgress panel;auto*parent=fake::make(fake::screen);
  Json result={{"id","terminal-history"},{"state","complete"},{"fresh",true}};
  assert(panel.open(parent,result));auto*root=parent->children.back();
  auto contains=[&](const std::string&value){for(const auto&n:fake::nodes)if(n->live&&n->text==value)return true;return false;};
  assert(contains("PLR complete."));
  result["fresh"]=false;panel.update(result);assert(contains("PLR complete."));
  assert(!contains("Waiting for printer status..."));
  result["state"]="abandoned";panel.update(result);assert(contains("Saved PLR discarded."));
  result["retirement_mode"]=true;result["retirement"]={{"state","complete"},{"available",false}};
  panel.update(result);assert(contains("Saved print discarded."));
  result.erase("retirement_mode");result.erase("retirement");
  for(const char*state:{"pending","running","paused","printing","unknown"}){
   result["state"]=state;panel.update(result);assert(contains("Waiting for printer status..."));
   for(auto*b:root->children)for(auto*l:b->children)
    if(l->text=="STOP"||l->text=="DISCARD"||l->text=="USE SAVED"||l->text=="CONFIRM")
     assert((b->flags&1)||(b->state&128));
  }
  panel.close();fake::del(parent);
 }
 // Recovery review is numbered even before an attempt receipt exists.
 {
  StockRecoveryProgress panel;auto*parent=fake::make(fake::screen);
  parent->flags|=1; // Native Continue hides the overlay before handoff.
  Json result={{"id","review-only"},{"state","pending"},{"fresh",true},{"message","Reviewing saved recovery"}};
  assert(panel.open(parent,result));
  auto find=[&](const std::string&value){for(const auto&n:fake::nodes)if(n->live&&n->text==value)return n.get();return static_cast<fake::Node*>(nullptr);};
  assert(!(parent->flags&1));
  auto*step=find("1. Check saved print");assert(step&&step->text_color==0xffff6600U);
  const auto count=fake::nodes.size();step->parent->scroll=30;
  result["state"]="refused";result["message"]="Saved format lacks required coordinates";panel.update(result);
  assert((step->flags&1)&&find("PLR could not start.\nSaved format lacks required coordinates"));
  assert(fake::nodes.size()==count&&step->parent->scroll==30);
  result["state"]="pending";result["review"]=Json::object();panel.update(result);
  assert(find("1. Check saved print")==step&&step->text_color==0xff888888U);
  assert(find("2. Prepare printer")->text_color==0xffff6600U);
  result["review"]["fan_warnings"]=Json::array({"Missing optional auxiliary_fan"});panel.update(result);
  assert(find("Power Loss Recovery in progress...\nOptional cooling fans unavailable; their settings will not be restored."));
  assert(fake::nodes.size()==count&&step->parent->scroll==30);
  result["review"]["fan_warnings"]=Json::array();panel.update(result);
  assert(find("Power Loss Recovery in progress...")&&!find("Power Loss Recovery in progress...\nOptional cooling fans unavailable; their settings will not be restored."));

  assert(fake::nodes.size()==count);fake::del(parent);assert(!panel.active());
 }
 // Recovery progress retains widgets through live, stale and terminal updates.
 {
  StockRecoveryProgress panel;unsigned stops=0;panel.stop=[&]{++stops;return true;};
  auto*parent=fake::make(fake::screen);
  Json result={{"id","recovery-1"},{"state","running"},{"fresh",true},{"receipt",{{"state","running"},
   {"stages",Json::array({{{"name","context"},{"state","complete"}},{{"name","heating"},{"state","running"}},{{"name","wipe"},{"state","pending"}}})}}},
   {"temperatures",{{"extruder2",{{"temperature",183.4},{"target",220}}}}}};
  assert(panel.open(parent,result));auto*root=parent->children.back();
  auto find=[&](const std::string&value){for(const auto&n:fake::nodes)if(n->live&&n->text==value)return n.get();return static_cast<fake::Node*>(nullptr);};
  auto*stop=find("STOP")->parent;auto*close=find("CLOSE")->parent;auto*heat=find("3. Heat bed and nozzles");
  assert(find("1. Check saved print")->text_color==0xff888888U);
  assert(root->background_opacity==255&&find("2. Prepare printer")->text_color==0xff888888U);
  assert(heat->text_color==0xffff6600U&&!(heat->flags&1));
  assert(!(find("4. Prime and wipe")->flags&1)&&find("4. Prime and wipe")->text_color==0xffeeeeeeU);
  auto*body=heat->parent;body->scroll=80;const auto count=fake::nodes.size();
  result["temperatures"]["extruder"]={{"temperature",30},{"target",0}};
  result["temperatures"]["extruder2"]["temperature"]=219.8;panel.update(result);
  assert(find("3. Heat bed and nozzles")==heat&&body->scroll==80&&fake::nodes.size()==count);
  bool temperature=false;for(const auto&n:fake::nodes)if(n->live&&n->text.find("Head 3: 220 / 220 C")!=std::string::npos)temperature=true;
  for(const auto&n:fake::nodes)if(n->live)assert(n->text.find("Head 1:")==std::string::npos&&n->text.find("extruder")==std::string::npos);
  assert(temperature);result["fresh"]=false;panel.update(result);fake::send(stop,7);assert(stops==0&&(stop->state&128));
  result["fresh"]=true;panel.update(result);fake::send(stop,7);fake::send(stop,7);assert(stops==1&&(stop->state&128));
  result["stop"]="requested";result["state"]="stopped";result["receipt"]["state"]="stopped";panel.update(result);
  assert(fake::nodes.size()==count&&panel.active());fake::send(close,7);assert(!panel.active()&&stops==1);
  panel.update(result);assert(!panel.active()); // status does not reopen dismissed views
  assert(panel.open(parent,result));fake::del(parent);assert(!panel.active());panel.close();
 }
 // Print preparation shows measurements, not a duplicate step title.
 {
  Json prep={{"phase","mesh"},{"steps",Json::array({{{"phase","mesh"},{"label","Prepare bed mesh"}}})},{"mesh_progress",{{"point",7},{"total",36}}}};
  auto view=print_preparation_view({{"print_preparation",prep}});
  assert(view["value"]=="Probing point 7 of 36");
  prep["phase"]="bed";prep["temperatures"]={{"bed",{{"actual",43.5},{"target",60.}}}};
  view=print_preparation_view({{"print_preparation",prep}});assert(view["value"]=="Bed: 43 / 60 C");
 }
 // Stock prefix heating precedes the Resume checks; do not claim they ran.
 {
  const auto view=resume_progress_view({{"fresh",true},{"resume_progress",{{"phase","preheating"}}}});
  assert(view["steps"].size()==1&&view["steps"][0]["label"]=="Preheat nozzle"&&view["steps"][0]["state"]=="running");
 }
 // PLR groups are complete only when every reported constituent completed.
 {
  const auto rows=plr_progress_steps(Json::array({{{"name","review"},{"state","complete"}},{{"name","home_xy"},{"state","failed"}},{{"name","select_head"},{"state","complete"}},{{"name","heating"},{"state","running"}},{{"name","return_xy"},{"state","complete"}},{{"name","return_z"},{"state","pending"}}}));
  assert(rows.size()==5&&rows[0]["state"]=="complete"&&rows[1]["label"]=="Home X/Y"&&rows[1]["state"]=="failed"&&rows[2]["label"]=="Select print head"&&rows[2]["state"]=="complete"&&rows[3]["state"]=="running"&&rows[4]["state"]=="pending");
  assert(plr_progress_steps(Json::array()).empty());
 }
 // Shared progress layout retains decision controls and has no operation state.
 {
  auto*parent=fake::make(fake::screen);StockProgressPanel panel;
  assert(panel.attach(parent,0,0,680,320));
  auto*choices=static_cast<fake::Node*>(panel.choices_parent());auto*decision=fake::make(choices);
  Json view={{"steps",Json::array({{{"label","Prepare"},{"state","complete"}},{{"label","Head 3"},{"state","running"}},{{"label","Finish"},{"state","pending"}}})},{"instruction","Insert filament, then continue."},{"decisions",true}};
  panel.update(view);const auto count=fake::nodes.size();
  assert(choices->parent->parent->x>0&&decision->live&&!(choices->flags&1));
  panel.update(view);assert(fake::nodes.size()==count&&panel.choices_parent()==choices&&decision->live);
  auto*root=choices->parent->parent->parent;auto*steps=root->children[1];
  assert(steps->children[0]->text=="1. Prepare"&&steps->children[0]->text_color==0xff888888U);
  assert(steps->children[1]->text_color==0xffff6600U&&steps->children[2]->text_color==0xffeeeeeeU);
  const auto row_layouts=steps->children[0]->layout_updates;
  view["instruction"]="127 / 160 C";panel.update(view);
  assert(steps->children[0]->layout_updates==row_layouts);
  view["steps"][1]["state"]="failed";panel.update(view);
  assert(steps->children[1]->text_color==0xffff6666U);
  view["steps_width"]=200;panel.update(view);assert(steps->w==200);
  view["steps_width"]=9999;panel.update(view);assert(steps->w==520);
  auto malformed=view;malformed["steps"]=Json::object();panel.update(malformed);
  assert(steps->children[1]->text_color==0xffff6666U&&steps->w==520);
  view["instruction"]="";view["decisions"]=false;panel.update(view);
  assert(steps->w==680&&(choices->parent->parent->flags&1)&&decision->live);
  view["steps"][1]["state"]="running";view["heading"]="Head 3";view["instruction"]="Head 3...";panel.update(view);
  assert(steps->w==680&&(choices->parent->parent->flags&1));
  view["value"]="120 / 160 C";panel.update(view);
  assert(steps->w<680&&!(choices->parent->parent->flags&1));
  view["value"]="";view["note"]="The nozzle is hot.";panel.update(view);
  assert(steps->w<680&&!(choices->parent->parent->flags&1));
  view["note"]="";view["heading"]="";view["instruction"]="";
  view["steps"]=Json::array();view["instruction"]="Print cancelled.";panel.update(view);
  assert((steps->flags&1)&&choices->parent->parent->x==0&&choices->parent->parent->w==680);
  fake::del(parent);assert(!panel.attached()&&!panel.choices_parent());panel.close();
 }
 // Resume uses shared progress and leaves removal to the stock popup.
 {
  auto*popup=fake::make(fake::top);popup->w=770;popup->h=380;auto*short_row=fake::make(popup);short_row->w=700;short_row->h=140;auto*label=static_cast<fake::Node*>(fake::make_label(short_row));label->text="Resuming print...";
  StockResumeProgress panel;
  auto progress=data;progress["owner"]="standalone";progress["fresh"]=true;
  progress["resume_progress"]={{"phase","heating"}};
  progress["heads"]=Json::array({{{"id","h2"},{"actual",160},{"target",220}}});
  panel.update(progress);const auto count=fake::nodes.size();
  auto find=[&](const std::string&text){for(const auto&n:fake::nodes)if(n->live&&n->text==text)return n.get();return static_cast<fake::Node*>(nullptr);};
  assert(find("2. Heat bed and nozzle")&&find("Head 3: 160 / 220 C"));
  assert(find("2. Heat bed and nozzle")->text_color==0xffff6600U);
  assert(find("3. Return to print")->parent->parent->parent==popup);
  assert(find("3. Return to print")->parent->h>=240);
  panel.update(progress);assert(fake::nodes.size()==count);
  progress["resume_progress"]["phase"]="returning";panel.update(progress);
  assert(find("3. Return to print")->text_color==0xffff6600U);
  progress["fresh"]=false;panel.update(progress);assert(find("Waiting for printer status..."));
  progress["fresh"]=true;progress["resume_progress"]=Json::object();panel.update(progress);assert(find("Preparing to resume..."));
  fake::del(popup);panel.update(progress);assert(!label->live&&fake::nodes.size()==count);
  popup=fake::make(fake::top);label=static_cast<fake::Node*>(fake::make_label(popup));label->text="Unrelated popup";
  const auto unrelated_count=fake::nodes.size();panel.update(progress);assert(fake::nodes.size()==unrelated_count);
  label->text="Resuming print...";progress["owner"]="openace";panel.update(progress);assert(fake::nodes.size()==unrelated_count);
  fake::del(popup);
 }
 // A paused empty head gets one review invitation, never automatic service.
 {
  fake::DeferredSizes deferred_layout;
  StockPausePrompt prompt;unsigned reviews=0,selected=99;
  prompt.review=[&](unsigned head){++reviews;selected=head;};
  auto paused=data;paused["fresh"]=true;paused["owner"]="standalone";paused["session"]="prompt-session";
  paused["job"]={{"state","paused"}};paused["filament_operation"]=Json::object();paused["toolhead_operation"]=Json::object();
  paused["heads"]=Json::array({{{"id","h2"},{"loaded",{{"state","empty"}}}}});
  paused["paused_filament"]={{"available",true},{"head","h2"},{"serviced",false},
   {"origin",{{"head","h2"},{"session","prompt-session"},{"id",std::string(32,'c')},{"file_position",120}}}};
  auto title=[&](){for(const auto&n:fake::nodes)if(n->live&&n->text=="Filament needed - Head 3")return n.get();return static_cast<fake::Node*>(nullptr);};
  auto button=[&](const std::string&caption){auto*t=title();if(!t)return static_cast<fake::Node*>(nullptr);for(auto*b:t->parent->children)for(auto*l:b->children)if(l->live&&l->text==caption)return b;return static_cast<fake::Node*>(nullptr);};
  prompt.update(paused);assert(title()&&button("LOAD")&&button("CANCEL")&&reviews==0);
  auto*card=title()->parent;auto*overlay=card->parent;
  assert(title()->text_color==0xffeeeeeeU);
  assert(button("CANCEL")->children[0]->text_color==0xffeeeeeeU);
  for(auto*n:card->children)for(auto*l:n->children)if(l->text.find("The print is paused.")==0)assert(l->text_color==0xffeeeeeeU);
  assert(card->w<=560&&card->h<=280&&card->x==(fake::screen->w-card->w)/2&&card->y==(fake::screen->h-card->h)/2);
  assert(overlay->w==fake::screen->w&&overlay->h==fake::screen->h&&(overlay->flags&2)&&overlay->background_opacity==0);
  assert(title()->font_address==MyriadPro_Regular_22&&button("LOAD")->children[0]->font_address==MyriadPro_Bold_24&&button("LOAD")->children[0]->h==40);
  const auto count=fake::nodes.size();prompt.update(paused);assert(fake::nodes.size()==count);
  auto*retained=button("LOAD");auto stale=paused;stale["fresh"]=false;prompt.update(stale);
  assert(title()&&button("LOAD")==retained&&(retained->state&128)&&fake::nodes.size()==count);
  fake::send(retained,7);assert(title()&&reviews==0);
  prompt.update(paused);assert(title()&&button("LOAD")==retained&&!(retained->state&128)&&fake::nodes.size()==count);fake::send(button("CANCEL"),7);assert(!title()&&reviews==0);
  prompt.update(paused);assert(!title()); // dismissal survives repeated status
  paused["paused_filament"]["origin"]["id"]=std::string(32,'d');
  prompt.update(paused);assert(title());fake::send(button("LOAD"),7);assert(!title()&&reviews==1&&selected==2);
  prompt.update(paused);assert(!title());
  paused["paused_filament"]["origin"]["id"]=std::string(32,'e');
  prompt.update(paused,false);assert(!title());prompt.update(paused);assert(title());
  auto resumed=paused;resumed["job"]["state"]="printing";prompt.update(resumed);assert(!title());
  for(const auto&kind:{"owner","session","loaded","serviced","operation"}){
   auto invalid=paused;
   if(std::string(kind)=="owner")invalid["owner"]="openace";
   if(std::string(kind)=="session")invalid["session"]="new-session";
   if(std::string(kind)=="loaded")invalid["heads"][0]["loaded"]["state"]="loaded";
   if(std::string(kind)=="serviced")invalid["paused_filament"]["serviced"]=true;
   if(std::string(kind)=="operation")invalid["filament_operation"]={{"state","running"}};
   prompt.update(invalid);assert(!title());
  }
  for(const auto*key:{"filament_operation","toolhead_operation"})for(const auto*state:{"unknown","failed","pending","running"}){
   auto changed=paused;changed[key]={{"state",state},{"recovered",false}};
   prompt.update(changed);const bool historical=std::string(state)=="unknown"||std::string(state)=="failed";
   assert(bool(title())==historical&&reviews==1);
   if(historical){
    bool guidance=false;for(const auto&n:fake::nodes)if(n->live&&n->text.find("The previous operation needs attention.")==0)guidance=true;
    assert(guidance&&button("LOAD")&&!(button("LOAD")->state&128));
   }
  }
  prompt.update(paused);assert(title());auto*old=button("LOAD");
  auto*previous=fake::screen;fake::screen=fake::make(nullptr);fake::send(old,7);assert(reviews==1&&!title());fake::screen=previous;
  prompt.close();
 }
 // Progressive enhancement follows definitive ownership only on the visible page.
 {
  StockDiagnostics diagnostics;auto*about=fake::make(fake::screen);about->w=800;about->h=480;
  auto supported_mapping=data;supported_mapping["fresh"]=true;supported_mapping["owner"]="standalone";supported_mapping["print_start_protocol"]=1;supported_mapping["capabilities"].erase("start_print");
  assert(StockDiagnostics::describe(supported_mapping).find("Print mapping: Supported")!=std::string::npos);
  supported_mapping["status_age_ms"]=2855;assert(StockDiagnostics::describe(supported_mapping).find("Last status update: 2855 ms ago")!=std::string::npos);
  supported_mapping["owner"]="openace";supported_mapping["openace_print_start_protocol"]=0;
  assert(StockDiagnostics::describe(supported_mapping).find("Print mapping: Unavailable")!=std::string::npos);
  supported_mapping["openace_print_start_protocol"]=1;
  assert(StockDiagnostics::describe(supported_mapping).find("Print mapping: Supported")!=std::string::npos);
  auto*sidebar_wrapper=fake::make(about);sidebar_wrapper->w=800;sidebar_wrapper->h=480;
  auto*content=fake::make(about);content->w=670;content->h=340;
  auto*stock_label=fake::make(content);stock_label->text="Stock firmware information";
  about->pending_layout=sidebar_wrapper->pending_layout=content->pending_layout=true;
  diagnostics.created(about);diagnostics.update(data);
  auto find=[&](const std::string&text){for(const auto&n:fake::nodes)if(n->live&&n->text==text)for(auto*p=n->parent;p;p=p->parent)if(p==content)return n->parent;return static_cast<fake::Node*>(nullptr);};
  auto*entry=find("WM+");assert(entry&&stock_label->live);
  fake::send(entry,7);assert(find("WM+ diagnostics")&&find("CLOSE"));
  for(const auto&n:fake::nodes)if(n->live&&n->text==StockDiagnostics::describe(data))assert(n->h!=-1);
  const auto size=fake::nodes.size();diagnostics.update(data);assert(fake::nodes.size()==size);
  auto stale=data;stale["fresh"]=false;diagnostics.update(stale);
  assert(find(StockDiagnostics::describe(stale))&&StockDiagnostics::describe(stale).find("Load: Unknown")!=std::string::npos);
  assert(StockDiagnostics::describe(stale).find("Filament owner: Unavailable")!=std::string::npos);
  fake::send(find("CLOSE"),7);assert(!find("WM+ diagnostics")&&stock_label->live);
  about->flags|=1;fake::send(entry,7);assert(!find("WM+ diagnostics"));about->flags&=~1U;
  fake::send(entry,7);assert(find("WM+ diagnostics"));fake::del(about);diagnostics.update(data);assert(!diagnostics.open());
 }
 {
  wmp_openace::UiChannel setup_channel;Runtime setup(http,port,setup_channel);
  auto idle=data;idle["owner"]="standalone";idle["fresh"]=true;idle["job"]={{"state","idle"}};
  idle["filament_operation"]=Json::object();idle["toolhead_operation"]=Json::object();
  idle["calibration_session"]="setup-session";
  char setup_directory[]="/tmp/wmp-onboarding-XXXXXX";
  assert(::mkdtemp(setup_directory));
  const auto marker=std::string(setup_directory)+"/need_oobe";
  {std::ofstream file(marker);file<<"setup required\n";assert(file.good());}
  unsigned completed=0;std::string destination;bool writable=false;
  setup.set_stock_navigation([&](const char*name){destination=name;});
  setup.set_finish_onboarding([&](){++completed;return writable&&finish_setup(setup_directory);});
  assert(!setup.finish_onboarding()&&completed==0);
  assert(!setup.onboarding_file_navigation("filelist_local_page"));
  // Enter through the production successful checkpoint handoff rather than
  // bypassing the guide transition with begin_onboarding().
  std::vector<std::string> setup_commands;
  setup.set_calibration_sender([&](const std::string&command){setup_commands.push_back(command);return true;});
  wmp_openace::runtime.store(&setup);
  wmp_openace::unified_setup_filament_guide(nullptr);
  assert(setup.onboarding_active()); // Marker protected before checkpoint completion.
  wmp_openace::unified_retired_guide_worker();wmp_openace::unified_retired_guide_worker();
  wmp_openace::runtime.store(nullptr);
  setup.gui_step();assert(destination.empty()&&setup_commands.empty());
  RuntimeReceiptTest::adoption_status(setup,idle,Json::object(),port.now);
  setup.gui_step();assert(destination.empty()&&setup_commands.size()==1);
  assert(setup_commands.front().find("_WMP_CALIBRATION_COMMAND HEX=4d343030 TOKEN=")==0);
  assert(::access(marker.c_str(),F_OK)==0&&completed==0);
  setup.gui_step();assert(setup_commands.size()==1&&destination.empty());
  idle["calibration_checkpoint"]=setup_commands.front().substr(setup_commands.front().find("TOKEN=")+6);
  RuntimeReceiptTest::adoption_status(setup,idle,Json::object(),port.now);
  setup.gui_step();assert(destination.empty()); // checkpoint queues navigation for the next GUI tick
  setup.gui_step();assert(destination=="filament_page"&&setup_commands.size()==1);destination.clear();
  for(bool managed:{false,true})for(auto caller:{std::uintptr_t(0x4fd4d4),std::uintptr_t(0x4fd48c),std::uintptr_t(0x44a454)})
   for(const auto&command:{std::string("rm /home/t13dp/need_oobe -f"),std::string("rm /tmp/other -f"),std::string("rm /home/t13dp/need_oobe -f; echo changed")})
    assert(suppress_file_setup_completion(caller,command,managed)==(managed&&caller==0x4fd4d4&&command=="rm /home/t13dp/need_oobe -f"));
  assert(!setup.onboarding_file_navigation(nullptr));
  assert(!setup.onboarding_file_navigation("filament_page"));
  assert(!setup.onboarding_file_navigation("filelist_local_page"));
  assert(setup.onboarding_active()&&completed==0&&::access(marker.c_str(),F_OK)==0);
  // Failed guide result has a real BACK exit; it never invokes completion.
  assert(setup.calibration_navigation("guide_calibration_finish_page"));
  auto failed_setup=idle;failed_setup["calibration_failed"]="setup probe failed";
  RuntimeReceiptTest::adoption_status(setup,failed_setup,Json::object(),port.now);setup.gui_step();
  fake::Node*setup_back=nullptr;
  for(auto&node:fake::nodes)if(node->live&&node->text=="BACK"&&node->parent&&node->parent->parent==fake::screen->children.back())setup_back=node->parent;
  assert(setup_back);fake::send(setup_back,7);
  assert(destination=="main_page"&&completed==0&&::access(marker.c_str(),F_OK)==0);
  assert(setup.stock_maintenance_allowed()); // History cannot reserve movement after leaving.
  assert(!setup.onboarding_file_navigation("filelist_local_page")); // Files may open without completion.
  setup.gui_step();destination.clear();
  for(const auto*key:{"filament_operation","toolhead_operation"})for(const auto*state:{"pending","running","unknown","failed"}){
   auto busy=idle;busy[key]={{"state",state}};RuntimeReceiptTest::adoption_status(setup,busy,Json::object(),port.now);
   assert(!setup.finish_onboarding()&&completed==0);
  }
  // A recorded calibration failure is intentionally latched for this Runtime;
  // its restart-required case is covered separately above, not cleared here.
  for(const auto&patch:{Json{{"calibration_active",true}},Json{{"calibration_session",""}}}){
   auto bad=idle;bad.update(patch);RuntimeReceiptTest::adoption_status(setup,bad,Json::object(),port.now);
   assert(!setup.finish_onboarding()&&completed==0);
  }
  auto paused=idle;paused["job"]["state"]="paused";RuntimeReceiptTest::adoption_status(setup,paused,Json::object(),port.now);
  assert(!setup.finish_onboarding()&&completed==0);
  RuntimeReceiptTest::adoption_status(setup,idle,Json::object(),port.now-3000);
  assert(!setup.finish_onboarding()&&completed==0);
  RuntimeReceiptTest::adoption_status(setup,idle,Json::object(),port.now);
  assert(!setup.finish_onboarding()&&completed==1&&destination.empty());
  assert(::access(marker.c_str(),F_OK)==0);
  writable=true;assert(setup.finish_onboarding()&&completed==2&&destination=="main_page");
  assert(::access(marker.c_str(),F_OK)<0&&errno==ENOENT);
  assert(::rmdir(setup_directory)==0);
  assert(!setup.finish_onboarding()&&completed==2);setup.gui_step();assert(destination=="main_page");
  assert(!setup.onboarding_file_navigation("filelist_local_page"));
 }
 wmp_openace::UiChannel presence_channel;Runtime presence_runtime(http,port,presence_channel);
 // Stock service entry opens the same editor/review, never submits a command.
 for(unsigned selected=0;selected<4;++selected)for(bool loading:{true,false}){
  wmp_openace::UiChannel service_channel;Runtime service(http,port,service_channel);
  auto state=data;state["owner"]="standalone";state["fresh"]=true;state["units"]=Json::array();state["sources"]=Json::array();
  for(auto&head:state["heads"]){const auto id=head.at("id").get<std::string>();head["loaded"]={{"state",loading?"empty":"loaded"},{"source","external:"+id}};
   state["sources"].push_back({{"id","external:"+id},{"kind","external"},{"head",id},{"available",true},{"identity",{{"brand","Generic"},{"material","PLA"},{"color","#888888"}}}});}
  state["capabilities"]={{"load",true},{"unload",true},{"save_identity",true}};
  fake::Node*page=nullptr;unsigned navigation=0;
  service.set_stock_navigation([&](const char*name){assert(std::string(name)=="filament_page");++navigation;
   if(page)fake::del(page);
   page=fake::make(fake::screen);auto*content=fake::make(page);content->w=670;content->h=340;
   StockFilamentWidgets w;w.content=content;w.count=4;
   for(auto&slot:w.slots){slot.card=fake::make(content);slot.number=fake::make(slot.card);slot.colour=fake::make(slot.card);slot.material=fake::make(slot.card);slot.material_label=fake::make(slot.material);}
   RuntimeReceiptTest::attach(service,w,page,fake::make(content),fake::make(content));});
  RuntimeReceiptTest::adoption_status(service,state,Json::object(),port.now-3000);
  service.request_stock_service(selected,loading);service.gui_step();assert(navigation==0);
  RuntimeReceiptTest::adoption_status(service,state,Json::object(),port.now);
  service.gui_step();assert(navigation==0); // No replay when status recovers.
  service.request_stock_service(selected,loading);service.gui_step();service.gui_step();
  assert(navigation==(loading?2u:1u));
  if(loading)assert(RuntimeReceiptTest::ace_source(service).value("head","")=="h"+std::to_string(selected));
  else assert(RuntimeReceiptTest::procedure_active(service));
  assert(RuntimeReceiptTest::tool_receipt(service).empty());
  fake::del(page);
 }
 unsigned presence_navigation=0;fake::Node*presence_page=nullptr;
 std::vector<fake::Node*>presence_pages;
 presence_runtime.set_stock_navigation([&](const char*name){
  assert(std::string(name)=="filament_page");++presence_navigation;
  if(presence_page)presence_page->flags|=1;
  presence_page=fake::make(fake::screen);presence_pages.push_back(presence_page);
  auto*content=fake::make(presence_page);content->w=670;content->h=340;
  auto*actions=fake::make(content);auto*tips=fake::make(content);StockFilamentWidgets w;w.content=content;w.count=4;
  for(auto&slot:w.slots){slot.card=fake::make(content);slot.number=fake::make(slot.card);slot.colour=fake::make(slot.card);slot.material=fake::make(slot.card);slot.material_label=fake::make(slot.material);}
  RuntimeReceiptTest::attach(presence_runtime,w,presence_page,actions,tips);
 });
 RuntimeReceiptTest::adoption_status(presence_runtime,data,http.ace,port.now);
 presence_runtime.request(7);presence_runtime.gui_step();assert(presence_navigation==1);
 auto*owned_picker=fake::make(fake::screen);auto*unrelated_modal=fake::make(fake::screen);RuntimeReceiptTest::picker(presence_runtime,owned_picker);
 auto absent=data;absent["owner"]="standalone";absent["fresh"]=false;
 RuntimeReceiptTest::adoption_status(presence_runtime,absent,Json::object(),port.now);presence_runtime.gui_step();assert(presence_navigation==1&&owned_picker->live);
 absent["fresh"]=true;RuntimeReceiptTest::adoption_status(presence_runtime,absent,Json::object(),port.now);presence_runtime.gui_step();assert(presence_navigation==2&&!owned_picker->live&&unrelated_modal->live);
 fake::del(unrelated_modal);
 presence_runtime.gui_step();assert(presence_navigation==2); // no reconstruction loop
 presence_page->flags|=1;RuntimeReceiptTest::adoption_status(presence_runtime,data,http.ace,port.now);presence_runtime.gui_step();assert(presence_navigation==2);
 presence_page->flags&=~1U;presence_runtime.gui_step();assert(presence_navigation==3);
 // Real stock-page entry -> slot card -> original colour modal -> typed save.
 // Two slots share a head: the saved address must remain the selected slot.
 auto colour_data=data;colour_data["session"]="colour-session";colour_data["job"]["state"]="idle";
 colour_data["sources"][1]["head"]=colour_data["sources"][0]["head"];
 auto colour_raw=http.ace;
 colour_raw["management"]["units"]["ace-1"]=Json::object();
 colour_raw["management"]["source_settings"]["ace-1:0"]=Json::object();
 colour_raw["management"]["identity_settings"]["ace-1:0"]=colour_raw["management"]["identity_settings"]["h0"];
 RuntimeReceiptTest::adoption_status(presence_runtime,colour_data,colour_raw,port.now);presence_runtime.gui_step();
 auto page_button=[&](const std::string&prefix){
  for(const auto&node:fake::nodes)if(node->live&&node->text.compare(0,prefix.size(),prefix)==0){
   for(auto*p=node->parent;p;p=p->parent)if(p==presence_page)return node->parent;
  }
  return static_cast<fake::Node*>(nullptr);
 };
 // Toolhead identity entry follows the loaded source, even when two slots
 // share its head. It must not select the first matching physical head.
 auto tool_identity_data=colour_data;
 const auto loaded_source=tool_identity_data["sources"][1];
 for(auto&h:tool_identity_data["heads"])if(h.value("id","")==loaded_source.value("head",""))
  h["loaded"]={{"state","loaded"},{"source",loaded_source.at("id")},{"identity",loaded_source.at("identity")}};
 RuntimeReceiptTest::adoption_status(presence_runtime,tool_identity_data,colour_raw,port.now);
 presence_runtime.request(9);presence_runtime.gui_step();
 assert(RuntimeReceiptTest::ace_source(presence_runtime).value("id","")==loaded_source.value("id",""));
 auto*identity_back=page_button("BACK");assert(identity_back);
 const auto return_navigation=presence_navigation;fake::send(identity_back,7);presence_runtime.gui_step();
 assert(presence_navigation==return_navigation+1&&page_button("Toolhead management"));

 for(auto&h:tool_identity_data["heads"])if(h.value("id","")==loaded_source.value("head",""))h["loaded"]={{"state","empty"}};
 RuntimeReceiptTest::adoption_status(presence_runtime,tool_identity_data,colour_raw,port.now);
 presence_runtime.request(9);presence_runtime.gui_step();
 assert(RuntimeReceiptTest::ace_source(presence_runtime).is_null()); // choose explicitly
 auto single_source_data=tool_identity_data;
 single_source_data["sources"]=Json::array({loaded_source});
 RuntimeReceiptTest::adoption_status(presence_runtime,single_source_data,colour_raw,port.now);
 presence_runtime.request(9);presence_runtime.gui_step();
 assert(RuntimeReceiptTest::ace_source(presence_runtime).value("id","")==loaded_source.value("id",""));
 for(auto&h:single_source_data["heads"])if(h.value("id","")==loaded_source.value("head",""))h["loaded"]={{"state","unknown"}};
 RuntimeReceiptTest::adoption_status(presence_runtime,single_source_data,colour_raw,port.now);
 presence_runtime.request(9);presence_runtime.gui_step();assert(RuntimeReceiptTest::ace_source(presence_runtime).is_null());
 single_source_data["fresh"]=false;
 RuntimeReceiptTest::adoption_status(presence_runtime,single_source_data,colour_raw,port.now);
 const auto stale_navigation=presence_navigation;presence_runtime.request(9);presence_runtime.gui_step();assert(presence_navigation==stale_navigation);
 RuntimeReceiptTest::adoption_status(presence_runtime,colour_data,colour_raw,port.now);
 presence_runtime.request(7);presence_runtime.gui_step();
 auto*source_card=page_button("Slot 1");assert(source_card);fake::send(source_card,7);presence_runtime.gui_step();
 fake::Node*slot_edit=nullptr;for(const auto&node:fake::nodes)if(node->live&&node->text=="Edit")for(auto*p=node->parent;p;p=p->parent)if(p==presence_page)slot_edit=node->parent;assert(slot_edit);fake::send(slot_edit,7);presence_runtime.gui_step();
 fake::Node*colour_button=nullptr;
 for(const auto&node:fake::nodes)if(node->live&&node->w==88&&node->h==48)for(auto*p=node->parent;p;p=p->parent)if(p==presence_page)colour_button=node.get();
 assert(colour_button);fake::send(colour_button,7);
 auto*actual_modal=static_cast<fake::Node*>(presence_runtime.stock_picker_modal());assert(actual_modal&&actual_modal->parent==presence_page);
 presence_runtime.stock_colour_pick(0);fake::del(actual_modal);presence_runtime.gui_step();
 assert(!RuntimeReceiptTest::pending(presence_runtime,false)); // draft only
 auto*save_colour=page_button("SAVE");assert(save_colour);fake::send(save_colour,7);presence_runtime.gui_step();
 assert(RuntimeReceiptTest::pending(presence_runtime,false));
 auto colour_request=presence_channel.take();
 assert(colour_request.command.find("UNIT=\"ace-1\" SLOT=0")!=std::string::npos);
 assert(colour_request.command.find("COLOR=")!=std::string::npos);
 const auto colour_ticket=std::to_string(colour_request.ticket);
 presence_channel.settle(colour_request.ticket);
 // An acknowledgement alone cannot turn an unchanged source into a saved one.
 RuntimeReceiptTest::observe(presence_runtime,colour_ticket);presence_runtime.gui_step();
 assert(RuntimeReceiptTest::pending(presence_runtime,false));
 colour_data["sources"][0]["identity"]["color"]=stock_solid_colour(0);
 colour_data["receipts"]={{colour_ticket,{{"state","complete"},{"message","Confirmed"}}}};
 RuntimeReceiptTest::adoption_status(presence_runtime,colour_data,colour_raw,port.now);presence_runtime.gui_step();
 assert(!RuntimeReceiptTest::pending(presence_runtime,false));
 assert(page_button("Filament settings saved."));
 // Save the stock unit editor through the typed rename backend, with exact readback.
 fake::send(page_button("BACK"),7);presence_runtime.gui_step();
 fake::send(page_button("Edit unit"),7);presence_runtime.gui_step();
 const auto unit_before=RuntimeReceiptTest::unit_draft(presence_runtime);assert(unit_before.is_object());
 const auto unit_id=unit_before.at("id").get<std::string>();
 colour_raw["default_tool_map"]=Json::object();colour_raw["management"]["source_settings"]=Json::object();
 int route_index=0;
 for(const auto&source:colour_data["sources"])if(source.value("unit","")==unit_id){
  const auto source_id=source.at("id").get<std::string>();
  colour_raw["management"]["source_settings"][source_id]=Json::object();
  const auto assigned=unit_before.at("assignments").value(source_id,"");
  if(!assigned.empty())colour_raw["default_tool_map"][std::to_string(route_index++)]={{"unit",unit_id},{"slot",source.at("slot")},{"head",assigned}};
 }
 RuntimeReceiptTest::adoption_status(presence_runtime,colour_data,colour_raw,port.now);presence_runtime.gui_step();
 assert(RuntimeReceiptTest::rename(presence_runtime,"Front ACE"));presence_runtime.gui_step();
 auto*unit_save=page_button("Save");assert(unit_save);fake::send(unit_save,7);
 assert(RuntimeReceiptTest::pending(presence_runtime,false));
 fake::send(unit_save,7); // Duplicate click cannot replace the pending operation.
 auto rename_request=presence_channel.take();assert(rename_request.command=="OPENACE_RENAME_UNIT UNIT=\""+unit_id+"\" NAME=\"Front ACE\"");
 presence_channel.settle(rename_request.ticket);
 const auto rename_ticket=std::to_string(rename_request.ticket);
 RuntimeReceiptTest::observe(presence_runtime,rename_ticket);presence_runtime.gui_step();
 assert(RuntimeReceiptTest::pending(presence_runtime,false));assert(RuntimeReceiptTest::unit_draft(presence_runtime).is_object());
 colour_data["receipts"]={{rename_ticket,{{"state","complete"},{"message","Confirmed"}}}};
 for(auto&unit:colour_data["units"])if(unit["id"]==unit_id)unit["name"]="Front ACE";
 auto wrong_assignment=colour_data;
 for(auto&unit:wrong_assignment["units"])if(unit["id"]==unit_id)unit["assignments"]=Json::object();
 RuntimeReceiptTest::adoption_status(presence_runtime,wrong_assignment,colour_raw,port.now);presence_runtime.gui_step();assert(RuntimeReceiptTest::pending(presence_runtime,false));
 RuntimeReceiptTest::adoption_status(presence_runtime,colour_data,colour_raw,port.now);presence_runtime.gui_step();
 assert(!RuntimeReceiptTest::pending(presence_runtime,false));assert(RuntimeReceiptTest::unit_draft(presence_runtime).is_null());
 fake::send(page_button("Edit unit"),7);presence_runtime.gui_step();
 assert(RuntimeReceiptTest::rename(presence_runtime,"Rear ACE"));presence_runtime.gui_step();
 auto paused_unit=colour_data;paused_unit["job"]["state"]="paused";
 RuntimeReceiptTest::adoption_status(presence_runtime,paused_unit,colour_raw,port.now);presence_runtime.gui_step();
 fake::send(page_button("Save"),7);assert(!RuntimeReceiptTest::pending(presence_runtime,false));
 RuntimeReceiptTest::adoption_status(presence_runtime,colour_data,colour_raw,port.now);presence_runtime.gui_step();
 fake::send(page_button("Save"),7);assert(RuntimeReceiptTest::pending(presence_runtime,false));
 auto uncertain_rename=presence_channel.take();presence_channel.settle(uncertain_rename.ticket);
 const auto uncertain_ticket=std::to_string(uncertain_rename.ticket);
 colour_data["receipts"]={{uncertain_ticket,{{"state","unknown"},{"message","Delivery uncertain"}}}};
 RuntimeReceiptTest::adoption_status(presence_runtime,colour_data,colour_raw,port.now);presence_runtime.gui_step();
 fake::send(page_button("Save"),7);assert(RuntimeReceiptTest::pending(presence_runtime,false));
 auto changed_session=colour_data;changed_session["session"]="another-session";
 for(auto&unit:changed_session["units"])if(unit["id"]==unit_id)unit["name"]="Rear ACE";
 changed_session["receipts"][uncertain_ticket]["state"]="complete";
 RuntimeReceiptTest::adoption_status(presence_runtime,changed_session,colour_raw,port.now);presence_runtime.gui_step();
 assert(!RuntimeReceiptTest::pending(presence_runtime,false));assert(RuntimeReceiptTest::unit_draft(presence_runtime).is_null());
 assert(RuntimeReceiptTest::edit_operation(presence_runtime)["state"]=="unknown");
 for(auto*page:presence_pages)fake::del(page);

 // Exercise the real native adapter, including DELETE token capture and scoped
 // stock callback interception. Native capture uses these same attach/tick paths.
 StockFilamentNative stock_native;
 auto stock_page=fake::make(fake::screen);auto stock_panel=fake::make(stock_page);
 stock_panel->w=670;stock_panel->h=340;
 auto actions=fake::make(stock_panel);auto action_button=fake::make(actions);
 auto tips=fake::make(stock_panel);StockFilamentWidgets widgets;
 widgets.content=stock_panel;widgets.count=4;
 for(auto&s:widgets.slots){s.card=fake::make(stock_panel);s.number=fake::make(s.card);
  s.colour=fake::make(s.card);s.material=fake::make(s.card);s.material_label=fake::make(s.material);}
 const auto allocation_count=fake::nodes.size();
 stock_native.attach(widgets,stock_page,actions,tips);
 assert(actions->flags&1); // motion row is inhibited before the first timer tick
 fake::Event early_motion{action_button,7,nullptr};assert(stock_native.intercept(&early_motion));
 stock_native.tick(false,true);assert(actions->flags&1); // geometry not yet migrated
 stock_native.tick(true,true);assert(actions->flags&1);assert(tips->text=="Filament settings");
 assert(fake::nodes.size()==allocation_count); // Navigation now lives in the shared Tools tab.
 fake::Event head_select{static_cast<fake::Node*>(widgets.slots[2].card),7,reinterpret_cast<void*>(6)};
 assert(!stock_native.intercept(&head_select));
 stock_native.tool_data(Json::object(),10,220);
 for(std::uintptr_t code=0;code<4;++code){fake::Event e{action_button,7,reinterpret_cast<void*>(code)};assert(stock_native.intercept(&e));}
 fake::Event colour_event{static_cast<fake::Node*>(widgets.slots[0].colour),7,reinterpret_cast<void*>(8)};
 assert(!stock_native.intercept(&colour_event)); // current stock editor retained
 unsigned picked=99;bool allow=false;
 stock_native.material_entry([&](unsigned head){picked=head;return allow;});
 fake::Event material_event{static_cast<fake::Node*>(widgets.slots[2].material),7,reinterpret_cast<void*>(14)};
 assert(stock_native.intercept(&material_event)&&picked==2);
 allow=true;assert(!stock_native.intercept(&material_event)); // original draws picker
 stock_native.material_labels({{"PLA","PETG","ASA","PC"}});
 stock_native.message("Filament settings confirmed.");stock_native.tick(true,true);
 assert(static_cast<fake::Node*>(widgets.slots[2].material_label)->text=="ASA");
 assert(tips->text=="Filament settings confirmed.");
 stock_native.colour_entry([&](unsigned head){picked=head;return allow;});
 allow=false;assert(stock_native.intercept(&colour_event)&&picked==0);
 allow=true;assert(!stock_native.intercept(&colour_event));
 stock_native.colour_sources({{"stock-white.bin",nullptr,"stock-red.bin",nullptr}});
 stock_native.tick(true,true);
 assert(static_cast<fake::Node*>(widgets.slots[0].colour)->image=="stock-white.bin");
 assert(static_cast<fake::Node*>(widgets.slots[2].colour)->image=="stock-red.bin");
 stock_native.colour_tints({{0xff123456U,0,0xff000000U,0}});stock_native.tick(true,true);
 auto*swatch=static_cast<fake::Node*>(widgets.slots[0].colour);
 assert(swatch->tint[0]==0xff123456U&&swatch->tint[1]==0xff123456U);
 assert(swatch->tint_opa[0]==255&&swatch->tint_opa[1]==255);
 stock_native.colour_tints({{0,0,0,0}});stock_native.tick(true,true);
 assert(swatch->tint_opa[0]==0&&swatch->tint_opa[1]==0);
 assert(fake::nodes.size()==allocation_count);
 fake::Node*import_button=nullptr;
 for(const auto&node:fake::nodes)if(node->live&&node->text=="Import profiles"&&node->parent->parent==stock_panel)import_button=node->parent;
 assert(!import_button&&!stock_native.import_active());
 assert(!stock_native.intercept(&colour_event));
 stock_native.tick(false,false);assert(stock_native.intercept(&colour_event));
 stock_native.tick(false,false);
 assert(tips->text=="Printer status unavailable");
 fake::Event other_page{retained,7,nullptr};assert(!stock_native.intercept(&other_page));
 fake::Event nonclick{action_button,1,nullptr};assert(!stock_native.intercept(&nonclick));
 // Old stock modals cannot send edits into the newer modal's draft.
 StockPickerLifetime picker;
 auto*failed_picker=fake::make(fake::screen);auto*foreign_picker=fake::make(fake::screen);
 fake::fail_binding=true;assert(!picker.bind_owned(failed_picker));fake::fail_binding=false;
 assert(!failed_picker->live&&foreign_picker->live&&!picker.modal());fake::del(foreign_picker);

 auto*old_modal=fake::make(fake::screen);auto*old_choice=fake::make(old_modal);
 auto*new_modal=fake::make(fake::screen);auto*new_choice=fake::make(new_modal);
 assert(picker.bind(old_modal)&&picker.accepts(old_choice));
 assert(picker.bind(new_modal)&&!picker.accepts(old_choice)&&picker.accepts(new_choice));
 fake::del(old_modal);assert(picker.modal()==new_modal&&picker.accepts(new_choice));
 picker.retire();assert(!picker.accepts(new_choice));
 assert(picker.bind(new_modal));fake::del(new_modal);assert(!picker.modal());
 const auto before_brands=fake::nodes.size();
 // Only brand adds widgets: four selectors inside the existing cards.
 unsigned brand_head=99,brand_saves=0;std::string selected_brand;
 stock_native.brand_controls().begin=[&](unsigned h){brand_head=h;return true;};
 stock_native.brand_controls().choose=[&](unsigned h,const std::string&v){assert(h==1);++brand_saves;selected_brand=v;};
 // The full Orca catalogue reaches the widget without the former 32-row cap.
 const auto full_brands=native::filament_brands(Json::array()).get<std::vector<std::string>>();
 stock_native.brands({{"Generic","Sunlu","Generic","Generic"}},full_brands);stock_native.tick(true,true);
 auto*full_brand=static_cast<fake::Node*>(widgets.slots[1].card)->children.back();
 const auto full_options=brand_choices(full_brands,"Sunlu");
 std::string full_text;for(const auto&name:full_options){if(!full_text.empty())full_text+='\n';full_text+=name;}
 assert(full_options.size()>100&&full_options.back()=="Zyltech");
 assert(full_brand->options==full_text&&full_options.at(full_brand->selected)=="Sunlu");
 stock_native.brands({{"Generic","Example","Generic","Generic"}},{"Example","Generic","Other"});
 stock_native.tick(true,true);
 auto*brand=static_cast<fake::Node*>(widgets.slots[1].card)->children.back();
 assert(brand->parent==widgets.slots[1].card&&brand->options=="Example\nGeneric\nOther");
 assert(brand->styles==std::vector<std::uintptr_t>({0x463c8e8,0x463c8f8}));
 assert(brand->y>=164&&brand->y+brand->h<=brand->parent->h);
 assert(fake::nodes.size()==before_brands+4);
 brand->parent->inset_x=2;brand->parent->inset_y=2;stock_native.tick(true,true);
 assert(brand->y>=172&&brand->y+brand->h<=fake::height(brand->parent));
 brand->parent->inset_y=60;stock_native.tick(true,true);assert(brand->flags&1);
 brand->parent->inset_y=2;stock_native.tick(true,true);assert(!(brand->flags&1));
 brand->open=true;fake::send(brand,31);assert(brand_head==1);
 stock_native.brands({{"Generic","Example","Generic","Generic"}},{"Changed"});stock_native.tick(true,true);
 assert(brand->options=="Example\nGeneric\nOther"); // freeze while picker is open
 brand->selected=2;fake::send(brand,28);fake::send(brand,28);
 assert(brand_saves==1&&selected_brand=="Other");
 brand->open=false;stock_native.tick(true,true);assert(brand->options=="Changed\nExample\nGeneric");
 brand->open=true;fake::send(brand,31);stock_native.tick(false,true);brand->selected=0;fake::send(brand,28);
 assert(brand_saves==1&&(brand->state&128));
 // The selected-head identity view reflows the same stock card and pickers.
 stock_native.identity_head(2);stock_native.tick(true,true);
 for(unsigned i=0;i<4;++i)assert(bool(static_cast<fake::Node*>(widgets.slots[i].card)->flags&1)==(i!=2));
 assert(static_cast<fake::Node*>(widgets.slots[2].card)->w==280);
 assert(static_cast<fake::Node*>(widgets.slots[2].material)->w==264);
 assert(tips->text=="Head 3 - filament settings");
 assert(stock_native.intercept(&colour_event)); // old other-head click cannot open its picker
 assert(!stock_native.intercept(&material_event)); // selected head retains its stock picker
 stock_native.brand_controls().retire();brand->open=true;fake::send(brand,31);brand->selected=0;fake::send(brand,28);
 assert(brand_saves==1); // retired page dropdown cannot start or commit another edit
 fake::del(stock_page); // real adapter DELETE callback retires binding
 assert(!stock_native.intercept(&colour_event));
 {
  StockProfileImport view;auto*parent=fake::make(fake::screen);parent->w=670;parent->h=340;
  Json snapshot={{"owner","standalone"},{"fresh",true},{"capabilities",{{"profile_import",true}}}};
  std::vector<std::pair<std::string,std::string>>requests;
  view.requested=[&](const std::string&a,const std::string&v){requests.push_back({a,v});return Receipt{"import-"+std::to_string(requests.size()),"pending",""};};
  view.update(snapshot);assert(view.show(parent));assert(requests.size()==1&&requests.back().first=="scan");
  auto find=[&](const std::string&text){for(const auto&n:fake::nodes)if(n->live&&n->text==text)for(auto*p=n->parent;p;p=p->parent)if(p==parent)return n->parent;return static_cast<fake::Node*>(nullptr);};
  assert(find("Reading USB profiles...")&&!find("Saving profiles..."));
  snapshot["profile_import"]={{"id","import-1"},{"state","files"},{"files",Json::array({{{"id",std::string(64,'a')},{"name","PLA.json"}}})}};
  view.update(snapshot);assert(find("PLA.json"));fake::send(find("PLA.json"),7);assert(requests.back().first=="review");assert(find("Reading USB profiles...")&&!find("Saving profiles..."));
  snapshot["profile_import"]={{"id","import-2"},{"state","review"},{"name","PLA.json"},{"token",std::string(48,'b')},{"profiles",Json::array({{{"name","My PLA"},{"identity",{{"brand","Example"},{"material","PLA"},{"nozzle_temp",220}}}}})}};
  view.update(snapshot);auto*save=find("SAVE");assert(save&&!(save->state&128));assert(requests.size()==2);fake::send(save,7);
  assert(requests.size()==3&&requests.back().first=="save"&&requests.back().second==std::string(48,'b'));
  assert(find("BACK")&&find("Saving profiles...")&&!find("Reading USB profiles..."));
  snapshot["profile_import"]={{"id","import-3"},{"state","saved"},{"count",1}};view.update(snapshot);
  assert(find("DONE"));fake::send(find("DONE"),7);assert(!view.active());fake::del(parent);
 }
 // Older helpers and ACE ownership cannot dispatch standalone imports.
 for(bool ace_enabled:{false,true}){
  StockFilamentNative imports;auto*page=fake::make(fake::screen);auto*content=fake::make(page);content->w=670;content->h=340;
  auto*actions=fake::make(content);auto*tips=fake::make(content);StockFilamentWidgets view;view.content=content;view.count=4;
  for(auto&slot:view.slots){slot.card=fake::make(content);slot.number=fake::make(slot.card);slot.colour=fake::make(slot.card);slot.material=fake::make(slot.card);slot.material_label=fake::make(slot.material);}
  imports.ace_mode(ace_enabled);imports.tool_data(data,10,220);imports.attach(view,page,actions,tips);imports.tick(true,true);
  auto find=[&](const std::string&text){for(const auto&n:fake::nodes)if(n->live&&n->text==text)for(auto*p=n->parent;p;p=p->parent)if(p==content)return n->parent;return static_cast<fake::Node*>(nullptr);};
  assert(!find("Import profiles")&&!imports.import_active());
  if(ace_enabled){
   unsigned finishes=0;imports.onboarding(true);imports.finish_setup=[&](){++finishes;imports.onboarding(false);};imports.tick(true,true);
   auto*finish=find("FINISH");assert(finish&&!(finish->flags&1));
   imports.tick(false,true);fake::send(finish,7);assert(finishes==0);
   imports.tick(true,true);page->flags|=1;fake::send(finish,7);assert(finishes==0);page->flags&=~1U;
   fake::send(finish,7);fake::send(finish,7);assert(finishes==1);
   fake::send(find("Edit unit"),7);assert(imports.ace_controls().unit_draft().is_object());
   assert(imports.ace_controls().rename_draft("Unsaved unit name"));
   page->flags|=1;imports.tick(true,true);assert(imports.ace_controls().unit_draft().is_null());
  }
  fake::del(page);

 }
 // Compact filament confirmations retain a full input shield, legible captions,
 // and exactly the existing submission action; progress expands in place.
 for(const auto*action:{"load","unload"}){
  fake::DeferredSizes deferred_layout;
  StockFilamentProcedure modal;auto*parent=fake::make(fake::screen);parent->w=800;parent->h=480;
  const bool unload=std::string(action)=="unload";
  Json data={{"owner","standalone"},{"session","compact-session"},{"revision","recipe"},{"identity_revision","identity"},{"fresh",true},
   {"job",{{"state","idle"}}},{"capabilities",{{"load",true},{"unload",true},{"confirm_filament",true}}},
   {"heads",Json::array({{{"id","h2"},{"loaded",{{"state",unload?"loaded":"empty"},{"source","external:h2"}}}}})},
   {"sources",Json::array({{{"id","external:h2"},{"head","h2"},{"available",true},{"name","External"}}})},
   {"procedures",Json::array({{{"head","h2"},{"source","external:h2"},{"action",action},{"revision","recipe"},
    {"token",std::string(64,'a')},{"target_temperature","210"},{"description","Heat and feed"}}})}};
  const std::string long_note=std::string(900,'x')+" End of transition instructions.";data["procedures"][0]["transition_note"]=long_note;
  unsigned submissions=0;modal.submit=[&](FilamentProcedureReview&){++submissions;return Receipt{"compact-result","pending","Heating nozzle"};};
  assert(!modal.open(nullptr,data,"h2",action)&&modal.open_failure()=="Filament page parent is unavailable.");
  parent->w=300;assert(!modal.open(parent,data,"h2",action));
  assert(modal.open_failure().find("width=300, height=480")!=std::string::npos);parent->w=800;
  fake::fail_binding=true;assert(!modal.open(parent,data,"h2",action));fake::fail_binding=false;
  assert(modal.open_failure()=="Filament dialog event binding failed.");
  assert(modal.open(parent,data,"h2",action));assert(modal.open_failure().empty());auto*root=parent->children.back();auto*card=root->children.front();
  auto caption=[&](const std::string&text){for(auto*b:root->children)for(auto*l:b->children)if(l->text==text)return b;return static_cast<fake::Node*>(nullptr);};
  assert(root->w==800&&root->h==480&&root->background_opacity==0&&(root->flags&2));
  assert(card->x==48&&card->y==90&&card->w==704&&card->h==300&&!(card->flags&1));
  auto*cancel=caption("CANCEL");auto*begin=caption(unload?"UNLOAD":"LOAD");assert(cancel&&begin);
  assert(begin->h==56&&begin->children.front()->h==40&&begin->children.front()->font_address==MyriadPro_Bold_24);
  assert(root->children.at(1)->font_address==MyriadPro_Bold_24);
  assert(begin->y>=card->y&&begin->y+begin->h<=card->y+card->h);
  {
   auto*body=root->children.at(2);assert((body->flags&16)&&body->dir==12);
   auto*description=body->children.back();assert(description->label_long_mode==0&&description->w==640&&description->font_address==MyriadPro_Regular_22);
   assert(description->text.find(long_note)!=std::string::npos);
   body->scroll=96;modal.update(data);assert(body->scroll==96&&description->text.find("End of transition instructions.")!=std::string::npos);
  }
  fake::send(cancel,7);assert(!modal.active()&&submissions==0);
  assert(modal.open(parent,data,"h2",action));root=parent->children.back();card=root->children.front();begin=caption(unload?"UNLOAD":"LOAD");
  fake::send(begin,7);fake::send(begin,7);assert(submissions==1);
  assert(root->background_opacity==255&&(card->flags&1)&&begin->h==34&&caption("CLOSE"));
  fake::del(parent);
 }
 {
  StockFilamentProcedure dialog;auto*parent=fake::make(fake::screen);parent->w=670;parent->h=340;
  Json procedure_data={{"owner","standalone"},{"session","session"},{"revision","rev"},{"fresh",true},{"job",{{"state","idle"}}},{"capabilities",{{"load",true}}},
   {"heads",Json::array({{{"id","h2"},{"loaded",{{"state","empty"}}}}})},
   {"sources",Json::array({{{"id","s"},{"head","h2"},{"available",true},{"name","Gray PLA"}}})},
   {"procedures",Json::array({{{"head","h2"},{"source","s"},{"action","load"},{"revision","rev"},{"token",std::string(64,'a')},{"target_temperature","210"},{"description","Heat Head 3 to 210 C and feed 20 mm."}}})}};
  struct ProcedureBackend:Backend{unsigned calls=0;std::string unavailable(const std::string&)const override{return "";}Receipt submit(const Request&r)override{assert(r.action=="load"&&r.arguments["head"]=="h2");++calls;return {"p1","pending","Waiting for load completion"};}} procedure_backend;
  dialog.submit=[&](FilamentProcedureReview&review){return review.confirm(procedure_data,procedure_backend);};
  auto find=[&](const std::string&text){for(const auto&n:fake::nodes)if(n->live&&n->text==text)for(auto*p=n->parent;p;p=p->parent)if(p==parent)return n->parent;return static_cast<fake::Node*>(nullptr);};
  assert(dialog.open(parent,procedure_data,"h2","load")&&procedure_backend.calls==0);
  bool load_guidance=false;
  for(const auto&n:fake::nodes)if(n->live&&n->text.find("Mount and heat to 210 C")!=std::string::npos&&n->text.find("Insert filament when prompted")!=std::string::npos)load_guidance=true;
  assert(load_guidance);
  const auto review_writes=fake::text_writes;
  for(int i=0;i<100;++i)dialog.update(procedure_data);
  assert(fake::text_writes==review_writes);
  auto unavailable_procedure=procedure_data;unavailable_procedure["procedures"]=Json::array();
  dialog.update(unavailable_procedure);
  assert(find("LOAD")->children[0]->text_color==0xff888888U);
  dialog.update(procedure_data);
  assert(find("LOAD")->children[0]->text_color==0xffeeeeeeU);
  procedure_data["revision"]="new-recipe";procedure_data["procedures"][0]["revision"]="new-recipe";
  procedure_data["procedures"][0]["target_temperature"]="230";procedure_data["procedures"][0]["token"]=std::string(64,'b');
  const auto recipe_nodes=fake::nodes.size();dialog.update(procedure_data);
  assert(procedure_backend.calls==0&&fake::nodes.size()==recipe_nodes);
  bool updated_recipe=false;for(const auto&n:fake::nodes)if(n->live&&n->text.find("Mount and heat to 230 C")!=std::string::npos&&n->text.find("Settings changed. Review and press LOAD.")!=std::string::npos)updated_recipe=true;
  assert(updated_recipe);
  auto*begin=find("LOAD");assert(begin&&!(begin->state&128));fake::send(begin,7);fake::send(begin,7);assert(procedure_backend.calls==1&&(begin->state&128));
  assert(find("STOP")==begin);fake::send(begin,7);assert(procedure_backend.calls==1);
  unsigned stops=0;dialog.cancel=[&](const std::string&id){assert(id=="p1");++stops;return true;};
  auto running=procedure_data;running["filament_cancel_protocol"]=1;
  running["filament_operation"]={{"id","p1"},{"session","session"},{"head","h2"},{"state","running"}};
  dialog.update(running);assert(find("STOP")==begin&&!(begin->state&128));
  running["filament_operation"]["phase"]="heating";
  running["filament_operation"]["steps"]=Json::array({{{"phase","preparing"},{"label","Position head"}},{{"phase","heating"},{"label","Heat nozzle"}},{{"phase","feeding"},{"label","Load filament"}}});
  running["heads"][0]["actual"]=123;running["heads"][0]["target"]=220;
  dialog.update(running);
  auto step=[&](const std::string&text){for(const auto&n:fake::nodes)if(n->live&&n->text==text&&!(n->flags&1))return n.get();return static_cast<fake::Node*>(nullptr);};
  auto*heat=step("2. Heat nozzle");assert(heat);
  assert(step("1. Position head"));
  assert(step("3. Load filament"));
  const auto heating_writes=fake::text_writes;const auto heating_nodes=fake::nodes.size();
  heat->parent->scroll=60;
  for(int i=0;i<100;++i)dialog.update(running);
  assert(fake::text_writes==heating_writes&&fake::nodes.size()==heating_nodes&&heat->parent->scroll==60);
  // Local receipt transitions must repaint even with identical synced data.
  dialog.result({{"state","failed"},{"message","Load interrupted"}});
  assert(find("STOPPED")==begin&&(begin->state&128));
  dialog.result({{"state","pending"},{"message","Waiting for load completion"}});
  assert(find("STOP")==begin&&!(begin->state&128));
  auto stale_running=running;stale_running["fresh"]=false;dialog.update(stale_running);
  assert(begin->state&128);dialog.update(running);assert(!(begin->state&128));
  auto ace_running=running;ace_running["owner"]="openace";ace_running["session"]="42";ace_running["print_helper_session"]="helper";
  ace_running["filament_operation"]["session"]="helper";
  dialog.update(ace_running);assert(begin->state&128);assert(step("Heat nozzle  123 / 220 °C"));
  ace_running["filament_operation"]["openace_cancel_supported"]=true;
  dialog.update(ace_running);assert(!(begin->state&128));fake::send(begin,7);assert(stops==1);stops=0;
  ace_running["filament_operation"]["session"]="42";dialog.update(ace_running);assert(begin->state&128);
  dialog.update(running);
  const auto stop_disables=begin->disable_writes;
  const auto nodes=fake::nodes.size();running["heads"][0]["actual"]=150;dialog.update(running);
  assert(!(begin->state&128)&&begin->disable_writes==stop_disables);
  assert(step("2. Heat nozzle")==heat&&fake::nodes.size()==nodes);
  auto complete=running;complete["filament_operation"]["state"]="complete";dialog.update(complete);
  assert(!step("3. Load filament")&&!step("2. Heat nozzle"));
  auto foreign=running;foreign["filament_operation"]["id"]="foreign";dialog.update(foreign);
  assert(!step("1. Position head"));dialog.update(running);
  parent->flags|=1;fake::send(begin,7);assert(stops==0);parent->flags&=~1U;
  fake::send(begin,7);assert(stops==1&&procedure_backend.calls==1);
  running["filament_operation"]["cancel_requested"]=true;dialog.update(running);
  assert(find("STOPPING")==begin&&(begin->state&128));fake::send(begin,7);assert(stops==1);
  running["filament_operation"]["cancel_requested"]=false;running["filament_operation"]["id"]="another-operation";dialog.update(running);
  assert(find("STOP")==begin);fake::send(begin,7);assert(stops==1);
  {
   auto interrupted_ace=running;interrupted_ace["owner"]="openace";interrupted_ace["session"]="42";interrupted_ace["print_helper_session"]="helper";
   interrupted_ace["filament_recovery_protocol"]=1;
   interrupted_ace["filament_operation"]={{"id","ace-recover"},{"session","helper"},{"head","h2"},{"action","load"},{"state","unknown"}};
   assert(!StockFilamentProcedure::interrupted(interrupted_ace));
   interrupted_ace["filament_operation"]["openace_recovery_supported"]=true;
   assert(StockFilamentProcedure::interrupted(interrupted_ace));
   StockFilamentProcedure ace_dialog;unsigned checks=0;
   ace_dialog.recover=[&](const std::string&id){assert(id=="ace-recover");++checks;return true;};
   assert(ace_dialog.open_interrupted(parent,interrupted_ace));
   auto*verify=find("RECOVER");assert(verify&&!(verify->state&128));fake::send(verify,7);assert(checks==1);
   interrupted_ace["filament_operation"]["session"]="42";ace_dialog.update(interrupted_ace);
   assert(verify->state&128);assert(!StockFilamentProcedure::interrupted(interrupted_ace));
   ace_dialog.close();
  }
  unsigned recoveries=0;dialog.recover=[&](const std::string&id){assert(id=="p1");++recoveries;return true;};
  running["filament_operation"]["id"]="p1";running["filament_operation"]["state"]="unknown";running["filament_recovery_protocol"]=1;
  dialog.update(running);dialog.result({{"state","unknown"},{"message","Heater stop uncertain"}});
  assert(find("RECOVER")==begin&&!(begin->state&128));
  // A changed temperature/status sync must not temporarily disable a usable
  // action between the press and release events.
  const auto recovery_disables=begin->disable_writes;
  running["heads"][0]["actual"]=61;
  dialog.update(running);
  assert(!(begin->state&128)&&begin->disable_writes==recovery_disables);
  parent->flags|=1;fake::send(begin,7);assert(recoveries==0);parent->flags&=~1U;
  auto stale_recovery=running;stale_recovery["fresh"]=false;dialog.update(stale_recovery);fake::send(begin,7);assert(recoveries==0);
  dialog.update(running);fake::send(begin,7);assert(recoveries==1&&procedure_backend.calls==1);
  running["filament_operation"]["id"]="other";dialog.update(running);fake::send(begin,7);assert(recoveries==1);
  for(const auto*state:{"partial","failed","unknown"}){
   dialog.result({{"state",state},{"message","Inspect the filament."}});
   const auto caption=std::string(state)=="failed"?"STOPPED":"RECOVER";
   assert(find(caption)==begin&&(begin->state&128));fake::send(begin,7);assert(procedure_backend.calls==1);
   fake::send(find("CLOSE"),7);assert(!dialog.active());assert(dialog.reopen_result(parent,procedure_data));
   begin=find(caption);assert(begin&&(begin->state&128));fake::send(begin,7);assert(procedure_backend.calls==1);
  }
  dialog.result({{"state","complete"},{"message","Motion completed; inspect filament."}});
  assert(find("DONE")==begin&&!(begin->state&128));fake::send(begin,7);
  assert(procedure_backend.calls==1&&!dialog.active());fake::send(begin,7);assert(procedure_backend.calls==1);
  assert(dialog.open(parent,procedure_data,"h2","load"));
  auto stale=procedure_data;stale["fresh"]=false;dialog.update(stale);begin=find("LOAD");assert(begin->state&128);fake::send(begin,7);assert(procedure_backend.calls==1);
  fake::send(find("CANCEL"),7);assert(!dialog.active());
  // The same modal shell supports tool recovery without ever offering a
  // filament Load/Unload or dispatching the original Take/Dock command.
  auto tool_recovery=procedure_data;tool_recovery["toolhead_recovery_protocol"]=1;
  tool_recovery["toolhead_operation"]={{"id","tool-interrupted"},{"session","session"},{"head","h2"},{"action","take"},{"state","unknown"}};
  unsigned tool_recoveries=0;
  dialog.recover_toolhead=[&](const std::string&id){assert(id=="tool-interrupted");++tool_recoveries;return true;};
  assert(!dialog.open(parent,tool_recovery,"h2","take"));
  assert(StockFilamentProcedure::interrupted(tool_recovery,true));
  tool_recovery["toolhead_operation"]["steps"]=Json::array({{{"phase","moving"},{"label","Mount head"}},{{"phase","verifying"},{"label","Verify attachment sensors"}}});
  tool_recovery["toolhead_operation"]["phase"]="verifying";
  assert(dialog.open_interrupted(parent,tool_recovery,true));
  assert(!step("1. Mount head"));
  assert(!step("2. Verify attachment sensors"));
  begin=find("RECOVER");assert(begin&&!(begin->state&128));
  assert(!find("LOAD")&&!find("UNLOAD")&&!find("STOP"));
  parent->flags|=1;fake::send(begin,7);assert(tool_recoveries==0);parent->flags&=~1U;
  auto tool_stale=tool_recovery;tool_stale["fresh"]=false;dialog.update(tool_stale);fake::send(begin,7);assert(tool_recoveries==0);
  dialog.update(tool_recovery);fake::send(begin,7);assert(tool_recoveries==1&&procedure_backend.calls==1);
  tool_recovery["toolhead_operation"]["state"]="failed";dialog.update(tool_recovery);
  dialog.result({{"state","failed"},{"message","Stopped. Head 1 is mounted."}});
  begin=find("STOPPED");assert(begin&&(begin->state&128));fake::send(begin,7);assert(tool_recoveries==1);
  fake::send(find("CLOSE"),7);assert(!dialog.active());
  assert(dialog.open_tracking(parent,tool_recovery,"h2","take",Receipt{"tool-interrupted","pending","Mounting head"}));
  assert(step("2. Verify attachment sensors"));assert(procedure_backend.calls==1);
  dialog.close();
  auto multi_source=procedure_data;multi_source["owner"]="openace";
  multi_source["units"]=Json::array({{{"id","ace-a"},{"name","ACE"}},{{"id","ace-b"},{"name","ACE"}}});
  multi_source["sources"]=Json::array();
  for(const auto*unit:{"ace-a","ace-b"})multi_source["sources"].push_back({{"id",std::string(unit)+":0"},{"kind","ace"},{"unit",unit},{"slot",0},{"name","Slot 1"},{"head","h2"},{"available",true}});
  assert(dialog.open(parent,multi_source,"h2","load"));
  assert(find("ACE (ace-a) - Slot 1")&&find("ACE (ace-b) - Slot 1"));fake::send(find("CLOSE"),7);
  assert(!dialog.open(parent,multi_source,"h2","load",false,"missing"));
  assert(dialog.open(parent,multi_source,"h2","load",false,"ace-b:0"));
  assert(find("LOAD")->state&128); // No matching backend procedure: nothing can be sent.
  fake::send(find("CLOSE"),7);
  assert(dialog.open(parent,procedure_data,"h2","load"));fake::del(parent);assert(!dialog.active());
  // Runtime uses the same review and the real typed queue, without performing HTTP.
  wmp_openace::UiChannel procedure_channel;Runtime procedure_runtime(http,port,procedure_channel);
  auto*runtime_page=fake::make(fake::screen);auto*runtime_content=fake::make(runtime_page);runtime_content->w=670;runtime_content->h=340;
  StockFilamentWidgets runtime_widgets;runtime_widgets.content=runtime_content;runtime_widgets.count=4;
  for(auto&slot:runtime_widgets.slots){slot.card=fake::make(runtime_content);slot.number=fake::make(slot.card);slot.colour=fake::make(slot.card);slot.material=fake::make(slot.card);slot.material_label=fake::make(slot.material);}
  RuntimeReceiptTest::attach(procedure_runtime,runtime_widgets,runtime_page,fake::make(runtime_content),fake::make(runtime_content));
  RuntimeReceiptTest::tool_context(procedure_runtime,procedure_data,port.now);
  auto managed=procedure_data;managed["sources"].push_back({{"id","ace:0"},{"kind","ace"},{"head","h2"},{"available",true}});
  RuntimeReceiptTest::tool_context(procedure_runtime,managed,port.now);
  RuntimeReceiptTest::tool_action(procedure_runtime,"load");assert(!RuntimeReceiptTest::procedure_active(procedure_runtime));
  RuntimeReceiptTest::tool_context(procedure_runtime,procedure_data,port.now);
  RuntimeReceiptTest::slot_load(procedure_runtime,"s");assert(RuntimeReceiptTest::procedure_active(procedure_runtime));
  auto runtime_find=[&](const std::string&text){for(const auto&n:fake::nodes)if(n->live&&n->text==text)for(auto*p=n->parent;p;p=p->parent)if(p==runtime_content)return n->parent;return static_cast<fake::Node*>(nullptr);};
  auto*runtime_begin=runtime_find("LOAD");assert(runtime_begin);fake::send(runtime_begin,7);
  const auto request_id=RuntimeReceiptTest::tool_receipt(procedure_runtime);assert(!request_id.empty());
  RuntimeReceiptTest::tool_context(procedure_runtime,procedure_data,port.now);
  fake::send(runtime_begin,7);assert(RuntimeReceiptTest::tool_receipt(procedure_runtime)==request_id);
  fake::send(runtime_find("CLOSE"),7);assert(!RuntimeReceiptTest::procedure_active(procedure_runtime));
  auto pending=procedure_data;pending["receipts"]={{request_id,{{"state","unknown"},{"message","Inspect filament"}}}};
  RuntimeReceiptTest::adoption_status(procedure_runtime,pending,Json::object(),port.now);RuntimeReceiptTest::update_tool(procedure_runtime);
  assert(RuntimeReceiptTest::tool_receipt(procedure_runtime).empty()); // Unconfirmed local history is not a machine lock.
  RuntimeReceiptTest::tool_action(procedure_runtime,"view-operation");assert(!RuntimeReceiptTest::procedure_active(procedure_runtime));
  pending["receipts"][request_id]={{"state","failed"},{"message","Procedure stopped; inspect filament."}};
  RuntimeReceiptTest::adoption_status(procedure_runtime,pending,Json::object(),port.now);RuntimeReceiptTest::update_tool(procedure_runtime);
  assert(RuntimeReceiptTest::tool_receipt(procedure_runtime).empty());
  RuntimeReceiptTest::tool_action(procedure_runtime,"view-operation");assert(!RuntimeReceiptTest::procedure_active(procedure_runtime));
  RuntimeReceiptTest::slot_load(procedure_runtime,"s");assert(RuntimeReceiptTest::procedure_active(procedure_runtime));
  auto*cancel_preflight=runtime_find("CANCEL");assert(cancel_preflight);
  fake::send(cancel_preflight,7);assert(!RuntimeReceiptTest::procedure_active(procedure_runtime));
  // Explicit overview actions report why they did not open a dialog. Notices
  // replace each other and never create a request or alter admission.
  auto refuse_action=[&](Json snapshot,const std::string&action,const std::string&message){
   RuntimeReceiptTest::tool_context(procedure_runtime,snapshot,port.now);
   RuntimeReceiptTest::slot_action(procedure_runtime,action);
   assert(RuntimeReceiptTest::filament_notice(procedure_runtime)&&runtime_find(message));
   auto count=fake::nodes.size();RuntimeReceiptTest::slot_action(procedure_runtime,action);
   assert(RuntimeReceiptTest::filament_notice(procedure_runtime)&&fake::nodes.size()>count);
   unsigned visible_notices=0;for(const auto&node:fake::nodes)if(node->live&&node->text==message)++visible_notices;
   assert(visible_notices==1);RuntimeReceiptTest::clear_filament_notice(procedure_runtime);
  };
  for(const auto*action:{"load-source:s","unload-source:s"}){
   auto missing=procedure_data;missing["sources"]=Json::array();
   refuse_action(missing,action,"Filament source changed. Select it again.");
   auto duplicate=procedure_data;duplicate["sources"].push_back(duplicate["sources"][0]);
   refuse_action(duplicate,action,"Filament source changed. Select it again.");
   auto stale=procedure_data;stale["fresh"]=false;
   refuse_action(stale,action,"Waiting for current printer status.");
   RuntimeReceiptTest::pending(procedure_runtime,true,"pending-tool");
   refuse_action(procedure_data,action,"Waiting for the previous operation result.");
   RuntimeReceiptTest::pending(procedure_runtime,true,"");
   RuntimeReceiptTest::pending(procedure_runtime,false,"pending-save");
   refuse_action(procedure_data,action,"Waiting for the previous settings save result.");
   RuntimeReceiptTest::pending(procedure_runtime,false,"");
  }
  RuntimeReceiptTest::tool_context(procedure_runtime,procedure_data,port.now);
  RuntimeReceiptTest::slot_load(procedure_runtime,"s");assert(RuntimeReceiptTest::procedure_active(procedure_runtime));
  refuse_action(procedure_data,"unload-source:s","Close the current filament dialog first.");
  fake::send(runtime_find("CANCEL"),7);assert(!RuntimeReceiptTest::procedure_active(procedure_runtime));
  auto unavailable=procedure_data;unavailable["sources"][0]["available"]=false;
  refuse_action(unavailable,"load-source:s","This filament source is unavailable.");
  refuse_action(procedure_data,"unload-source:s","Loaded filament changed. Check this head.");
  auto loaded=procedure_data;loaded["heads"][0]["loaded"]={{"state","loaded"},{"source","s"}};
  // A small but valid page still hosts the diagnostic notice; the actual
  // procedure requires at least 400px. Verify a useful exact open reason.
  runtime_content->w=300;
  refuse_action(loaded,"unload-source:s","Cannot open the filament dialog. Try reopening Filament.");
  runtime_content->w=670;
  auto legacy=procedure_data;legacy["owner"]="openace";legacy["sources"]=Json::array();
  RuntimeReceiptTest::tool_context(procedure_runtime,legacy,port.now);
  RuntimeReceiptTest::slot_action(procedure_runtime,"unload-source:s");assert(!RuntimeReceiptTest::filament_notice(procedure_runtime));
  RuntimeReceiptTest::tool_context(procedure_runtime,procedure_data,port.now);
  RuntimeReceiptTest::slot_action(procedure_runtime,"unload-source:s");assert(RuntimeReceiptTest::filament_notice(procedure_runtime));
  fake::del(runtime_page);assert(!RuntimeReceiptTest::filament_notice(procedure_runtime));

 }
 // Take/Dock use the same numbered progress panel as filament operations.
 for(const auto*action:{"take","dock"}){
  StockFilamentProcedure dialog;auto*parent=fake::make(fake::screen);parent->w=670;parent->h=340;
  Json snapshot={{"owner","standalone"},{"session","tool-session"},{"fresh",true},
   {"toolhead_operation",{{"id","tool-progress"},{"session","tool-session"},{"head","h3"},
    {"action",action},{"state","running"},{"phase","moving"},
    {"steps",Json::array({{{"phase","checking"},{"label","Check head attachment"}},
     {{"phase","moving"},{"label",std::string(action)=="take"?"Mount head":"Dock head"}},
     {{"phase","verifying"},{"label","Verify attachment sensors"}}})}}}};
  auto find=[&](const std::string&text){for(const auto&n:fake::nodes)if(n->live&&n->text==text&&!(n->flags&1))for(auto*p=n->parent;p;p=p->parent)if(p==parent)return n.get();return static_cast<fake::Node*>(nullptr);};
  assert(dialog.open_tracking(parent,snapshot,"h3",action,{"tool-progress","pending","Mounting head"}));
  assert(find("1. Check head attachment"));
  auto*move=find(std::string("2. ")+(std::string(action)=="take"?"Mount head":"Dock head"));
  assert(move&&move->text_color==0xffff6600U);
  assert(find("3. Verify attachment sensors"));
  snapshot["toolhead_operation"]["phase"]="verifying";dialog.update(snapshot);
  assert(find("3. Verify attachment sensors")->text_color==0xffff6600U);
  dialog.close();fake::del(parent);
 }
 // Unload progress survives navigation without repeating motion or cancellation.
 // Failure at withdrawal must not paint the later verification stage complete.
 {
  StockFilamentProcedure dialog;auto*parent=fake::make(fake::screen);parent->w=670;parent->h=340;
  Json snapshot={{"owner","standalone"},{"session","unload-session"},{"fresh",true},
   {"heads",Json::array({{{"id","h2"},{"actual",150},{"target",220}}})},
   {"filament_operation",{{"id","unload-existing"},{"session","unload-session"},{"head","h2"},
    {"action","unload"},{"state","running"},{"phase","heating"},
    {"steps",Json::array({{{"phase","preparing"},{"label","Position head"}},
     {{"phase","heating"},{"label","Heat nozzle"}},{{"phase","feeding"},{"label","Retract filament"}},
     {{"phase","finishing"},{"label","Finish and turn heater off"}}})}}}};
  unsigned submitted=0,cancelled=0;
  dialog.submit=[&](FilamentProcedureReview&){++submitted;return Receipt{"unexpected","pending",""};};
  dialog.cancel=[&](const std::string&){++cancelled;return true;};
  auto find=[&](const std::string&text){for(const auto&n:fake::nodes)if(n->live&&n->text==text&&!(n->flags&1))for(auto*p=n->parent;p;p=p->parent)if(p==parent)return n.get();return static_cast<fake::Node*>(nullptr);};
  assert(dialog.open_tracking(parent,snapshot,"h2","unload",{"unload-existing","pending","Heating Head 3"}));
  assert(find("2. Heat nozzle"));
  fake::send(find("CLOSE")->parent,7);assert(!dialog.active()&&!submitted&&!cancelled);
  snapshot["heads"][0]["actual"]=220;snapshot["filament_operation"]["phase"]="feeding";
  assert(dialog.reopen_result(parent,snapshot));
  assert(find("2. Heat nozzle"));
  auto*withdraw=find("3. Retract filament");assert(withdraw);assert(withdraw->text_color==0xffff6600U);
  assert(find("4. Finish and turn heater off"));
  snapshot["filament_operation"]["state"]="failed";
  snapshot["filament_operation"]["message"]="Withdrawal interrupted; inspect filament.";
  const auto nodes=fake::nodes.size();dialog.update(snapshot);
  dialog.result({{"state","failed"},{"message","Withdrawal interrupted; inspect filament."}});
  assert(!find("3. Retract filament")&&(withdraw->flags&1)&&fake::nodes.size()==nodes);
  fake::send(find("CLOSE")->parent,7);assert(dialog.reopen_result(parent,snapshot));
  assert(!find("3. Retract filament"));
  assert(!find("4. Finish and turn heater off"));
  bool failure_visible=false;for(const auto&n:fake::nodes)if(n->live&&n->text.find("Withdrawal interrupted; inspect filament.")!=std::string::npos)failure_visible=true;
  assert(failure_visible);
  auto*stopped=find("STOPPED")->parent;assert(stopped->state&128);fake::send(stopped,7);
  assert(!submitted&&!cancelled);fake::del(parent);
 }
 // A new screen runtime can reopen either backend interrupted operation.
 for(bool tool:{false,true}){
  wmp_openace::UiChannel restarted_channel;Runtime restarted(http,port,restarted_channel);
  auto*page=fake::make(fake::screen);auto*content=fake::make(page);content->w=670;content->h=340;
  StockFilamentWidgets widgets;widgets.content=content;widgets.count=4;
  for(auto&slot:widgets.slots){slot.card=fake::make(content);slot.number=fake::make(slot.card);slot.colour=fake::make(slot.card);slot.material=fake::make(slot.card);slot.material_label=fake::make(slot.material);}
  RuntimeReceiptTest::attach(restarted,widgets,page,fake::make(content),fake::make(content));
  Json interrupted={{"owner","standalone"},{"fresh",true},{"session","live-session"},{"revision","rev"},{"job",{{"state","idle"}}},{"filament_recovery_protocol",1},
   {"heads",Json::array({{{"id","h2"},{"loaded",{{"state","loaded"}}}}})},
   {"filament_operation",{{"id","existing-operation"},{"session","live-session"},{"head","h2"},{"action","load"},{"state","unknown"}}}};
  if(tool){
   interrupted["toolhead_recovery_protocol"]=1;
   interrupted["toolhead_operation"]=interrupted["filament_operation"];
   interrupted["toolhead_operation"]["action"]="take";
   interrupted.erase("filament_operation");
  }
  RuntimeReceiptTest::tool_context(restarted,interrupted,port.now);
  assert(RuntimeReceiptTest::tool_receipt(restarted).empty());RuntimeReceiptTest::tool_action(restarted,"view-operation");
  assert(RuntimeReceiptTest::procedure_active(restarted)&&RuntimeReceiptTest::tool_receipt(restarted)=="existing-operation");
  fake::Node*recover=nullptr;
  for(const auto&n:fake::nodes)if(n->live&&n->text=="RECOVER")for(auto*p=n->parent;p;p=p->parent)if(p==content)recover=n->parent;
  assert(recover&&!(recover->state&128));fake::send(recover,7);fake::send(recover,7);
  auto changed=interrupted;changed["session"]="different-session";RuntimeReceiptTest::tool_context(restarted,changed,port.now);RuntimeReceiptTest::update_tool(restarted);
  assert(recover->state&128);fake::del(page);
 }
 // Terminal results have exactly one visible exit and cannot be reopened
 // through an old progress shortcut, including after a UI restart.
 for(const auto*action:{"load","unload","take","dock"})for(const auto*state:{"complete","failed","refused"}){
  auto*parent=fake::make(fake::screen);parent->w=670;parent->h=340;
  StockFilamentProcedure panel;unsigned submitted=0;
  panel.submit=[&](FilamentProcedureReview&){++submitted;return Receipt{};};
  Json snapshot={{"owner","standalone"},{"fresh",true},{"session","current"},{"job",{{"state","idle"}}}};
  assert(panel.open_tracking(parent,snapshot,"h2",action,{"terminal",state,"Operation ended"}));
  std::vector<fake::Node*>exits;
  for(const auto&node:fake::nodes){auto*n=node.get();if(!n->live||n->children.empty()||!n->children[0]->is_label)continue;
   const auto text=n->children[0]->text;if(text!="DONE"&&text!="CLOSE"&&text!="STOPPED"&&text!="LOAD"&&text!="UNLOAD"&&text!="LOADED"&&text!="EMPTY")continue;
   bool shown=true,under=false;for(auto*p=n;p;p=p->parent){if(p->flags&1)shown=false;if(p==parent){under=true;break;}}
   if(shown&&under)exits.push_back(n);
  }
  assert(exits.size()==1&&exits[0]->children[0]->text==(std::string(state)=="complete"?"DONE":"CLOSE"));
  fake::send(exits[0],7);assert(!panel.active()&&!submitted);fake::del(parent);
 }
 // Completion describes actual Take/Dock, while reconciliation claims only a check.
 for(const auto*action:{"take","dock"})for(bool recovered:{false,true}){
  StockFilamentProcedure panel;auto*parent=fake::make(fake::screen);parent->w=670;parent->h=340;
  Json snapshot={{"owner","standalone"},{"fresh",true},{"session","current"},{"revision","rev"},{"job",{{"state","idle"}}},
   {"heads",Json::array({{{"id","h2"}}})},{"toolhead_operation",{{"id","result"},{"session","current"},{"recovered",recovered}}}};
  Receipt receipt;receipt.id="result";receipt.state="complete";
  assert(panel.open_tracking(parent,snapshot,"h2",action,receipt));
  const std::string expected=recovered?"Head check complete.":std::string(action)=="take"?"Head mounted.":"Head docked.";
  auto check=[&]{bool found=false;for(const auto&n:fake::nodes)if(n->live&&n->text==expected)for(auto*p=n->parent;p;p=p->parent)if(p==parent)found=true;assert(found);};
  check();panel.close();assert(panel.reopen_result(parent,snapshot));check();panel.close();fake::del(parent);
 }
 // Positive target confirmation uses the bound service receipt; Off uses its independent transport above.
 for(int target:{210}){
  wmp_openace::UiChannel heat_channel;Runtime heat_runtime(http,port,heat_channel);
  auto*page=fake::make(fake::screen);auto*content=fake::make(page);content->w=670;content->h=340;
  StockFilamentWidgets widgets;widgets.content=content;widgets.count=4;
  for(auto&slot:widgets.slots){slot.card=fake::make(content);slot.number=fake::make(slot.card);slot.colour=fake::make(slot.card);slot.material=fake::make(slot.card);slot.material_label=fake::make(slot.material);}
  RuntimeReceiptTest::attach(heat_runtime,widgets,page,fake::make(content),fake::make(content));
  auto heat_data=data;heat_data["owner"]="standalone";heat_data["fresh"]=true;
  heat_data["capabilities"]["temperature"]=true;heat_data["heater_limits"]["h2"]={{"min",0},{"max",300}};
  RuntimeReceiptTest::tool_context(heat_runtime,heat_data,port.now);
  auto old=heat_data;old["revision"]="stale";
  assert(!RuntimeReceiptTest::temperature(heat_runtime,old,target));
  assert(!RuntimeReceiptTest::temperature(heat_runtime,heat_data,301));
  assert(RuntimeReceiptTest::temperature(heat_runtime,heat_data,target));
  assert(!RuntimeReceiptTest::tool_receipt(heat_runtime).empty());
  assert(!RuntimeReceiptTest::temperature(heat_runtime,heat_data,target));
  fake::del(page);
 }
 // General's immediate-write nozzle page must open the managed draft editor.
 {
  Http wire;Port clock;clock.now=10000;wmp_openace::UiChannel c;Runtime r(wire,clock,c);
  Json status={{"fresh",true},{"owner","standalone"},{"session","session-a"},{"nozzle_revision","revision-a"},
   {"job",{{"state","idle"}}},{"capabilities",{{"save_nozzle",true}}},
   {"attachment",{{"head","h2"}}},
   {"nozzle_settings",{{"h0",{{"material","Hardened steel"},{"diameter",0.4}}},
                       {"h2",{{"material","Hardened steel"},{"diameter",0.4}}}}}};
  RuntimeReceiptTest::tool_context(r,status,clock.now);
  assert(!r.nozzle_navigation(nullptr)&&!r.nozzle_navigation("other_page"));
  auto stale=status;stale["fresh"]=false;RuntimeReceiptTest::tool_context(r,stale,clock.now);
  assert(r.nozzle_navigation("nozzle_type_page")&&RuntimeReceiptTest::requested(r)==-1);
  auto ace=status;ace["owner"]="openace";RuntimeReceiptTest::tool_context(r,ace,clock.now);
  assert(!r.nozzle_navigation("nozzle_type_page")&&RuntimeReceiptTest::requested(r)==-1);
  RuntimeReceiptTest::tool_context(r,status,clock.now);
  RuntimeReceiptTest::pending(r,true,"busy");assert(r.nozzle_navigation("nozzle_type_page")&&RuntimeReceiptTest::requested(r)==32);
  RuntimeReceiptTest::pending(r,true,"");
  auto unmounted=status;unmounted["attachment"]=Json::object();RuntimeReceiptTest::tool_context(r,unmounted,clock.now);
  assert(r.nozzle_navigation("nozzle_type_page")&&RuntimeReceiptTest::requested(r)==30);
  r.request(0);r.gui_step();
  RuntimeReceiptTest::tool_context(r,status,clock.now);
  auto*page=fake::make(fake::screen);auto*content=fake::make(page);content->w=670;content->h=340;
  unsigned navigations=0;
  r.set_stock_navigation([&](const char*name){
   assert(std::string(name)=="filament_page");++navigations;
   StockFilamentWidgets widgets;widgets.content=content;widgets.count=4;
   for(auto&slot:widgets.slots){slot.card=fake::make(content);slot.number=fake::make(slot.card);slot.colour=fake::make(slot.card);slot.material=fake::make(slot.card);slot.material_label=fake::make(slot.material);}
   RuntimeReceiptTest::attach(r,widgets,page,fake::make(content),fake::make(content));
  });
  assert(r.nozzle_navigation("nozzle_type_page")&&RuntimeReceiptTest::requested(r)==32);
  r.gui_step();assert(navigations==0&&RuntimeReceiptTest::nozzle_active(r));
  fake::Node*nozzle_root=nullptr;for(const auto&n:fake::nodes)if(n->live&&n->text=="Head 3 - Nozzle")nozzle_root=n->parent;
  assert(nozzle_root&&RuntimeReceiptTest::tool_receipt(r).empty());
  for(const auto&n:fake::nodes)if(n->live&&n->text=="BACK"&&n->parent&&n->parent->parent==nozzle_root){
   fake::send(n->parent,7);break;
  }
  assert(!RuntimeReceiptTest::nozzle_active(r)&&navigations==0);
  fake::del(page);
 }
 // Nozzle edits are drafts; only explicit Save submits the physical head.
 {
  StockNozzleEditor editor;unsigned saves=0;Json submitted;
  auto*page=fake::make(fake::screen);page->w=670;page->h=340;
  Json status={{"fresh",true},{"owner","standalone"},{"session","session-a"},{"nozzle_revision","revision-a"},
   {"job",{{"state","idle"}}},{"capabilities",{{"save_nozzle",true}}},
   {"nozzle_settings",{{"h2",{{"material","Hardened steel"},{"diameter",0.4}}}}}};
  editor.submit=[&](const Json&draft){++saves;submitted=draft;return Receipt{"nozzle-1","pending","Saving"};};
  auto find=[&](const std::string&text){for(const auto&n:fake::nodes)if(n->live&&n->text==text)for(auto*p=n->parent;p;p=p->parent)if(p==page)return n->parent;return static_cast<fake::Node*>(nullptr);};
  auto select=[&](const std::string&prefix,unsigned value){for(const auto&n:fake::nodes)if(n->live&&n->options.find(prefix)==0)for(auto*p=n->parent;p;p=p->parent)if(p==page){fake::send(n.get(),31);n->selected=value;fake::send(n.get(),28);return;}assert(false);};
  editor.update(status);assert(editor.show(page,2));assert(find("SAVE")->state&128);
  auto stale_status=status;stale_status["fresh"]=false;editor.update(stale_status);assert(find("Waiting for printer status."));
  editor.update(status);assert(!find("Waiting for printer status."));
  select("Select material",2);select("Select diameter",3);assert(saves==0);
  fake::send(find("BACK"),7);assert(!editor.active()&&saves==0);
  assert(editor.show(page,2));assert(find("SAVE")->state&128);
  select("Select diameter",3);select("Select material",2);
  for(const auto*job:{"printing","paused"}){
   status["job"]["state"]=job;status["toolhead_operation"]={{"state","running"}};
   editor.update(status);assert((find("SAVE")->state&128)&&saves==0);
   assert(find("Finish or cancel the print before changing nozzle settings."));
   fake::send(find("SAVE"),7);assert(saves==0);
   for(const auto&n:fake::nodes)if(n->live&&(n->options.find("Select diameter")==0||n->options.find("Select material")==0))
    for(auto*p=n->parent;p;p=p->parent)if(p==page)assert(n->state&128);
  }
  status["job"]["state"]="idle";editor.update(status);assert(!(find("SAVE")->state&128));
  for(const auto*state:{"pending","running"}){
   status["identification"]={{"state",state}};editor.update(status);assert(find("SAVE")->state&128);
   assert(find("Wait for head identification to finish before saving."));fake::send(find("SAVE"),7);assert(saves==0);
  }
  status["identification"]["state"]="complete";editor.update(status);assert(!(find("SAVE")->state&128));
  page->flags|=1;fake::send(find("SAVE"),7);assert(saves==0);page->flags&=~1U;
  fake::send(find("SAVE"),7);assert(saves==1&&submitted["head"]=="h2"&&submitted["diameter"]==0.6&&submitted["material"]=="Stainless steel"&&submitted["expected"]=="revision-a");
  fake::send(find("SAVE"),7);assert(saves==1);
  status["receipts"]={{"nozzle-1",{{"state","complete"},{"message","Saved. Restart required."}}}};
  editor.update(status);assert(!editor.active());
  assert(editor.show(page,2));select("Select diameter",3);
  status["nozzle_revision"]="revision-b";editor.update(status);fake::send(find("SAVE"),7);assert(saves==1);
  assert(find("Settings changed. Go back and reopen."));
  editor.close();fake::fail_binding=true;assert(!editor.show(page,2));fake::fail_binding=false;assert(!editor.active());
  assert(editor.show(page,2));fake::del(page);assert(!editor.active());editor.close();
 }
 // Rebind actual stock keypad objects: original heating callback is removed.
 StockTemperatureKeypad keypad;unsigned confirmations=0;int requested_temperature=0;
 auto keypad_fixture=[&](std::array<void*,13>&keys,fake::Node*&text){
  auto*modal=fake::make(fake::screen);text=fake::make(modal);
  fake::bind(text,reinterpret_cast<void(*)(void*)>(number_text_event),7,nullptr);
  fake::bind(text,reinterpret_cast<void(*)(void*)>(number_text_event),31,nullptr);
  for(auto&key:keys){key=fake::make(modal);fake::bind(key,reinterpret_cast<void(*)(void*)>(number_key_event),7,nullptr);}
  return modal;
 };
 std::array<void*,13>keys;fake::Node*entry=nullptr;auto*keypad_modal=keypad_fixture(keys,entry);
 assert(keypad.attach(keypad_modal,entry,keys,220,[&](int n){++confirmations;if(n>300)return false;requested_temperature=n;return true;}));
 assert(entry->callbacks.empty()); // no vendor READY path remains
 for(unsigned i=0;i<3;++i)fake::send(static_cast<fake::Node*>(keys[12]),7);
 for(unsigned i:{1U,4U,9U})fake::send(static_cast<fake::Node*>(keys[i]),7);
 assert(entry->text=="250");fake::send(static_cast<fake::Node*>(keys[11]),7);
 assert(confirmations==1&&requested_temperature==250&&!keypad_modal->live);
 keypad_modal=keypad_fixture(keys,entry);
 assert(keypad.attach(keypad_modal,entry,keys,350,[&](int n){++confirmations;return n<=300;}));
 fake::send(static_cast<fake::Node*>(keys[11]),7);assert(keypad_modal->live&&confirmations==2);
 fake::send(static_cast<fake::Node*>(keys[10]),7);assert(!keypad_modal->live&&confirmations==2);
 // A zero target must accept 220 directly, with no leading-zero backspace.
 for(const bool save:{false,true}){
  keypad_modal=keypad_fixture(keys,entry);unsigned commits=0;int value=-1;
  assert(keypad.attach(keypad_modal,entry,keys,0,[&](int n){++commits;value=n;return true;}));
  auto*cancel_cover=static_cast<fake::Node*>(keys[10])->children.back();
  auto*save_cover=static_cast<fake::Node*>(keys[11])->children.back();
  assert(cancel_cover->children.back()->text=="CANCEL"&&save_cover->children.back()->text=="SAVE");
  assert(!(cancel_cover->flags&2)&&!(save_cover->flags&2));
  for(unsigned i:{9U,9U})fake::send(static_cast<fake::Node*>(keys[i]),7);
  assert(entry->text=="0");
  for(unsigned i:{1U,1U,9U})fake::send(static_cast<fake::Node*>(keys[i]),7);
  assert(entry->text=="220"&&commits==0);
  fake::send(static_cast<fake::Node*>(keys[8]),7);assert(entry->text=="220");
  fake::send(static_cast<fake::Node*>(keys[save?11:10]),7);
  assert(!keypad_modal->live&&commits==(save?1u:0u));if(save)assert(value==220);
 }
 keypad_modal=keypad_fixture(keys,entry);entry->callbacks.clear();
 assert(!keypad.attach(keypad_modal,entry,keys,220,[](int){assert(false);return true;}));assert(!keypad_modal->live);
 // New Toolhead controls occupy stock content, with no screen-sized root.
 auto*tool_page=fake::make(fake::screen);auto*tool_content=fake::make(tool_page);tool_content->w=670;tool_content->h=340;
 auto*tool_rule=fake::make(tool_content);tool_rule->w=650;tool_rule->h=1;
 auto*tool_actions=fake::make(tool_content);auto*tool_tips=fake::make(tool_content);
 StockFilamentWidgets tool_widgets;tool_widgets.content=tool_content;tool_widgets.count=4;
 for(auto&slot:tool_widgets.slots){slot.card=fake::make(tool_content);slot.number=fake::make(slot.card);slot.colour=fake::make(slot.card);slot.material=fake::make(slot.card);slot.material_label=fake::make(slot.material);}
 stock_native.tool_mode(true,2);stock_native.attach(tool_widgets,tool_page,tool_actions,tool_tips);
 std::string tool_action;stock_native.tool_controls().action=[&](const std::string&id){tool_action=id;};
 tool_actions->flags&=~1U; // Vendor refresh can re-show its controls.
 stock_native.tool_data(data,25,220);stock_native.tick(true,true);
 assert(tool_actions->flags&1);assert(tool_rule->flags&1);
 tool_rule->flags&=~1U;stock_native.tick(true,true);assert(tool_rule->flags&1);
 assert(tool_content->parent==tool_page&&tool_page->parent==fake::screen);
 for(unsigned i=0;i<4;++i){const auto&slot=tool_widgets.slots[i];
  assert(static_cast<fake::Node*>(slot.card)->parent==tool_content);
  if(i==2){assert(static_cast<fake::Node*>(slot.card)->y==80);
   bool loaded=false;for(const auto&head:data["heads"])if(head.value("id","")=="h2")loaded=head.value("loaded",Json::object()).value("state","")=="loaded";
   assert(static_cast<fake::Node*>(slot.material)->flags&1);
   (void)loaded;}
  else assert(static_cast<fake::Node*>(slot.card)->flags&1);
 }
 fake::Node*retract=nullptr;
 for(const auto&node:fake::nodes)if(node->live&&node->text=="Retract\n25 mm")retract=node->parent;
 assert(retract&&retract->parent==tool_content);
 for(auto*n:tool_content->children){if(n->text=="Distance (mm)"||n->text=="Actual: 28 / 0 C")assert(n->text_color==0xffeeeeeeU);}
 fake::send(retract,7);assert(tool_action=="retract");
 const auto tool_allocations=fake::nodes.size();stock_native.tick(true,true);assert(fake::nodes.size()==tool_allocations);
 auto tool_button=[&](const std::string&caption)->fake::Node*{for(const auto&node:fake::nodes)if(node->live&&node->text==caption&&node->parent&&node->parent->parent==tool_content)return node->parent;return nullptr;};
 auto*edit_icon=tool_button("\xef\x8c\x84");assert(edit_icon&&edit_icon->background_opacity==0);
 assert(edit_icon->x==152&&edit_icon->y==80&&edit_icon->w==40&&edit_icon->h==32);
 tool_action.clear();fake::send(edit_icon,7);assert(tool_action.empty()&&(edit_icon->flags&1));
 tool_action.clear();tool_content->flags|=1;fake::send(edit_icon,7);assert(tool_action.empty());tool_content->flags&=~1U;
 for(int distance:{1,10,25,50})assert(tool_button(std::to_string(distance))->styles.back()==(distance==25?0x463c918U:0x463c908U));
 assert(!tool_button("5"));
 for(int distance:{1,10,25,50}){auto*b=tool_button(std::to_string(distance));assert(b->h==52&&b->w>=70);}
 assert(retract->children.size()==2&&retract->children[1]->x==51&&retract->children[1]->y==8);
 auto*extrude=tool_button("Extrude\n25 mm");assert(extrude->children.size()==2&&extrude->children[1]->y==56);
 assert(retract->children[0]->text_alignment==2&&extrude->children[0]->text_alignment==2);
 assert(!tool_button("[25]"));
 stock_native.tool_data(data,10,220);stock_native.tick(true,true);
 assert(tool_button("10")->styles.back()==0x463c918U&&tool_button("25")->styles.back()==0x463c908U);
 auto tool_state=data;tool_state["fresh"]=true;
 tool_state["sources"]=Json::array({{{"id","external:h2"},{"kind","external"},{"head","h2"},{"available",true}}});
 tool_state["heads"]=Json::array({{{"id","h2"},{"actual",28},{"target",0},{"loaded",{{"state","empty"}}}}});
 stock_native.tool_data(tool_state,25,220);stock_native.tick(true,true);
 assert(!(tool_button("Load")->flags&1)&&(tool_button("Unload")->flags&1));
 assert(tool_button("Load")->w==180&&tool_button("Unload")->w==180);
 assert(tool_button("Load")->x==tool_button("Unload")->x);
 assert(tool_button("Load")->y+tool_button("Load")->h==tool_button("Extrude\n25 mm")->y+tool_button("Extrude\n25 mm")->h);
 assert(tool_button("Load")->children[0]->text_alignment==2);
 auto tool_label=[&](const std::string&caption){for(const auto&node:fake::nodes)if(node->live&&node->parent==tool_content&&node->text==caption&&!(node->flags&1))return true;return false;};
 assert(tool_label("Empty"));
 tool_state["heads"][0]["loaded"]["sensor_present"]=true;
 stock_native.tool_data(tool_state,25,220);stock_native.tick(true,true);
 assert(tool_label("Inserted")&&!tool_label("Empty"));
 assert(!(tool_button("Load")->flags&1)&&(tool_button("Unload")->flags&1));
 tool_state["heads"][0]["loaded"]["sensor_present"]=false;
 stock_native.tool_data(tool_state,25,220);stock_native.tick(true,true);
 assert(tool_label("Empty")&&!tool_label("Inserted"));
 assert(static_cast<fake::Node*>(tool_widgets.slots[2].material)->flags&1);
 // Error text alone does not disable Take; live SD/pause still does.
 for(bool sd:{false,true})for(bool paused:{false,true}){
  Json error_status={{"webhooks",{{"state","ready"}}},{"print_stats",{{"state","error"}}},{"virtual_sdcard",{{"is_active",sd}}},{"pause_resume",{{"is_paused",paused}}}};
  auto available=tool_state;available["owner"]="standalone";available["job"]=project(error_status,Json::object(),false,"test")["job"];
  available["capabilities"]["toolhead_action"]=true;available["attachment"]={{"state","empty"}};available["heads"][0]["mounting"]="No head mounted";
  stock_native.tool_data(available,25,220);stock_native.tick(true,true);auto*take=tool_button("Mount");assert(take);
  assert(bool(take->state&128)==(sd||paused));tool_action.clear();fake::send(take,7);assert((tool_action=="take-dock")==(!sd&&!paused));
 }
 auto mounted=tool_state;mounted["owner"]="standalone";mounted["job"]={{"state","idle"}};mounted["capabilities"]["toolhead_action"]=true;mounted["heads"][0]["mounting"]="Mounted";
 stock_native.tool_data(mounted,25,220);stock_native.tick(true,true);
 assert(tool_button("Head 3")->children[0]->text_color==0xffff6600U);
 // Viewing a different head keeps the physical mount indicator on Head 4.
 auto other_mounted=mounted;
 other_mounted["heads"][0]["mounting"]="Not mounted";
 other_mounted["heads"].push_back({{"id","h3"},{"mounting","Mounted"}});
 stock_native.tool_data(other_mounted,25,220);stock_native.tick(true,true);
 assert(tool_button("Head 3")->styles.back()==0x463c918U);
 assert(tool_button("Head 3")->children[0]->text_color==0xffeeeeeeU);
 assert(tool_button("Head 4")->children[0]->text_color==0xffff6600U);
 other_mounted["fresh"]=false;stock_native.tool_data(other_mounted,25,220);stock_native.tick(true,true);
 assert(tool_button("Head 4")->children[0]->text_color==0xffeeeeeeU);
 stock_native.tool_data(mounted,25,220);stock_native.tick(true,true);
 assert(tool_button("Dock")&&!(tool_button("Dock")->state&128));tool_action.clear();fake::send(tool_button("Dock"),7);assert(tool_action=="take-dock");
 for(bool allowed:{false,true})for(bool fresh:{false,true})for(const auto*op:{"complete","pending","running"}){
  auto fault=mounted;fault["job"]["state"]="paused";fault["fresh"]=fresh;
  fault["toolchange_pause"]={{"manual_toolhead_available",allowed}};fault["toolhead_operation"]={{"state",op}};
  stock_native.tool_data(fault,25,220);stock_native.tick(true,true);
  auto*dock=tool_button(fresh?"Dock":"Mount state unknown");assert(dock);const bool enabled=allowed&&fresh&&std::string(op)=="complete";
  assert(bool(dock->state&128)==!enabled);tool_action.clear();fake::send(dock,7);assert((tool_action=="take-dock")==enabled);
 }
 for(const auto*head:{"h2","h3"})for(const auto*action:{"dock","take"}){
  auto ordinary=mounted;ordinary["job"]["state"]="paused";ordinary.erase("toolchange_pause");
  ordinary["paused_toolhead_actions"]={{"head",head},{"actions",Json::array({action})}};
  stock_native.tool_data(ordinary,25,220);stock_native.tick(true,true);
  const bool allowed=std::string(head)=="h2"&&std::string(action)=="dock";
  assert(bool(tool_button("Dock")->state&128)==!allowed);
  tool_action.clear();fake::send(tool_button("Dock"),7);assert((tool_action=="take-dock")==allowed);
 }
 mounted["toolhead_operation"]={{"state","running"}};stock_native.tool_data(mounted,25,220);stock_native.tick(true,true);
 assert(tool_button("Dock")->state&128);tool_action.clear();fake::send(tool_button("Dock"),7);assert(tool_action.empty());
 mounted["toolhead_operation"]=Json::object();mounted["heads"][0]["mounting"]="Not mounted";
 stock_native.tool_data(mounted,25,220);stock_native.tick(true,true);assert(tool_button("Mount")&&!(tool_button("Mount")->state&128));
 auto inserted=mounted;inserted["capabilities"]["confirm_filament"]=true;
 inserted["heads"][0]["loaded"]={{"state","empty"},{"sensor_present",true}};
 stock_native.tool_data(inserted,25,220);stock_native.tick(true,true);
 assert(!tool_button("Check filament"));
 assert(tool_button("Load")&&!(tool_button("Load")->state&128));
 inserted["heads"][0]["loaded"]["state"]="loaded";
 stock_native.tool_data(inserted,25,220);stock_native.tick(true,true);
 assert(stock_native.tool_controls().edit_allowed());
 assert(!tool_button("Check filament"));
 auto ace_empty=tool_state;ace_empty["sources"].push_back({{"id","ace:0"},{"kind","ace"},{"head","h2"},{"available",false}});
 stock_native.tool_data(ace_empty,25,220);stock_native.tick(true,true);
 assert(tool_button("Load")->flags&1);assert(!stock_native.tool_controls().edit_allowed());
 stock_native.tool_data(tool_state,25,220);stock_native.tick(true,true);

 tool_state["heads"][0]["loaded"]={{"state","loaded"}};
 stock_native.tool_data(tool_state,25,220);stock_native.tick(true,true);
 assert((tool_button("Load")->flags&1)&&!(tool_button("Unload")->flags&1));
 assert(!tool_button("Filament identity unknown\nLoaded"));
 assert(static_cast<fake::Node*>(tool_widgets.slots[2].material_label)->text=="Unknown");
 assert(static_cast<fake::Node*>(tool_widgets.slots[2].material)->flags&1);
 // An interrupted backend operation must block controls even after the UI
 // loses its local busy record. Synthetic clicks must not bypass disabling.
 for(const auto*operation:{"filament_operation","toolhead_operation"}){
  auto interrupted=tool_state;interrupted[operation]={{"state","unknown"}};
  stock_native.tool_data(interrupted,25,220);stock_native.tick(true,true);
  for(const auto*caption:{"Load","Unload","X","Retract\n25 mm","Extrude\n25 mm"}){
   auto*control=tool_button(caption);assert(control&&(control->state&128));
   tool_action.clear();fake::send(control,7);assert(tool_action.empty());
  }
 }
 stock_native.tool_data(tool_state,25,220);stock_native.tick(true,true);
 tool_action.clear();fake::send(tool_button("Unload"),7);assert(tool_action=="unload");
 tool_action.clear();fake::send(tool_button("Load"),7);assert(tool_action.empty());

 tool_state["tool_ui_busy"]={{"pending",true},{"action","retract"},{"head","h2"}};
 stock_native.tool_data(tool_state,25,220);stock_native.tick(true,true);
 assert(tool_button("Retracting...")&&(tool_button("Retracting...")->state&128));
 assert(edit_icon->state&128);tool_action.clear();fake::send(edit_icon,7);assert(tool_action.empty());
 assert(tool_button("Extrude\n25 mm")->state&128);
 for(unsigned i=0;i<4;++i)assert(tool_button("Head "+std::to_string(i+1))->styles.back()==(i==2?0x463c918U:0x463c908U));
 tool_state["tool_ui_busy"]["pending"]=false;stock_native.tool_data(tool_state,25,220);stock_native.tick(true,true);
 assert(!(tool_button("Retract\n25 mm")->state&128));
 tool_state["heads"][0]["loaded"]={{"state","unknown"}};
 stock_native.tool_data(tool_state,25,220);stock_native.tick(true,true);
 assert(!tool_button("Filament identity unknown\nCheck filament"));
 assert((tool_button("Load")->flags&1)&&(tool_button("Unload")->flags&1));
 tool_state["owner"]="standalone";stock_native.tool_data(tool_state,25,220);stock_native.tick(true,true);
 tool_state["tool_ui_busy"]["pending"]=true;stock_native.tool_data(tool_state,25,220);stock_native.tick(true,true);
 assert(!(edit_icon->state&128));tool_action.clear();fake::send(edit_icon,7);assert(tool_action=="edit-filament");
 tool_state["tool_ui_busy"]["pending"]=false;stock_native.tool_data(tool_state,25,220);stock_native.tick(true,true);
 assert(!tool_button("Check filament"));
 tool_state["heads"][0]["mounting"]="Mounted";
 stock_native.tool_data(tool_state,25,220);stock_native.message("");stock_native.tick(true,true);
 assert(tool_tips->text=="Toolhead management - Mounted"&&tool_tips->y+tool_tips->h<=32);assert(tool_button("Dock")&&(tool_button("Dock")->state&128));
 stock_native.message("Operation refused");stock_native.tick(true,true);assert(tool_tips->text=="Mounted - Operation refused");stock_native.message("");
 tool_state["heads"][0]["mounting"]="Not mounted";stock_native.tool_data(tool_state,25,220);stock_native.tick(true,true);
 assert(tool_tips->text=="Toolhead management - Not mounted");assert(tool_button("Mount"));
 tool_state["heads"][0]["mounting"]="bogus";stock_native.tool_data(tool_state,25,220);stock_native.tick(true,true);
 assert(tool_tips->text=="Toolhead management - Attachment unknown");
 stock_native.tick(false,false);assert(tool_tips->text=="Printer status unavailable");stock_native.tick(true,true);

 tool_state["tool_ui_busy"]={{"pending",true},{"action","load"},{"head","h2"}};
 stock_native.tool_data(tool_state,25,220);stock_native.tick(true,true);
 assert(tool_button("Progress")&&!(tool_button("Progress")->flags&1));
 tool_state["tool_ui_busy"]={{"interrupted",true}};stock_native.tool_data(tool_state,25,220);stock_native.tick(true,true);
 assert(tool_button("Recover")&&!(tool_button("Recover")->flags&1));
 tool_state["tool_ui_busy"]={{"reviewable",true}};stock_native.tool_data(tool_state,25,220);
 for(int content_width:{640,670})for(int content_height:{300,320,340}){
  tool_content->w=content_width;
  tool_content->h=content_height;stock_native.tick(true,true);assert(!tool_button("Check filament"));
  auto*result=tool_button("Progress");assert((result->flags&1)&&result->x+result->w<=content_width);
  for(const auto*caption:{"Mount state unknown","X"}){
   auto*other=tool_button(caption);assert(result->x+result->w<=other->x||other->x+other->w<=result->x||result->y+result->h<=other->y||other->y+other->h<=result->y);
  }
 }
 tool_content->h=340;stock_native.tick(true,true);

 // Preserve stock identity objects while switching heads; tabs never dispatch
 // a vendor take/load callback. Stock colour/material clicks enter WM+ editing.
 unsigned tool_head_selected=99;
 stock_native.select_tool=[&](unsigned h){tool_head_selected=h;stock_native.tool_mode(true,h);};
 stock_native.message("Old head result");fake::send(tool_button("Head 1"),7);assert(tool_head_selected==0);
 stock_native.tick(true,true);
 assert(tool_tips->text.find("Old head result")==std::string::npos);
 assert(!(static_cast<fake::Node*>(tool_widgets.slots[0].card)->flags&1));
 assert(static_cast<fake::Node*>(tool_widgets.slots[2].card)->flags&1);
 fake::Event stock_material_click{static_cast<fake::Node*>(tool_widgets.slots[0].material),7,reinterpret_cast<void*>(12)};
 tool_action.clear();assert(stock_native.intercept(&stock_material_click));assert(tool_action.empty());
 stock_native.interaction_blocked(true);tool_action.clear();tool_head_selected=99;
 fake::send(tool_button("Head 2"),7);assert(tool_head_selected==99);
 assert(stock_native.intercept(&stock_material_click)&&tool_action.empty());
 stock_native.interaction_blocked(false);stock_native.tick(false,false);
 fake::send(tool_button("Head 2"),7);assert(tool_head_selected==99);
 assert(stock_native.intercept(&stock_material_click)&&tool_action.empty());
 stock_native.tool_mode(true,2);stock_native.tick(true,true);
 auto known_identity=tool_state;
 known_identity["heads"][0]["loaded"]={{"state","loaded"},{"identity",{{"brand","Example"},{"material","PETG"},{"color","#cd001a"}}}};
 stock_native.tool_data(known_identity,25,220);stock_native.tick(true,true);
 assert(static_cast<fake::Node*>(tool_widgets.slots[2].material_label)->text=="PETG");
 bool plain_material=false;for(auto*n:tool_content->children)if(n->live&&n->text=="PETG"&&n->y==tool_content->h-151)plain_material=true;assert(plain_material);
 assert(!(static_cast<fake::Node*>(tool_widgets.slots[2].colour)->flags&1));
 tool_content->flags|=1;tool_head_selected=99;fake::send(tool_button("Head 1"),7);assert(tool_head_selected==99);tool_content->flags&=~1U;

 tool_state["owner"]="openace";stock_native.tool_data(tool_state,25,220);stock_native.tick(true,true);
 assert(!tool_button("Check filament"));


 // Reconstruct stock page for ACE mode (same structure as the stock constructor).
 fake::del(tool_page);stock_native.tick(true,true);
 auto*integrated_page=fake::make(fake::screen);auto*integrated_content=fake::make(integrated_page);integrated_content->w=670;integrated_content->h=340;
 auto*integrated_actions=fake::make(integrated_content);auto*integrated_tips=fake::make(integrated_content);
 StockFilamentWidgets integrated;integrated.content=integrated_content;integrated.count=4;
 for(auto&slot:integrated.slots){slot.card=fake::make(integrated_content);slot.number=fake::make(slot.card);slot.colour=fake::make(slot.card);slot.material=fake::make(slot.card);slot.material_label=fake::make(slot.material);}
 stock_native.ace_mode(true,1);stock_native.tool_data(data,10,220);stock_native.attach(integrated,integrated_page,integrated_actions,integrated_tips);stock_native.tick(true,true);
 assert(integrated_tips->flags&1);assert(integrated_actions->flags&1);
 unsigned chosen_head=99;stock_native.select_tool=[&](unsigned h){chosen_head=h;stock_native.ace_mode(true,h);};
 fake::Event ace_head_click{static_cast<fake::Node*>(integrated.slots[2].card),7,reinterpret_cast<void*>(6)};
 assert(stock_native.intercept(&ace_head_click)&&chosen_head==2);stock_native.tick(true,true);
 bool integrated_scroll=false;for(auto*child:integrated_content->children)if(child->dir==12){integrated_scroll=true;assert(child->y==52&&child->h==238);}
 assert(integrated_scroll);
 assert(stock_native.intercept(&ace_head_click));stock_native.tick(true,true);
 for(unsigned i=0;i<4;++i)assert(static_cast<fake::Node*>(integrated.slots[i].card)->styles.back()==0x463c908U);
 // Modal edges must not reveal overview head tabs, even after vendor refresh.
 fake::Node*edit_unit=nullptr;
 for(const auto&node:fake::nodes)if(node->live&&node->text=="Edit unit")for(auto*p=node->parent;p;p=p->parent)if(p==integrated_content)edit_unit=node->parent;
 assert(edit_unit);fake::send(edit_unit,7);stock_native.tick(true,true);
 assert(stock_native.ace_controls().modal_active());
 for(const auto&slot:integrated.slots){auto*card=static_cast<fake::Node*>(slot.card);assert(card->flags&1);card->flags&=~1U;}
 stock_native.tick(true,true);
 for(const auto&slot:integrated.slots)assert(static_cast<fake::Node*>(slot.card)->flags&1);
 stock_native.ace_controls().discard_drafts();stock_native.tick(true,true);
 for(const auto&slot:integrated.slots)assert(!(static_cast<fake::Node*>(slot.card)->flags&1));
 fake::del(integrated_page);stock_native.tick(true,true);

 // A loaded external source offers Unload; selecting it only requests a review.
 {
  auto external=data;external["units"]=Json::array();
  external["sources"]=Json::array({{{"id","external:h0"},{"kind","external"},{"head","h0"},{"name","Head 1"},{"available",true},{"identity",{{"brand","Generic"},{"material","PLA"},{"color","#888888"}}}}});
  external["heads"][0]["loaded"]={{"state","loaded"},{"source","external:h0"}};
  auto*parent=fake::make(fake::screen);StockAceFilaments view;std::string action;
  view.action=[&](const std::string&id){action=id;};view.mount(parent);view.update(external,"",670,340);
  auto find=[&](const std::string&text){for(const auto&n:fake::nodes)if(n->live&&n->text==text)for(auto*p=n->parent;p;p=p->parent)if(p==parent)return n->parent;return static_cast<fake::Node*>(nullptr);};
  assert(find("Unknown filament")&&find("?")&&!find("Generic PLA"));
  // Presence identity, rather than configured defaults, drives the card, and
  // changing it while still loaded must invalidate the cached layout.
  external["heads"][0]["loaded"]["identity"]={{"brand","SUNLU"},{"material","PETG"},{"color","#00FF00"}};
  view.update(external,"",670,340);
  assert(find("SUNLU")&&find("PETG")&&!find("Unknown filament")&&!find("Generic PLA"));
  external["heads"][0]["loaded"]["identity"]={{"brand","Kexcelled"},{"material","PLA Matte"},{"color","#7D8A92"}};
  view.update(external,"",670,340);
  assert(find("Kexcelled")&&find("PLA Matte")&&!find("Kexcelled PLA Matte"));
  auto*identity_card=find("Kexcelled");assert(identity_card==find("PLA Matte"));
  for(auto*n:identity_card->children)if(n->text=="Kexcelled"||n->text=="PLA Matte")assert(n->h==20&&n->y+n->h<=identity_card->h);
  external["heads"][0]["loaded"]["state"]="empty";view.update(external,"",670,340);
  assert(find("Load")&&!find("Kexcelled")&&!find("PLA Matte")&&!find("Unknown filament"));
  fake::send(find("Load"),7);assert(action=="load-source:external:h0");action.clear();
  // A stale or unavailable direct Load must not dispatch through this shortcut.
  external["sources"][0]["available"]=false;view.update(external,"",670,340);
  fake::send(find("Load"),7);assert(action.empty());
  external["sources"][0]["available"]=true;external["fresh"]=false;view.update(external,"",670,340);
  fake::send(find("Load"),7);assert(action.empty());external["fresh"]=true;

  // A paused external head can open the real load editor, but an open
  // editor must not silently transfer to another pause or to idle.
  auto paused=external;paused["owner"]="standalone";paused["job"]["state"]="paused";
  paused["paused_filament"]={{"available",true},{"head","h0"},{"origin",{{"head","h0"},{"session",paused.value("session","")},{"id",std::string(32,'a')},{"file_position",120}}}};
  paused["brands"]=native::filament_brands(Json::array());
  view.update(paused,"",670,340);view.open_load("external:h0");view.update(paused,"",670,340);
  assert(view.loading()&&view.identity_ready());
  assert(find("NEXT")&&!find("SAVE"));
  // Brand grid is a draft-only subdialog. It retains controls during sync,
  // paginates the full list and Cancel preserves the parent load editor.
  assert(find("Generic"));
  auto*brand_field=find("Generic");
  assert(brand_field->children.front()->text_alignment==0&&brand_field->children.front()->x==0);
  fake::send(brand_field,7);view.update(paused,"",670,340);
  assert(find("Select brand")&&find("Generic")&&find("Next"));
  assert(find("Generic")->background_color==0xffbf4900U);
  while(!(find("Previous")->state&128)){fake::send(find("Previous"),7);view.update(paused,"",670,340);}
  assert(find("3D BEST-Q"));
  auto*first_brand=find("3D BEST-Q");const auto brand_nodes=fake::nodes.size();
  auto refreshed=paused;refreshed["heads"][0]["actual"]=123;
  view.update(refreshed,"",670,340);assert(find("3D BEST-Q")==first_brand&&fake::nodes.size()==brand_nodes);
  fake::send(find("Next"),7);view.update(paused,"",670,340);
  assert(!find("3D BEST-Q")&&find("Previous"));
  unsigned grid_pages=1;
  while(!(find("Next")->state&128)){assert(++grid_pages<20);fake::send(find("Next"),7);view.update(paused,"",670,340);}
  assert(find("Zyltech"));
  while(!(find("Previous")->state&128)){fake::send(find("Previous"),7);view.update(paused,"",670,340);}
  assert(find("3D BEST-Q"));
  fake::send(find("3D BEST-Q"),7);view.update(paused,"",670,340);
  assert(view.draft_identity()["brand"]=="3D BEST-Q"&&view.loading()&&action.empty());
  fake::send(find("3D BEST-Q"),7);view.update(paused,"",670,340);
  auto stale_brands=paused;stale_brands["fresh"]=false;view.update(stale_brands,"",670,340);
  fake::send(find("3D-Fuel"),7);assert(view.draft_identity()["brand"]=="3D BEST-Q");
  fake::send(find("BACK"),7);view.update(stale_brands,"",670,340);
  assert(view.loading()&&!find("Select brand")&&view.draft_identity()["brand"]=="3D BEST-Q");
  view.update(paused,"",670,340);

  auto no_position=paused;no_position["filament_position"]={{"ready",false},{"reason","Z position was lost. Keep the print paused; do not home Z over the print."}};
  view.update(no_position,"",670,340);assert(!view.identity_ready());
  assert(find("Z position was lost. Keep the print paused; do not home Z over the print."));
  for(const auto&n:fake::nodes)if(n->live&&n->text=="Z position was lost. Keep the print paused; do not home Z over the print.")assert(n->h!=-1);
  assert(find("NEXT")&&(find("NEXT")->state&128));
  view.update(paused,"",670,340);assert(view.identity_ready());
  auto changed_pause=paused;changed_pause["paused_filament"]["origin"]["id"]=std::string(32,'b');
  view.update(changed_pause,"",670,340);assert(!view.identity_ready());
  view.update(external,"",670,340);assert(!view.identity_ready());
  view.discard_drafts();view.update(paused,"",670,340);view.open_load("external:h0");view.update(paused,"",670,340);
  assert(view.identity_ready());view.discard_drafts();

  // External Load exposes the backend-selected temperature, including changes
  // that do not alter spool metadata or rebuild the whole screen.
  auto thermal=external;thermal["owner"]="standalone";thermal["job"]={{"state","idle"}};
  thermal["procedures"]=Json::array({{{"head","h0"},{"action","load"},{"source","external:h0"},{"temperature_description","Load temperature: 245 C. Material transition."}}});
  view.update(thermal,"",670,340);view.open_load("external:h0");view.update(thermal,"",670,340);
  assert(find("Load temperature: 245 C. Material transition."));
  thermal["procedures"][0]["temperature_description"]="Load temperature: 240 C. Material transition.";
  view.update(thermal,"",670,340);
  assert(find("Load temperature: 240 C. Material transition.")&&!find("Load temperature: 245 C. Material transition."));
  thermal["procedures"]=Json::array();thermal["procedure_errors"]={{"h0:load","No shared nozzle temperature range"}};
  view.update(thermal,"",670,340);assert(find("No shared nozzle temperature range"));
  thermal["fresh"]=false;view.update(thermal,"",670,340);
  assert(find("Printer status unavailable.")&&!find("No shared nozzle temperature range"));
  view.discard_drafts();

  external["heads"][0]["loaded"]["state"]="loaded";view.update(external,"",670,340);
  auto*card=find("Head 1");assert(card);fake::send(card,7);view.update(external,"",670,340);
  auto*unload=find("Unload");assert(unload&&!(unload->state&128)&&!find("Load"));assert(action.empty());
  fake::send(unload,7);assert(action=="unload-source:external:h0");
  external["sources"].push_back({{"id","external:h1"},{"kind","external"},{"head","h1"},{"name","Head 2"},{"available",true}});
  unsigned focused=99;view.focus_head=[&](unsigned h){focused=h;};view.update(external,"",670,340);
  fake::send(find("Head 1"),7);view.update(external,"",670,340);assert(focused==0);
  auto*old_edit=find("Edit");assert(old_edit);
  fake::send(find("Head 2"),7);assert(focused==1);view.update(external,"",670,340);
  assert(!old_edit->live&&find("Edit")&&find("Edit")!=old_edit);
  fake::send(find("Cancel"),7);view.update(external,"",670,340);assert(!find("Edit"));
  fake::del(parent);
 }
 {
  auto imported=data;imported["owner"]="standalone";imported["units"]=Json::array();
  imported["sources"]=Json::array({{{"id","external:h0"},{"kind","external"},{"head","h0"},{"name","Head 1"},{"available",true},{"identity",{{"brand","Generic"},{"material","PLA"},{"color","#888888"}}}}});
  imported["filament_catalogue"]=Json::array({{{"name","Example PETG"},{"identity",{{"brand","Example"},{"material","PETG"},{"nozzle_temp",245},{"nozzle_temp_min",230},{"nozzle_temp_max",260}}}}});
  auto*parent=fake::make(fake::screen);StockAceFilaments view;view.mount(parent);view.update(imported,"",670,340);
  auto find=[&](const std::string&text){for(const auto&n:fake::nodes)if(n->live&&n->text==text)for(auto*p=n->parent;p;p=p->parent)if(p==parent)return n->parent;return static_cast<fake::Node*>(nullptr);};
  fake::send(find("Head 1"),7);view.update(imported,"",670,340);fake::send(find("Edit"),7);view.update(imported,"",670,340);
  fake::Node*profiles=nullptr;for(const auto&n:fake::nodes)if(n->live&&n->options=="Custom\nExample PETG")profiles=n.get();
  assert(profiles);fake::send(profiles,31);profiles->selected=1;fake::send(profiles,28);view.update(imported,"",670,340);
  assert(view.identity_ready());const auto draft=view.draft_identity();assert(draft["material"]=="PETG"&&draft["brand"]=="Example"&&draft["nozzle_temp"]==245&&draft["color"]=="#888888");
  view.discard_drafts();assert(!view.modal_active());fake::del(parent);
 }
 // ACE units occupy a scroll pane within stock content, not a replacement root.
 auto*ace_page=fake::make(fake::screen);auto*ace_content=fake::make(ace_page);
 StockAceFilaments ace_view;std::string ace_action;ace_view.action=[&](const std::string&id){ace_action=id;};
 ace_view.mount(ace_content);auto*pane=ace_content->children.back();
 ace_view.update(data,"h0",670,340);assert(pane->parent==ace_content&&pane->dir==12&&pane->y==52);
 const auto ace_allocations=fake::nodes.size();pane->scroll=90;
 ace_view.update(data,"h0",670,340);assert(fake::nodes.size()==ace_allocations&&pane->scroll==90);
 fake::Node*slot_card=nullptr;
 for(const auto&node:fake::nodes)if(node->live&&node->text=="Slot 1"&&node->parent->parent->parent==pane){slot_card=node->parent;break;}
 assert(slot_card&&slot_card->opacity==255);
 bool stock_swatch=false;
 for(auto*child:slot_card->children)if(child->image=="stock-white-filament.bin"){
  stock_swatch=true;assert(child->zoom_factor==256&&child->w==83&&child->h==83);
  assert(child->tint_opa[0]==255&&!(child->flags&2));
 }
 assert(stock_swatch);
 // A status refresh during a press retains the card and every stable child.
 const auto stable_count=fake::nodes.size();auto*pressed_card=slot_card;
 fake::send(pressed_card,0);
 auto fluctuating=data;fluctuating["fresh"]=false;
 ace_view.update(fluctuating,"h0",670,340);
 assert(pressed_card->live&&(pressed_card->state&128)&&fake::nodes.size()==stable_count);
 fake::send(pressed_card,7);assert(ace_action.empty()); // Stale actions still fail closed.
 fluctuating=data;fluctuating["units"][0]["connected"]=false;
 ace_view.update(fluctuating,"h0",670,340);
 assert(pressed_card->live&&fake::nodes.size()==stable_count);
 ace_view.update(data,"h0",670,340);
 assert(pressed_card->live&&!(pressed_card->state&128)&&fake::nodes.size()==stable_count);
 assert(pressed_card->callbacks.size()==1);
 fake::send(pressed_card,0);auto rerouted=data;rerouted["revision"]="changed-during-press";
 ace_view.update(rerouted,"h0",670,340);fake::send(pressed_card,7);
 ace_view.update(data,"h0",670,340);
 assert(fake::nodes.size()==stable_count); // No source menu opened for a changed context.
 for(auto*a:slot_card->children)for(auto*b:slot_card->children){
  if(a==b||a->text.empty()||b->text.empty())continue;
  assert(a->y+a->h<=b->y||b->y+b->h<=a->y);
 }

fake::send(slot_card,7);assert(ace_action.empty());
 ace_view.update(data,"h0",670,340);
 fake::Node*slot_edit_menu=nullptr;
 for(const auto&node:fake::nodes)if(node->live&&node->text=="Edit")for(auto*p=node->parent;p;p=p->parent)if(p==pane)slot_edit_menu=node->parent;
 assert(slot_edit_menu&&ace_view.selected_source().is_null());
 auto*retired_menu_address=slot_edit_menu->parent;
 fake::send(slot_edit_menu,7);
 ace_view.update(data,"h0",670,340);bool source_profile=false;fake::Node*source_back=nullptr;
 for(const auto&node:fake::nodes)if(node->live&&node->parent&&node->parent->parent==pane){

  if(node->text=="BACK")source_back=node->parent;
 }
 for(const auto&node:fake::nodes)if(node->live&&node->parent&&node->parent->parent==pane&&node->text=="Generic")source_profile=true;
 assert(source_profile&&source_back);
 // Model LVGL reusing a deleted menu's address for an unrelated live object.
 // Opening a later menu must not hide that replacement object.
 assert(!retired_menu_address->live);
 *retired_menu_address=fake::Node();
 retired_menu_address->parent=fake::screen;
 fake::screen->children.push_back(retired_menu_address);

 const auto editing_id=ace_view.selected_source().at("id").get<std::string>();
 ace_view.colour_draft(editing_id,"#ffffff");ace_view.update(data,"h0",670,340);
 const auto before_material_preview=ace_view.draft_identity();
 assert(ace_view.modal_active()&&pane->y==8&&pane->h==324&&!(pane->flags&16));
 for(auto*node:pane->children){
  assert(node->y>=0&&node->y+node->h<=pane->h);
  for(auto*caption:node->children)if(caption->text=="BACK"||caption->text=="SAVE")assert(node->y==0);
 }
 fake::Node*material_entry=nullptr;
 for(auto*node:pane->children)if(node->options.find("PLA\nPETG")==0)material_entry=node;
 assert(material_entry);
 // Telemetry/revision redraws retain widgets; their attached styles must not
 // accumulate. Stock LVGL stores the style count in a six-bit field.
 std::map<fake::Node*,std::size_t>editor_styles;
 for(const auto&node:fake::nodes)if(node->live)editor_styles[node.get()]=node->styles.size();
 for(int refresh=0;refresh<128;++refresh){
  auto changing=data;changing["fresh"]=(refresh%2)==0;
  ace_view.update(changing,"h0",670,340);
 }
 ace_view.update(data,"h0",670,340);
 for(const auto&entry:editor_styles)if(entry.first->live)assert(entry.first->styles.size()==entry.second);
 // Real LVGL reparents an open list to the screen. A long material list must
 // stay below the modal actions and within its content even on cached ticks.
 fake::popup_owner=material_entry;fake::popup_list=fake::make(fake::screen);
 auto*popup=fake::popup_list;popup->x=255;popup->y=-80;popup->w=800;popup->h=600;
 material_entry->open=true;fake::send(material_entry,31);
 // Keep the open selector and its callback armed while unrelated status and
 // freshness change. No set_options/recreation may reset an active list.
 auto*open_material=material_entry;const auto open_allocations=fake::nodes.size();
 auto changed_status=data;changed_status["units"][0]["connected"]=false;
 ace_view.update(changed_status,"h0",670,340);
 assert(open_material->live&&open_material->open&&fake::nodes.size()==open_allocations);
 changed_status["fresh"]=false;ace_view.update(changed_status,"h0",670,340);
 assert(open_material->live&&open_material->open&&(open_material->state&128));
 ace_view.update(data,"h0",670,340);
 assert(open_material->live&&open_material->open&&!(open_material->state&128)&&fake::nodes.size()==open_allocations);
 ace_view.update(data,"h0",670,340);
 assert(popup->y>=pane->y+38&&popup->y+popup->h<=pane->y+pane->h);
 assert(popup->x>=pane->x&&popup->x+popup->w<=pane->x+pane->w);
 auto popup_y=popup->y,popup_height=popup->h;ace_view.update(data,"h0",670,340);
 assert(popup->y==popup_y&&popup->h==popup_height);
 material_entry->open=false;fake::del(popup);fake::popup_owner=fake::popup_list=nullptr;
 material_entry->selected=1;fake::send(material_entry,28);
 ace_view.update(data,"h0",670,340);assert(ace_view.draft_identity()["material"]=="PETG"&&ace_view.identity_ready());
 for(auto*node:pane->children)if(node->options.find("PLA\nPETG")==0)material_entry=node;
 fake::send(material_entry,31);material_entry->selected=0;fake::send(material_entry,28);ace_view.update(data,"h0",670,340);
 assert(ace_view.draft_identity()==before_material_preview);
 // A material edit after a successful save must retire the success notice.
 auto saved_source=ace_view.selected_source();
 {
  StockAceFilaments standalone_editor;auto*parent=fake::make(fake::screen);
  auto standalone_data=data;standalone_data["owner"]="standalone";
  standalone_data["sources"]=Json::array({saved_source});
  const auto head=saved_source.value("head","h0");
  for(auto&entry:standalone_data["heads"])if(entry.value("id","")==head)entry["loaded"]={{"state","empty"}};
  std::string destination;standalone_editor.action=[&](const std::string&value){destination=value;};
  standalone_editor.mount(parent);standalone_editor.update(standalone_data,head,670,340);
  assert(standalone_editor.open_head_identity(head));standalone_editor.source_origin(2);
  standalone_editor.update(standalone_data,head,670,340);assert(standalone_editor.modal_active());
  standalone_editor.colour_saved(standalone_data,saved_source);
  assert(!standalone_editor.modal_active()&&destination=="toolhead:2");
  fake::del(parent);
 }
 ace_view.colour_saved(data,saved_source);ace_view.update(data,"h0",670,340);
 auto notice_visible=[&](const std::string&text){for(auto*node:pane->children)if(node->live&&node->text==text)return true;return false;};
 assert(notice_visible("Filament settings saved."));
 auto remote_changed=data;remote_changed["identity_revision"]="new-remote-identity";
 ace_view.update(remote_changed,"h0",670,340);
 assert(!ace_view.identity_ready());
 assert(notice_visible("Filament settings changed. Go back and reopen."));
 assert(!notice_visible("Filament settings saved."));
 ace_view.update(data,"h0",670,340);

 for(auto*node:pane->children)if(node->options.find("PLA\nPETG")==0)material_entry=node;
 fake::send(material_entry,31);material_entry->selected=1;fake::send(material_entry,28);ace_view.update(data,"h0",670,340);
 assert(ace_view.identity_ready()&&notice_visible("Unsaved changes\nBack discards unsaved changes.")&&!notice_visible("Filament settings saved."));
 for(auto*node:pane->children)if(node->options.find("PLA\nPETG")==0)material_entry=node;
 fake::send(material_entry,31);material_entry->selected=0;fake::send(material_entry,28);ace_view.update(data,"h0",670,340);
 assert(!ace_view.identity_ready()&&!notice_visible("Unsaved changes\nBack discards unsaved changes.")&&!notice_visible("Filament settings saved."));
 ace_view.colour_result(editing_id,"Refused. Reopen Colour to review and try again.");ace_view.update(data,"h0",670,340);
 bool save_disabled=false;
 for(const auto&node:fake::nodes)if(node->live&&node->text=="SAVE"&&node->parent->parent==pane)save_disabled=(node->parent->state&128)!=0;
 assert(save_disabled);
 // The Back action remains available after a refused save.
 for(const auto&node:fake::nodes)if(node->live&&node->text=="BACK"&&node->parent->parent==pane)source_back=node->parent;
 fake::send(source_back,7);
 // If rebuilding the overview fails, the same status snapshot must retry.
 // Otherwise the cached layout freezes the half-built pane indefinitely.
 fake::fail_binding=true;bool overview_failed=false;
 try{ace_view.update(data,"h0",670,340);}catch(const std::runtime_error&){overview_failed=true;}
 fake::fail_binding=false;assert(overview_failed);
 ace_view.update(data,"h0",670,340);
 for(const auto&node:fake::nodes)if(node->live&&node->text=="Slot 1"&&node->parent->parent->parent==pane){slot_card=node->parent;break;}
 unsigned visible_slots=0,dimmed_slots=0;
 for(const auto&node:fake::nodes)if(node->live&&node->text.compare(0,5,"Slot ")==0&&node->parent->parent->parent==pane){++visible_slots;if(node->parent->opacity==100)++dimmed_slots;}
 assert(visible_slots==8&&dimmed_slots==3);
 fake::send(slot_card,7);
 assert(!(retired_menu_address->flags&1));
 ace_view.discard_drafts();ace_view.update(data,"h0",670,340);
 fake::del(retired_menu_address);


 ace_action.clear();ace_page->flags|=1;fake::send(slot_card,7);assert(ace_action.empty());ace_page->flags&=~1U;
 auto stale_ace=data;stale_ace["fresh"]=false;ace_view.update(stale_ace,"h1",670,340);assert(pane->scroll==90);
 for(const auto&node:fake::nodes)if(node->live&&node->text=="Slot 1"&&node->parent->parent->parent==pane){slot_card=node->parent;break;}
 fake::send(slot_card,7);assert(ace_action.empty());
 auto discovered=data;discovered["capabilities"]["adopt"]=true;discovered["candidates"]=Json::array({{{"id","candidate-a"},{"name","New ACE"},{"device_label","USB A"}},{{"id","candidate-b"},{"name","New ACE"},{"device_label","USB B"},{"logical_name","ace-new"},{"context","observed-b"}}});
 ace_view.update(discovered,"h0",670,340);bool candidate_a=false,candidate_b=false;
 for(const auto&node:fake::nodes)if(node->live&&node->parent&&node->parent->parent==pane){
  if(node->text=="Adopt New ACE - USB A")candidate_a=true;
  if(node->text=="Adopt New ACE - USB B"){candidate_b=true;fake::send(node->parent,7);}
 }
 assert(candidate_a&&candidate_b&&ace_action.empty());
 // Unit details reuse this stock pane; quick/custom changes are local previews.
 auto ace_tap=[&](const std::string&text){fake::Node*target=nullptr;
  for(const auto&node:fake::nodes)if(node->live&&node->text==text&&node->parent){
   for(auto*p=node->parent;p;p=p->parent)if(p==pane){target=node->parent;break;}
   if(target)break;
  }
  assert(target);fake::send(target,7);
 };
 unsigned adoption_submits=0;
 ace_view.adopt=[&](const Json&candidate,const Json&context){++adoption_submits;assert(candidate["logical_name"]=="ace-new"&&context["session"]==data["session"]);return Receipt{"adopt-ticket","pending","Waiting for readback"};};
 ace_view.update(discovered,"h0",670,340);ace_tap("Adopt");ace_tap("Adopt");assert(adoption_submits==1);
 auto ack=discovered;ack["receipts"]={{"adopt-ticket",{{"owner","openace"},{"session",data["session"]},{"action","adopt"},{"state","complete"},{"message","Registered"}}}};
 ace_view.update(ack,"h0",670,340);assert(ace_view.adoption_operation()["state"]=="pending");
 auto uncertain=ack;uncertain["receipts"]["adopt-ticket"]["state"]="unknown";
 ace_view.update(uncertain,"h0",670,340);ace_tap("Back to units");ace_view.update(uncertain,"h0",670,340);
 assert(ace_view.adoption_operation()["state"]=="unknown"&&ace_view.adoption_unresolved());
 ace_tap("Adopt New ACE - USB B");assert(adoption_submits==1);
 ace_tap("ACE registration: unknown - View");ace_view.update(uncertain,"h0",670,340);
 ack["units"].push_back({{"id","ace-new"},{"name","New ACE"},{"connected",true},{"assignments",Json::object()}});
 ace_view.update(ack,"h0",670,340);assert(ace_view.adoption_operation()["state"]=="complete");
 auto removed_adopted=ack;removed_adopted["units"]=data["units"];
 ace_view.update(removed_adopted,"h0",670,340);ace_tap("Review slots");assert(!ace_view.unit_draft().is_object());
 auto changed_adopted=ack;changed_adopted["session"]="another-session";
 ace_view.update(changed_adopted,"h0",670,340);ace_tap("Review slots");assert(!ace_view.unit_draft().is_object());
 ace_view.update(ack,"h0",670,340);ace_tap("Review slots");ace_view.update(ack,"h0",670,340);
 assert(ace_view.unit_draft().value("id","")=="ace-new"&&adoption_submits==1&&ace_action.empty());
 ace_tap("Cancel");ace_view.update(data,"h0",670,340);assert(pane->scroll==90);
 ace_action.clear();ace_tap("Dryer ?");ace_view.update(data,"h0",670,340);
 assert(ace_view.modal_active()&&pane->y==8);
 bool missing_humidity=false;
 for(auto*node:pane->children){if(node->text=="Humidity: -- %")missing_humidity=true;
  for(auto*caption:node->children)if(caption->text=="Start"||caption->text=="Stop")assert(node->state&128);
 }
 assert(missing_humidity);ace_tap("Start");ace_tap("Stop");assert(ace_action.empty());
 auto dryer_stale=data;dryer_stale["fresh"]=false;ace_view.update(dryer_stale,"h0",670,340);
 ace_tap("CLOSE");ace_view.update(data,"h0",670,340);assert(!ace_view.modal_active()&&pane->scroll==90);
 ace_action.clear();ace_tap("Edit unit");ace_view.update(data,"h0",670,340);
 const auto original_unit=ace_view.unit_draft();assert(original_unit.is_object());
 assert(ace_view.rename_draft("Left ACE"));assert(ace_view.unit_draft()["name"]=="Left ACE");
 assert(ace_view.unit_draft()["assignments"]==original_unit["assignments"]&&ace_action.empty());
 assert(!ace_view.rename_draft("   ")&&!ace_view.rename_draft("ACE\nRESET")&&!ace_view.rename_draft(std::string(65,'x')));
 auto renamed_elsewhere=data;for(auto&unit:renamed_elsewhere["units"])if(unit["id"]==original_unit["id"])unit["name"]="Elsewhere";
 ace_view.update(renamed_elsewhere,"h0",670,340);assert(!ace_view.rename_draft("Overwrite"));
 ace_view.update(data,"h0",670,340);
 assert(pane->scroll==0);ace_tap("All slots to one head");ace_view.update(data,"h0",670,340);
 ace_tap("Head 2");ace_view.update(data,"h0",670,340);assert(ace_action.empty());
 // Each slot keeps the unit dialog and uses exactly four head options.
 auto slot_dropdown=[&](unsigned index){unsigned n=0;for(auto*node:pane->children)if(node->options=="Head 1\nHead 2\nHead 3\nHead 4"){if(n++==index)return node;}return static_cast<fake::Node*>(nullptr);};
 auto*third_slot=slot_dropdown(2);assert(third_slot&&third_slot->selected==1);
 fake::send(third_slot,31);third_slot->selected=2;fake::send(third_slot,28);ace_view.update(data,"h0",670,340);
 assert(slot_dropdown(2)->selected==2&&ace_view.modal_active()&&pane->y==8);
 assert(slot_dropdown(0)->selected==1); // other slots retain quick assignment
 ace_tap("Save");assert(ace_action.empty()); // route edits remain unavailable
 ace_tap("Remove");ace_view.update(data,"h0",670,340);assert(ace_action.empty());
 ace_tap("Remove");assert(ace_action.empty()); // unavailable, including queued taps
 bool removal_route=false,other_unit_route=false,disabled_remove=false;
 for(const auto&node:fake::nodes)if(node->live&&node->parent==pane){
  if(node->text=="T0 - Slot 1 - Head 1")removal_route=true;
  if(node->text=="T4 - Slot 1 - Head 1")other_unit_route=true;
 }
 for(const auto&node:fake::nodes)if(node->live&&node->text=="Remove"&&node->parent->parent==pane)disabled_remove=(node->parent->state&128)!=0;
 assert(removal_route&&!other_unit_route&&disabled_remove);
 ace_tap("Cancel");ace_view.update(data,"h0",670,340);
 auto printing=data;printing["job"]["state"]="printing";ace_view.update(printing,"h0",670,340);
 ace_tap("Remove");assert(ace_action.empty());
 auto changed=data;changed["revision"]="changed";ace_view.update(changed,"h0",670,340);
 ace_tap("Save");assert(ace_action.empty());
 changed["fresh"]=false;ace_view.update(changed,"h0",670,340);ace_tap("Cancel");ace_view.update(data,"h0",670,340);assert(pane->scroll==90);
 ace_tap("Edit unit");ace_view.update(data,"h0",670,340);ace_tap("Auto-distribute");ace_view.update(data,"h0",670,340);
 assert(slot_dropdown(2)&&slot_dropdown(2)->selected==2);

 // The same stock-styled unit cards serve as a destination chooser.
 Json picker_fixture;std::ifstream picker_input(argv[1]);picker_input>>picker_fixture;
 App picker_app(backend);picker_app.update(picker_fixture);picker_app.event("file:demo-file");picker_app.event("map:0");
 ace_view.picker_mode(true);ace_view.action=[&](const std::string&id){picker_app.event(id);};
 ace_view.update(picker_app.source_picker_state(),"",670,340);assert(pane->y==0);
 ace_tap("Slot 1");assert(!picker_app.source_picker_state()["picker_open"].get<bool>());
 assert(picker_app.preview_state()["rows"][0]["route"]["id"]=="route-0-0");
 auto alias=picker_fixture["routes"][0];alias["id"]="alias-route";alias["label"]="T9 - same slot";picker_fixture["routes"].push_back(alias);
 picker_app.update(picker_fixture);picker_app.event("map:0");ace_view.update(picker_app.source_picker_state(),"",670,340);
 pane->scroll=72;ace_tap("Slot 1");ace_view.update(picker_app.source_picker_state(),"",670,340);assert(pane->scroll==0);
 ace_tap("Back to slots");ace_view.update(picker_app.source_picker_state(),"",670,340);assert(pane->scroll==72);
 ace_tap("Slot 1");ace_view.update(picker_app.source_picker_state(),"",670,340);
 assert(picker_app.source_picker_state()["picker_route_source"]=="ace-1:0");
 ace_tap("T9 - same slot");assert(picker_app.preview_state()["rows"][0]["route"]["id"]=="alias-route");
 // Stale choices cannot change the mapping and edit-unit actions are absent.
 picker_app.event("map:0");picker_fixture["fresh"]=false;picker_app.update(picker_fixture);
 ace_view.update(picker_app.source_picker_state(),"",670,340);ace_tap("Slot 1");
 assert(picker_app.preview_state()["rows"][0]["route"]["id"]=="alias-route");
 ace_tap("CANCEL");assert(!picker_app.source_picker_state()["picker_open"].get<bool>());
 fake::del(ace_page);ace_view.update(data,"h0",670,340);


 {
  StockPrintPreparation preparation;
  Json data={{"owner","standalone"},{"fresh",true},{"print_preparation",{{"active",true},{"id","job1"},{"phase","homing"},
   {"steps",Json::array({{{"phase","preheat"},{"label","Preheat probe nozzle"}},{{"phase","homing"},{"label","Home printer"}}})}}}};
  auto find_preparation=[&](const std::string&text){for(auto it=fake::nodes.rbegin();it!=fake::nodes.rend();++it){const auto&n=*it;if(n->live&&n->text==text&&!(n->flags&1))return n.get();}return static_cast<fake::Node*>(nullptr);};
  preparation.navigation("main_page");preparation.update(data);
  auto*step=find_preparation("2. Home printer");assert(step&&step->text_color==0xffff6600U);
  auto*close=find_preparation("CLOSE");assert(close);fake::send(close->parent,7);
  assert(!step->live);preparation.update(data);assert(!find_preparation("2. Home printer"));
  data["print_preparation"]["id"]="job2";preparation.update(data);assert(find_preparation("2. Home printer"));
  preparation.navigation("setting_page");assert(!find_preparation("2. Home printer"));
  preparation.navigation("main_page");preparation.update(data);assert(find_preparation("2. Home printer"));
  data["print_preparation"]["active"]=false;preparation.update(data);assert(!find_preparation("2. Home printer"));
 }

}
