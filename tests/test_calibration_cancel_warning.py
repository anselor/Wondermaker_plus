"""A confirmed normal Stop must not turn into a stock restart warning."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'client-preload/unified-ui/native'


def test_only_matching_confirmed_cancel_suppresses_warning(tmp_path):
    source = tmp_path / 'warning.cpp'
    source.write_text(r'''
#include "calibration_cancel_notice.hpp"
#include <cassert>
using namespace wmp_ui::native;
using wmp_ui::Json;
int main() {
 const std::string session(32,'a'), request(32,'b'), ticket="7";
 Json data{{"fresh",true},{"printer_state","ready"},{"owner","standalone"},
   {"calibration_session",session},{"maintenance_cancel_requested",true},
   {"maintenance_cancel_session",session},{"maintenance_cancel_request",request},
   {"calibration_active",false},
   {"calibration_attempt",{{"protocol",1},{"session",session},{"request",request},{"ticket",ticket},
     {"operation","home"},{"state","failed"},{"cancel_requested",true},
     {"cancel_phase","after Y homing"},{"error","Homing cancellation requested; stopped after Y homing"},
     {"cancel_cleanup",{{"state","complete"},{"offsets","not_needed"},{"park","held"},{"error",""}}}}}};
 const auto text=data["calibration_attempt"]["error"].get<std::string>();
 auto matches=[&](const Json&d,const std::string&m){return confirmed_calibration_cancel_notice(d,session,request,ticket,m);};
 assert(matches(data,text));
 assert(!matches(data,"ZRU-B001: Screen-Mainboard communication error"));
 assert(!matches(data,text+"; transport failed"));
 for(const auto*key:{"fresh","maintenance_cancel_requested"}){auto d=data;d[key]=false;assert(!matches(d,text));}
 for(const auto*state:{"error","shutdown","startup"}){auto d=data;d["printer_state"]=state;assert(!matches(d,text));}
 for(const auto*key:{"calibration_session","maintenance_cancel_session","maintenance_cancel_request"}){auto d=data;d[key]=std::string(32,'c');assert(!matches(d,text));}
 for(const auto*owner:{"openace","AFC","unknown"}){auto d=data;d["owner"]=owner;assert(!matches(d,text));}
 auto d=data;d["calibration_active"]=true;assert(!matches(d,text));
 for(const auto*key:{"session","request","ticket"}){d=data;d["calibration_attempt"][key]="replacement";assert(!matches(d,text));}
 for(const auto*state:{"pending","complete","refused"}){d=data;d["calibration_attempt"]["state"]=state;assert(!matches(d,text));}
 d=data;d["calibration_attempt"]["cancel_requested"]=false;assert(!matches(d,text));
 d=data;d["calibration_attempt"]["cancel_phase"]="";assert(!matches(d,text));
 for(const auto*key:{"state","offsets","park","error"}){d=data;d["calibration_attempt"]["cancel_cleanup"][key]="unconfirmed";assert(!matches(d,text));}
 d=data;d["calibration_attempt"]["error"]="endstop failed";assert(!matches(d,"endstop failed"));
 d=data;d["calibration_attempt"]["operation"]="calibration";
 assert(!matches(d,text));
 d["calibration_attempt"]["cancel_phase"]="during heater wait";
 d["calibration_attempt"]["error"]="Calibration cancellation requested; stopped during heater wait";
 d["calibration_attempt"]["cancel_cleanup"]["park"]="parked";
 assert(matches(d,d["calibration_attempt"]["error"]));
 assert(!confirmed_calibration_cancel_notice(data,"",request,ticket,text));
 assert(!confirmed_calibration_cancel_notice(data,session,"",ticket,text));
 assert(!confirmed_calibration_cancel_notice(data,session,request,"",text));
 // Bad or absent data cannot silence a warning, and must never throw.
 for(const auto&bad:{Json(),Json::array(),Json{{"fresh","bad"}},Json{{"calibration_attempt",17}}})assert(!matches(bad,text));
}
''')
    exe = tmp_path / 'warning'
    subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror',
                    '-I'+str(NATIVE), '-I'+str(ROOT/'client-preload/openace-compat/screen1113/source/vendor'),
                    str(source),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)


def test_actual_warning_callback_uses_current_owned_receipt(tmp_path):
    source = tmp_path / 'callback.cpp'
    source.write_text(r'''
#define WMP_NATIVE_TEST 1
#include "native/bootstrap.cpp"
#include <cassert>
using wmp_ui::Json;
static unsigned warnings=0;
static void warning(char*){++warnings;}
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
namespace wmp_ui {namespace native {
void*test_stock_colour_picker(void*,int){assert(false);return nullptr;}
StockTextKeyboardState&test_text_keyboard_state(){static StockTextKeyboardState state;return state;}
void*test_resolve(std::uintptr_t){assert(false);return nullptr;}
struct RuntimeReceiptTest {
 static void bind(Runtime&r){
  const std::string session(32,'a'),request(32,'b');
  r.calibration_binding_={&r,session,request};r.calibration_binding_.ticket="7";
  r.calibration_cancel_requested_=true;r.at_=1000;
  r.normalized_={{"fresh",true},{"printer_state","ready"},{"owner","standalone"},
   {"calibration_session",session},{"calibration_active",false},
   {"calibration_attempt",{{"protocol",1},{"session",session},{"request",request},{"ticket","7"},
    {"operation","home"},{"state","failed"},{"cancel_requested",true},
    {"cancel_phase","after Y homing"},{"error","Homing cancellation requested; stopped after Y homing"},
    {"cancel_cleanup",{{"state","complete"},{"offsets","not_needed"},{"park","held"},{"error",""}}}}}};
 }
 static void stale(Runtime&r){r.at_=-1;}
 static void replaced(Runtime&r){r.calibration_binding_.request=std::string(32,'c');}
};
}}
int main(){
 using namespace wmp_openace;
 char cancel[]="Homing cancellation requested; stopped after Y homing";
 char fault[]="ZRU-B001: Screen-Mainboard communication error";
 original_warning_callback.store(&warning);
 unified_warning_callback(cancel);assert(warnings==1); // runtime absent -> stock
 Http http;Port port;wmp_openace::UiChannel channel;ScreenRuntime r(http,port,channel);
 runtime.store(&r);wmp_ui::native::RuntimeReceiptTest::bind(r);
 unified_warning_callback(cancel);assert(warnings==1); // confirmed Stop only
 unified_warning_callback(fault);assert(warnings==2); // actual fault preserved
 wmp_ui::native::RuntimeReceiptTest::stale(r);unified_warning_callback(cancel);assert(warnings==3);
 wmp_ui::native::RuntimeReceiptTest::bind(r);wmp_ui::native::RuntimeReceiptTest::replaced(r);
 unified_warning_callback(cancel);assert(warnings==4);
 runtime.store(nullptr);
}
''')
    exe = tmp_path / 'callback'
    subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-pthread',
                    '-I'+str(NATIVE.parent), '-I'+str(NATIVE),
                    '-I'+str(ROOT/'client-preload/openace-compat/screen1113/source/client'),
                    '-I'+str(ROOT/'client-preload/openace-compat/screen1113/source/vendor'),
                    str(source),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
