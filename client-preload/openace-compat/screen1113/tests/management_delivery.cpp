#include "worker_bridge.hpp"
#include "management_commands.hpp"
#include <fstream>
#include <sstream>
#include <cassert>
using namespace wmp_openace;
struct ManagementHttp : HttpPort {
 json status;std::string query,command;int posts=0;bool fail=false;std::function<void()>during;
 std::string get(const std::string&p)override{query=p;return json{{"result",{{"status",{{"openace",status}}}}}}.dump();}
 std::string post(const std::string&,const std::string&body)override{++posts;command=json::parse(body).at("script");if(during)during();if(fail)throw std::runtime_error("unknown HTTP outcome");return "{\"result\":\"ok\"}";}
};
int main(int argc,char**argv){assert(argc==2);std::ifstream in(argv[1]);std::ostringstream s;s<<in.rdbuf();ManagementHttp http;http.status=json::parse(s.str());
 UiChannel channel;ScreenWorker worker(http,channel);worker.poll(100);assert(http.query==ScreenWorker::query());assert(!channel.latest()->management);
 channel.set_management_open(true);worker.poll(101);assert(http.query==ScreenWorker::management_query()&&channel.latest()->management);
 json request{{"action","head_set"},{"head","h0"},{"fields",{{"capture_mm","18"}}}};
 auto expected=management_command(http.status,request);auto session=http.status.at("session_id").get<std::int64_t>();
 auto ticket=channel.enqueue_management(request,expected,session);assert(ticket);
 http.during=[&](){assert(!channel.enqueue_management(request,expected,session));};http.fail=true;worker.deliver(102);
 assert(http.posts==1&&http.command==expected);assert(channel.latest()->delivery.ticket==ticket&&channel.latest()->delivery.outcome==Delivery::Unknown);
 worker.deliver(103);assert(http.posts==1);worker.poll(104);assert(channel.latest()->status_generation>channel.latest()->delivery.status_generation);
 assert(channel.enqueue_management(request,expected,session));http.fail=false;worker.deliver(105);assert(http.posts==2);
 // Closing the page disowns a queued unsent settings action.
 assert(channel.enqueue_management(request,expected,session));channel.set_management_open(false);worker.deliver(106);assert(http.posts==2&&channel.latest()->delivery.outcome==Delivery::NotSent);
 // No alternate command or physical action can pass the fixed worker builder.
 channel.set_management_open(true);worker.poll(107);assert(channel.enqueue_management(request,"OPENACE_LOAD_DIRECT HEAD=h0",session));worker.deliver(108);assert(http.posts==2);
 assert(!channel.enqueue_management(json{{"action","load_direct"}},"OPENACE_LOAD_DIRECT HEAD=h0",session));
 assert(channel.enqueue_management(request,expected,session+1));worker.deliver(109);assert(http.posts==2);
}
