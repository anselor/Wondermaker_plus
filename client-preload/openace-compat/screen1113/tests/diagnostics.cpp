#include <cassert>
#include <cstdarg>
#include <fstream>
#include <sstream>
#include <thread>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include "screen_diagnostics.hpp"
#include "screen_runtime.hpp"
#define main renderer_prior_contract
#include "native_renderer.cpp"
#undef main
using namespace wmp_openace;
static bool gui_phase=false;
extern "C" int __real_open(const char*,int,...);
extern "C" ssize_t __real_write(int,const void*,size_t);
extern "C" int __real_socket(int,int,int);
extern "C" int __wrap_open(const char*path,int flags,...){
 assert(!gui_phase);va_list args;va_start(args,flags);
 const int mode=flags&O_CREAT?va_arg(args,int):0;va_end(args);
 return __real_open(path,flags,mode);
}
extern "C" ssize_t __wrap_write(int fd,const void*p,size_t n){assert(!gui_phase);return __real_write(fd,p,n);}
extern "C" int __wrap_socket(int a,int b,int c){assert(!gui_phase);return __real_socket(a,b,c);}
struct Http:HttpPort{
 std::string payload;int calls=0;
 std::string get(const std::string&)override{assert(!gui_phase);++calls;return "{\"result\":{\"status\":{\"openace\":"+payload+"}}}";}
 std::string post(const std::string&,const std::string&)override{assert(false);return "";}
};
int main(int argc,char**argv){
 assert(argc==2);
 char path[96];std::snprintf(path,sizeof(path),"/tmp/wmp_openace_screen_%ld.log",long(getpid()));
 // Never replace a preexisting path, including a symlink.
 assert(::symlink("/dev/null",path)==0);
 ScreenDiagnosticLog refused;assert(!refused.open_process_file());assert(::unlink(path)==0);
 ScreenDiagnosticLog log;assert(log.open_process_file());
 struct stat info{};assert(::lstat(path,&info)==0&&S_ISREG(info.st_mode));
 assert((info.st_mode&0777)==0644&&info.st_uid==geteuid()&&info.st_nlink==1);
 ScreenDiagnosticLog duplicate;assert(!duplicate.open_process_file());
 auto&facts=screen_diagnostics();facts.bootstrap.store(DiagnosticBootstrap::Running);
 // Scalar-only owned-widget record; GUI population must not perform I/O.
 gui_phase=true;
 facts.widgets[0].geometry[0].store(8);facts.widgets[0].hidden.store(0);
 facts.widgets[0].visible.store(1);facts.widgets[0].opacity.store(255);
 facts.widgets[0].recursive_opacity.store(255);facts.widgets[0].background_opacity.store(255);
 facts.widgets[0].text_opacity.store(255);facts.widgets[0].font_present.store(1);
 gui_phase=false;
 for(int i=0;i<5000;++i){facts.refresh_calls.fetch_add(1);log.emit(i);}
 assert(log.lines()==1);
 for(int i=1;i<100;++i)log.emit(i*5000);
 assert(log.lines()==60);
 std::ifstream input(path);std::string line;int lines=0;
 while(std::getline(input,line)){++lines;assert(line.find("bootstrap=")!=std::string::npos);assert(line.size()<1536);
  for(const auto*name:{"owned_root=","owned_badge=","owned_label=","owned_top="})assert(line.find(name)!=std::string::npos);
  assert(line.find("owned_root=8,-1,-1,-1,0,1,255,255,255,255,1")!=std::string::npos);}
 assert(lines==60);
 // A long idle period must not hide the next navigation attempt. Late records
 // remain rate limited and bounded; they never alter admission or do GUI I/O.
 gui_phase=true;
 record_gui_timing(-1,100,110);record_gui_timing(100,400,750);
 record_gui_timing(400,401,402);record_gui_timing(-1,-1,-1);
 assert(facts.gui_gap_max_ms.load()==300&&facts.gui_duration_max_ms.load()==350);
 facts.navigation_requests.fetch_add(1);facts.navigation_page.store(7);
 facts.navigation_at.store(500001);facts.navigation_stale.fetch_add(1);
 gui_phase=false;
 log.emit(500001);assert(log.lines()==61);
 log.emit(510001);assert(log.lines()==61);
 for(int i=1;i<=100;++i){facts.navigation_requests.fetch_add(1);log.emit(510001+i*5000);}
 assert(log.lines()==120);
 std::ifstream late(path);std::string last;
 while(std::getline(late,line))last=line;
 assert(last.find("nav_page=7")!=std::string::npos&&last.find("nav_stale=1")!=std::string::npos);
 assert(last.find("gui_duration_max_ms=350")!=std::string::npos);
 std::ifstream source(argv[1]);std::ostringstream text;text<<source.rdbuf();
 Http http;http.payload=text.str();UiChannel channel;Fake ui;ScreenRuntime runtime(http,ui,channel);
 runtime.worker_step(100);
 gui_phase=true;runtime.gui_step();gui_phase=false;
 bool visible=false;for(const auto&row:ui.objects)if(!row.second.hidden&&row.second.text=="openACE setup")visible=true;
 assert(visible&&http.calls==1&&ui.commands==0&&channel.take().ticket==0);
 assert(facts.gui_calls.load()>0&&facts.renderer.load()==DiagnosticRenderer::Visible);
 assert(facts.worker_calls.load()>0&&facts.worker_flags.load()==3&&facts.worker_session.load()>=0);
 assert(::unlink(path)==0);
}
