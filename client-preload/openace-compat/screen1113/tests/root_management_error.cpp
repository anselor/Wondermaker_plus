#include "worker_bridge.hpp"
#include <fstream>
#include <sstream>
#include <iostream>
using namespace wmp_openace;
struct Port:HttpPort{json status;int posts=0;
 std::string get(const std::string&)override{return json{{"result",{{"status",{{"openace",status}}}}}}.dump();}
 std::string post(const std::string&,const std::string&)override{++posts;return json{{"error",{{"code",400},{"message","head h0 is busy: qualification trial"}}}}.dump();}
};
int main(int argc,char**argv){if(argc!=2)return 2;Port p;std::ifstream f(argv[1]);f>>p.status;UiChannel c;ScreenWorker w(p,c);c.set_management_open(true);w.poll(10);json r={{"action","head_set"},{"head","h0"},{"fields",{{"capture_mm","18"}}}};auto cmd=management_command(p.status,r);if(!c.enqueue_management(r,cmd,p.status["session_id"].get<std::int64_t>()))return 3;w.deliver(11);std::cout<<c.latest()->delivery_message<<"\n";return p.posts==1&&c.latest()->delivery_message.find("qualification trial")!=std::string::npos?0:9;}
