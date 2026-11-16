#include "management_panel.hpp"
#include <cassert>
#include <fstream>
#include <sstream>
using namespace wmp_openace;
int main(int argc,char**argv){assert(argc==2);std::ifstream f(argv[1]);std::ostringstream text;text<<f.rdbuf();auto status=std::make_shared<const json>(json::parse(text.str()));
 ManagementPanelModel model;model.open();model.update(status,true,1,Delivery());
 int commands=0;std::string sent;auto queue=[&](const json&,const std::string&command,std::int64_t){++commands;sent=command;return std::uint64_t(commands);};
 auto press=[&](const std::string&id){return model.press(id,model.view().serial,queue);};
 assert(press("heads"));assert(model.view().title.find("h0")!=std::string::npos);assert(commands==0);
 assert(press("edit"));assert(press("erase"));assert(press("key:1"));assert(press("key_next"));assert(commands==0);
 assert(press("review"));assert(model.view().title.find("Review")!=std::string::npos);assert(commands==0);
 assert(press("apply"));assert(commands==1&&sent.find("OPENACE_HEAD_SET")==0);
 assert(!press("apply"));assert(commands==1);
 model.update(status,true,2,Delivery());assert(!press("apply")&&commands==1);
 Delivery done;done.ticket=1;done.status_generation=2;done.outcome=Delivery::Unknown;
 model.update(status,true,2,done);assert(!press("apply")&&commands==1);
 model.update(status,true,3,done);assert(press("apply")&&commands==2);
 auto stale=model.view().serial;press("back");assert(!model.press("devices",stale,queue));
 assert(press("tools"));assert(press("map"));assert(commands==2);assert(!press("apply"));
 done.ticket=2;done.status_generation=4;model.update(status,true,4,done);assert(!press("apply"));
 model.update(status,true,5,done);assert(press("apply"));assert(commands==3);
 // Untrusted names remain visibly escaped; command data is never silently stripped.
 json dirty=*status;dirty["management"]["identity_settings"]["h0"]={
  {"values",{{"material","PLA"},{"nozzle_temp",210},{"color","#112233"}}},
  {"display_name","spool\rmisleading"}};
 model.close();model.open();model.update(std::make_shared<const json>(dirty),true,6,Delivery());
 assert(press("filament"));assert(model.view().detail.find("\\r")!=std::string::npos);
 // A partial draft never crosses a printer session boundary.
 assert(press("edit"));assert(press("key:P" )==false); // No arbitrary button IDs.
 assert(press("review"));assert(model.view().detail.find("not saved")!=std::string::npos);
 dirty["session_id"]=dirty["session_id"].get<std::int64_t>()+1;
 model.update(std::make_shared<const json>(dirty),true,7,Delivery());
 assert(press("filament"));assert(model.view().detail.find("not saved")==std::string::npos);
}
