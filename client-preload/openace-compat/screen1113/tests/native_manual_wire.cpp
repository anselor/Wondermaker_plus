#define main original_native_renderer_test
#include "native_renderer.cpp"
#undef main
#include "native_management.hpp"
struct Wire:HttpPort{
 json exchange(const json&request){std::cout<<request.dump()<<std::endl;std::string line;if(!std::getline(std::cin,line))throw std::runtime_error("test wire closed");auto reply=json::parse(line);if(reply.contains("throw"))throw std::runtime_error("test response lost");return reply;}
 std::string get(const std::string&path)override{return exchange(json{{"get",path}}).dump();}
 std::string post(const std::string&path,const std::string&body)override{return exchange(json{{"post",json::parse(body)},{"path",path}}).dump();}
};
int main(int argc,char**argv){
 assert(argc==2);std::string mode=argv[1];Wire http;UiChannel channel;ScreenWorker worker(http,channel);Fake ui;NativeScreen screen(ui,channel);int now=100;
 auto show=[&](){ui.clock=now;screen.tick(*channel.latest());};
 auto poll=[&](){worker.poll(now);show();};
 auto has=[&](const std::string&id){for(const auto&b:screen.manual_view().buttons)if(b.first==id)return true;return false;};
 auto press=[&](const std::string&id){const auto buttons=screen.manual_view().buttons;for(std::size_t i=0;i<buttons.size();++i)if(buttons[i].first==id){auto object=screen.material().manual_button(i);ui.event(object,1);ui.event(object,7);show();return;}std::cerr<<"Missing "<<id<<" in "<<screen.manual_view().detail<<"\n";std::abort();};
 auto act=[&](const std::string&id){press(id);press("apply");worker.deliver(++now);show();++now;poll();};
 poll();
 if(mode=="no_manual"){assert(!screen.manual_view().visible);(void)http.exchange(json{{"finished",true}});return 0;}
 assert(screen.manual_view().visible&&screen.material().badge());assert(!screen.management().root());
 ui.event(screen.material().badge(),7);show();
 if(mode=="restart_hold"){assert(!has("prepare")&&!has("done"));for(int i=0;i<3;++i){++now;poll();worker.deliver(now);}(void)http.exchange(json{{"finished",true}});return 0;}
 assert(has("prepare"));act("prepare");
 if(mode=="unknown_prepare"){
  assert(!has("done")&&has("prepare")); // New explicit request is reachable, never an automatic retry.
  (void)http.exchange(json{{"check_no_auto",true}});poll();act("prepare");
 }
 if(mode=="cancel_before_post"||mode=="source_edit_before_post"){
  if(mode=="cancel_before_post")assert(!screen.manual_view().visible);else assert(!has("done"));(void)http.exchange(json{{"finished",true}});return 0;
 }
 if(has("plan"))act("plan");
 (void)http.exchange(json{{"insert",true}});++now;poll();
 assert(has("done"));act("done");
 if(mode=="partial"){
  assert(has("done"));act("done");
 }
 if(mode=="unknown_suffix"||mode=="save_failed"){
  assert(!has("done"));for(int i=0;i<3;++i){++now;poll();worker.deliver(now);}assert(!has("done"));
 }else assert(!has("done"));
 if(mode=="colour"){
  assert(channel.latest()->view.confirm_enabled);
  auto colour=screen.material().manual_button(screen.manual_view().buttons.size());ui.event(colour,1);ui.event(colour,7);
  worker.deliver(++now);++now;poll();assert(!channel.latest()->view.pending_confirmation);
 }
 (void)http.exchange(json{{"finished",true}});return 0;
}
