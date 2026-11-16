#define main old_renderer_control
#include "native_renderer.cpp"
#undef main
#include "native_management.hpp"
#include "loopback_http.hpp"
struct Errors:HttpPort{
 json status,reply;int posts=0;
 std::string get(const std::string&)override{return json{{"result",{{"status",{{"openace",status}}}}}}.dump();}
 std::string post(const std::string&,const std::string&)override{++posts;return reply.dump();}
};
void queue_head(UiChannel&channel,const json&status){json r={{"action","head_set"},{"head","h0"},{"fields",{{"capture_mm","18"}}}};assert(channel.enqueue_management(r,management_command(status,r),status["session_id"].get<std::int64_t>()));}
int main(int argc,char**argv){
 assert(argc>=2);
 if(std::string(argv[1])=="http"){
  assert(argc==3);LoopbackHttp http(std::uint16_t(std::stoi(argv[2])));UiChannel channel;ScreenWorker worker(http,channel);channel.set_management_open(true);worker.poll(100);assert(channel.latest()->management);queue_head(channel,*channel.latest()->management);worker.deliver(101);
  assert(channel.latest()->delivery.outcome==Delivery::Unknown);std::cout<<channel.latest()->delivery_message;return 0;
 }
 std::ifstream file(argv[1]);json data;file>>data;
 for(const json&message:std::vector<json>{"head h0 is busy: qualification trial",std::string(600,'x'),"name\nG1 X100\r\x01",false,nullptr}){
  Errors http;http.status=data;http.reply={{"error",{{"message",message}}}};UiChannel channel;ScreenWorker worker(http,channel);Fake ui;NativeScreen screen(ui,channel);
  auto show=[&](){screen.tick(*channel.latest());};auto&renderer=screen.management();
  auto click=[&](const std::string&id){for(std::size_t i=0;i<renderer.panel().buttons.size();++i)if(renderer.panel().buttons[i].first==id){ui.event(renderer.button(i),1);ui.event(renderer.button(i),7);show();return;}std::cerr<<"Missing "<<id<<" on "<<renderer.panel().detail<<"\n";assert(false);};
  worker.poll(100);show();ui.event(renderer.badge(),7);ui.clock=101;worker.poll(101);show();click("heads");click("edit");click("review");click("apply");ui.clock=102;worker.deliver(102);show();
  assert(http.posts==1&&channel.latest()->delivery.outcome==Delivery::Unknown);
  const auto reason=channel.latest()->delivery_message;assert(!reason.empty()&&reason.size()<=400);
  for(unsigned char c:reason)assert(c>=32&&c!=127);
  assert(renderer.panel().detail.find(reason)==std::string::npos); // Still awaiting refreshed status.
  if(message.is_string()&&message.get<std::string>().find("qualification")!=std::string::npos)assert(reason.find("qualification trial")!=std::string::npos);
  if(message.is_string()&&message.get<std::string>().size()>256)assert(reason.find("...")!=std::string::npos);
  if(!message.is_string())assert(reason.find("Command reported an error")!=std::string::npos);
  // Settlement alone is not refreshed status; the actual native label shows the
  // exact matching reason only after the next current status generation.
  ui.clock=103;worker.poll(103);show();bool visible_reason=false;
  for(const auto&o:ui.objects)if(!o.second.hidden&&o.second.text.find(reason)!=std::string::npos)visible_reason=true;
  assert(visible_reason);worker.deliver(104);assert(http.posts==1);
 }
}
