#pragma once
#include "worker_bridge.hpp"
#include "native_management.hpp"
#include "screen_diagnostics.hpp"
namespace wmp_openace {
// Process-lifetime orchestration only. Worker and GUI own disjoint mutable
// objects; their sole exchange is the bounded UiChannel above.
class ScreenRuntime {
public:
 ScreenRuntime(HttpPort&http,NativeUi&ui,UiChannel&channel)
  :channel_(channel),worker_(http,channel),renderer_(ui,channel){}
 void worker_step(std::int64_t now)noexcept {
  worker_.poll(now);worker_.deliver(now);
  try{
   auto&d=screen_diagnostics();d.worker_calls.fetch_add(1,std::memory_order_relaxed);
   auto value=channel_.latest();
   if(value){d.worker_session.store(value->view.session,std::memory_order_relaxed);
    d.worker_flags.store(int(value->view.connected)|(int(value->view.data_current)<<1)
     |(int(value->view.visible)<<2),std::memory_order_relaxed);}
  }catch(...){} // Diagnostic observation cannot change the worker's failure policy.
 }
 void gui_step()noexcept {
  auto&d=screen_diagnostics();d.gui_calls.fetch_add(1,std::memory_order_relaxed);
  try {auto value=channel_.latest();d.snapshot.store(bool(value),std::memory_order_relaxed);
   if(value){d.session.store(value->view.session,std::memory_order_relaxed);
    d.view_flags.store(int(value->view.connected)|(int(value->view.data_current)<<1)|(int(value->view.visible)<<2),std::memory_order_relaxed);
    renderer_.tick(*value);}}
  catch(...){} // Native C timer callback never receives a C++ exception.
 }
private:
 UiChannel&channel_;ScreenWorker worker_;NativeScreen renderer_;
};
}
