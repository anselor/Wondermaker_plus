#include "native/stock_identification_flow.hpp"
#include <cassert>
using namespace wmp_ui;using namespace wmp_ui::native;
int main(){
 Json data={{"fresh",true},{"owner","standalone"},{"calibration_session","a"},{"identification",{{"protocol",2},{"state","idle"}}}};
 StockIdentificationFlow browsing;
 for(const auto*state:{"pending","running"}){
  auto external=data;external["identification"]["state"]=state;
  assert(!browsing.blocks_navigation(external));assert(!browsing.can_start(external,true));
 }
 StockIdentificationFlow flow;
 assert(!flow.blocks_navigation(data));
 assert(!flow.start(data,false));assert(flow.start(data,true));assert(!flow.start(data,true));assert(flow.blocks_navigation(data));
 assert(flow.message(data)=="Starting head identification...");
 data["identification"]["state"]="running";assert(!flow.can_restart(data));assert(flow.blocks_navigation(data));
 auto external=data;external["identification"]["request_result"]={{"session","a"},{"request","another-caller"},{"state","pending"}};
 assert(!flow.blocks_navigation(external));assert(!flow.can_start(external,true));
 data["identification"]["state"]="complete";assert(!flow.can_restart(data));
 data["identification"]["restart_required"]=true;assert(!flow.can_restart(data));
 auto request0=flow.command().substr(flow.command().find("REQUEST=")+8);
 data["identification"]["request_result"]={{"session","a"},{"request",request0},{"state","pending"}};
 assert(!flow.can_restart(data));data["identification"]["request_result"]["state"]="complete";
 assert(flow.can_restart(data));
 data["fresh"]=false;assert(!flow.restart(data));assert(flow.message(data)=="Waiting for printer status...");
 data["fresh"]=true;assert(flow.restart(data));assert(!flow.restart(data));
 data["calibration_session"]="b";data["identification"]["state"]="idle";flow.observe(data);assert(flow.can_start(data,true));assert(!flow.blocks_navigation(data));
 assert(flow.start(data,true));data["calibration_session"]="c";flow.observe(data);assert(flow.can_start(data,true));assert(!flow.blocks_navigation(data));assert(flow.message(data).find("restarted before")!=std::string::npos);
 StockIdentificationFlow missing;data["identification"].erase("protocol");assert(!missing.start(data,true));
 data["identification"]["protocol"]=2;data["owner"]="openace";assert(!missing.start(data,true));
 data["owner"]="standalone";assert(missing.start(data,true));missing.send_failed();assert(missing.can_start(data,true));assert(!missing.blocks_navigation(data));
 data["identification"]["state"]="complete";assert(!missing.can_restart(data));
 // A new touchscreen can inspect a completed backend operation and restart it.
 StockIdentificationFlow reopened;assert(reopened.restart(data));data["calibration_session"]="d";data["identification"]["state"]="idle";reopened.observe(data);assert(reopened.can_start(data,true));
 // Only the matching backend receipt settles a preflight refusal.
 data["calibration_session"]="e";data["identification"]={{"protocol",2},{"state","idle"}};
 StockIdentificationFlow refused;assert(refused.start(data,true));
 const auto command=refused.command();const auto request=command.substr(command.find("REQUEST=")+8);
 assert(request.size()==32);
 data["identification"]["request_result"]={{"session","e"},{"request",std::string(32,'0')},{"state","refused"},{"error","Resolve probe editor"}};
 refused.observe(data);assert(refused.blocks_navigation(data));
 data["identification"]["request_result"]["request"]=request;
 data["fresh"]=false;refused.observe(data);assert(refused.blocks_navigation(data));
 data["fresh"]=true;refused.observe(data);assert(!refused.blocks_navigation(data));
 assert(refused.message(data)=="Resolve probe editor");assert(refused.can_start(data,true));
 assert(refused.start(data,true));assert(refused.command()!=command);
 refused.observe(data);assert(refused.blocks_navigation(data)); // Old receipt cannot settle new request.
}
