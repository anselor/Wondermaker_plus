#define main renderer_prior_contract
#include "native_renderer.cpp"
#undef main
#include "worker_bridge.hpp"
struct QueuedUi : Fake {
 UiChannel&channel;explicit QueuedUi(UiChannel&c):channel(c){}
 std::uint64_t enqueue(const std::string&c)override{auto ticket=channel.enqueue(c);if(ticket){++commands;command=c;}return ticket;}
};
struct DeliveryHttp : HttpPort {
 json current;int posts=0;std::string mode;std::function<void()>during;
 std::string get(const std::string&)override{return json{{"result",{{"status",{{"openace",current}}}}}}.dump();}
 std::string post(const std::string&,const std::string&)override{++posts;if(during)during();
  if(mode=="unknown")throw std::runtime_error("connection closed before reply");
  return mode=="rejected"?"{\"error\":{\"message\":\"storage failed\"}}":"{\"result\":\"ok\"}";
 }
};
int main(int argc,char**argv){
 assert(argc==2);std::ifstream in(argv[1]);std::ostringstream text;text<<in.rdbuf();auto current=json::parse(text.str());
 for(const auto&mode:{"unknown","rejected","expired","replied","changed"}){
  UiChannel channel;QueuedUi ui(channel);NativeRenderer renderer(ui);DeliveryHttp http;http.current=current;http.mode=mode;ScreenWorker worker(http,channel);
  auto show=[&](){auto value=channel.latest();assert(value);renderer.tick(value->view,value->received_at_ms,value->delivery,value->status_generation);};
  auto click=[&](){ui.event(renderer.confirm(),1);ui.event(renderer.confirm(),7);};
  worker.poll(100);show();ui.event(renderer.badge(),7);show();click();assert(ui.commands==1);
  // Repeated genuine fresh polls do not unlock a queued/in-flight ticket.
  if(http.mode=="changed"){
   std::ifstream other(std::string(argv[1]).substr(0,std::string(argv[1]).find_last_of('/'))+"/family_compact.json");
   std::ostringstream next;next<<other.rdbuf();http.current=json::parse(next.str());
  }
  worker.poll(101);show();click();assert(ui.commands==1&&http.posts==0);
  http.during=[&](){show();click();assert(ui.commands==1);assert(!channel.enqueue(ui.command));};
  bool expired=http.mode=="expired",not_sent=expired||http.mode=="changed";auto settled_at=expired?3100:102;ui.clock=settled_at;
  worker.deliver(settled_at);show();click();assert(ui.commands==1);
  assert(http.posts==(not_sent?0:1));
  const auto snapshot=channel.latest();assert(snapshot->delivery.ticket==1&&snapshot->delivery.outcome!=Delivery::None);
  assert(snapshot->delivery.status_generation==snapshot->status_generation);
  // Only settlement plus a NEW current status makes one deliberate retry possible.
  worker.poll(settled_at+1);ui.clock=settled_at+1;show();assert(ui.commands==1);
  if(http.mode=="replied"){
   click();assert(ui.commands==1&&http.posts==1); // Successful delivery waits for actual backend approval, never auto-approves.
   continue;
  }
  click();assert(ui.commands==2);click();assert(ui.commands==2);
  assert(http.posts==(not_sent?0:1));
  http.during=nullptr;worker.deliver(settled_at+2);assert(http.posts==(not_sent?1:2));
  worker.deliver(settled_at+3);assert(http.posts==(not_sent?1:2));
 }
}
