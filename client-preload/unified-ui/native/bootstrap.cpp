// Native unified screen candidate derived from the existing WM+ bootstrap.
// Separate build; does not replace the sealed installed artifact.
#include <cstdlib>
#include "../typed_management.hpp"
#include "native1113_port.hpp"
#include "runtime.hpp"
#include "stock_runout_gate.hpp"
#include "stock_navigation_tabs.hpp"
#include "stock_preview_event_gate.hpp"
#include "stock_preview_loading.hpp"
#include "stock_reprint_gate.hpp"
#include "stock_completed_display.hpp"
#include "stock_job_busy_hook.hpp"
#include "stock_async.hpp"
#include "stock_service_event.hpp"
#include "stock_maintenance_command.hpp"
#include "stock_cancel_route.hpp"
#include "stock_exclude_cancel.hpp"
#include "stock_mapping_backup.hpp"
#include "stock_resume_preheat.hpp"
#include "stock_startup_restart.hpp"
#include "loopback_http.hpp"
#include "usb_copy_http.hpp"
#include "refresh_bridge.hpp"
#include "timer_windows.hpp"
#include "screen_diagnostics.hpp"
#include "setup_completion.hpp"
#include "touch_frame_hook.hpp"
#include "hook_transaction.hpp"
#include <atomic>
#include <pthread.h>
#include <sys/mman.h>
#include <unistd.h>
#include <new>
#include <memory>
#include <cerrno>
#include <cstdio>
#include <cstring>
namespace wmp_openace {
using ScreenRuntime=wmp_ui::native::Runtime;
namespace {
using TimerCallback=RefreshBridge::Callback;
using TimerCreate=void*(*)(TimerCallback,std::uint32_t,void*);
static std::atomic<TimerCreate> original_create{nullptr};
static std::atomic<ScreenRuntime*> runtime{nullptr};
using StockPage=void(*)(const char*);using StockEvent=void(*)(void*);
using StockShell=std::string(*)(std::string);
static std::atomic<StockShell> original_shell{nullptr};
static std::atomic<void(*)()> original_exclude_object{nullptr};
static std::atomic<StockPage> original_page{nullptr};
using StockMenu=void(*)(void*,unsigned char);
static std::atomic<StockMenu> original_sidebar{nullptr},original_filelist_menu{nullptr},original_setting_menu{nullptr};
static std::atomic<bool> video_page_destination{false};
extern "C" void unified_page_to(const char*)noexcept;
static wmp_ui::native::StockNavigationTabs&navigation_tabs(){
 static auto*value=new wmp_ui::native::StockNavigationTabs;
 return *value;
}
template<std::size_t N>static std::array<void*,N> menu_buttons(std::uintptr_t address){
 std::array<void*,N>result{};auto*source=reinterpret_cast<void*volatile*>(address);
 for(std::size_t i=0;i<N;++i)result[i]=source[i];
 return result;
}
extern "C" void unified_sidebar(void*parent,unsigned char selected)noexcept{try{
 auto original=original_sidebar.load();if(original)original(parent,video_page_destination.load()?1:selected);
}catch(...){} }
extern "C" void unified_filelist_menu(void*parent,unsigned char selected)noexcept{try{
 auto original=original_filelist_menu.load();if(!original)return;original(parent,selected);
 navigation_tabs().files(menu_buttons<3>(wmp_ui::native::stock_filelist_buttons),selected==3);
}catch(...){} }
extern "C" void unified_setting_menu(void*parent,unsigned char selected)noexcept{try{
 if(selected==2){unified_filelist_menu(parent,3);return;}
 auto original=original_setting_menu.load();if(!original)return;
 auto*r=runtime.load();original(parent,selected==1&&r&&r->tools_active()?2:selected);
 navigation_tabs().settings(menu_buttons<5>(wmp_ui::native::stock_setting_buttons));
}catch(...){} }

static std::atomic<StockEvent> original_main_event{nullptr};
static std::atomic<StockEvent> original_preview{nullptr};
static std::atomic<StockEvent> original_preview_event{nullptr};
static std::atomic<void(*)()> original_filament_pause{nullptr};
static std::atomic<void(*)()> original_preview_metadata{nullptr};
static std::atomic<void(*)(std::string)> original_loading_popup{nullptr};
static wmp_ui::native::StockPreviewEventGate preview_event_gate;
static std::atomic<StockEvent> original_filament_setup{nullptr};
static std::atomic<StockEvent> original_filament_event{nullptr};
static std::atomic<StockEvent> original_material_pick{nullptr};
static std::atomic<StockEvent> original_colour_pick{nullptr};
static std::atomic<StockEvent> original_about_setup{nullptr};
static std::atomic<StockEvent> original_calibration_setup{nullptr};
static std::atomic<void(*)()> original_calibration_worker{nullptr};
static std::atomic<StockEvent> original_identification_setup{nullptr};
static std::atomic<StockEvent> original_nozzle_flow_event{nullptr};
static std::atomic<StockEvent> original_maintenance_event{nullptr};
static std::atomic<StockEvent> original_guide_calibration_event{nullptr};
static std::atomic<StockEvent> original_home_event{nullptr};
static std::atomic<StockEvent> original_factory_event{nullptr};
static std::atomic<StockEvent> original_knife_event{nullptr};
static std::atomic<void(*)(std::string)> original_command_sender{nullptr};
static std::atomic<void(*)(int)> original_draw_pop{nullptr};
static std::atomic<void(*)(char*)> original_warning_callback{nullptr};
static std::atomic<void(*)(int)> original_popup_build{nullptr};
static std::atomic<StockEvent> original_popup_event{nullptr};
static wmp_ui::native::StockReprintGate reprint_gate;
static std::atomic<std::uint64_t> popup_generation{0};
static wmp_ui::native::StockCompletedDisplay completed_display;
static std::atomic<bool(*)()> original_is_printing{nullptr};
// Stock's predicate also treats completed jobs as busy. Keep its diagnostics
// and all other states, but allow user actions after a completed print.
extern "C" bool unified_is_printing()noexcept {
 try{
  auto original=original_is_printing.load();
  if(!original)return true;
  const bool busy=original();
  return wmp_ui::native::stock_job_busy(busy,
   *reinterpret_cast<const std::string*>(0xe645170),
   *reinterpret_cast<const std::string*>(0xe645338));
 }catch(...){return true;}
}
// Keep the result card visible until dismissal, independently of admission.
extern "C" void unified_main_refresh()noexcept {
 using namespace wmp_ui::native;
 try{
  stock_function<void(*)()>(main_update_common)();
  stock_function<void(*)()>(main_update_printing)();
  stock_function<void(*)()>(main_update_tips)();
  auto original=original_is_printing.load();
  const bool stock_visible=original?original():stock_function<bool(*)()>(stock_is_printing)();
  const bool show=completed_display.visible(stock_visible,
   *reinterpret_cast<const std::string*>(0xe645338),
   *reinterpret_cast<const std::string*>(0xe645430));
  auto*mode=reinterpret_cast<unsigned char*>(0x386ceb8);
  if(show!=bool(*mode)){
   *mode=show;
   stock_function<void(*)()>(show?main_show_printing:main_hide_printing)();
   *reinterpret_cast<unsigned char*>(0x384e060)=1;
   *reinterpret_cast<unsigned char*>(0x386ceb9)=0;
  }
 }catch(...){}
}
extern "C" void unified_draw_preview(void*parent)noexcept;
static bool popup_button_live(void*button,int kind){
 using namespace wmp_ui::native;
 const auto current_kind=*reinterpret_cast<const int*>(0x384e938);
 // The vendor can clear its modal bookkeeping while the retained recovery
 // prompt remains visible beneath our discard panel. Its current LVGL buttons
 // and callback still identify that prompt; do not rewrite vendor state.
 if(!button||(current_kind!=kind&&!(kind==3&&current_kind==-1)))return false;
 auto*top=stock_function<void*(*)(void*)>(lv_disp_get_layer_top)(nullptr);
 for(unsigned depth=0;button&&depth<12;++depth){
  if(!stock_function<bool(*)(void*)>(lv_obj_is_valid)(button)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(button,1))return false;
  if(button==top)return true;
  button=stock_function<void*(*)(void*)>(lv_obj_get_parent)(button);
 }
 return false;
}
extern "C" void unified_popup_build(int kind)noexcept {
 try{
  ++popup_generation;reprint_gate.begin(kind);
  auto original=original_popup_build.load();if(!original)return;original(kind);
  if(kind!=5&&kind!=6)return;
  auto*button=*reinterpret_cast<void*volatile*>(0x386ebe8);
  auto path=*reinterpret_cast<const std::string*>(0xe643278);
  auto*r=runtime.load();if(kind==5&&path.empty()&&r)path=r->stopped_job_file();
  reprint_gate.arm(button,path,runtime.load()&&wmp_ui::native::preview_path(path)&&popup_button_live(button,kind));
 }catch(...){reprint_gate.invalidate();}
}
struct ReprintCall {wmp_ui::native::StockReprintGate::Request request;void*button;int kind;};
static void review_reprint(void*data)noexcept {
 std::unique_ptr<ReprintCall> call(static_cast<ReprintCall*>(data));
 try{
  if(!call||!reprint_gate.pending(call->request)||!popup_button_live(call->button,call->kind))return;
  auto*r=runtime.load();auto page=original_page.load();if(!r||!page)return;
  if(!reprint_gate.take(call->request))return;
  // Match only the popup dismissal prefix. Do not run stock mapping writes,
  // loading flags, mesh selection, or its direct print-file submission.
  auto*top=wmp_ui::native::stock_function<void*(*)(void*)>(wmp_ui::native::lv_disp_get_layer_top)(nullptr);
  wmp_ui::native::stock_function<void(*)(void*,unsigned)>(wmp_ui::native::lv_obj_add_flag)(top,1);
  *reinterpret_cast<int*>(0x384e938)=-1;
  page("filelist_local_page");
  auto*parent=*reinterpret_cast<void*volatile*>(0x3864330);
  if(!parent||!wmp_ui::native::stock_function<bool(*)(void*)>(wmp_ui::native::lv_obj_is_valid)(parent))return;
  // cur_page_ui is the vendor's char[80] (page_to copies into it with
  // strcpy), not a std::string. Reading it as a string rejects this handoff.
  if(std::strncmp(reinterpret_cast<const char*>(0x463c500),"filelist_local_page",80)!=0)return;
  *reinterpret_cast<unsigned char*>(0xe643270)=0;
  *reinterpret_cast<std::string*>(0xe643278)=call->request.path;
  unified_draw_preview(parent);
 }catch(...){reprint_gate.invalidate();}
}
extern "C" void unified_factory_reset() noexcept;
// Hide only the captured vendor popup, never the shared top layer or a sibling.
static bool hide_recovery_offer(void*button,void*top){
 using namespace wmp_ui::native;
 auto*popup=button;
 for(unsigned depth=0;popup&&depth<12;++depth){
  if(!stock_function<bool(*)(void*)>(lv_obj_is_valid)(popup))return false;
  auto*parent=stock_function<void*(*)(void*)>(lv_obj_get_parent)(popup);
  if(parent==top){stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(popup,1);return true;}
  popup=parent;
 }
 return false;
}
extern "C" void unified_popup_event(void*event)noexcept {
 try{
  if(!event)return;
  using namespace wmp_ui::native;
  const auto kind=reinterpret_cast<std::uintptr_t>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(event));
  if(kind==3){
   // The stock Cancel prefix deletes PLR records and queues PARK_CURRENT_TOOL.
   // Keep its prompt underneath our opaque review until verified retirement.
   const int code=stock_function<int(*)(void*)>(lv_event_get_code)(event);
   auto*target=stock_function<void*(*)(void*)>(lv_event_get_target)(event);
   auto*button=*reinterpret_cast<void*volatile*>(0x386ebe8);
   auto*close=*reinterpret_cast<void*volatile*>(0x386ebe0);
   if(code!=7||(target!=button&&target!=close)||!popup_button_live(target,3))return;
   auto*r=runtime.load();if(r&&r->native_discard_blocks_prompt())return;
   if(target==button){
    const auto generation=popup_generation.load();
    if(r)r->native_continue_started([button,generation]{
     if(popup_generation.load()!=generation||*reinterpret_cast<void*volatile*>(0x386ebe8)!=button||!popup_button_live(button,3))return;
     auto*top=stock_function<void*(*)(void*)>(lv_disp_get_layer_top)(nullptr);
     if(hide_recovery_offer(button,top))*reinterpret_cast<int*>(0x384e938)=-1;
    });
    auto original=original_popup_event.load();if(original)original(event);return;
   }
   if(!r)return;
   const auto generation=popup_generation.load();
   r->request_native_discard([close,generation]{
    if(popup_generation.load()!=generation)return;
    if(*reinterpret_cast<void*volatile*>(0x386ebe0)!=close||!popup_button_live(close,3))return;
    auto*top=stock_function<void*(*)(void*)>(lv_disp_get_layer_top)(nullptr);
    auto*popup=close;
    for(unsigned depth=0;depth<12;++depth){
     auto*parent=stock_function<void*(*)(void*)>(lv_obj_get_parent)(popup);
     if(parent==top){stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(popup,1);
      *reinterpret_cast<int*>(0x384e938)=-1;return;}
     if(!parent)return;
     popup=parent;
    }
   });return;
  }
  if(kind==69){
   // Stock Stop confirmation calls stop_printing_handler (quick_stop first)
   // and reset_plr_files before its worker reaches CANCEL_PRINT. Intercept
   // here so the managed owner records intent before either destructive prefix.
   const int code=stock_function<int(*)(void*)>(lv_event_get_code)(event);
   auto*target=stock_function<void*(*)(void*)>(lv_event_get_target)(event);
   auto*button=*reinterpret_cast<void*volatile*>(0x386ebe8);
   auto*close=*reinterpret_cast<void*volatile*>(0x386ebe0);
   if(code!=7||(target!=button&&target!=close)||!popup_button_live(target,69))return;
   if(target==close){auto original=original_popup_event.load();if(original)original(event);return;}
   auto*r=runtime.load();if(!r)return;
   if(!r->route_print_cancel()){auto original=original_popup_event.load();if(original)original(event);return;}
   auto*top=stock_function<void*(*)(void*)>(lv_disp_get_layer_top)(nullptr);
   // The managed result is another child of this same overlay layer. Hide
   // only the old stock popup, otherwise its new progress panel is invisible.
   auto*popup=target;
   for(unsigned depth=0;depth<12;++depth){
    auto*parent=stock_function<void*(*)(void*)>(lv_obj_get_parent)(popup);
    if(parent==top)break;
    if(!parent)return;
    popup=parent;
   }
   stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(popup,1);
   *reinterpret_cast<int*>(0x384e938)=-1;
   return;
  }
  if(kind==21){
   // Reset confirmation: stock first shows an endless progress popup and then
   // queues the destructive worker. Consume stale events and replace only the
   // live affirmative click; preserve the ordinary Cancel dismissal.
   const int code=stock_function<int(*)(void*)>(lv_event_get_code)(event);
   auto*target=stock_function<void*(*)(void*)>(lv_event_get_target)(event);
   auto*button=*reinterpret_cast<void*volatile*>(0x386ebe8);
   auto*close=*reinterpret_cast<void*volatile*>(0x386ebe0);
   if(code!=7||(target!=button&&target!=close)||!popup_button_live(target,21))return;
   if(target==close){auto original=original_popup_event.load();if(original)original(event);return;}
   auto*top=stock_function<void*(*)(void*)>(lv_disp_get_layer_top)(nullptr);
   stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(top,1);
   *reinterpret_cast<int*>(0x384e938)=-1;
   unified_factory_reset();return;
  }
  if(kind!=5&&kind!=6){auto original=original_popup_event.load();if(original)original(event);return;}
  const int code=stock_function<int(*)(void*)>(lv_event_get_code)(event);
  auto*target=stock_function<void*(*)(void*)>(lv_event_get_target)(event);
  auto*button=*reinterpret_cast<void*volatile*>(0x386ebe8);
  auto*close=*reinterpret_cast<void*volatile*>(0x386ebe0);
  StockReprintGate::Request request;
  const bool live=(target==button||target==close)&&popup_button_live(target,int(kind));
  if(code==7&&live&&target==close){
   if(kind==6)completed_display.dismiss(*reinterpret_cast<const std::string*>(0xe645338),
    *reinterpret_cast<const std::string*>(0xe645430));
   reprint_gate.invalidate();auto original=original_popup_event.load();if(original)original(event);return;}
  const auto action=reprint_gate.event(int(kind),code,target,button,live,request);
  if(action==StockReprintGate::Action::Delegate){auto original=original_popup_event.load();if(original)original(event);return;}
  if(action!=StockReprintGate::Action::Review)return;
  std::unique_ptr<ReprintCall> call(new ReprintCall{request,button,int(kind)});
  if(!queue_stock_async(stock_function<int(*)(void(*)(void*),void*)>(lv_async_call),&review_reprint,std::move(call)))reprint_gate.invalidate();
 }catch(...){reprint_gate.invalidate();}
}

extern "C" void unified_draw_pop(int kind) noexcept {
 try {
  // Stock runout/tangle dialogs promise automatic heating and preparation.
  // Keep fault banners and detection, but route recovery into WM+ Filaments.
  if(kind==99||kind==100){auto*r=runtime.load();if(r)r->request(7);return;}
  auto original=original_draw_pop.load();if(original)original(kind);
 }catch(...){}
}
// Run on the GUI thread immediately before the stock popup is drawn. Keep the
// stock warning history and parser/fault handling; avoid a redundant Restart
// prompt only for an owned cancellation with confirmed successful cleanup.
extern "C" void unified_warning_callback(char*text)noexcept {
 try {
  auto*r=runtime.load();
  if(r&&text&&strnlen(text,500)<500&&r->confirmed_cancel_warning(text))return;
 }catch(...){}
 try{auto original=original_warning_callback.load();if(original)original(text);}catch(...){}
}
// Recovery hooks share the native installation transaction. A second constructor
// must not silently reject them after command_sender has already been patched.
// The recovery-fix module calls this only after binding the native checkpoint
// to the selected filename. Copy bounded arguments synchronously; the runtime
// worker owns subsequent review/delivery, and LVGL runs only on its GUI timer.
extern "C" __attribute__((visibility("default"))) int wmp_managed_recovery_ready(unsigned version)noexcept{
 return version==1&&runtime.load(std::memory_order_acquire)?1:0;
}
extern "C" __attribute__((visibility("default"))) int wmp_managed_recovery_select(
 unsigned version,const char*file,const char*checkpoint,const char*checkpoint_hash,const char*job_hash)noexcept{
 try{
  if(!file||!checkpoint||!checkpoint_hash||!job_hash||version!=1)return 0;
  if(strnlen(file,4096)>=4096||strnlen(checkpoint,32)>=32||strnlen(checkpoint_hash,17)!=16||strnlen(job_hash,17)!=16)return 0;
  auto*screen=runtime.load(std::memory_order_acquire);
  return screen&&screen->select_recovery(version,file,checkpoint,checkpoint_hash,job_hash)?1:0;
 }catch(...){return 0;}
}
// Blocked legacy selections have no executable request. Queue only presentation;
// review/discard still require separate explicit actions from the user.
extern "C" __attribute__((visibility("default"))) int wmp_managed_recovery_review(unsigned version,unsigned reason)noexcept{
 try{
  auto*screen=runtime.load(std::memory_order_acquire);
  return version==1&&screen&&screen->request_recovery_review(reason)?1:0;
 }catch(...){return 0;}
}
// The native reset worker deletes recovery/job/file state before its first
// shell command. Never delegate until the managed reset transaction exists.
extern "C" void unified_factory_reset() noexcept {
 if(auto*screen=runtime.load(std::memory_order_acquire))screen->request_factory_reset_refusal();
}
extern "C" void unified_runout_purge() noexcept {}
extern "C" void unified_resume_check() noexcept {}
extern "C" void unified_filament_pause() noexcept {
 try {auto*r=runtime.load();if(r&&r->backend_runout_owned())return;}catch(...){}
 if(auto original=original_filament_pause.load())original();
}
extern "C" void unified_resume_prepare() noexcept {
 try {auto send=original_command_sender.load();if(send)send("RESUME");}catch(...){}
}
extern "C" void unified_exclude_object()noexcept {
 try{
  const auto&name=*reinterpret_cast<const std::string*>(0x4634ef0);
  wmp_ui::native::exclude_with_managed_cancel(name,
   [](const std::string&value){return reinterpret_cast<bool(*)(const std::string&)>(0x545598)(value);},
   []{auto*r=runtime.load();return !r||r->route_print_cancel();},
   []{auto original=original_exclude_object.load();if(original)original();});
 }catch(...){}
}
extern "C" __attribute__((noinline)) std::string unified_shell(std::string command){
 const auto caller=reinterpret_cast<std::uintptr_t>(__builtin_extract_return_addr(__builtin_return_address(0)));
 auto*screen=runtime.load();
 if(wmp_ui::native::suppress_file_setup_completion(caller,command,screen&&screen->onboarding_active()))return {};
 if(wmp_ui::native::suppress_startup_restart(caller,command))return {};
 if(wmp_ui::native::suppress_startup_discovery(caller,command))return {};
 const char*defaults_owner=std::getenv("WMP_DEFAULTS_OWNER");
 if(wmp_ui::native::suppress_startup_defaults(caller,command,defaults_owner&&std::string(defaults_owner)=="1"))return {};
 auto original=original_shell.load();
 if(!original)throw std::runtime_error("Stock shell trampoline unavailable");
 return original(std::move(command));
}
// Forwards one stock command on behalf of the send that returns to caller.
static void forward_stock_command(std::uintptr_t caller,const std::string&command){
 auto original=original_command_sender.load();if(!original)return;
 const auto preheat=wmp_ui::native::stock_resume_preheat_command(caller,command);
 if(preheat!=command){original(preheat);return;}
 auto*r=runtime.load();
 if(r&&r->refuse_unbound_guide_calibration_send(caller))return;
 if(r&&r->suppress_cancelled_calibration_send(caller))return;
 // A stopped brush run ends the offset stage: its probing and park sends are not
 // forwarded. The withheld park clears the vendor's pairing-failed byte only
 // when that byte is 1 and fresh status shows early_save_available; the worker
 // then goes on to its SAVE_CONFIG. Otherwise the byte is left as it is.
 // The park send first holds the worker for the nozzle re-check; the commands
 // sent during that hold leave through the same wrapper as the scrub's.
 if(r&&caller==wmp_ui::native::offset_park){
  if(r->withhold_offset_send(caller,[r,original](const std::string&inner){
   original(r->stock_calibration_command_for_worker(wmp_ui::native::offset_park,inner));}))return;
 }else if(r&&r->withhold_offset_send(caller))return;
 original(r?r->stock_calibration_command_for_worker(caller,command):wmp_ui::native::stock_calibration_command(caller,command));
 // The offset stage begins with this G28. A bound nozzle scrub holds the
 // vendor worker here; its commands leave through the same wrapper, so they
 // carry the worker's session, request, ticket and next sequence numbers.
 if(r&&caller==wmp_ui::native::offset_home)
  r->nozzle_scrub_at_offset_stage([r,original](const std::string&inner){
   original(r->stock_calibration_command_for_worker(wmp_ui::native::offset_home,inner));});
}
extern "C" __attribute__((noinline)) void unified_command_sender(std::string command){
 if(wmp_ui::native::route_stock_cancel(command,[]{auto*screen=runtime.load();return !screen||screen->route_print_cancel();}))return;
 const auto caller=reinterpret_cast<std::uintptr_t>(__builtin_extract_return_addr(__builtin_return_address(0)));
 if(caller==0x63dc20){
  auto*screen=runtime.load();
  if(wmp_ui::native::suppress_stock_mapping_backup(caller,command,screen&&screen->standalone_mapping_owned()))return;
 }
 if(wmp_ui::native::refuse_factory_confirmation(caller,
    []{auto*r=runtime.load();return r&&r->stock_maintenance_allowed();},
    []{auto*r=runtime.load();if(r)r->request_factory_command_refusal();}))return;
 forward_stock_command(caller,command);
}
extern "C" void unified_maintenance_event(void*event)noexcept {
 try{
  const auto gate=wmp_ui::native::stock_maintenance_event(event,[]{auto*r=runtime.load();return r&&r->stock_maintenance_allowed();});
  if(gate==2){auto*r=runtime.load();if(r)r->request_maintenance_refusal();return;}
  if(gate==3){
   auto*r=runtime.load();if(r)r->open_probe_editor();return;
  }
  if(gate)return;
  auto original=original_maintenance_event.load();if(!original)return;
  const auto action=reinterpret_cast<std::uintptr_t>(wmp_ui::native::stock_function<void*(*)(void*)>(wmp_ui::native::lv_event_get_user_data)(event));
  auto*r=runtime.load();const bool starting=action==0;
  // Accurate offset calibration first asks how the nozzles will be cleaned.
  // The choice re-sends this click with the decision made.
  if(starting&&r&&!r->nozzle_scrub_decided()&&r->offer_nozzle_scrub(wmp_ui::native::stock_maintenance_start_button(event)))return;
  if(starting&&(!r||!r->begin_stock_calibration())){if(r)r->request_maintenance_refusal();return;}
  try{original(event);}catch(...){if(starting&&r)r->finish_stock_calibration_start();throw;}
  if(starting&&r)r->finish_stock_calibration_start();
 }catch(...){} // Do not delegate an event whose admission failed.
}
extern "C" void unified_home_event(void*event)noexcept {
 try{
  using namespace wmp_ui::native;
  const int action=stock_home_action(event);if(action<0)return;
  auto*r=runtime.load();
  if(action>=10&&action<=14){
   if(r&&r->home_external_owner()){auto original=original_home_event.load();if(original)original(event);return;}
   if(r)r->begin_home(unsigned(action));
   return;
  }
  if(r&&r->home_active())return; // No jog/disable behind an owned Home overlay.
  auto original=original_home_event.load();if(original)original(event);
 }catch(...){} // Never fall back to an unbound Home after refusal.
}
extern "C" void unified_guide_calibration_event(void*event)noexcept {
 try{
  using namespace wmp_ui::native;
  const int action=stock_guide_calibration_action(event);if(action<0)return;
  auto*r=runtime.load();
  if(action==0){if(r)r->calibration_navigation("guide_filament_page");return;} // Never delete need_oobe here.
  if(action==1){if(r)r->begin_guide_calibration(stock_function<void*(*)(void*)>(lv_event_get_target)(event));return;}
  auto original=original_guide_calibration_event.load();if(original)original(event);
 }catch(...){} // A rejected START never delegates to an unbound vendor worker.
}
extern "C" void unified_factory_event(void*event)noexcept {
 try{
  const auto gate=wmp_ui::native::stock_factory_probe_event(event,[]{auto*r=runtime.load();return r&&r->stock_maintenance_allowed();});
  if(gate==2){auto*r=runtime.load();if(r)r->request_maintenance_refusal();return;}
  if(gate==3){auto*r=runtime.load();if(r)r->open_probe_editor();return;}
  if(gate)return;
  auto original=original_factory_event.load();if(original)original(event);
 }catch(...){} // Never fall back to legacy probe preparation after interception.
}
extern "C" void unified_knife_event(void*event)noexcept {
 try{
  const auto gate=wmp_ui::native::stock_knife_event(event,[]{auto*r=runtime.load();return r&&r->stock_maintenance_allowed();});
  if(gate==2){auto*r=runtime.load();if(r)r->request_maintenance_refusal();return;}
  if(gate)return;
  auto original=original_knife_event.load();if(original)original(event);
 }catch(...){} // Never delegate after failed admission or malformed input.
}
extern "C" void unified_legacy_probe_event(void*event)noexcept {
 try{if(wmp_ui::native::stock_probe_editor_event(event)){auto*r=runtime.load();if(r)r->open_probe_editor();}}
 catch(...){} // Fully replace both callbacks; never execute old jog or save code.
}
extern "C" void unified_nozzle_flow_event(void*event)noexcept {
 try{
  if(wmp_ui::native::stock_service_event(event,[](unsigned head,bool load){auto*r=runtime.load();if(r)r->request_stock_service(head,load);}))return;
  auto original=original_nozzle_flow_event.load();if(original)original(event);
 }catch(...){} // Never fall back to an unadmitted service command.
}
extern "C" void unified_setup_identification(void*parent)noexcept {
 auto original=original_identification_setup.load();if(!original)return;original(parent);
 try{auto*r=runtime.load();if(r)r->stock_identification_created(parent);}catch(...){}
}
// Neither stale vendor events nor its background worker may publish UUIDs.
extern "C" void unified_setup_guide_identification(void*parent)noexcept {
 try{auto*r=runtime.load();if(r)r->stock_identification_created(parent,true);}catch(...){}
}
extern "C" void unified_retired_guide_identification_refresh()noexcept {}
extern "C" void unified_retired_identification_event(void*)noexcept {}
extern "C" void unified_retired_identification_worker()noexcept {}
extern "C" void unified_calibration_worker(){
 auto original=original_calibration_worker.load();if(!original)return;
 auto*r=runtime.load();if(r)r->run_stock_calibration_worker([=]{original();});else original();
}
extern "C" void unified_setup_calibration(void*parent)noexcept {
 auto original=original_calibration_setup.load();if(!original)return;
 const auto state=*reinterpret_cast<const std::uint32_t*>(0x385fc18);
 auto*r=runtime.load();const bool queues=state==1||state==4||state==7||state==10;
 if(queues&&r)r->stock_calibration_enqueued();
 // The verified enqueue has strong exception safety: its only post-commit
 // operations are noexcept notification/destruction. Keep our later UI hook
 // outside this rollback boundary.
 try{original(parent);}catch(...){if(queues&&r)r->stock_calibration_enqueue_failed();return;}
 try{auto*r=runtime.load();if(r)r->stock_calibration_created(parent,*reinterpret_cast<void**>(0x385fc28));}catch(...){}
}
extern "C" void unified_setup_about(void*parent)noexcept {
 auto original=original_about_setup.load();if(!original)return;original(parent);
 try{auto*r=runtime.load();if(r)r->stock_about_created(parent);}catch(...){}
}
extern "C" void unified_colour_pick(void*event)noexcept {
 try {
  auto*r=runtime.load();
  if(r&&event&&reinterpret_cast<int(*)(void*)>(wmp_ui::native::lv_event_get_code)(event)==7){
   const auto index=reinterpret_cast<std::uintptr_t(*)(void*)>(wmp_ui::native::lv_event_get_user_data)(event);
   if(index>=21)return;
   if(r->stock_picker_gate(reinterpret_cast<void*(*)(void*)>(wmp_ui::native::lv_event_get_target)(event))==1)return;
   if(r->stock_colour_pick(unsigned(index))){
    auto*modal=r->stock_picker_modal();
    if(modal&&reinterpret_cast<bool(*)(void*)>(wmp_ui::native::lv_obj_is_valid)(modal))
     reinterpret_cast<void(*)(void*)>(wmp_ui::native::lv_obj_del)(modal);
    return;
   }
  }
 }catch(...){return;}
 auto original=original_colour_pick.load();if(original)original(event);
}

extern "C" void unified_material_pick(void*event)noexcept {
 try {
  auto*r=runtime.load();
  if(r&&event&&reinterpret_cast<int(*)(void*)>(0x6979fc)(event)==7){
   const auto index=reinterpret_cast<std::uintptr_t(*)(void*)>(0x697a30)(event);
   // Exact verified stock table: 18 std::string material names.
   if(index>=18)return;
   if(r->stock_picker_gate(reinterpret_cast<void*(*)(void*)>(wmp_ui::native::lv_event_get_target)(event))==1)return;
   const auto&material=reinterpret_cast<const std::string*>(0x38624a8)[index];
   if(r->stock_material_pick(material)){
    auto*modal=r->stock_picker_modal();
    if(modal&&reinterpret_cast<bool(*)(void*)>(wmp_ui::native::lv_obj_is_valid)(modal))
     reinterpret_cast<void(*)(void*)>(wmp_ui::native::lv_obj_del)(modal);
    return;
   }
  }
 }catch(...){return;}
 auto original=original_material_pick.load();if(original)original(event);
}

extern "C" void unified_filament_event(void*event)noexcept {
 try{
  auto*r=runtime.load();
  const int code=event?reinterpret_cast<int(*)(void*)>(wmp_ui::native::lv_event_get_code)(event):0;
  const auto action=event?reinterpret_cast<std::uintptr_t(*)(void*)>(wmp_ui::native::lv_event_get_user_data)(event):0;
  if(r&&code==7&&action==16){
   const int gate=r->stock_picker_gate(reinterpret_cast<void*(*)(void*)>(wmp_ui::native::lv_event_get_target)(event));
   if(gate==1)return;
   if(gate==2){auto*modal=r->stock_picker_modal();r->stock_picker_cancel();
    if(modal&&reinterpret_cast<bool(*)(void*)>(wmp_ui::native::lv_obj_is_valid)(modal))
     reinterpret_cast<void(*)(void*)>(wmp_ui::native::lv_obj_del)(modal);
    return;
   }
  }
  if(r&&r->stock_filament_event(event))return;
  auto original=original_filament_event.load();if(original)original(event);
  if(r&&code==7&&action>=8&&action<=15)
   r->stock_picker_opened(*reinterpret_cast<void*volatile*>(0x3862bc0));
 }catch(...){return;}
}
extern "C" void unified_setup_filament(void*parent)noexcept {
 auto original=original_filament_setup.load();
 if(!original)return;
 original(parent); // Keep vendor sidebar, Settings tabs, styles and widgets.
 try{auto*r=runtime.load();if(r)r->stock_filament_created(parent);}catch(...){}
}
extern "C" void unified_setup_filament_guide(void*)noexcept {
 // Never construct the legacy guide's motion callbacks. The next GUI tick
 // opens the shared Filament page, including a guarded explicit Finish action.
 try{auto*r=runtime.load();if(r)r->calibration_navigation("guide_filament_page");}catch(...){}
}
extern "C" void unified_retired_guide_worker()noexcept {}
extern "C" void unified_filament_guide_event(void*event)noexcept {
 // Also consume callbacks from a guide constructed before hook installation.
 // In particular, Next must not turn off the old head or queue another worker.
 try{auto*r=runtime.load();if(r&&event&&reinterpret_cast<int(*)(void*)>(wmp_ui::native::lv_event_get_code)(event)==7)r->calibration_navigation("guide_filament_page");}catch(...){}
}
extern "C" void unified_preview_event(void*event)noexcept {
 try{
  if(!event)return;
  auto*target=reinterpret_cast<void*(*)(void*)>(wmp_ui::native::lv_event_get_target)(event);
  const auto code=reinterpret_cast<int(*)(void*)>(wmp_ui::native::lv_event_get_code)(event);
  if(preview_event_gate.consume(target,code))return;
  const auto action=reinterpret_cast<std::uintptr_t(*)(void*)>(wmp_ui::native::lv_event_get_user_data)(event);
  auto*before=*reinterpret_cast<void*volatile*>(0x386ef98);
  const bool before_valid=before&&reinterpret_cast<bool(*)(void*)>(wmp_ui::native::lv_obj_is_valid)(before);
  auto original=original_preview_event.load();if(original)original(event);
  if(code==7&&action>=9&&action<=12){
   auto*after=*reinterpret_cast<void*volatile*>(0x386ef98);
   if(after!=before||!before_valid)preview_event_gate.usb_modal(target,after);
  }
 }catch(...){return;}
}
// Legacy unbound async callbacks (including ones queued before installation)
// must not gain authority from whichever preview happens to be current now.
extern "C" void unified_preview_metadata()noexcept {}
struct PreviewMetadataCall {void*origin;std::uint64_t ticket;};
static void scheduled_preview_metadata(void*data)noexcept {
 std::unique_ptr<PreviewMetadataCall> call(static_cast<PreviewMetadataCall*>(data));
 try {
  if(!call)return;
  auto*current=*reinterpret_cast<void*volatile*>(0x386ee38);
  if(!preview_event_gate.metadata_allowed(call->origin,current,call->ticket))return;
  auto original=original_preview_metadata.load();if(original)original();
 }catch(...){}
}
extern "C" void unified_schedule_preview_metadata()noexcept {
 try {
  const auto origin=preview_event_gate.scheduled_origin();if(!origin.ticket)return;
  std::unique_ptr<PreviewMetadataCall> call(new PreviewMetadataCall{origin.content,origin.ticket});
  wmp_ui::native::queue_stock_async(reinterpret_cast<int(*)(void(*)(void*),void*)>(wmp_ui::native::lv_async_call),&scheduled_preview_metadata,std::move(call));
 }catch(...){}
}
extern "C" void unified_loading_popup(std::string text)noexcept {
 try {
  if(wmp_ui::native::StockPreviewLoadingScope::suppress())return;
  auto original=original_loading_popup.load();if(original)original(std::move(text));
 }catch(...){}
}
extern "C" void unified_draw_preview(void*parent)noexcept {
 try {
  auto*r=runtime.load();auto original=original_preview.load();if(!original)return;
  const bool usb=*reinterpret_cast<const unsigned char*>(0xe643270)!=0;
  const bool managed=r!=nullptr;
  if(managed){
   const auto path=*reinterpret_cast<const std::string*>(0xe643278);
   const bool leveling=*reinterpret_cast<const unsigned char*>(0x384ea58)!=0;
   const bool timelapse=*reinterpret_cast<const unsigned char*>(0x386ee09)!=0;
   const bool available=*reinterpret_cast<const unsigned char*>(0x386ea54)!=0;
   if(path.size()>1024||!(usb?r->prepare_usb_preview(path):r->prepare_stock_preview(path,leveling,timelapse,available)))return;
  }
  preview_event_gate.begin(parent,managed);
  {wmp_ui::native::StockPreviewLoadingScope loading(managed);
   original(parent); // Preserve the actual stock preview and surrounding page.
  }
  auto widgets=wmp_ui::native::StockPreviewInventory::capture();
  preview_event_gate.finish(widgets.content);
  if(managed){
   const auto&white=reinterpret_cast<const std::string*>(0x38626e8)[0];
   if(usb)r->usb_preview_created(widgets);else r->stock_preview_created(widgets,white);
  }
 }catch(...){preview_event_gate.finish(nullptr);}
}

extern "C" void unified_page_to(const char*name)noexcept {
 try {reprint_gate.invalidate();auto*r=runtime.load();
  if(r&&r->identification_blocks_navigation())return;
  if(r&&r->onboarding_file_navigation(name))return;
  if(r&&r->nozzle_navigation(name))return;
  if(wmp_ui::native::stock_probe_page(name)){if(r)r->open_probe_editor();return;}
  if(r&&r->calibration_navigation(name))return;
  if(r&&name&&(std::strcmp(name,"filament_page")==0||wmp_ui::native::stock_filament_service_page(name))){r->request(7);return;}
  if(r&&r->active())r->request(0);
  if(r)r->print_preparation_navigation(name);
  video_page_destination.store(name&&std::strcmp(name,"camera_page")==0);
  auto original=original_page.load();if(original)original(name);
 }catch(...){}
}
extern "C" void unified_main_event(void*event)noexcept {
 try {auto*r=runtime.load();
  if(r&&event){auto code=reinterpret_cast<int(*)(void*)>(0x6979fc)(event);
   auto data=reinterpret_cast<std::uintptr_t(*)(void*)>(0x697a30)(event);
   // Exact stock Main callback: 1..4 open physical heater panels, 7 opens
   // Filament. Other events, including Pause/Stop, retain the original handler.
   if(code==7&&((data>=1&&data<=4)||data==7)){r->request(int(data));return;}
  }
  auto original=original_main_event.load();if(original)original(event);
 }catch(...){}
}
#if defined(__aarch64__)
static ScreenDiagnosticLog&diagnostic_log(){static ScreenDiagnosticLog log;return log;}
#endif
static void notify(void*)noexcept {navigation_tabs().refresh();auto*r=runtime.load(std::memory_order_acquire);if(r)r->gui_step();}
static const RefreshBridge& bridge(){
 static const RefreshBridge value(reinterpret_cast<TimerCallback>(0x553de8),&notify,true);return value;
}
extern "C" void screen_refresh_wrapper(void*timer)noexcept {
 static std::int64_t previous=-1;
 auto milliseconds=[]()->std::int64_t{timespec t{};return clock_gettime(CLOCK_MONOTONIC,&t)?-1:std::int64_t(t.tv_sec)*1000+t.tv_nsec/1000000;};
 const auto started=milliseconds();
 screen_diagnostics().refresh_calls.fetch_add(1,std::memory_order_relaxed);bridge().invoke(timer);
 record_gui_timing(previous,started,milliseconds());previous=started;
}
extern "C" void*screen_timer_wrapper(TimerCallback requested,std::uint32_t period,void*data)noexcept {
 auto&d=screen_diagnostics();d.timer_calls.fetch_add(1,std::memory_order_relaxed);
 auto original=original_create.load(std::memory_order_acquire);
 if(!original)return nullptr; // Never installed until original trampoline exists.
 try{auto selected=bridge().select(requested,period,data,&screen_refresh_wrapper);
  if(selected!=requested)d.timer_matches.fetch_add(1,std::memory_order_relaxed);
  return original(selected,period,data);}
 catch(...){return nullptr;}
}
#if defined(__aarch64__)
static void jump(void*destination,std::uintptr_t address){
 const std::uint32_t code[]={0x58000050U,0xd61f0200U};
 std::memcpy(destination,code,8);std::memcpy(static_cast<char*>(destination)+8,&address,8);
}
struct HookMemoryOps {
 bool protect(std::uintptr_t address,std::size_t size,bool writable)noexcept {
  return mprotect(reinterpret_cast<void*>(address),size,
                  PROT_READ|PROT_EXEC|(writable?PROT_WRITE:0))==0;
 }
 void flush(std::uintptr_t address,std::size_t size)noexcept {
  __builtin___clear_cache(reinterpret_cast<char*>(address),reinterpret_cast<char*>(address+size));
 }
 void failure(const char*operation,std::uintptr_t address)noexcept {
  const int error=errno;auto&d=screen_diagnostics();
  d.error.store(error);d.address.store(address);d.bootstrap.store(DiagnosticBootstrap::EntryProtectFailed);
  std::fprintf(stderr,"WM+ native hook %s failed at 0x%lx: errno=%d; entry bytes and page permissions are separate outcomes\n",
               operation,static_cast<unsigned long>(address),error);
 }
};
struct NavigationHook {std::uintptr_t entry;void* trampoline;};
static NavigationHook navigation_hooks[]={{0x553b6c,nullptr},{0x519a34,nullptr},{0x537710,nullptr},{0x4f6dec,nullptr},{0x4f667c,nullptr},{0x4f86b8,nullptr},{0x4f8020,nullptr},{0x536958,nullptr},{0x538c7c,nullptr},{0x535958,nullptr},{0x539474,nullptr},{0x50d044,nullptr},{0x50e83c,nullptr},{0x50ecf0,nullptr},{0x50c9bc,nullptr},{0x4b0510,nullptr},{0x529218,nullptr},{0x4b4768,nullptr},{0x614338,nullptr},{0x4b6470,nullptr},{0x52a4cc,nullptr},{0x52a1e4,nullptr},{0x510350,nullptr},{0x50fb98,nullptr},{0x5100c8,nullptr},{0x51a7b4,nullptr},{0x5328b4,nullptr},{0x61b2c4,nullptr},{0x5352e0,nullptr},{0x532da8,nullptr},{0x5303e4,nullptr},{0x64fc84,nullptr},{0x4c41a4,nullptr},{0x4c76dc,nullptr},{0x53d150,nullptr},{0x548078,nullptr},{0x4c6490,nullptr},{0x545924,nullptr},{0x73ca58,nullptr},{0x4b7558,nullptr},{0x51ebf8,nullptr},{0x542308,nullptr},{0x5252f4,nullptr},{0x525a38,nullptr},{0x519600,nullptr},{wmp_ui::native::filament_pause,nullptr},{0x50b7f8,nullptr},{0x526770,nullptr},{0x54c93c,nullptr}};
// One timer hook plus every navigation hook; adding an entry grows the transaction.
constexpr std::size_t startup_hook_count=1+sizeof(navigation_hooks)/sizeof(navigation_hooks[0]);
using HookTransaction=wmp_ui::native::HookTransaction<HookMemoryOps,startup_hook_count>;
static bool prepare_navigation_hooks(HookTransaction&transaction)noexcept {
 using namespace wmp_ui::native;
 const std::uintptr_t replacements[]={reinterpret_cast<std::uintptr_t>(&unified_page_to),reinterpret_cast<std::uintptr_t>(&unified_main_event),reinterpret_cast<std::uintptr_t>(&unified_draw_preview),reinterpret_cast<std::uintptr_t>(&unified_setup_filament),reinterpret_cast<std::uintptr_t>(&unified_filament_event),reinterpret_cast<std::uintptr_t>(&unified_material_pick),reinterpret_cast<std::uintptr_t>(&unified_colour_pick),reinterpret_cast<std::uintptr_t>(&unified_preview_event),reinterpret_cast<std::uintptr_t>(&unified_preview_metadata),reinterpret_cast<std::uintptr_t>(&unified_loading_popup),reinterpret_cast<std::uintptr_t>(&unified_schedule_preview_metadata),reinterpret_cast<std::uintptr_t>(&unified_setup_filament_guide),reinterpret_cast<std::uintptr_t>(&unified_retired_guide_worker),reinterpret_cast<std::uintptr_t>(&unified_retired_guide_worker),reinterpret_cast<std::uintptr_t>(&unified_filament_guide_event),reinterpret_cast<std::uintptr_t>(&unified_setup_about),reinterpret_cast<std::uintptr_t>(&unified_nozzle_flow_event),reinterpret_cast<std::uintptr_t>(&unified_maintenance_event),reinterpret_cast<std::uintptr_t>(&unified_command_sender),reinterpret_cast<std::uintptr_t>(&unified_setup_calibration),reinterpret_cast<std::uintptr_t>(&unified_setup_identification),reinterpret_cast<std::uintptr_t>(&unified_retired_identification_event),reinterpret_cast<std::uintptr_t>(&unified_retired_identification_worker),reinterpret_cast<std::uintptr_t>(&unified_setup_guide_identification),reinterpret_cast<std::uintptr_t>(&unified_retired_guide_identification_refresh),reinterpret_cast<std::uintptr_t>(&unified_resume_prepare),reinterpret_cast<std::uintptr_t>(&unified_runout_purge),reinterpret_cast<std::uintptr_t>(&unified_resume_check),reinterpret_cast<std::uintptr_t>(&unified_draw_pop),reinterpret_cast<std::uintptr_t>(&unified_popup_build),reinterpret_cast<std::uintptr_t>(&unified_popup_event),reinterpret_cast<std::uintptr_t>(&unified_shell),reinterpret_cast<std::uintptr_t>(&unified_factory_event),reinterpret_cast<std::uintptr_t>(&unified_legacy_probe_event),reinterpret_cast<std::uintptr_t>(&unified_legacy_probe_event),reinterpret_cast<std::uintptr_t>(&unified_factory_reset),reinterpret_cast<std::uintptr_t>(&unified_knife_event),reinterpret_cast<std::uintptr_t>(&unified_exclude_object),reinterpret_cast<std::uintptr_t>(&unified_evdev_frame),reinterpret_cast<std::uintptr_t>(&unified_calibration_worker),reinterpret_cast<std::uintptr_t>(&unified_main_refresh),reinterpret_cast<std::uintptr_t>(&unified_sidebar),reinterpret_cast<std::uintptr_t>(&unified_filelist_menu),reinterpret_cast<std::uintptr_t>(&unified_setting_menu),reinterpret_cast<std::uintptr_t>(&unified_is_printing),reinterpret_cast<std::uintptr_t>(&unified_filament_pause),reinterpret_cast<std::uintptr_t>(&unified_guide_calibration_event),reinterpret_cast<std::uintptr_t>(&unified_home_event),reinterpret_cast<std::uintptr_t>(&unified_warning_callback)};
 // Profile initialization verified the complete file and all 32-byte windows.
 // The first eleven hooks, About and Nozzle Flow call through to stock code; their reviewed
 // prologues contain no PC-relative instructions. The guide hooks completely
 // replace stock behavior and must not copy their ADRP instructions to trampolines.
 for(auto&h:navigation_hooks){
  if(&h>=navigation_hooks+11&&h.entry!=0x4b0510&&h.entry!=0x529218&&h.entry!=0x4b4768&&h.entry!=0x614338&&h.entry!=0x4b6470&&h.entry!=0x52a4cc&&h.entry!=0x5352e0&&h.entry!=0x532da8&&h.entry!=0x5303e4&&h.entry!=0x64fc84&&h.entry!=0x4c41a4&&h.entry!=0x4c6490&&h.entry!=0x545924&&h.entry!=0x4b7558&&h.entry!=0x542308&&h.entry!=0x5252f4&&h.entry!=0x525a38&&h.entry!=stock_is_printing&&h.entry!=filament_pause&&h.entry!=guide_calibration_event&&h.entry!=home_event&&h.entry!=warning_callback)continue;
  const std::size_t size=h.entry==filament_pause?44:h.entry==stock_is_printing?40:32;
  h.trampoline=mmap(nullptr,size,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
  if(h.trampoline==MAP_FAILED){h.trampoline=nullptr;screen_diagnostics().error.store(errno);screen_diagnostics().address.store(h.entry);screen_diagnostics().bootstrap.store(DiagnosticBootstrap::MmapFailed);return false;}
  if(h.entry==filament_pause)stock_runout_trampoline(h.trampoline,reinterpret_cast<void*>(h.entry));
  else if(h.entry==stock_is_printing)stock_job_busy_trampoline(h.trampoline,reinterpret_cast<void*>(h.entry));
  else {std::memcpy(h.trampoline,reinterpret_cast<void*>(h.entry),16);jump(static_cast<char*>(h.trampoline)+16,h.entry+16);}
  __builtin___clear_cache(static_cast<char*>(h.trampoline),static_cast<char*>(h.trampoline)+size);
  if(mprotect(h.trampoline,size,PROT_READ|PROT_EXEC)){screen_diagnostics().error.store(errno);screen_diagnostics().address.store(h.entry);screen_diagnostics().bootstrap.store(DiagnosticBootstrap::TrampolineProtectFailed);return false;}
 }
 original_warning_callback.store(reinterpret_cast<void(*)(char*)>(navigation_hooks[48].trampoline));
 original_home_event.store(reinterpret_cast<StockEvent>(navigation_hooks[47].trampoline));
 original_guide_calibration_event.store(reinterpret_cast<StockEvent>(navigation_hooks[46].trampoline));
 original_filament_pause.store(reinterpret_cast<void(*)()>(navigation_hooks[45].trampoline));
 original_sidebar.store(reinterpret_cast<StockMenu>(navigation_hooks[41].trampoline));
 original_filelist_menu.store(reinterpret_cast<StockMenu>(navigation_hooks[42].trampoline));
 original_setting_menu.store(reinterpret_cast<StockMenu>(navigation_hooks[43].trampoline));
 original_is_printing.store(reinterpret_cast<bool(*)()>(navigation_hooks[44].trampoline));
 original_exclude_object.store(reinterpret_cast<void(*)()>(navigation_hooks[37].trampoline));
 original_knife_event.store(reinterpret_cast<StockEvent>(navigation_hooks[36].trampoline));
 original_factory_event.store(reinterpret_cast<StockEvent>(navigation_hooks[32].trampoline));
 original_shell.store(reinterpret_cast<StockShell>(navigation_hooks[31].trampoline));
 original_popup_build.store(reinterpret_cast<void(*)(int)>(navigation_hooks[29].trampoline));
 original_popup_event.store(reinterpret_cast<StockEvent>(navigation_hooks[30].trampoline));
 original_draw_pop.store(reinterpret_cast<void(*)(int)>(navigation_hooks[28].trampoline));
 original_page.store(reinterpret_cast<StockPage>(navigation_hooks[0].trampoline));
 original_main_event.store(reinterpret_cast<StockEvent>(navigation_hooks[1].trampoline));
 original_preview.store(reinterpret_cast<StockEvent>(navigation_hooks[2].trampoline));
 original_filament_setup.store(reinterpret_cast<StockEvent>(navigation_hooks[3].trampoline));
 original_filament_event.store(reinterpret_cast<StockEvent>(navigation_hooks[4].trampoline));
 original_material_pick.store(reinterpret_cast<StockEvent>(navigation_hooks[5].trampoline));
 original_colour_pick.store(reinterpret_cast<StockEvent>(navigation_hooks[6].trampoline));
 original_preview_event.store(reinterpret_cast<StockEvent>(navigation_hooks[7].trampoline));
 original_preview_metadata.store(reinterpret_cast<void(*)()>(navigation_hooks[8].trampoline));
 original_loading_popup.store(reinterpret_cast<void(*)(std::string)>(navigation_hooks[9].trampoline));
 original_about_setup.store(reinterpret_cast<StockEvent>(navigation_hooks[15].trampoline));
 original_nozzle_flow_event.store(reinterpret_cast<StockEvent>(navigation_hooks[16].trampoline));
 original_maintenance_event.store(reinterpret_cast<StockEvent>(navigation_hooks[17].trampoline));
 original_identification_setup.store(reinterpret_cast<StockEvent>(navigation_hooks[20].trampoline));
 original_calibration_setup.store(reinterpret_cast<StockEvent>(navigation_hooks[19].trampoline));
 original_calibration_worker.store(reinterpret_cast<void(*)()>(navigation_hooks[39].trampoline));
 original_command_sender.store(reinterpret_cast<void(*)(std::string)>(navigation_hooks[18].trampoline));
 static_assert(sizeof(replacements)/sizeof(replacements[0])==sizeof(navigation_hooks)/sizeof(navigation_hooks[0]),"hook count mismatch");
 for(unsigned i=0;i<sizeof(navigation_hooks)/sizeof(navigation_hooks[0]);++i){auto&h=navigation_hooks[i];
  unsigned char replacement[16];jump(replacement,replacements[i]);
  if(!transaction.add(h.entry,replacement))return false;
 }
 return true;
}
static bool prepare_timer_hook(HookTransaction&transaction)noexcept {
 auto&d=screen_diagnostics();
 constexpr std::uintptr_t entry=0x6cf084;
 if(std::memcmp(reinterpret_cast<void*>(entry),timer_window,32)){
  d.bootstrap.store(DiagnosticBootstrap::TimerMismatch);d.address.store(entry);return false;}
 if(std::memcmp(reinterpret_cast<void*>(0x553de8),refresh_window,32)){
  d.bootstrap.store(DiagnosticBootstrap::RefreshMismatch);d.address.store(0x553de8);return false;}
 void*code=mmap(nullptr,32,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
 if(code==MAP_FAILED){d.error.store(errno);d.bootstrap.store(DiagnosticBootstrap::MmapFailed);return false;}
 std::memcpy(code,reinterpret_cast<void*>(entry),16);jump(static_cast<char*>(code)+16,entry+16);
 __builtin___clear_cache(static_cast<char*>(code),static_cast<char*>(code)+32);
 if(mprotect(code,32,PROT_READ|PROT_EXEC)){d.error.store(errno);d.bootstrap.store(DiagnosticBootstrap::TrampolineProtectFailed);munmap(code,32);return false;}
 original_create.store(reinterpret_cast<TimerCreate>(code),std::memory_order_release);
 unsigned char replacement[16];jump(replacement,reinterpret_cast<std::uintptr_t>(&screen_timer_wrapper));
 return transaction.add(entry,replacement);
}
static void*worker_main(void*arg)noexcept {
 auto*r=static_cast<ScreenRuntime*>(arg);
 for(;;){
  try {timespec t{};if(!clock_gettime(CLOCK_MONOTONIC,&t)){
   const auto now=std::int64_t(t.tv_sec)*1000+t.tv_nsec/1000000;
   r->worker_step(now);diagnostic_log().emit(now);}
  }catch(...){}
  timespec wait{0,250000000};while(nanosleep(&wait,&wait)&&errno==EINTR){}
 }
}
#endif
}
// Intended only for process-start LD_PRELOAD, not hot injection. The final
// shared object is NODELETE: callbacks and the process-lifetime worker cannot
// outlive their code. Unified native hooks own Resume dispatch; the linked
// C compatibility constructor does not install competing hooks in this build.
extern "C" __attribute__((constructor)) void wmp_openace_screen_initialize()noexcept {
#if defined(__aarch64__)
 auto&d=screen_diagnostics();d.bootstrap.store(DiagnosticBootstrap::Started);
 try {
  // Heap ownership is deliberately process-lifetime; no off-GUI destructor can
  // invoke LVGL after its display/task has been deleted.
  (void)bridge(); // Construct callback policy off the GUI thread before publication.
  auto*channel=new UiChannel;
  auto*ui=new Native1113Port([channel](const std::string&c){return channel->enqueue(c);});
  if(!ui->initialize()){
   d.bootstrap.store(DiagnosticBootstrap::ProfileRejected);
   // Inherited LD_PRELOAD also reaches stock helper executables. Only a
   // recognized client with a mismatched native window needs a failure file.
   if(d.address.load(std::memory_order_relaxed)){(void)diagnostic_log().open_process_file();diagnostic_log().emit(0);}
   delete ui;delete channel;return;
  }
  (void)diagnostic_log().open_process_file();
  auto*http=new UnifiedLoopbackHttp;
  auto*screen=new ScreenRuntime(*http,*ui,*channel);
  screen->print_preparation_navigation(reinterpret_cast<const char*>(0x463c500));
  if(!screen->initialize())return;
  auto*usb_http=new wmp_ui::native::UsbCopyHttp;
  screen->enable_usb(*usb_http,"/home/t13dp/printer_data/gcodes/USB");
  auto*recovery_http=new UnifiedLoopbackHttp;auto*recovery_stop_http=new UnifiedLoopbackHttp;
  auto*resolution_http=new UnifiedLoopbackHttp;
  screen->enable_recovery(*recovery_http,*recovery_stop_http,*resolution_http);
  auto*probe_editor_http=new UnifiedLoopbackHttp;auto*probe_stop_http=new UnifiedLoopbackHttp;
  screen->enable_probe_editor(*probe_editor_http,*probe_stop_http);
  auto*calibration_cancel_http=new UnifiedLoopbackHttp;screen->enable_calibration_cancel(*calibration_cancel_http);
  auto*command_http=new UnifiedLoopbackHttp;auto*preview_http=new UnifiedLoopbackHttp;auto*off_http=new UnifiedLoopbackHttp;
  screen->enable_background(*command_http,*preview_http,*off_http);
  auto*cancel_http=new UnifiedLoopbackHttp;screen->enable_print_cancel(*cancel_http);
  auto*cancel_resolution_http=new UnifiedLoopbackHttp;screen->enable_print_cancel_resolution(*cancel_resolution_http);
  screen->set_local_preview([](void*parent,const std::string&path){
   *reinterpret_cast<unsigned char*>(0xe643270)=0;
   *reinterpret_cast<std::string*>(0xe643278)=path;
   unified_draw_preview(parent);
  });
  screen->set_calibration_sender([](const std::string&command){auto sender=original_command_sender.load();if(!sender)return false;sender(command);return true;});
  screen->set_stock_navigation([](const char*name){video_page_destination.store(name&&std::strcmp(name,"camera_page")==0);auto original=original_page.load();if(original)original(name);});
  screen->set_finish_onboarding([](){return wmp_ui::native::finish_setup("/home/t13dp");});
  const long page=sysconf(_SC_PAGESIZE);
  if(page<=0){d.error.store(errno);d.bootstrap.store(DiagnosticBootstrap::PageFailed);diagnostic_log().emit(0);return;}
  HookMemoryOps memory;HookTransaction transaction(memory,static_cast<std::size_t>(page));
  // Prepare all trampolines and entry pages before publishing a single jump.
  // Published stubs stay alive even on rollback: callbacks may be in flight.
  if(!prepare_timer_hook(transaction)||!prepare_navigation_hooks(transaction)||!transaction.prepare()){
   transaction.rollback();diagnostic_log().emit(0);return;
  }
  navigation_tabs().tools=[](){if(auto*r=runtime.load())r->open_tools();};
  navigation_tabs().video=[](){unified_page_to("camera_page");};
  navigation_tabs().refresh_video_files=[](){wmp_ui::native::stock_function<void(*)()>(wmp_ui::native::stock_refresh_udisk)();};
  runtime.store(screen,std::memory_order_release);
  while(transaction.patch_next()){}
  d.bootstrap.store(DiagnosticBootstrap::HookReady);
  pthread_t thread;
  const int rc=pthread_create(&thread,nullptr,&worker_main,screen);
  if(!rc){
   const bool permissions_restored=transaction.commit();
   if(permissions_restored)d.bootstrap.store(DiagnosticBootstrap::Running);
   else std::fprintf(stderr,"WM+ native hooks active; restoring executable page permissions failed\n");
   pthread_detach(thread);diagnostic_log().emit(0);
  }else{
   d.error.store(rc);d.bootstrap.store(DiagnosticBootstrap::WorkerFailed);
   const bool permissions_restored=transaction.rollback();
   runtime.store(nullptr,std::memory_order_release);
   std::fprintf(stderr,"WM+ native worker creation failed: rc=%d; stock entry bytes restored; RX permissions %s\n",rc,permissions_restored?"restored":"FAILED");
   diagnostic_log().emit(0);
  }
 }catch(...){runtime.store(nullptr,std::memory_order_release);d.bootstrap.store(DiagnosticBootstrap::Exception);diagnostic_log().emit(0);} // Never unwind into process startup.
#endif
}
}
