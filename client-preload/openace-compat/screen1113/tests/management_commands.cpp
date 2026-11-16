#include "management_commands.hpp"
#include <cassert>
#include <fstream>
#include <sstream>
#include <iostream>
using namespace wmp_openace;
json load(const std::string&p){std::ifstream f(p);assert(f);std::ostringstream s;s<<f.rdbuf();return json::parse(s.str());}
int main(int argc,char**argv){
 if(argc==4&&std::string(argv[1])=="--command"){
  try{std::cout<<management_command(load(argv[2]),load(argv[3]));return 0;}
  catch(const std::exception&e){std::cerr<<e.what();return 2;}
 }
 assert(argc==2);std::string root=argv[1];auto actual=load(root+"/management_available1078.json");
 auto ctx=actual["management"]["add_candidates"][0]["expect_context"];
 auto command=management_command(actual,json{{"action","unit_add"},{"unit","ace0"},{"context",ctx}});
 assert(command.find("OPENACE_UNIT_ADD UNIT=\"ace0\" USB_SERIAL=\"INVENTORY\"")==0);
 assert(command.find("EXPECT_CONTEXT="+ctx.get<std::string>())!=std::string::npos);
 for(auto key:{"version","unit_add_expect_context"}){
  auto malformed=actual;malformed["management"]["capabilities"][key]=true;
  bool refused=false;try{management_command(malformed,json{{"action","unit_add"},{"unit","ace0"},{"context",ctx}});}catch(...){refused=true;}assert(refused);
 }
 auto zero=load(root+"/management_zero1078.json");
 assert(management_command(zero,json{{"action","map_tool"},{"tool",3},{"head","h3"}})=="OPENACE_MAP_TOOL TOOL=3 HEAD=\"h3\"");
 assert(management_command(zero,json{{"action","head_set"},{"head","h0"},{"fields",{{"capture_mm","110"},{"capture_step_mm","10"}}}})=="OPENACE_HEAD_SET HEAD=\"h0\" CAPTURE_MM=110 CAPTURE_STEP_MM=10");
 auto registered=load(root+"/management_registered1078.json");
 auto source=management_command(registered,json{{"action","source_set"},{"unit","ace0"},{"slot",0},{"fields",{{"feeder_hold_mm","10"},{"feeder_to_inlet_mm","80"}}}});
 assert(source=="OPENACE_SOURCE_SET UNIT=\"ace0\" SLOT=0 FEEDER_HOLD_MM=10 FEEDER_TO_INLET_MM=80");
 for(auto text:{"bad\nRESUME","bad#suffix","bad;suffix","bad*suffix","bad\\suffix","bad\"suffix"}){
  bool rejected=false;try{(void)safe_gcode_literal(text);}catch(...){rejected=true;}assert(rejected);
 }
 assert(safe_gcode_literal("Maker Co O'Reilly")=="\"Maker Co O'Reilly\"");
 auto initial=management_command(zero,json{{"action","set_filament"},{"head","h0"},{"fields",{{"material","PLA"},{"nozzle_temp",210},{"color","112233"}}}});
 assert(initial.find("OPENACE_SET_FILAMENT HEAD=\"h0\" MATERIAL=\"PLA\" TEMP=210 COLOR=112233")==0);
 auto known=load(root+"/management_manual_config1078.json");
 bool blocked=false;try{management_command(known,json{{"action","set_filament"},{"head","h0"},{"fields",{{"material","PLA"},{"nozzle_temp",210},{"color","112233"}}}});}catch(...){blocked=true;}assert(blocked); // Existing raw name unavailable: do not resend display_name.
}
