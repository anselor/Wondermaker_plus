#include "openace_view.hpp"
#include <cassert>
#include <fstream>
#include <iostream>
#include <sstream>
using namespace wmp_openace;
std::string read(const std::string& path) {std::ifstream in(path);assert(in);std::ostringstream out;out<<in.rdbuf();return out.str();}
int main(int argc,char**argv) {
 if(argc==3 && std::string(argv[1])=="--click") {
  ScreenModel m;if(!m.update(read(argv[2]),true,1000))return 2;
  if(!m.click_confirm(m.view().serial,1000,[](const std::string&cmd){std::cout<<cmd;return true;}))return 3;
  return 0;
 }
 assert(argc==2);const std::string root=argv[1];
 const auto load=[&](const char*name){return read(root+"/"+name+".json");};
 // Exact top-level Moonraker selective fields, not a raw diagnostic poll.
 const auto full=json::parse(load("pending_compact"));
 json selected=json::object();
 for(const auto& key:{"session_id","material_change_prompt","loaded"})
  if(full.contains(key))selected[key]=full[key];
 ScreenModel projected;
 assert(projected.update(selected.dump(),true,1) && projected.view().confirm_enabled);
 // Unrelated retained diagnostic data cannot affect selective-query response size.
 auto diagnostics=full;diagnostics["qualification"]=std::string(1024*1024,'x');
 json selected_large=json::object();
 for(const auto& key:{"session_id","material_change_prompt","loaded"})
  if(diagnostics.contains(key))selected_large[key]=diagnostics[key];
 assert(selected_large==selected && selected_large.dump().size()<256*1024);
 // Real field-filtered Moonraker status retains a missing optional field as null.
 const auto idle=json::parse(load("moonraker_idle_filtered"));
 assert(idle.contains("material_change_prompt") && idle["material_change_prompt"].is_null());
 ScreenModel fresh_idle;
 assert(fresh_idle.update(idle.dump(),true,100));
 assert(fresh_idle.view().connected && fresh_idle.view().data_current);
 assert(fresh_idle.view().session==idle["session_id"].get<std::int64_t>());
 assert(!fresh_idle.view().visible && !fresh_idle.view().confirm_enabled);
 ScreenModel changed_to_idle;int null_commands=0;
 assert(changed_to_idle.update(load("pending_compact"),true,100));
 const auto pending_serial=changed_to_idle.view().serial;
 assert(changed_to_idle.update(idle.dump(),true,101));
 assert(!changed_to_idle.click_confirm(pending_serial,102,[&](const std::string&){++null_commands;return true;}));
 assert(null_commands==0 && !changed_to_idle.view().approved);
 for(const auto&invalid:std::vector<json>{false,12,"invalid",json::array(),json::object()}){
  auto bad_idle=idle;bad_idle["material_change_prompt"]=invalid;
  assert(!fresh_idle.update(bad_idle.dump(),true,102));
  assert(!fresh_idle.view().confirm_enabled);
 }
 auto invalid_session=idle;invalid_session["session_id"]=false;
 assert(!fresh_idle.update(invalid_session.dump(),true,103));
 ScreenModel m;int commands=0;std::string command;
 const auto port=[&](const std::string& x){++commands;command=x;return true;};
 assert(m.update(load("declared_change1049"),true,100));
 assert(m.view().visible && m.view().message.find("Gray")!=std::string::npos);
 assert(m.view().from_label.find("#112233")!=std::string::npos);
 assert(m.view().to_label=="Gray [PLA+ #445566]");
 assert(!m.view().confirm_enabled && commands==0);
 assert(m.update(load("bare_m6001049"),true,100));
 assert(m.view().to_label=="not declared by slicer");
 assert(m.update(load("record_unsaved1049"),true,100));
 assert(!m.view().confirm_enabled && m.view().error.find("not saved")!=std::string::npos);
 assert(m.update(load("pending_colour1049"),true,100));
 assert(!m.view().confirm_enabled && !m.view().error.empty());
 assert(!m.click_confirm(m.view().serial,101,port)); // Unknown parameter ignored by old backend: never send.
 assert(commands==0);
 assert(m.update(load("pending_colour1050"),true,101));
 assert(m.view().visible && !m.view().confirm_enabled); // Even old EXPECT_CONTEXT support needs compact capability.
 const auto old=load("pending_compact"), changed=load("family_compact");
 assert(m.update(load("declared_pending_compact"),true,900));
 assert(m.view().to_label=="Gray [PLA+ #445566]");
 assert(m.view().replacement_label.find("#778899")!=std::string::npos);
 assert(m.update(old,true,1000));assert(m.view().confirm_enabled);
 assert(m.view().expected_label=="PLA #112233");
 assert(m.view().replacement_label.find("#445566")!=std::string::npos);
 const auto serial=m.view().serial;
 for(int i=0;i<10;++i)assert(m.update(old,true,1000+i));
 assert(commands==0 && m.view().serial==serial); // Polling is not approval or new display intent.
 assert(m.click_confirm(serial,1100,port));
 assert(commands==1 && command.find("EXPECT_CONTEXT=")!=std::string::npos);
 assert(!m.click_confirm(serial,1101,port));assert(commands==1);
 assert(m.update(old,true,1102) && !m.view().confirm_enabled); // In-flight request is not approval.
 assert(m.update(load("approved_compact"),true,1103));
 assert(m.view().approved && !m.view().confirm_enabled && m.view().visible);
 assert(m.update(load("completed_compact"),true,1104) && !m.view().visible);
 assert(m.update(old,true,2000));const auto stale=m.view().serial;
 assert(m.update(changed,true,2001) && m.view().serial!=stale);
 assert(!m.click_confirm(stale,2002,port) && commands==1);
 auto visible=m.view().serial;m.disconnected();assert(m.view().visible && !m.view().confirm_enabled);
 assert(!m.click_confirm(visible,2003,port));
 assert(m.update(changed,true,2004));assert(!m.click_confirm(visible,2005,port));
 assert(!m.click_confirm(m.view().serial,5000,port)); // Expired last status.
 assert(!m.update("{broken",true,5000));assert(!m.view().confirm_enabled);
 assert(!m.update(std::string(262145,'x'),true,5000));
 assert(!m.update(std::string(33,'[')+"0"+std::string(33,']'),true,5000));
 auto unsupported=json::parse(old);unsupported["material_change_prompt"]["confirmation"]["version"]=2;
 assert(m.update(unsupported.dump(),true,5000) && m.view().visible && !m.view().confirm_enabled);
 auto bad=json::parse(old);bad["material_change_prompt"]["tool"]=true;
 assert(!m.update(bad.dump(),true,5000));
 bad=json::parse(old);bad["material_change_prompt"]["confirmation"]["context"]="00\nRESUME";
 assert(m.update(bad.dump(),true,5000) && !m.view().confirm_enabled);
 assert(!m.click_confirm(m.view().serial,5001,port));
 bad=json::parse(old);bad["material_change_prompt"]["actual_from"]["name"]=std::string("x\0y",3);
 assert(!m.update(bad.dump(),true,5000));
 assert(m.update(old,true,6000));assert(!m.click_confirm(m.view().serial,6001,[](const std::string&)->bool{throw std::runtime_error("queue full");}));
 assert(commands==1);
 assert(m.update(old,true,7000));const auto prior_session=m.view().serial;
 bad=json::parse(old);bad["session_id"]=bad["session_id"].get<int>()+1;
 assert(m.update(bad.dump(),true,7001) && m.view().serial!=prior_session);
 assert(!m.click_confirm(prior_session,7002,port));
 bad=json::parse(old);bad["material_change_prompt"]["actual_from"]["name"]="name\nmisleading label";
 assert(!m.update(bad.dump(),true,7003));
 assert(m.update("",false,6002) && !m.view().visible && !m.view().confirm_enabled);
 std::cout<<"view contract controls passed; commands issued only on one explicit click\n";
}
