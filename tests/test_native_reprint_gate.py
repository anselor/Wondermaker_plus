"""A queued Re-print review must retain its original popup/file ownership."""
import subprocess
from pathlib import Path


def test_reprint_popup_ownership(tmp_path):
    native = Path(__file__).resolve().parents[1] / 'client-preload/unified-ui/native'
    source = tmp_path / 'reprint.cpp'
    source.write_text(r'''
#include "stock_reprint_gate.hpp"
#include <cassert>
using wmp_ui::native::StockReprintGate;
int main() {
 using Action=StockReprintGate::Action;
 StockReprintGate gate; StockReprintGate::Request request, stale;
 int button, close, replacement;
 for(int kind: {5,6}) {
  gate.begin(kind);
  assert(gate.arm(&button,"job.gcode",true));
  assert(gate.event(kind,7,&button,&button,true,request)==Action::Review);
  assert(request.path=="job.gcode" && gate.pending(request));
  stale=request;
  assert(gate.event(kind,7,&button,&button,true,request)==Action::Consume);
  assert(gate.take(stale)); assert(!gate.take(stale));
  gate.begin(kind);assert(gate.arm(&button,"other.gcode",true));
  assert(!gate.pending(stale));
  assert(gate.event(kind,7,&button,&replacement,true,request)==Action::Consume);
  assert(!gate.pending(stale));
  gate.begin(kind);assert(gate.arm(&button,"job.gcode",true));
  assert(gate.event(kind,7,&button,&button,true,request)==Action::Review);
  stale=request;
  assert(gate.event(kind,7,&close,&button,true,request)==Action::Delegate);
  assert(!gate.pending(stale));
  gate.begin(kind);assert(!gate.arm(&button,"job.gcode",false));
  assert(gate.event(kind,7,&button,&button,true,request)==Action::Consume);
  gate.begin(kind);assert(gate.arm(&button,"job.gcode",true));
  assert(gate.event(kind,7,&button,&button,false,request)==Action::Consume);
  assert(gate.event(kind,1,&button,&button,true,request)==Action::Consume);
  assert(gate.event(kind==5?6:5,7,&button,&button,true,request)==Action::Consume);
 }
 // Runout, PLR, and unrelated popups are not Re-print events.
 for(int kind: {0,3,62,99,100})
  assert(gate.event(kind,7,&button,&button,true,request)==Action::Delegate);
 gate.begin(6);assert(gate.arm(&button,"job.gcode",true));
 assert(gate.event(6,7,&button,&button,true,request)==Action::Review);
 stale=request;gate.begin(62);assert(!gate.pending(stale));
}
''')
    executable = tmp_path / 'reprint'
    subprocess.run(['g++', '-std=c++11', '-Wall', '-Wextra', '-Werror',
                    '-I'+str(native), str(source), '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True)


def test_reprint_native_event_intercepts_before_vendor_prefix(tmp_path):
    root = Path(__file__).resolve().parents[1]
    native = root / 'client-preload/unified-ui/native'
    source = tmp_path / 'event.cpp'
    source.write_text(r'''
#define WMP_NATIVE_TEST 1
#include "native/bootstrap.cpp"
#include <cassert>
#include <sys/mman.h>
struct Node {explicit Node(Node*p):parent(p){} Node*parent;bool live=true;bool hidden=false;};
struct Event {Node*target;int code;std::uintptr_t kind;};
static Node top{nullptr}, panel{&top}, button{&panel}, close_button{&panel};
static unsigned delegated=0,queued=0,shown=0,cleared=0,updates=0;
static void update(){++updates;}
static bool printing(){return true;}
static void show_card(){++shown;}
static void clear_card(){++cleared;}
static void(*queued_fn)(void*)=nullptr;static void*queued_data=nullptr;
static int code(void*p){return static_cast<Event*>(p)->code;}
static void* user(void*p){return reinterpret_cast<void*>(static_cast<Event*>(p)->kind);}
static void* target(void*p){return static_cast<Event*>(p)->target;}
static void* layer(void*){return &top;}
static bool valid(void*p){return p&&static_cast<Node*>(p)->live;}
static void hide(void*p,unsigned){static_cast<Node*>(p)->hidden=true;}
static bool hidden(void*p,unsigned){return static_cast<Node*>(p)->hidden;}
static void* parent(void*p){return static_cast<Node*>(p)->parent;}
static int queue(void(*fn)(void*),void*data){++queued;queued_fn=fn;queued_data=data;return 1;}
static void vendor(void*){++delegated;}
static void build_popup(int kind){*reinterpret_cast<int*>(0x384e938)=kind;top.hidden=false;}
static unsigned pages=0,previews=0;
static void page(const char*name){
 assert(std::string(name)=="filelist_local_page");++pages;
 // Firmware cur_page_ui is char[80], not std::string. The manager
 // invokes page construction synchronously before page_to returns.
 std::strncpy(reinterpret_cast<char*>(0x463c500),name,80);
 *reinterpret_cast<void**>(0x3864330)=&panel;
}
struct Port : wmp_openace::NativeUi {
 bool profile1113()const override{return true;}bool frame(wmp_openace::Frame&,void*)override{return false;}
 void*create(void*,Kind,Event,void*,std::uint64_t)override{assert(false);return nullptr;}
 void erase(void*)override{assert(false);}void rect(void*,wmp_openace::Rect)override{}
 void literal_text(void*,const std::string&)override{}void hidden(void*,bool)override{}void behind_stock(void*)override{}
 std::uint64_t enqueue(const std::string&)override{assert(false);return 0;}
 std::int64_t now_ms()const override{return 1000;}
};
struct Http : wmp_openace::HttpPort {
 std::string get(const std::string&)override{assert(false);return {};}
 std::string post(const std::string&,const std::string&)override{assert(false);return {};}
};
// Stop at the stock drawing boundary; actual widget rendering is covered by
// native lifecycle tests. Reaching this function requires real managed preview
// preparation to have succeeded, with no HTTP or G-code submission.
static void preview(void*p){assert(p==&panel);++previews;throw std::runtime_error("drawing boundary");}
namespace wmp_ui {namespace native {
void*test_stock_colour_picker(void*,int){assert(false);return nullptr;}
struct RuntimeReceiptTest {
 static std::function<void()> discard_finish(Runtime&r){return r.native_discard_done_;}
 static void discard_panel_gone(Runtime&r){r.show_recovery_.store(false);}
 static bool cancellation_requested(Runtime&r){return r.show_cancel_.load();}
 static void stopped_job(Runtime&r,const std::string&state,const std::string&path,bool fresh=true){
  r.normalized_={{"fresh",fresh},{"job",{{"state",state},{"id",path}}}};r.at_=1000;
 }
 static void other_cancel_owner(Runtime&r){r.cancel_worker_->observe(
  Json{{"afc_metadata",{{"owner","openace"}}}},Json::object(),true);}
 static void verify(Runtime&r,const std::string&path,std::uint64_t generation){
  assert(r.selected_file_==path&&r.pending_preview_==path);
  assert(r.preview_generation_==generation&&r.native_preview_session_);
 }
};
StockTextKeyboardState&test_text_keyboard_state(){static StockTextKeyboardState state;return state;}
void*test_resolve(std::uintptr_t a){
#define MAP(symbol,fn) if(a==symbol)return reinterpret_cast<void*>(&fn)
 MAP(lv_event_get_code,code);MAP(lv_event_get_user_data,user);MAP(lv_event_get_target,target);
 MAP(lv_disp_get_layer_top,layer);MAP(lv_obj_is_valid,valid);MAP(lv_obj_has_flag,hidden);
 MAP(lv_obj_get_parent,parent);MAP(lv_async_call,queue);MAP(lv_obj_add_flag,hide);
 MAP(main_update_common,update);MAP(main_update_printing,update);MAP(main_update_tips,update);
 MAP(stock_is_printing,printing);MAP(main_show_printing,show_card);MAP(main_hide_printing,clear_card);
#undef MAP
 assert(false);return nullptr;
}
}}
int main(){
 using namespace wmp_openace;
 for(auto address:{0x384e000UL,0x386e000UL,0x386c000UL,0xe645000UL})assert(mmap(reinterpret_cast<void*>(address),4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED,-1,0)!=MAP_FAILED);
 *reinterpret_cast<void**>(0x386ebe8)=&button;*reinterpret_cast<void**>(0x386ebe0)=&close_button;
 original_popup_event.store(&vendor);
 auto&state=*new(reinterpret_cast<void*>(0xe645338))std::string("complete");
 auto&filename=*new(reinterpret_cast<void*>(0xe645430))std::string("part.gcode");
 auto&host=*new(reinterpret_cast<void*>(0xe645170))std::string("ready");
 original_is_printing.store(&printing);
 assert(!unified_is_printing()); // complete permits calibration and file selection
 assert(state=="complete"&&filename=="part.gcode"); // receipt remains available
 for(const auto&job:{"printing","paused","error"}){state=job;assert(unified_is_printing());}
 state="complete";host="shutdown";assert(unified_is_printing());
 host="ready";assert(!unified_is_printing());

 *reinterpret_cast<unsigned char*>(0x386ceb8)=1;
 for(int kind:{5,6}){
  *reinterpret_cast<int*>(0x384e938)=kind;
  reprint_gate.begin(kind);assert(reprint_gate.arm(&button,"part.gcode",true));
  Event e{&button,7,std::uintptr_t(kind)};
  auto before=delegated;auto before_queue=queued;
  unified_popup_event(&e);assert(delegated==before&&queued==before_queue+1);
  assert(*reinterpret_cast<int*>(0x384e938)==kind); // stock dismissal prefix never ran
  unified_popup_event(&e);assert(delegated==before&&queued==before_queue+1);
  e.target=&close_button;unified_popup_event(&e);assert(delegated==before+1);
  unified_main_refresh();assert(*reinterpret_cast<unsigned char*>(0x386ceb8)==(kind==6?0:1));
  const auto hidden_count=cleared;
  unified_main_refresh();assert(cleared==hidden_count); // stays hidden without repeated transitions
  assert(state=="complete"&&filename=="part.gcode"); // backend-facing state untouched
  state="printing";unified_main_refresh();assert(*reinterpret_cast<unsigned char*>(0x386ceb8)==1);
  state="complete";unified_main_refresh(); // same file's next completion is visible
  assert(*reinterpret_cast<unsigned char*>(0x386ceb8)==1&&updates>0);
  if(kind==6)assert(shown>0);
  queued_fn(queued_data); // cancelled request must not touch navigation or runtime
  e.target=&button;button.hidden=true;unified_popup_event(&e);button.hidden=false;
  assert(delegated==before+1&&queued==before_queue+1);
 }
 // Exercise the queued callback into a real Runtime, not just the gate.
 for(auto address:{0x3864000UL,0x463c000UL,0xe643000UL})
  assert(mmap(reinterpret_cast<void*>(address),4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED,-1,0)!=MAP_FAILED);
 std::memset(reinterpret_cast<void*>(0x463c500),0,80);
 new(reinterpret_cast<void*>(0xe643278))std::string;
 Http wire;Port port;UiChannel channel;ScreenRuntime live_runtime(wire,port,channel);
 runtime.store(&live_runtime);original_page.store(&page);original_preview.store(&preview);
 wmp_ui::native::RuntimeReceiptTest::stopped_job(live_runtime,"idle","stopped.gcode");
 assert(live_runtime.stopped_job_file()=="stopped.gcode");
 for(const auto*state:{"printing","paused","complete","unknown"}){
  wmp_ui::native::RuntimeReceiptTest::stopped_job(live_runtime,state,"new.gcode");
  assert(live_runtime.stopped_job_file().empty());
 }
 wmp_ui::native::RuntimeReceiptTest::stopped_job(live_runtime,"idle","old.gcode",false);
 assert(live_runtime.stopped_job_file().empty());
 wmp_ui::native::RuntimeReceiptTest::stopped_job(live_runtime,"idle","../unsafe.gcode");
 assert(live_runtime.stopped_job_file().empty());
 std::uint64_t generation=0;
 for(int kind:{5,6}){
  top.hidden=false;*reinterpret_cast<int*>(0x384e938)=kind;
  const std::string path=kind==6?"completed.gcode":"stopped.gcode";
  if(kind==5){
   // The real stopped-popup builder runs after stock clears its browser path.
   *reinterpret_cast<std::string*>(0xe643278)="";
   original_popup_build.store(&build_popup);
   wmp_ui::native::RuntimeReceiptTest::stopped_job(live_runtime,"idle",path);
   unified_popup_build(kind);
  }else{reprint_gate.begin(kind);assert(reprint_gate.arm(&button,path,true));}
  Event click{&button,7,std::uintptr_t(kind)};const auto before=delegated;
  unified_popup_event(&click);
  // A later stock filename must not replace the captured popup's filename.
  *reinterpret_cast<std::string*>(0xe643278)="unrelated.gcode";
  queued_fn(queued_data);
  assert(delegated==before&&top.hidden&&*reinterpret_cast<int*>(0x384e938)==-1);
  assert(*reinterpret_cast<std::string*>(0xe643278)==path);
  assert(pages==++generation&&previews==generation);
  wmp_ui::native::RuntimeReceiptTest::verify(live_runtime,path,generation);
 }
 // Native Stop must be intercepted before quick_stop and PLR-file removal,
 // even when cancellation is refused (this Runtime has no cancel worker).
 top.hidden=false;*reinterpret_cast<int*>(0x384e938)=69;
 Event stop{&button,1,69};const auto before_stop=delegated;
 unified_popup_event(&stop);assert(!top.hidden&&delegated==before_stop);
 stop.code=7;button.hidden=true;unified_popup_event(&stop);
 assert(!top.hidden&&delegated==before_stop);button.hidden=false;
 stop.target=&close_button;unified_popup_event(&stop);assert(delegated==before_stop+1);
 stop.target=&button;unified_popup_event(&stop);
 assert(!top.hidden&&panel.hidden&&*reinterpret_cast<int*>(0x384e938)==-1&&delegated==before_stop+1);
 assert(wmp_ui::native::RuntimeReceiptTest::cancellation_requested(live_runtime));
 top.hidden=false;*reinterpret_cast<int*>(0x384e938)=62;
 unified_popup_event(&stop);assert(!top.hidden&&delegated==before_stop+1);
 panel.hidden=false;
 live_runtime.enable_print_cancel(wire);
 wmp_ui::native::RuntimeReceiptTest::other_cancel_owner(live_runtime);
 top.hidden=false;*reinterpret_cast<int*>(0x384e938)=69;
 unified_popup_event(&stop);assert(!top.hidden&&delegated==before_stop+2);
 runtime.store(nullptr);
 Event unrelated{&button,7,62};unified_popup_event(&unrelated);assert(delegated==5);
 // PLR Cancel never reaches reset_plr_files/PARK_CURRENT_TOOL. A managed
 // review preserves the native prompt until its verified completion callback.
 runtime.store(&live_runtime);live_runtime.enable_recovery(wire,wire,wire);
 *reinterpret_cast<int*>(0x384e938)=3;top.hidden=false;panel.hidden=false;
 Event plr{&close_button,1,3};auto before_plr=delegated;
 unified_popup_event(&plr);assert(!live_runtime.native_discard_active());
 plr.code=7;close_button.hidden=true;unified_popup_event(&plr);close_button.hidden=false;
 assert(!live_runtime.native_discard_active()&&delegated==before_plr);
 plr.target=&button;unified_popup_event(&plr);assert(delegated==before_plr+1);
 // A dismissed WM+ overlay can leave the still-visible vendor prompt with
 // popupkind=-1. Only its current visible buttons may dispatch recovery.
 *reinterpret_cast<int*>(0x384e938)=-1;
 button.hidden=true;unified_popup_event(&plr);assert(delegated==before_plr+1);
 button.hidden=false;Node stale{&panel};plr.target=&stale;
 unified_popup_event(&plr);assert(delegated==before_plr+1);
 plr.target=&button;*reinterpret_cast<int*>(0x384e938)=69;
 unified_popup_event(&plr);assert(delegated==before_plr+1);
 *reinterpret_cast<int*>(0x384e938)=-1;
 unified_popup_event(&plr);assert(delegated==before_plr+2);
 ++before_plr; // Keep the remaining independent scenario's baseline.
 *reinterpret_cast<int*>(0x384e938)=3;
 plr.target=&close_button;unified_popup_event(&plr);
 assert(live_runtime.native_discard_active()&&!panel.hidden&&!top.hidden);
 assert(*reinterpret_cast<int*>(0x384e938)==3&&delegated==before_plr+1);
 plr.target=&button;unified_popup_event(&plr);assert(delegated==before_plr+1);
 // External deletion consumed the presentation but must not reserve the
 // printer or eat a later explicit Continue. No discard command is sent.
 wmp_ui::native::RuntimeReceiptTest::discard_panel_gone(live_runtime);
 *reinterpret_cast<int*>(0x384e938)=-1;
 unified_popup_event(&plr);assert(delegated==before_plr+2&&!live_runtime.native_discard_active());
 ++before_plr;
 plr.target=&close_button;unified_popup_event(&plr);
 assert(live_runtime.native_discard_active());
 *reinterpret_cast<int*>(0x384e938)=3;
 auto finish=wmp_ui::native::RuntimeReceiptTest::discard_finish(live_runtime);
 ++popup_generation;finish();assert(!panel.hidden&&*reinterpret_cast<int*>(0x384e938)==3);
 --popup_generation;finish();assert(panel.hidden&&!top.hidden&&*reinterpret_cast<int*>(0x384e938)==-1);
 panel.hidden=false;*reinterpret_cast<int*>(0x384e938)=3;
 runtime.store(nullptr);plr.target=&close_button;unified_popup_event(&plr);assert(delegated==before_plr+1);
 // Reset must not delegate its affirmative click to the stock progress/worker
 // prefix. Invalid, stale and duplicate input must not dismiss another popup.
 *reinterpret_cast<int*>(0x384e938)=21;Event reset{&button,7,21};
 const auto before_reset=delegated;const auto before_reset_queue=queued;
 top.hidden=false;button.hidden=true;unified_popup_event(&reset);
 assert(*reinterpret_cast<int*>(0x384e938)==21&&!top.hidden);
 button.hidden=false;reset.code=1;unified_popup_event(&reset);
 assert(*reinterpret_cast<int*>(0x384e938)==21&&!top.hidden);
 reset.code=7;reset.target=&close_button;unified_popup_event(&reset);
 assert(delegated==before_reset+1);reset.target=&button;
 unified_popup_event(&reset);
 assert(top.hidden&&*reinterpret_cast<int*>(0x384e938)==-1);
 assert(delegated==before_reset+1&&queued==before_reset_queue);
 top.hidden=false;*reinterpret_cast<int*>(0x384e938)=62;
 unified_popup_event(&reset);
 assert(!top.hidden&&*reinterpret_cast<int*>(0x384e938)==62);
 assert(delegated==before_reset+1&&queued==before_reset_queue);

}
''')
    executable = tmp_path / 'event'
    subprocess.run(['g++', '-std=c++11', '-Wall', '-Wextra', '-Werror', '-pthread',
                    '-I'+str(native.parent), '-I'+str(native),
                    '-I'+str(root/'client-preload/openace-compat/screen1113/source/client'),
                    '-I'+str(root/'client-preload/openace-compat/screen1113/source/vendor'),
                    str(source), '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
