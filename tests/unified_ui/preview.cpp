// SPDX-License-Identifier: GPL-3.0-or-later
#include "native/preview.hpp"
#include "native/file_tools.hpp"
#include <fstream>
#include "native/loopback_http.hpp"
#include "screens.hpp"
#include "print_request.hpp"
#include <cassert>
using namespace wmp_ui;
int main(){
 // Absent Moonraker metadata: inspect actual commands with bounded storage.
 {
  char path[]="/tmp/wmp-preview-tools-XXXXXX";assert(::mkdtemp(path));const std::string root=path,file="scan #1;*.gcode",full=root+"/"+file;
  auto write=[&](const std::string&text){std::ofstream out(full,std::ios::binary);out<<text;};
  write("; T1 ignored\nSTART_PRINT INITIAL_TOOL=2 BED_TEMP=60\nTEMPERATURE_WAIT SENSOR=extruder\nT3 ; switch\n# T0 ignored\n");
  auto metadata=native::inspect_file_tools(root,file,[]{return true;});assert(metadata["wmp_used_tools"]==Json::array({2,3}));
  int cache_checks=0;assert(native::inspect_file_tools(root,file,[&]{++cache_checks;return true;},metadata)==metadata&&cache_checks==1);
  auto parsed=native::preview_file(file,metadata,"",true);assert(parsed["usage_known"]==true&&parsed["sliced"].size()==2&&parsed["sliced"][0]["material"]=="Unknown");
  assert(!parsed["sliced"][0].contains("filament_used_mm"));
  auto refuses=[&](const std::function<bool()>&current){bool failed=false;try{native::inspect_file_tools(root,file,current);}catch(...){failed=true;}assert(failed);};
  write("T9\n");refuses([]{return true;});write("START_PRINT INITIAL_TOOL={dynamic}\n");refuses([]{return true;});
  write("G1 X12\n");refuses([]{return true;});
  write("EXCLUDE_OBJECT_DEFINE POLYGON="+std::string(200000,'x')+"\nT0\n");assert(native::inspect_file_tools(root,file,[]{return true;})["wmp_used_tools"]==Json::array({0}));
  write(";"+std::string(200000,'x')+"\nT0\n");int chunks=0;refuses([&]{return ++chunks<2;});
  write("T0\n");bool changed=false;refuses([&]{if(!changed){changed=true;write("T1\nT2\n");}return true;});
  ::unlink(full.c_str());assert(::mkfifo(full.c_str(),0600)==0);refuses([]{return true;});
  ::unlink(full.c_str());::rmdir(root.c_str());
 }

 for(const auto&bad:{"","/absolute.gcode","../escape.gcode","folder/../escape.gcode","folder//file.gcode","bad\nfile.gcode","folder\\file.gcode"})assert(!native::preview_path(bad));
 auto query=native::metadata_query("folder/part #1 & blue.gcode");assert(query=="/server/files/metadata?filename=folder%2Fpart%20%231%20%26%20blue.gcode");assert(wmp_openace::UnifiedLoopbackHttp::allowed_query(query));
 assert(!wmp_openace::UnifiedLoopbackHttp::allowed_query(query+"&evil=1"));
 // Complete Preview -> Tools -> Load review flow. Metadata composition must
 // rebind the UI revision, while leaving the helper's approval token unchanged.
 {
  struct FlowBackend:Backend {int sent=0;std::string unavailable(const std::string&)const override{return "";}Receipt submit(const Request&)override{++sent;return {"flow-1","pending","Queued"};}} transport;
  auto base=native::project(Json{{"webhooks",{{"state","ready"}}},{"extruder",{{"temperature",250.0},{"target",250.0}}},{"print_stats",{{"state","standby"}}}},Json::object(),false,"session");
  base["heads"][0]["loaded"]={{"state","empty"}};base["capabilities"]["load"]=true;
  const std::string token(64,'a');
  base["procedures"]=Json::array({{{"action","load"},{"head","h0"},{"source","external:h0"},{"description","Reviewed helper procedure"},{"token",token},{"revision",base["revision"]}}});
  Json meta={{"filename","flow.gcode"},{"filament_type","PLA"},{"size",100},{"modified",1.0}};
  auto snapshot=base;native::project_preview(snapshot,"flow.gcode",meta,"");
  assert(snapshot["procedures"][0]["revision"]==snapshot["revision"]);
  assert(snapshot["procedures"][0]["token"]==token);
  App flow(transport);flow.update(snapshot);flow.event("file:flow.gcode");flow.event("nav:tools");flow.event("load");flow.event("load-source:external:h0");
  auto begin_enabled=[&](){auto view=flow.render();for(const auto&w:view["widgets"])if(w["id"]=="begin")return w["enabled"].get<bool>();return false;};
  assert(begin_enabled());
  // A file change while a review is open still invalidates that review. The
  // composed plans are available only after a new explicit review is opened.
  snapshot=base;meta["modified"]=2.0;native::project_preview(snapshot,"flow.gcode",meta,"");flow.update(snapshot);
  assert(!begin_enabled());flow.event("begin");assert(transport.sent==0);
  flow.event("close");flow.event("load");flow.event("load-source:external:h0");assert(begin_enabled());
  // A new backend token for otherwise identical visible content must not be
  // silently substituted into an already-open review.
  snapshot["procedures"][0]["token"]=std::string(64,'b');flow.update(snapshot);
  assert(!begin_enabled());flow.event("begin");assert(transport.sent==0);
  flow.event("close");flow.event("load");flow.event("load-source:external:h0");assert(begin_enabled());
  flow.event("close");flow.event("begin");assert(transport.sent==0);
  flow.event("load");flow.event("load-source:external:h0");flow.event("begin");assert(transport.sent==1);
 }
 Json metadata={{"filename","part.gcode"},{"filament_type",Json::array({"PLA","PETG","ABS"})},{"preset_colours",Json::array({"#ab1234","bad","#FFFFFF"})},{"size",1000},{"modified",10.0}};
 auto used=metadata;used["filament_used_mm"]=Json::array({0,12.5,0});
 auto used_file=native::preview_file("part.gcode",used,"");
 assert(filament_usage_text(used_file["sliced"][0])=="12.50 mm");
 assert(used_file["sliced"].size()==1&&used_file["sliced"][0]["id"]=="1");
 used["filament_used_g"]=Json::array({0.01,0.2,0});
 assert(native::preview_file("part.gcode",used,"")["sliced"].size()==2);
 used["filament_used_mm"]=Json::array({0});bool bad_usage=false;
 try{native::preview_file("part.gcode",used,"");}catch(...){bad_usage=true;}assert(bad_usage);
 Json superbird={{"filament_type",Json::array({"PLA","PLA","PLA","PLA","PLA","PLA","PLA"})},
 {"preset_colours",Json::array({"#FFD700","#00A651","#FF69B4","#FF69B4","#FF69B4","#FF69B4","#05D1F5"})},
 {"filament_used_mm",Json::array({16532.5,0,0,0,0,0,0})}};
 superbird["filament_used_g"]=Json::array({49.31,0,0,0,0,0,0});
 auto single=native::preview_file("Superbird.gcode",superbird,"");assert(single["sliced"].size()==1&&single["sliced"][0]["id"]=="0");
 assert(single["sliced"][0]["filament_used_mm"]==16532.5);
 assert(filament_usage_text(single["sliced"][0])=="49.31 g");
 assert(filament_usage_text(Json::object()).empty());
 // Existing Moonraker cache entries can encode material lists as semicolon
 // strings while retaining array-valued colors and per-tool usage.
 Json locomotive={{"filament_type","PLA;PLA;PLA;PLA"},
  {"preset_colours",Json::array({"#C12E1F","#000000","#0056B8","#0000FF"})},
  {"filament_used_mm",Json::array({0,16637.48,10433.68,0})},
  {"filament_used_g",Json::array({0,50.42,31.62,0})}};
 auto train=native::preview_file("train.gcode",locomotive,"");
 assert(train["sliced"].size()==2);
 assert(train["sliced"][0]["id"]=="1"&&train["sliced"][0]["material"]=="PLA");
 assert(train["sliced"][1]["id"]=="2"&&train["sliced"][1]["material"]=="PLA");
 assert(filament_usage_text(train["sliced"][0])=="50.42 g");
 assert(filament_usage_text(train["sliced"][1])=="31.62 g");
 assert(native::metadata_strings(Json{{"filament_type","PLA;;PETG;"}},"filament_type")==Json::array({"PLA","","PETG",""}));
 for(const auto&bad:std::vector<std::string>{std::string(129,'P'),std::string(32,';')}){
  bool refused=false;try{native::metadata_strings(Json{{"filament_type",bad}},"filament_type");}catch(...){refused=true;}assert(refused);
 }
 // Sparse multicolor usage must retain original sliced IDs and their paired
 // material/color/weight, rather than renumbering the surviving rows.
 auto sparse=superbird;
 sparse["filament_type"][5]="PETG";
 sparse["filament_used_mm"]=Json::array({0,100,0,0,0,200,0});
 sparse["filament_used_g"]=Json::array({0,0.3,0,0,0,0.6,0});
 auto sparse_file=native::preview_file("sparse.gcode",sparse,"");
 assert(sparse_file["sliced"].size()==2);
 assert(sparse_file["sliced"][0]["id"]=="1"&&sparse_file["sliced"][1]["id"]=="5");
 assert(sparse_file["sliced"][0]["color"]=="#00A651");
 assert(sparse_file["sliced"][1]["material"]=="PETG");
 assert(filament_usage_text(sparse_file["sliced"][1])=="0.60 g");
 for(const auto&bad:Json::array({-1,"0.6",true,nullptr})){
  auto broken=sparse;broken["filament_used_g"][5]=bad;
  bool refused=false;try{native::preview_file("sparse.gcode",broken,"");}catch(...){refused=true;}assert(refused);
 }
 auto unused=sparse;
 unused["filament_used_mm"]=Json::array({0,0,0,0,0,0,0});
 unused["filament_used_g"]=Json::array({0,0,0,0,0,0,0});
 auto unused_file=native::preview_file("unused.gcode",unused,"");
 assert(unused_file["sliced"].empty()&&!unused_file["metadata_error"].get<std::string>().empty());
 auto file=native::preview_file("part.gcode",metadata,"");assert(file["sliced"].size()==3&&file["sliced"][1]["id"]=="1"&&file["sliced"][1]["color"]=="#888888");
 auto out=native::project(Json{{"webhooks",{{"state","ready"}}},{"extruder",{{"temperature",20.0},{"target",0.0}}},{"print_stats",{{"state","standby"}}}},Json::object(),false,"session");
 native::project_preview(out,"part.gcode",metadata,"");StubBackend backend;App app(backend);app.update(out);app.event("file:part.gcode");auto frame=app.render();assert(frame["page"]=="preview");
 auto usage_snapshot=out;native::project_preview(usage_snapshot,"Superbird.gcode",superbird,"");
 App usage_app(backend);usage_app.update(usage_snapshot);usage_app.event("file:Superbird.gcode");
 auto usage_frame=usage_app.render();bool weight_rendered=false;
 for(const auto&w:usage_frame["widgets"])if(w["id"]=="slice:0"){weight_rendered=w["text"].get<std::string>().find("49.31 g")!=std::string::npos;}
 assert(weight_rendered);
 auto unsupported_snapshot=out;unsupported_snapshot["owner"]="standalone";
 native::project_preview(unsupported_snapshot,"sparse.gcode",sparse,"");
 App unsupported_app(backend);unsupported_app.update(unsupported_snapshot);unsupported_app.event("file:sparse.gcode");
 assert(unsupported_app.preview_state()["reason"]=="Standalone: reslice using tools T0–T3.");
 assert(!unsupported_app.preview_state()["can_start"].get<bool>());
 auto ace_sparse=unsupported_snapshot;ace_sparse["owner"]="openace";
 App ace_sparse_app(backend);ace_sparse_app.update(ace_sparse);ace_sparse_app.event("file:sparse.gcode");
 assert(ace_sparse_app.preview_state()["reason"]=="Choose a source for every sliced filament.");
 auto supported_sparse=unsupported_snapshot;supported_sparse["files"][0]["sliced"][1]["id"]="3";
 App supported_sparse_app(backend);supported_sparse_app.update(supported_sparse);supported_sparse_app.event("file:sparse.gcode");
 assert(supported_sparse_app.preview_state()["reason"]=="Choose a source for every sliced filament.");
 bool scroll=false;for(const auto&w:frame["widgets"]){if(w["id"]=="preview-rows")scroll=w["kind"]=="scroll";if(w["id"]=="map:2")assert(w["parent"]=="preview-rows");assert(w["id"]!="scroll-next");}assert(scroll);
 bool found=false;for(const auto&w:frame["widgets"])if(w["id"]=="slice:1"){found=true;assert(w["text"].get<std::string>().find("PETG")!=std::string::npos);}assert(found);
 for(const auto&w:frame["widgets"])if(w["id"]=="start")assert(w["enabled"]==false);
 // No usage cannot establish used-tool count: label rows as presets without
 // inventing weights or changing their IDs. Once mapped, retain the warning.
 assert(!file["usage_known"].get<bool>());
 assert(app.preview_state()["reason"]=="Usage unavailable. Choose a source for every preset.");
 assert(used_file["usage_known"].get<bool>());
 auto revision=out["revision"];metadata["modified"]=11.0;
 auto newer=native::project(Json{{"webhooks",{{"state","ready"}}},{"print_stats",{{"state","standby"}}}},Json::object(),false,"session");native::project_preview(newer,"part.gcode",metadata,"");assert(newer["revision"]!=revision);
 bool rejected=false;try{native::preview_file("other.gcode",metadata,"");}catch(...){rejected=true;}assert(rejected);
 file=native::preview_file("part.gcode",Json::object(),"Metadata unavailable");assert(file["sliced"].empty());
 metadata["filament_type"]=Json::array({4});rejected=false;try{native::preview_file("part.gcode",metadata,"");}catch(...){rejected=true;}assert(rejected);

 Json status={{"webhooks",{{"state","ready"}}},{"print_stats",{{"state","standby"}}},{"extruder2",{{"temperature",25.0},{"target",0.0}}},{"save_variables",{{"variables",{{"box_modify_t0",2},{"box_modify_t1",2}}}}},{"wm_material",{{"identities",{{"h2",{{"brand","Generic"},{"material","PLA"},{"color","#abcdef"}}}}}}}};
 status["wm_material"]["session_id"]="session";
 status["wm_material"]["filament_loaded"]["h2"]={{"state","loaded"},{"evidence","sensor"},{"session","session"}};
 metadata["filament_type"]=Json::array({"PLA","PETG"});metadata["preset_colours"]=Json::array({"#123456","#654321"});
 auto standalone=native::project(status,Json::object(),false,"session");native::project_preview(standalone,"part.gcode",metadata,"");
 assert(standalone["routes"].size()==1&&standalone["routes"][0]["id"]=="head:h2");assert(standalone["routes"][0]["sliced_rows"]==Json::array({"0"}));
 App physical(backend);physical.update(standalone);physical.event("file:part.gcode");physical.event("map:0");frame=physical.render();bool source_button=false;for(const auto&w:frame["widgets"])if(w["id"]=="choose:head:h2"){source_button=true;assert(w["enabled"]==true);}assert(source_button);
 physical.event("choose:head:h2");frame=physical.render();assert(frame["modal"]=="");bool selected=false;for(const auto&w:frame["widgets"])if(w["id"]=="map:0"){selected=true;assert(w["text"].get<std::string>()=="Head 3 · External");}assert(selected);
 // Cosmetic PLA Matte maps to PLA in both directions without changing identity.
 assert(native::material_key(" pla matte ")==native::material_key("PLA"));
 for(const auto&different:{"PETG","PCTG","PLA-CF","PLA GF","PLA HT"})
  assert(native::material_key(different)!=native::material_key("PLA"));
 auto matte_status=status;matte_status["wm_material"]["identities"]["h2"]["material"]="PLA Matte";
 auto matte=native::project(matte_status,Json::object(),false,"session");native::project_preview(matte,"part.gcode",metadata,"");
 assert(matte["routes"][0]["sliced_rows"]==Json::array({"0"}));
 assert(matte["sources"][0]["identity"]["material"]=="PLA Matte");
 matte_status["wm_material"]["filament_loaded"]["h2"]["state"]="empty";
 auto empty_matte=native::project(matte_status,Json::object(),false,"session");native::project_preview(empty_matte,"part.gcode",metadata,"");
 assert(!empty_matte["routes"][0]["eligible"].get<bool>()&&empty_matte["routes"][0]["sliced_rows"].empty());
 // Head 2 was absent from the previous logical map, but must be selectable.
 status["extruder1"]={{"temperature",25.0},{"target",0.0}};status["wm_material"]["identities"]["h1"]=status["wm_material"]["identities"]["h2"];
 status["wm_material"]["filament_loaded"]["h1"]=status["wm_material"]["filament_loaded"]["h2"];
 status["save_variables"]["variables"]={{"box_modify_t0",2},{"box_modify_t1",2},{"box_modify_t2",2},{"box_modify_t3",2}};
 status["wm_material"]["print_start_protocol"]=1;status["wm_material"]["identity_revision"]=std::string(64,'a');
 auto all_heads=native::project(status,Json::object(),false,"session");
 auto single_metadata=metadata;single_metadata["filament_type"]=Json::array({"PLA"});single_metadata["preset_colours"]=Json::array({"#123456"});
 native::project_preview(all_heads,"part.gcode",single_metadata,"");assert(all_heads["routes"].size()==2);
 auto warning_context=all_heads;warning_context["capabilities"]["start_print"]=true;
 struct ReadyBackend:Backend {std::string unavailable(const std::string&)const override{return "";}Receipt submit(const Request&)override{assert(false);return {};}} ready_backend;
 App missing_usage(ready_backend);missing_usage.update(warning_context);missing_usage.event("file:part.gcode");
 missing_usage.event("map:0");missing_usage.event("choose:head:h1");
 assert(missing_usage.preview_state()["can_start"].get<bool>());
 assert(missing_usage.preview_state()["notice"]=="Usage unavailable; all filament presets are shown.");
 warning_context["fresh"]=false;missing_usage.update(warning_context);
 assert(!missing_usage.preview_state()["can_start"].get<bool>());
 assert(missing_usage.preview_state()["notice"]!="Usage unavailable; all filament presets are shown.");
 auto request=standalone_print_request(all_heads,Json{{"file","part.gcode"},{"routes",{{"0","head:h1"}}},{"options",{{"leveling",true},{"timelapse",false}}}},"check-1");
 assert(request["mapping"]["0"]==1&&request["expected_mapping"]==Json::array({2,2,2,2}));
 // USB copy/review is filesystem-only; starting the resulting local file still
 // observes normal print admission while another print is running or paused.
 for(const auto*state:{"printing","paused"}){
  auto active=all_heads;active["job"]["state"]=state;bool refused=false;
  try{standalone_print_request(active,Json{{"file","part.gcode"},{"routes",{{"0","head:h1"}}},{"options",{{"leveling",true},{"timelapse",false}}}},"check-active");}catch(...){refused=true;}
  assert(refused);
 }

 auto train_snapshot=all_heads;locomotive["size"]=17679715;locomotive["modified"]=1786820072.8051264;
 native::project_preview(train_snapshot,"train.gcode",locomotive,"");
 auto train_request=standalone_print_request(train_snapshot,Json{{"file","train.gcode"},{"routes",{{"1","head:h1"},{"2","head:h2"}}},{"options",{{"leveling",true},{"timelapse",false}}}},"train-check");
 assert(train_request["mapping"]==Json({{"1",1},{"2",2}}));
 // New standalone consent is explicit, locally bound, and never a global hold.
 {
  auto raw=status;raw["wm_material"]["print_material_confirmation_protocol"]=1;
  raw["wm_material"]["print_sequence_protocol"]=1;raw["wm_material"]["print_request_sequence"]=42;
  raw["wm_material"]["filament_loaded"]["h1"]["sensor_present"]=true;
  raw["wm_material"]["filament_loaded"]["h1"]["state"]="unknown";
  auto snapshot=native::project(raw,Json::object(),false,"session");
  auto meta=single_metadata;meta["filename"]="part #1;*.gcode";meta["filament_type"]=Json::array({"PETG"});
  native::project_preview(snapshot,"part #1;*.gcode",meta,"");snapshot["capabilities"]["start_print"]=true;
  struct ConsentBackend:Backend {int sent=0;Json arguments;std::string unavailable(const std::string&)const override{return "";}Receipt submit(const Request&r)override{++sent;arguments=r.arguments;return {"consent","pending","Sent"};}} transport;
  App consent(transport);consent.print_options(true,false,true);consent.update(snapshot);consent.event("file:part #1;*.gcode");consent.event("map:0");consent.event("choose:head:h1");
  assert(consent.preview_state().value("can_start",false));consent.event("start");
  assert(transport.sent==0&&consent.preview_state().value("material_review",false));
  consent.event("material-review-cancel");assert(!consent.preview_state().value("material_review",true));
  assert(consent.preview_state().value("editable",false));
  consent.event("start");auto changed=snapshot;changed["session"]="restarted";consent.update(changed);consent.event("material-review-confirm");assert(transport.sent==0);
  consent.update(snapshot);
  assert(!consent.preview_state().value("can_start",false)); // Session change retires the old source choice.
  consent.event("map:0");consent.event("choose:head:h1");
  consent.event("start");consent.event("material-review-confirm");assert(transport.sent==1&&transport.arguments["material_confirmation"]==true);
  auto args=transport.arguments;args["material_confirmation"]=false;bool refused=false;
  try{standalone_print_request(snapshot,args,"print_43");}catch(...){refused=true;}assert(refused);
  args["material_confirmation"]=true;auto prepared=standalone_print_request(snapshot,args,"print_43");
  assert(prepared["sequence"]==43&&prepared["id"]=="print_43"&&prepared["sliced_materials"]["0"]=="PETG");
  assert(prepared["file"]["path"]=="part #1;*.gcode");
  snapshot["print_request_sequence"]=43;refused=false;try{standalone_print_request(snapshot,args,"print_43");}catch(...){refused=true;}assert(refused);
  // Missing material names can use explicit per-tool usage, never guessed tools.
  meta.erase("filament_type");meta.erase("preset_colours");meta["filament_used_mm"]=Json::array({0,0,12,0});
  auto known=native::preview_file("part #1;*.gcode",meta,"",true);assert(known["sliced"].size()==1&&known["sliced"][0]["id"]=="2");
  meta.erase("filament_used_mm");assert(native::preview_file("part #1;*.gcode",meta,"",true)["sliced"].empty());
  raw["wm_material"]["filament_loaded"]["h1"]["sensor_present"]=false;
  auto empty=native::project(raw,Json::object(),false,"session");for(const auto&r:empty["routes"])if(r["head"]=="h1")assert(!r["eligible"].get<bool>());
 }
 auto old_revision=all_heads["revision"];status["save_variables"]["variables"]["box_modify_t0"]=1;
 auto changed=native::project(status,Json::object(),false,"session");native::project_preview(changed,"part.gcode",single_metadata,"");assert(changed["revision"]!=old_revision);
 Json ace={{"session_id",1},{"default_tool_map",{{"7",{{"head","h2"},{"unit","ace0"},{"slot",1}}}}},{"management",{{"units",{{"ace0",Json::object()}}},{"source_settings",{{"ace0:1",Json::object()}}},{"identity_settings",{{"ace0:1",{{"values",{{"vendor","Generic"},{"material","PLA"},{"color","#abcdef"}}}}}}}}},{"units",Json::array({{{"id","ace0"},{"name","Rear ACE"}}})},{"devices",{{"units",{{"ace0",{{"connected",true}}}}}}}};
 auto mapped=native::project(status,ace,true,"ignored");native::project_preview(mapped,"part.gcode",metadata,"");assert(mapped["routes"][0]["id"]=="T7");assert(mapped["routes"][0]["source"]=="ace0:1");assert(mapped["routes"][0]["head"]=="h2");assert(mapped["routes"][0]["sliced_rows"]==Json::array({"0"}));
 // openACE Start preparation preserves virtual routing; never translates T7
 // into physical h2 or writes the vendor box_modify map.
 {
  auto context=mapped;context["files"][0]["sliced"]=Json::array({context["files"][0]["sliced"][0]});
  Json args={{"file","part.gcode"},{"routes",{{"0","T7"}}},{"options",{{"leveling",true},{"timelapse",false}}}};
  auto prepared=openace_print_request(context,args);
  assert(prepared["command"]=="SDCARD_PRINT_FILE FILENAME=\"part.gcode\" OPENACE_MAP=\"[[0,7]]\"");
  assert(prepared["pairs"]==Json::array({Json::array({0,7})}));
  assert(prepared["session"]==context["session"]&&prepared["file_identity"]==context["files"][0]["file_identity"]);
  auto refuses=[&](Json state,Json request){bool failed=false;try{(void)openace_print_request(state,request);}catch(const std::exception&){failed=true;}assert(failed);};
  auto invalid=context;invalid["fresh"]=false;refuses(invalid,args);
  invalid=context;invalid["owner"]="standalone";refuses(invalid,args);
  invalid=context;invalid["job"]["state"]="paused";refuses(invalid,args);
  invalid=context;invalid["routes"][0]["eligible"]=false;refuses(invalid,args);
  invalid=context;invalid["sources"]=Json::array();refuses(invalid,args);
  invalid=context;invalid["routes"][0]["tool"]=2;refuses(invalid,args);
  invalid=context;invalid["routes"].push_back(invalid["routes"][0]);refuses(invalid,args);
  invalid=context;invalid["files"][0]["file_identity"]["size"]=0;refuses(invalid,args);
  auto wrong=args;wrong["routes"]["1"]="T7";refuses(context,wrong);
  for(const auto&path:{"../part.gcode","part.gcode;G28","part\nG28","part\".gcode","part#.gcode"}){wrong=args;wrong["file"]=path;refuses(context,wrong);}
  // All 32 sliced indices are supported, sorted numerically rather than by
  // string key; aliases are preserved and may share a destination.
  auto many=context;many["files"][0]["sliced"]=Json::array();many["routes"][0]["sliced_rows"]=Json::array();wrong=args;wrong["routes"]=Json::object();
  for(int i=31;i>=0;--i){auto key=std::to_string(i);many["files"][0]["sliced"].push_back({{"id",key}});many["routes"][0]["sliced_rows"].push_back(key);wrong["routes"][key]="T7";}
  prepared=openace_print_request(many,wrong);assert(prepared["pairs"].size()==32);
  for(int i=0;i<32;++i)assert(prepared["pairs"][i]==Json::array({i,7}));
  many["files"][0]["sliced"][0]["id"]="01";refuses(many,wrong);
 }
 ace["default_tool_map"]["9"]=ace["default_tool_map"]["7"];
 auto two_aliases=native::project(status,ace,true,"ignored");native::project_preview(two_aliases,"part.gcode",metadata,"");
 App aliases(backend);aliases.update(two_aliases);aliases.event("file:part.gcode");aliases.event("map:0");aliases.event("route-source:ace0:1");assert(aliases.render()["modal"]=="routes");aliases.event("choose:T9");assert(aliases.render()["modal"]=="");
 ace["default_tool_map"].erase("9");
 ace["blocked_tools"]={{"7","head holds hand-loaded filament"}};auto blocked=native::project(status,ace,true,"ignored");native::project_preview(blocked,"part.gcode",metadata,"");assert(!blocked["routes"][0]["eligible"].get<bool>());assert(blocked["routes"][0]["sliced_rows"].empty());assert(mapped["revision"]!=blocked["revision"]);
 ace["blocked_tools"]=Json::object();ace["devices"]["units"]["ace0"]["connected"]=false;auto disconnected=native::project(status,ace,true,"ignored");assert(!disconnected["routes"][0]["eligible"].get<bool>());
 // A new file/routing revision dismisses an open selector and rejects queued taps.
 App changing(backend);changing.update(standalone);changing.event("file:part.gcode");changing.event("map:0");assert(changing.render()["modal"]=="sources");
 auto replacement_context=standalone;replacement_context["revision"]="replacement-file";changing.update(replacement_context);assert(changing.render()["modal"]=="");
 changing.event("choose:head:h2");frame=changing.render();for(const auto&w:frame["widgets"])if(w["id"]=="map:0")assert(w["text"]=="Choose source");
 changing.event("map:0");changing.event("choose:head:h2");frame=changing.render();for(const auto&w:frame["widgets"])if(w["id"]=="map:0")assert(w["text"]=="Head 3 · External");
 changing.event("map:missing-row");assert(changing.render()["modal"]=="");
 // Losing freshness also prevents a selection from an already open chooser.
 changing.event("map:0");replacement_context["fresh"]=false;changing.update(replacement_context);changing.event("choose:head:h2");assert(changing.render()["modal"]=="sources");

}
