#include "manual_flow.hpp"
#include <fstream>
#include <iostream>
using namespace wmp_openace;
int main(int argc,char**argv){if(argc!=2)return 90;std::ifstream in(argv[1]);json old;in>>old;ManualFlowModel m;m.update(old,true,1,Delivery(),"");
if(!m.press("prepare",m.view().serial,[](const std::string&,const std::string&,std::int64_t){return 11;}))return 91;
if(!m.press("apply",m.view().serial,[](const std::string&,const std::string&,std::int64_t){return 11;}))return 92;
auto now=old;now["manual_flow"]["head"]="h1";now["manual_flow"]["source"]="h1";now["manual_flow"]["tool"]=1;now["manual_flow"]["context"]=std::string(64,'a');now["manual_flow"]["change_id"]="new-unprepared-material-context";
Delivery d;d.ticket=11;d.status_generation=1;d.outcome=Delivery::Replied;m.update(now,true,2,d,"");
std::cout<<m.view().title<<"\n"<<m.view().detail<<"\n";for(const auto&button:m.view().buttons){std::cout<<button.first<<"\n";if(button.first=="done")return 9;}return 0;}
