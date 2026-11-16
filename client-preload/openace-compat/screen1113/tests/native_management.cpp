#define main renderer_prior_contract
#include "native_renderer.cpp"
#undef main
#include "native_management.hpp"
#include <memory>
int main(int argc,char**argv){assert(argc==2);std::ifstream f(argv[1]);std::ostringstream s;s<<f.rdbuf();auto data=std::make_shared<const json>(json::parse(s.str()));
 Fake ui;UiChannel channel;NativeScreen screen(ui,channel);View idle;idle.connected=idle.data_current=true;idle.session=data->at("session_id");
 UiSnapshot snapshot{idle,100,Delivery(),1,nullptr,""};screen.tick(snapshot);auto&renderer=screen.management();assert(renderer.visible()&&renderer.badge()&&!channel.management_open());assert(!ui.objects.at(renderer.badge()).hidden);
 ui.event(renderer.badge(),7);assert(channel.management_open());snapshot.management=data;screen.tick(snapshot);
 auto press=[&](const std::string&id){const auto&view=renderer.panel();for(std::size_t i=0;i<view.buttons.size();++i)if(view.buttons[i].first==id){ui.event(renderer.button(i),1);ui.event(renderer.button(i),7);return;}assert(false);};
 press("heads");screen.tick(snapshot);press("edit");screen.tick(snapshot);press("erase");screen.tick(snapshot);press("key:1");screen.tick(snapshot);press("review");screen.tick(snapshot);
 assert(renderer.panel().title.find("Review")!=std::string::npos);assert(!channel.take().ticket); // No Apply yet.
 press("apply");auto queued=channel.take();assert(queued.ticket&&queued.management&&queued.command.find("OPENACE_HEAD_SET")==0);channel.settle(queued.ticket);
 // Current native overlay/page/layout changes suppress every owned object and command input.
 ui.modal=true;screen.tick(snapshot);assert(!renderer.visible()&&ui.objects.at(renderer.root()).hidden);
 ui.modal=false;ui.layout=false;screen.tick(snapshot);assert(!renderer.visible());
 ui.layout=true;screen.tick(snapshot);auto oldroot=renderer.root();auto old=ui.objects.at(oldroot);ui.erase(oldroot);screen.tick(snapshot);assert(renderer.root()!=oldroot);old.cb(old.ctx,oldroot,7,old.generation);
 // An actual material prompt wins and closes the setup observer; no two roots.
 snapshot.view=pending();screen.tick(snapshot);assert(!renderer.root()&&!channel.management_open());
 int roots=0;for(const auto&entry:ui.objects)if(entry.second.parent==ui.layer)++roots;assert(roots==1);
}
