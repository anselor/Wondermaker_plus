#include "loopback_http.hpp"
#include <iostream>
int main(int argc,char**argv){
 if(argc!=3)return 2;
 wmp_openace::LoopbackHttp http(static_cast<std::uint16_t>(std::stoi(argv[1])),100);
 wmp_openace::UiChannel channel;wmp_openace::ScreenWorker worker(http,channel);worker.poll(100);
 auto s=channel.latest();if(!s)return 3;
 if(std::string(argv[2])=="confirm"&&s->view.confirm_enabled){
  channel.enqueue("OPENACE_CONFIRM_CHANGE TOOL="+std::to_string(s->view.tool)+" CONFIRM=1 EXPECT_CONTEXT="+s->view.context);
  worker.deliver(101);worker.deliver(102);
 }
 s=channel.latest();std::cout<<wmp_openace::json{{"visible",s->view.visible},{"current",s->view.data_current},{"approved",s->view.approved},{"confirm_enabled",s->view.confirm_enabled}}.dump();
}
