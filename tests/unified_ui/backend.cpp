// SPDX-License-Identifier: GPL-3.0-or-later
#include "openace_backend.hpp"
#include <cassert>
#include <fstream>
using namespace wmp_ui;
struct ManagementHttp : wmp_openace::HttpPort {
 Json status;int posts=0;std::string sent;
 std::string get(const std::string&)override{return Json{{"result",{{"status",{{"openace",status}}}}}}.dump();}
 std::string post(const std::string&path,const std::string&body)override{assert(path=="/printer/gcode/script");++posts;sent=Json::parse(body).at("script");return "{\"result\":\"ok\"}";}
};
int main(int argc,char**argv){
 assert(argc==2);std::ifstream input(argv[1]);Json raw;input>>raw;
 wmp_openace::UiChannel channel;OpenAceBackend backend(channel);backend.update(raw,"rev",true);
 Json draft={{"id","external:h0"},{"kind","external"},{"head","h0"},{"identity",{{"brand","Maker Co"},{"material","PLA"},{"color","#334455"}}}};
 Request edit={"save_identity","rev","openace",{{"draft",draft}}};
 auto receipt=backend.submit(edit);assert(receipt.state=="pending");auto q=channel.take();
 assert(q.command.find("OPENACE_SET_FILAMENT HEAD=\"h0\"")!=std::string::npos);
 assert(q.command.find("TEMP=210")!=std::string::npos&&q.command.find("COLOR=334455")!=std::string::npos);assert(q.command.find("VENDOR=\"Maker Co\"")!=std::string::npos);
 assert(backend.submit(edit).state=="refused");channel.settle(q.ticket);
 edit.arguments["draft"]["identity"]["brand"]="Generic";assert(backend.submit(edit).state=="pending");q=channel.take();assert(q.request["fields"]["vendor"]=="Generic");assert(q.command.find("VENDOR=\"Generic\"")!=std::string::npos);channel.settle(q.ticket);edit.arguments["draft"]["identity"]["brand"]="Maker Co";
 edit.arguments["draft"]["identity"]["material"]="ABS";assert(backend.submit(edit).state=="pending");q=channel.take();assert(q.command.find("TEMP=250")!=std::string::npos&&q.command.find("TEMP_MIN=0 TEMP_MAX=0")!=std::string::npos);channel.settle(q.ticket);edit.arguments["draft"]["identity"]["material"]="PLA";
 edit.revision="old";assert(backend.submit(edit).state=="refused");edit.revision="rev";
 edit.arguments["draft"]["head"]="h1";assert(backend.submit(edit).state=="pending");q=channel.take();assert(q.command.find("HEAD=\"h1\"")!=std::string::npos&&q.command.find("TEMP=220")!=std::string::npos);channel.settle(q.ticket);
 // ACE addresses use numeric slot from authoritative normalized source, not display index.
 raw["management"]["units"]["ace1"]=Json::object();raw["management"]["source_settings"]["ace1:0"]=Json::object();raw["management"]["identity_settings"]["ace1:0"]=raw["management"]["identity_settings"]["h0"];
 backend.update(raw,"rev",true);edit.arguments["draft"]={{"id","ace1:0"},{"kind","ace"},{"unit","ace1"},{"slot",0},{"identity",draft["identity"]}};
 receipt=backend.submit(edit);assert(receipt.state=="pending");q=channel.take();assert(q.command.find("UNIT=\"ace1\" SLOT=0")!=std::string::npos);channel.settle(q.ticket);
 // Rename with complete assignment inventory only; omitted or changed assignments refuse.
 raw["default_tool_map"]={{"0",{{"unit","ace1"},{"slot",0},{"head","h0"}}},{"1",{{"unit",nullptr},{"slot",nullptr},{"head","h1"}}}};
 backend.update(raw,"rev",true);Request rename={"save_unit","rev","openace",{{"draft",{{"id","ace1"},{"name","Front ACE"},{"assignments",{{"ace1:0","h0"}}}}}}};
 assert(backend.submit(rename).state=="pending");q=channel.take();assert(q.command=="OPENACE_RENAME_UNIT UNIT=\"ace1\" NAME=\"Front ACE\"");channel.settle(q.ticket);
 rename.arguments["draft"]["assignments"]=Json::object();assert(backend.submit(rename).state=="refused");rename.arguments["draft"]["assignments"]={{"ace1:0","h3"}};assert(backend.submit(rename).state=="refused");
 // Adoption retains the observation context; stale contexts cannot be queued.
 auto context=std::string(64,'a');raw["management"]["capabilities"]["unit_add_expect_context"]=1;raw["management"]["add_candidates"]=Json::array({{{"expect_context",context},{"usb_serial","device-test"}}});backend.update(raw,"rev",true);
 Request adopt={"adopt","rev","openace",{{"logical_name","ace2"},{"context",context}}};assert(backend.submit(adopt).state=="pending");q=channel.take();assert(q.command.find("EXPECT_CONTEXT="+context)!=std::string::npos);channel.settle(q.ticket);
 adopt.arguments["context"]=std::string(64,'b');assert(backend.submit(adopt).state=="refused");backend.update(raw,"rev",false);assert(backend.submit(edit).state=="refused");
 // The unchanged worker must rebuild the extended typed request at delivery.
 wmp_openace::UiChannel delivery_channel;OpenAceBackend delivering(delivery_channel);ManagementHttp http;http.status=raw;
 wmp_openace::ScreenWorker worker(http,delivery_channel);delivering.update(raw,"delivery-rev",true);
 Request brand_edit={"save_identity","delivery-rev","openace",{{"draft",draft}}};brand_edit.arguments["draft"]["identity"]["brand"]="Generic";
 auto sent_receipt=delivering.submit(brand_edit);assert(sent_receipt.state=="pending");worker.poll(1000);worker.deliver(1000);
 assert(http.posts==1);assert(http.sent.find("VENDOR=\"Generic\"")!=std::string::npos);assert(http.sent.find("TEMP=210")!=std::string::npos);
 assert(delivery_channel.latest()->delivery.outcome==wmp_openace::Delivery::Replied);
 // Preserved profile data changing before delivery must prevent a stale write.
 sent_receipt=delivering.submit(brand_edit);assert(sent_receipt.state=="pending");http.status["management"]["identity_settings"]["h0"]["values"]["nozzle_temp"]=215;
 worker.poll(1800);worker.deliver(1800);assert(http.posts==1);assert(delivery_channel.latest()->delivery.outcome==wmp_openace::Delivery::NotSent);
 for(const auto&bad:{std::string("Bad;G28"),std::string("Bad\nG28"),std::string(65,'x')}){brand_edit.arguments["draft"]["identity"]["brand"]=bad;assert(delivering.submit(brand_edit).state=="refused");}

}
