#define main renderer_prior_contract
#include "native_renderer.cpp"
#undef main
#include "native_management.hpp"
#include <iostream>
struct ActualStatusHttp : HttpPort {
 json status;std::vector<std::string>commands;
 std::string get(const std::string&)override{return json{{"result",{{"status",{{"openace",status}}}}}}.dump();}
 std::string post(const std::string&,const std::string&body)override{commands.push_back(json::parse(body).at("script"));return "{\"result\":\"ok\"}";}
};
int main(int argc,char**argv){
 assert(argc>=4);std::ifstream in(argv[1]);std::ostringstream text;text<<in.rdbuf();
 ActualStatusHttp http;http.status=json::parse(text.str());UiChannel channel;ScreenWorker worker(http,channel);Fake ui;NativeScreen screen(ui,channel);
 auto show=[&](){screen.tick(*channel.latest());};auto&renderer=screen.management();
 auto available=[&](const std::string&id){for(const auto&button:renderer.panel().buttons)if(button.first==id)return true;return false;};
 auto click=[&](const std::string&id){for(std::size_t i=0;i<renderer.panel().buttons.size();++i)if(renderer.panel().buttons[i].first==id){ui.event(renderer.button(i),1);ui.event(renderer.button(i),7);show();return;}std::cerr<<"Missing button "<<id<<" on "<<renderer.panel().detail;std::abort();};
 auto enter=[&](const std::string&value){
  click("edit");for(int n=0;n<256;++n)click("erase");
  for(char c:value){std::string key="key:"+std::string(1,c);for(int n=0;!available(key)&&n<100;++n)click("key_next");assert(available(key));click(key);}
  click("review");assert(http.commands.empty());
 };
 worker.poll(100);show();assert(renderer.badge());ui.event(renderer.badge(),7);worker.poll(100);show();
 std::string action=argv[2];int index=std::atoi(argv[3]);
 if(action=="map_tool"){
  click("tools");for(int i=0;i<index;++i){click("next");click("head_cycle");}click("map");
 }else if(action=="set_filament"){
  assert(argc==7);click("filament");for(int i=0;i<index;++i)click("next");
  enter(argv[4]);click("field");enter(argv[5]);click("field");enter(argv[6]);click("assignment_review");
 }else if(action=="head_set"){
  assert(argc==5);click("heads");for(int i=0;i<index;++i)click("next");enter(argv[4]);
 }else return 2;
 assert(http.commands.empty());click("apply");assert(http.commands.empty());worker.deliver(101);assert(http.commands.size()==1);
 std::cout<<http.commands[0];return 0;
}
