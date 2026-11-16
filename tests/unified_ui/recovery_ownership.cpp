// SPDX-License-Identifier: GPL-3.0-or-later
#define main prior_renderer_contract
#include "../../client-preload/openace-compat/screen1113/tests/native_renderer.cpp"
#undef main
#include "native_management.hpp"

int main() {
 Fake ui; UiChannel channel; NativeScreen screen(ui,channel,false);
 channel.set_management_open(true); // Unified worker owns observation.
 View idle; idle.connected=idle.data_current=true; idle.session=1;
 UiSnapshot snapshot{idle,100,Delivery(),1,nullptr,""};
 for(int i=0;i<3;++i)screen.tick(snapshot);
 assert(ui.created==0 && !screen.management().root() && channel.management_open());
 // Recovery still owns its scoped alert and confirmation controls.
 snapshot.view=pending(); screen.tick(snapshot);
 assert(screen.material().root() && !screen.management().root());
 ui.event(screen.material().badge(),7);screen.tick(snapshot);
 assert(screen.material().confirm());
 ui.event(screen.material().confirm(),1);ui.event(screen.material().confirm(),7);
 assert(ui.commands==1 && ui.command.find("OPENACE_CONFIRM_CHANGE TOOL=3 ")==0);
 // Clearing recovery must remove it without resurrecting old setup.
 snapshot.view=idle;screen.tick(snapshot);
 assert(ui.objects.empty() && channel.management_open());
 screen.management().deactivate();assert(channel.management_open());
 // A GUI tick while a management HTTP response is in flight cannot revoke
 // the unified worker's subscription or discard the returned management data.
 struct PollHttp : HttpPort {
  std::function<void()> during_get;
  std::string get(const std::string& path)override {
   assert(path==ScreenWorker::management_query());during_get();
   return json{{"result",{{"status",{{"openace",{{"session_id",1}}}}}}}}.dump();
  }
  std::string post(const std::string&,const std::string&)override{assert(false);return "";}
 } http;
 http.during_get=[&](){screen.tick(snapshot);screen.management().deactivate();};
 ScreenWorker worker(http,channel);worker.poll(100);
 assert(channel.management_open() && channel.latest()->management);
 // Standalone legacy bundle preserves its original default behavior.
 Fake legacy_ui; UiChannel legacy_channel; NativeScreen legacy(legacy_ui,legacy_channel);
 legacy.tick(snapshot);
 assert(legacy.management().root() && legacy.management().visible());
 legacy_channel.set_management_open(true);legacy.management().deactivate();
 assert(!legacy_channel.management_open());
}
