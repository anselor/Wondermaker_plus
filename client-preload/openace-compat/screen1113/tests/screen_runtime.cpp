#define main renderer_prior_contract
#include "native_renderer.cpp"
#undef main
#include "screen_runtime.hpp"
#include <thread>
struct WorkerHttp : HttpPort {
 json status;std::thread::id gui;int calls=0;
 std::string get(const std::string&)override{assert(std::this_thread::get_id()!=gui);++calls;return json{{"result",{{"status",{{"openace",status}}}}}}.dump();}
 std::string post(const std::string&,const std::string&)override{assert(std::this_thread::get_id()!=gui);++calls;return "{\"result\":\"ok\"}";}
};
int main(int argc,char**argv){
 assert(argc==2);std::ifstream in(argv[1]);std::ostringstream text;text<<in.rdbuf();
 // Exercise real worker -> model -> channel -> native renderer with the captured idle response.
 const std::string fixture=argv[1];
 std::ifstream idle_file(fixture.substr(0,fixture.find_last_of('/'))+"/moonraker_idle_filtered.json");
 assert(idle_file);std::ostringstream idle_text;idle_text<<idle_file.rdbuf();
 WorkerHttp idle_http;idle_http.status=json::parse(idle_text.str());idle_http.gui=std::this_thread::get_id();
 UiChannel idle_channel;Fake idle_ui;ScreenRuntime idle_runtime(idle_http,idle_ui,idle_channel);
 std::thread idle_worker([&](){idle_runtime.worker_step(100);});idle_worker.join();
 idle_runtime.gui_step();bool setup_visible=false;
 for(const auto&item:idle_ui.objects)if(!item.second.hidden&&item.second.text=="openACE setup")setup_visible=true;
 assert(setup_visible && idle_http.calls==1 && idle_ui.commands==0 && idle_channel.take().ticket==0);
 WorkerHttp http;http.status=json::parse(text.str());http.gui=std::this_thread::get_id();
 UiChannel channel;Fake ui;ScreenRuntime runtime(http,ui,channel);
 runtime.gui_step();assert(http.calls==0&&ui.created==0);
 std::thread worker([&](){runtime.worker_step(100);});worker.join();assert(http.calls==1&&ui.created==0);
 runtime.gui_step();assert(ui.created==2&&http.calls==1);
 // Invalid current main/Stop context removes even the collapsed badge.
 ui.layout=false;runtime.gui_step();assert(ui.objects.begin()->second.hidden&&http.calls==1);
}
