// Offline delivery candidate. No installer references this file yet.
#include "native1113_port.hpp"
#include "screen_runtime.hpp"
#include "loopback_http.hpp"
#include "refresh_bridge.hpp"
#include "timer_windows.hpp"
#include "screen_diagnostics.hpp"
#include <atomic>
#include <pthread.h>
#include <sys/mman.h>
#include <unistd.h>
#include <new>
namespace wmp_openace {
namespace {
using TimerCallback=RefreshBridge::Callback;
using TimerCreate=void*(*)(TimerCallback,std::uint32_t,void*);
static std::atomic<TimerCreate> original_create{nullptr};
static std::atomic<ScreenRuntime*> runtime{nullptr};
#if defined(__aarch64__)
static ScreenDiagnosticLog&diagnostic_log(){static ScreenDiagnosticLog log;return log;}
#endif
static void notify(void*)noexcept {auto*r=runtime.load(std::memory_order_acquire);if(r)r->gui_step();}
static const RefreshBridge& bridge(){
 static const RefreshBridge value(reinterpret_cast<TimerCallback>(0x553de8),&notify,true);return value;
}
extern "C" void screen_refresh_wrapper(void*timer)noexcept {
 screen_diagnostics().refresh_calls.fetch_add(1,std::memory_order_relaxed);bridge().invoke(timer);
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
static bool install_timer_hook()noexcept {
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
 long page=sysconf(_SC_PAGESIZE);
 if(page<=0){d.error.store(errno);d.bootstrap.store(DiagnosticBootstrap::PageFailed);munmap(code,32);return false;}
 auto start=entry&~(std::uintptr_t(page)-1),end=(entry+16+page-1)&~(std::uintptr_t(page)-1);
 if(mprotect(reinterpret_cast<void*>(start),end-start,PROT_READ|PROT_WRITE|PROT_EXEC)){
  d.error.store(errno);d.bootstrap.store(DiagnosticBootstrap::EntryProtectFailed);
  munmap(code,32);return false;
 }
 original_create.store(reinterpret_cast<TimerCreate>(code),std::memory_order_release);
 jump(reinterpret_cast<void*>(entry),reinterpret_cast<std::uintptr_t>(&screen_timer_wrapper));
 __builtin___clear_cache(reinterpret_cast<char*>(entry),reinterpret_cast<char*>(entry+16));
 // If restoring RX fails the already-published trampoline must stay alive.
 (void)mprotect(reinterpret_cast<void*>(start),end-start,PROT_READ|PROT_EXEC);
 d.bootstrap.store(DiagnosticBootstrap::HookReady);
 return true;
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
// outlive their code. The existing C Resume/heater hooks are linked unchanged.
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
  auto*http=new LoopbackHttp;
  auto*screen=new ScreenRuntime(*http,*ui,*channel);
  runtime.store(screen,std::memory_order_release);
  if(!install_timer_hook()){runtime.store(nullptr,std::memory_order_release);diagnostic_log().emit(0);return;}
  pthread_t thread;
  const int rc=pthread_create(&thread,nullptr,&worker_main,screen);
  if(!rc){d.bootstrap.store(DiagnosticBootstrap::Running);pthread_detach(thread);}
  else{d.error.store(rc);d.bootstrap.store(DiagnosticBootstrap::WorkerFailed);diagnostic_log().emit(0);}
 }catch(...){d.bootstrap.store(DiagnosticBootstrap::Exception);diagnostic_log().emit(0);} // Never unwind into process startup.
#endif
}
}
