#include "worker_bridge.hpp"
#include <cassert>
#include <fstream>
#include <sstream>
using namespace wmp_openace;
struct Http : HttpPort {
 json current;int gets=0,posts=0;bool failed=false,uncertain=false;std::string sent;
 std::string get(const std::string&p)override{assert(p==ScreenWorker::query());++gets;if(failed)throw 3;return json{{"result",{{"status",current}}}}.dump();}
 std::string post(const std::string&p,const std::string&b)override{assert(p=="/printer/gcode/script");++posts;sent=json::parse(b)["script"];if(uncertain)throw 4;return "{\"result\":\"ok\"}";}
};
std::string read(const std::string&p){std::ifstream in(p);assert(in);std::ostringstream s;s<<in.rdbuf();return s.str();}
std::string click(UiChannel&c){auto s=c.latest();assert(s&&s->view.confirm_enabled);return "OPENACE_CONFIRM_CHANGE TOOL="+std::to_string(s->view.tool)+" CONFIRM=1 EXPECT_CONTEXT="+s->view.context;}
int main(int argc,char**argv){assert(argc==2);Http http;UiChannel channel;ScreenWorker worker(http,channel);
 auto before=json::parse(read(std::string(argv[1])+"/pending_compact.json"));
 auto changed=json::parse(read(std::string(argv[1])+"/family_compact.json"));
 // Sharing a fresh response never performs another HTTP GET; disconnect clears
 // actionable state, and a queued old confirmation cannot cross ownership loss.
 {
  Http shared_http;UiChannel shared_channel;ScreenWorker shared(shared_http,shared_channel);
  shared_channel.set_management_open(true);
  shared.observe_status(json{{"openace",before}},90);
  assert(shared_http.gets==0&&shared_channel.latest()->management);
  auto command=click(shared_channel);assert(shared_channel.enqueue(command));
  shared.disconnected();assert(!shared_channel.latest()->view.data_current);
  assert(!shared_channel.latest()->management&&!shared_channel.latest()->manual_status);
  shared.deliver(91);assert(shared_http.posts==0);
  shared.observe_status(json{{"openace",before}},92);assert(shared_channel.latest()->view.data_current);
  assert(shared_channel.enqueue(click(shared_channel)));
  shared.observe_status(json::object(),93);shared.deliver(94);
  assert(shared_http.gets==0&&shared_http.posts==0&&!shared_channel.latest()->view.visible);
 }
 http.current={{"openace",before}};worker.poll(100);auto old=click(channel);
 for(int i=0;i<10;++i)worker.poll(100+i);
 assert(http.posts==0);
 assert(!channel.enqueue("RESUME")&&!channel.enqueue(old+"\nRESUME"));
 assert(channel.enqueue(old)&&!channel.enqueue(old));
 http.current={{"openace",changed}};worker.poll(111);worker.deliver(112);assert(http.posts==0);
 auto current=click(channel);assert(current!=old&&channel.enqueue(current));worker.deliver(113);
 assert(http.posts==1&&http.sent==current&&!channel.latest()->view.confirm_enabled&&!channel.latest()->view.approved);
 worker.deliver(114);assert(http.posts==1);
 http.current={{"openace",json::parse(read(std::string(argv[1])+"/approved_compact.json"))}};worker.poll(115);assert(channel.latest()->view.approved);
 http.current=json::object();worker.poll(116);assert(!channel.latest()->view.visible);
 http.current={{"openace",before}};worker.poll(120);auto queued=click(channel);assert(channel.enqueue(queued));
 http.failed=true;worker.poll(121);worker.deliver(122);assert(http.posts==1&&!channel.latest()->view.data_current);
 http.failed=false;worker.poll(130);queued=click(channel);assert(channel.enqueue(queued));http.uncertain=true;
 worker.deliver(131);assert(http.posts==2&&!channel.latest()->view.approved&&!channel.latest()->view.confirm_enabled);
 worker.deliver(132);assert(http.posts==2); // Never automatic replay after unknown delivery.
}
