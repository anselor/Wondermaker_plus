// SPDX-License-Identifier: GPL-3.0-or-later
#include "standalone_backend.hpp"
#include "native/projection.hpp"
#include "native/loopback_http.hpp"
#include "native/print_context.hpp"
#include "native/stock_identity_edit.hpp"
#include "screens.hpp"
#include <cassert>
using namespace wmp_ui;
struct Http:wmp_openace::HttpPort {
 int posts=0;bool fail=false;std::string script,guard;
 std::string get(const std::string&)override{return "{}";}
 std::string post(const std::string&path,const std::string&body)override{assert(path=="/printer/gcode/script");++posts;script=Json::parse(body).at("script");guard.clear();if(script.find("WMP_CHECK_COMMAND_GENERATION ")==0){auto end=script.find('\n');assert(end!=std::string::npos);guard=script.substr(0,end);script=script.substr(end+1);}if(fail)throw std::runtime_error("timeout");return "{\"result\":\"ok\"}";}
};
int main(){
 for(bool allowed:{false,true})for(bool fresh:{false,true})for(const auto*op:{"complete","pending","running"}){
  Json data={{"fresh",fresh},{"owner","standalone"},{"session","repair"},{"revision","r"},{"job",{{"state","paused"}}},
   {"capabilities",{{"toolhead_action",true}}},{"attachment",{{"state","attached"},{"head","h2"}}},
   {"toolchange_pause",{{"manual_toolhead_available",allowed},{"manual_toolhead_reason","Fault job is still moving."}}},
   {"toolhead_operation",{{"state",op}}}};
  auto other_owner=data;other_owner["owner"]="openace";assert(!paused_toolhead_repair_available(other_owner));
  auto ordinary=data;ordinary.erase("toolchange_pause");assert(!paused_toolhead_repair_available(ordinary));
  auto moving=data;moving["job"]["state"]="printing";assert(!paused_toolhead_repair_available(moving));
  StandaloneBackend backend;backend.observe(data);
  const auto result=backend.submit({"dock","r","standalone",{{"head","h2"},{"attached","h2"}}});
  assert((result.state=="pending")==bool(allowed&&fresh&&std::string(op)=="complete"));
 }

 // Ordinary pause permits only the backend's exact original-head action.
 for(const auto*action:{"dock","take"})for(const auto*selected:{"h2","h3"}){
  Json data={{"owner","standalone"},{"fresh",true},{"revision","r"},{"session","s"},{"job",{{"state","paused"}}},
   {"capabilities",{{"toolhead_action",true}}},{"attachment",{{"state",std::string(action)=="dock"?"attached":"empty"},{"head","h2"}}},
   {"paused_toolhead_actions",{{"head","h2"},{"actions",Json::array({action})}}}};
  const bool allowed=std::string(selected)=="h2";
  assert(paused_toolhead_action_available(data,selected,action)==allowed);
  assert(!paused_toolhead_action_available(data,selected,std::string(action)=="dock"?"take":"dock"));
  StandaloneBackend backend;backend.observe(data);
  auto result=backend.submit({action,"r","standalone",{{"head",selected},{"attached",std::string(action)=="dock"?"h2":"none"}}});
  assert((result.state=="pending")==allowed);
  data["fresh"]=false;assert(!paused_toolhead_action_available(data,selected,action));
  data["fresh"]=true;data["owner"]="openace";assert(!paused_toolhead_action_available(data,selected,action));
 }

 // Malformed cosmetic metadata remains raw evidence, but cannot hide unrelated
 // live controls. Only an explicit correction submits a changed identity.
 for(const auto*field:{"brand","color"})for(const auto&bad:{Json(),Json(7),Json::object(),Json::array(),Json("#not-rgb")}){
  if(std::string(field)=="brand"&&bad.is_string())continue;
  Json identity={{"brand","Generic"},{"material","PLA"},{"color","#123456"}};identity[field]=bad;
  Json status={{"webhooks",{{"state","ready"}}},{"print_stats",{{"state","standby"}}},
   {"extruder",{{"temperature",25.0},{"target",0.0}}},{"wm_material",{{"session_id","session"},{"identity_writable",true},
   {"identity_revision",std::string(64,'a')},{"identities",{{"h0",identity}}},
   {"heater_settings",{{"extruder",{{"min_temp",0},{"max_temp",300}}}}}}}};
  status["wm_material"]["filament_loaded"]={{"h0",{{"state","loaded"},{"source","external:h0"},{"evidence","sensor"},{"session","session"},{"identity",identity}}}};
  auto snapshot=native::project(status,Json::object(),false,"session");
  assert(snapshot["heads"][0]["loaded"]["identity"]==identity);
  assert(snapshot["sources"][0]["identity"]==identity);
  StandaloneBackend backend;backend.observe(snapshot);App app(backend);app.update(snapshot);
  assert(app.data()["fresh"]==true);app.render();
  assert(identity_display_text(identity,field,"unavailable")=="unavailable");
  Http wire;auto heat=backend.submit({"temperature",snapshot["revision"],"standalone",{{"head","h0"},{"target",0}}});
  assert(heat.state=="pending");backend.deliver(wire);assert(wire.posts==1&&wire.script=="SET_HEATER_TEMPERATURE HEATER=extruder TARGET=0");
  StandaloneBackend save;save.observe(snapshot);Http save_wire;
  auto invalid=save.submit({"save_identity",snapshot["revision"],"standalone",{{"draft",snapshot["sources"][0]}}});
  assert(invalid.state=="refused");save.deliver(save_wire);assert(save_wire.posts==0);
  native::StockIdentityEdit edit;assert(edit.begin(snapshot,"h0",field));
  assert(edit.draft()["identity"]==identity);
  auto repaired=edit.choose(snapshot,std::string(field)=="brand"?"Generic":"#abcdef",save);
  assert(repaired.state=="pending");save.deliver(save_wire);assert(save_wire.posts==1);
  assert(snapshot["sources"][0]["identity"]==identity); // no read-time repair
  for(const auto*physical:{"material","nozzle_temp"}){
   auto unsafe=snapshot;unsafe["sources"][0]["identity"][physical]=Json::object();
   App invalid_app(save);invalid_app.update(unsafe);assert(!invalid_app.data().value("fresh",false));
  }
 }
 // Malformed diagnostic text cannot discard current state or receipt identity.
 for(const auto&message:{Json(),Json(7),Json::object(),Json::array(),Json("Exact dock refusal")}){
  Json current={{"owner","standalone"},{"fresh",true},{"session","text-session"},{"revision","text-rev"},{"job",{{"state","idle"}}},{"capabilities",{{"toolhead_action",true}}},{"attachment",{{"state","empty"}}}};
  StandaloneBackend backend;Http wire;backend.observe(current);
  auto receipt=backend.submit({"take","text-rev","standalone",{{"head","h0"},{"attached","none"}}});assert(receipt.state=="pending");backend.deliver(wire);
  current["toolhead_operation"]={{"id","different"},{"session","text-session"},{"head","h0"},{"action","take"},{"state","complete"},{"message",message}};
  backend.observe(current);assert(current["receipts"][receipt.id]["state"]=="pending");
  current["toolhead_operation"]["id"]=receipt.id;current["toolhead_operation"]["state"]="failed";
  backend.observe(current);assert(current["receipts"][receipt.id]["state"]=="failed");
  auto text=current["receipts"][receipt.id]["message"].get<std::string>();
  assert(message.is_string()?text=="Exact dock refusal":text.find("message text unavailable")!=std::string::npos);
  assert(wire.posts==1); // No replay due to diagnostic parsing.
 }
 // Restored unknown outcomes do not reserve standalone settings or mutually
 // strand explicit reconciliation. Pending/running work still owns motion,
 // but idle nozzle settings remain independent of those operation records.
 for(const auto*other_state:{"unknown","pending","running"}){
  Json data={{"owner","standalone"},{"fresh",true},{"session","session"},{"revision","rev"},{"command_generation",0},
   {"job",{{"state","idle"}}},{"capabilities",{{"save_nozzle",true}}},
   {"nozzle_settings",{{"h2",{{"diameter",0.4},{"material","Hardened steel"}}}}},{"nozzle_revision",std::string(64,'a')},
   {"toolhead_recovery_protocol",1},{"filament_recovery_protocol",1},
   {"toolhead_operation",{{"id","oldtool"},{"session","session"},{"previous_session","before"},{"head","h2"},{"action","take"},{"state","unknown"}}},
   {"filament_operation",{{"id","oldfeed"},{"session","session"},{"previous_session","before"},{"head","h2"},{"action","load"},{"state","unknown"}}}};
  const bool historical=std::string(other_state)=="unknown";
  for(const auto*key:{"toolhead_operation","filament_operation"}){
   auto current=data;current[key]["state"]=other_state;
   StandaloneBackend backend;Http wire;backend.observe(current);
   auto result=backend.submit({"save_nozzle","rev","standalone",{{"head","h2"},{"expected",std::string(64,'a')},{"diameter",0.4},{"material","Hardened steel"}}});
   assert(result.state=="pending");backend.deliver(wire);
   assert(wire.posts==1);
  }
  for(const auto*job:{"printing","paused","idle"})for(const auto*identification:{"idle","pending","running","complete"}){
   auto current=data;current["job"]["state"]=job;current["identification"]={{"state",identification}};
   StandaloneBackend backend;Http wire;backend.observe(current);
   auto result=backend.submit({"save_nozzle","rev","standalone",{{"head","h2"},{"expected",std::string(64,'a')},{"diameter",0.6},{"material","Hardened steel"}}});
   const bool print_active=std::string(job)=="printing"||std::string(job)=="paused";
   const bool conflict=print_active||std::string(identification)=="pending"||std::string(identification)=="running";
   assert(result.state==(conflict?"refused":"pending"));backend.deliver(wire);assert(wire.posts==(conflict?0:1));
   if(conflict)assert(result.message.find(print_active?"job.state=":"identification.state=")!=std::string::npos);
  }
  for(bool tool:{true,false}){
   auto current=data;current[tool?"filament_operation":"toolhead_operation"]["state"]=other_state;
   StandaloneBackend backend;Http wire;backend.observe(current);
   assert(tool?backend.resume_toolhead("oldtool"):backend.resume_filament("oldfeed"));
   assert((tool?backend.recover_toolhead("oldtool"):backend.recover_filament("oldfeed"))==historical);
   backend.deliver(wire);assert(wire.posts==(historical?1:0));
   if(historical)assert(wire.script.find(tool?"WMP_RECOVER_TOOLHEAD":"WMP_RECOVER_FILAMENT")==0);
  }
  // This correction does not change the separately managed owner's semantics.
  data["owner"]="openace";data["print_helper_session"]="session";
  data["filament_operation"]["openace_recovery_supported"]=true;
  data["toolhead_operation"]["state"]=other_state;
  StandaloneBackend external;Http untouched;external.observe(data);
  assert(external.resume_filament("oldfeed"));
  const bool external_allowed=std::string(other_state)=="pending"; // Preserve pre-existing owner policy.
  assert(external.recover_filament("oldfeed")==external_allowed);
  external.deliver(untouched);assert(untouched.posts==(external_allowed?1:0));
 }
 // Read-only import stages work while printing or paused; Save is separate.
 for(const auto*job:{"printing","paused"})for(const auto*action:{"scan","review","save"}){
  Json data={{"owner","standalone"},{"fresh",true},{"session","test-session"},{"revision","rev"},{"job",{{"state",job}}},{"capabilities",{{"profile_import",true}}},{"profile_import",{{"state","review"},{"token",std::string(48,'a')}}}};
  StandaloneBackend backend;Http wire;backend.observe(data);
  const auto receipt=backend.submit({"profile_import","rev","standalone",{{"action",action},{"value",std::string(std::string(action)=="review"?64:48,'a')}}});
  assert(receipt.state==(std::string(action)=="save"?"refused":"pending"));
  assert(!backend.machine_request_pending());backend.deliver(wire);
  assert(wire.posts==(std::string(action)=="save"?0:1));
 }
 // Explicit retry replaces unknown history, but never an executing HTTP call.
 {
  Json data={{"owner","standalone"},{"fresh",true},{"session","retry"},{"revision","rev"},{"job",{{"state","idle"}}},{"capabilities",{{"toolhead_action",true}}},{"attachment",{{"state","attached"},{"head","h1"}}}};
  StandaloneBackend backend;Request request={"dock","rev","standalone",{{"head","h1"},{"attached","h1"}}};
  struct Reply:Http{std::function<void()>during;std::string post(const std::string&p,const std::string&b)override{Http::post(p,b);if(during)during();return "{\"error\":{\"message\":\"failed after effect\"}}";}} wire;
  backend.observe(data);auto first=backend.submit(request);assert(first.state=="pending");
  wire.during=[&]{auto changed=data;changed["session"]="restarted";backend.observe(changed);assert(backend.submit(request).state=="refused");};
  backend.deliver(wire);wire.during={};backend.observe(data);
  assert(data["receipts"][first.id]["state"]=="unknown"&&!backend.machine_request_pending());
  auto next=backend.submit(request);assert(next.state=="pending"&&next.id!=first.id);
  data["toolhead_operation"]={{"id",first.id},{"session","retry"},{"head","h1"},{"action","dock"},{"state","complete"}};
  backend.observe(data);assert(data["receipts"][next.id]["state"]=="pending");
  backend.deliver(wire);assert(wire.posts==2);
 }
 // Authoritative status may arrive while the command HTTP reply is blocked.
 // A late error, timeout, or success must not replace that terminal outcome.
 for(const auto*state:{"complete","refused","failed"})for(int reply:{0,1,2}){
  Json data={{"owner","standalone"},{"fresh",true},{"session","receipt-session"},{"revision","rev"},{"job",{{"state","idle"}}},{"capabilities",{{"toolhead_action",true}}},{"attachment",{{"state","attached"},{"head","h1"}}}};
  StandaloneBackend backend;backend.observe(data);auto ticket=backend.submit({"dock","rev","standalone",{{"head","h1"},{"attached","h1"}}});assert(ticket.state=="pending");
  struct Reply:Http{std::function<void()>during;int mode=0;std::string post(const std::string&p,const std::string&b)override{auto result=Http::post(p,b);during();if(mode==1)throw std::runtime_error("lost reply");return mode==2?"{\"error\":{\"message\":\"late error\"}}":result;}} wire;
  wire.mode=reply;wire.during=[&]{data["toolhead_operation"]={{"id",ticket.id},{"session","receipt-session"},{"head","h1"},{"action","dock"},{"state",state},{"message","Confirmed readback"}};backend.observe(data);assert(data["receipts"][ticket.id]["state"]==state);assert(backend.machine_request_pending());};
  backend.deliver(wire);data.erase("toolhead_operation");for(int i=0;i<12;++i)backend.observe(data);
  assert(data["receipts"][ticket.id]["state"]==state&&!backend.machine_request_pending());
 }
 // Distinct refusal conditions keep their cause and never submit a command.
 {
  assert(rejection_value(std::string(100,'x')).size()==64);
  assert(rejection_value("afc\nother")=="afc?other");
  Json data={{"owner","standalone"},{"fresh",true},{"session","session"},{"revision","rev"},{"command_generation",1},{"job",{{"state","idle"}}},{"heater_limits",{{"h2",{{"min",0},{"max",290}}}}}};
  StandaloneBackend backend;Http wire;backend.observe(data);
  Request r={"temperature","rev","openace",{{"head","h2"},{"target",220}}};
  auto refused=backend.submit(r);assert(refused.state=="refused"&&refused.message.find("reviewed=openace, current=standalone")!=std::string::npos);
  r.owner="standalone";r.revision="old-secret-revision";refused=backend.submit(r);assert(refused.message.find("revision changed")!=std::string::npos&&refused.message.find("secret")==std::string::npos);
  r.revision="rev";auto queued=backend.submit(r);assert(queued.state=="pending");data["command_generation"]=2;backend.observe(data);backend.deliver(wire);backend.observe(data);
  assert(wire.posts==0);assert(data["receipts"][queued.id]["message"].get<std::string>().find("reviewed=1, current=2")!=std::string::npos);
 }

 // A backend restart retains the operation ID but creates a new recovery scope.
 for(int mode:{0,1,2})for(bool late_reply:{false,true}){
  const bool tool=mode==1,ace=mode==2;
  const auto key=tool?"toolhead_operation":"filament_operation";
  Json data={{"owner","standalone"},{"fresh",true},{"session","before"},{"revision","rev"},
   {"job",{{"state","idle"}}},{tool?"toolhead_recovery_protocol":"filament_recovery_protocol",1},
   {key,{{"id","retained"},{"session","before"},{"head","h2"},{"action",tool?"take":"load"},{"state","unknown"}}}};
  if(ace){data["owner"]="openace";data["session"]="ace-session";data["print_helper_session"]="before";
   data[key]["openace_recovery_supported"]=true;}
  StandaloneBackend backend;
  struct Reply:Http{std::function<void()> during;std::string post(const std::string&p,const std::string&b)override{
   auto result=Http::post(p,b);if(during)during();return result;
  }} wire;
  auto resume=[&]{return tool?backend.resume_toolhead("retained"):backend.resume_filament("retained");};
  auto recover=[&]{return tool?backend.recover_toolhead("retained"):backend.recover_filament("retained");};
  auto restart=[&]{data[ace?"print_helper_session":"session"]="after";data[key]["session"]="after";data[key]["previous_session"]="before";
   backend.observe(data);assert(resume());};
  auto stale=data;stale["fresh"]=false;backend.observe(stale);assert(!resume());assert(backend.resume_refusal().find("not fresh")!=std::string::npos);
  backend.observe(data);assert(!backend.resume_filament("different"));assert(backend.resume_refusal().find(tool?"protocol":"identifier")!=std::string::npos);
  backend.observe(data);assert(resume());assert(backend.resume_refusal().empty());assert(recover());
  if(late_reply)wire.during=restart;
  backend.deliver(wire);wire.during={};
  if(!late_reply){assert(!recover());restart();}
  assert(wire.posts==1);backend.deliver(wire);assert(wire.posts==1); // No automatic retry.
  assert(recover());assert(!recover());backend.deliver(wire);
  assert(wire.posts==2&&wire.script.find("SESSION=after")!=std::string::npos);
  assert(wire.script.find(tool?"WMP_RECOVER_TOOLHEAD":"WMP_RECOVER_FILAMENT")==0);
 }

 for(const auto*job:{"printing","paused"})for(const auto*action:{"scan","review","save"}){
  Json data={{"owner","standalone"},{"fresh",true},{"session","test-session"},{"revision","rev"},{"job",{{"state",job}}},{"capabilities",{{"profile_import",true}}},{"profile_import",{{"state","review"},{"token",std::string(48,'a')}}}};
  StandaloneBackend backend;Http wire;backend.observe(data);
  const auto receipt=backend.submit({"profile_import","rev","standalone",{{"action",action},{"value",std::string(std::string(action)=="review"?64:48,'a')}}});
  assert(receipt.state==(std::string(action)=="save"?"refused":"pending"));
  assert(!backend.machine_request_pending());backend.deliver(wire);
  assert(wire.posts==(std::string(action)=="save"?0:1));
 }
 {
  Json data={{"owner","standalone"},{"fresh",true},{"session","test-session"},{"revision","rev"},{"job",{{"state","idle"}}},{"capabilities",{{"profile_import",true}}}};
  StandaloneBackend backend;Http http;backend.observe(data);
  auto receipt=backend.submit({"profile_import","rev","standalone",{{"action","scan"},{"value",""}}});assert(receipt.state=="pending");backend.deliver(http);
  assert(http.script.find("WMP_PROFILE_IMPORT ACTION=scan ID=")==0);
  data["profile_import"]={{"id",receipt.id},{"state","files"},{"files",Json::array()}};backend.observe(data);assert(data["receipts"][receipt.id]["state"]=="complete");
  assert(backend.submit({"profile_import","rev","standalone",{{"action","review"},{"value","bad;G28"}}}).state=="refused");
  assert(backend.submit({"profile_import","rev","standalone",{{"action","save"},{"value",std::string(48,'a')}}}).state=="refused");
  data["profile_import"]={{"state","review"},{"token",std::string(48,'a')}};backend.observe(data);
  receipt=backend.submit({"profile_import","rev","standalone",{{"action","save"},{"value",std::string(48,'a')}}});assert(receipt.state=="pending");
  data["profile_import"]["token"]=std::string(48,'b');backend.observe(data);backend.deliver(http);assert(http.posts==1);
 }

 {
  Json data={{"owner","standalone"},{"fresh",true},{"session","test-session"},{"revision","rev"},{"job",{{"state","idle"}}},{"capabilities",{{"toolhead_action",true}}},{"attachment",{{"state","attached"},{"head","h1"}}}};
  StandaloneBackend backend;Http http;backend.observe(data);
  Request take={"take","rev","standalone",{{"head","h2"},{"attached","h1"}}};
  auto receipt=backend.submit(take);assert(receipt.state=="pending"&&http.posts==0);backend.deliver(http);
  assert(http.script.find("WMP_TOOLHEAD_ACTION HEAD=2 ACTION=take ID=")==0);
  assert(http.guard=="WMP_CHECK_COMMAND_GENERATION SESSION=test-session GENERATION=0");
  assert(http.script.find("SESSION=test-session ATTACHED=h1")!=std::string::npos);
  data["toolhead_operation"]={{"id",receipt.id},{"session","test-session"},{"head","h2"},{"action","take"},{"state","running"},{"message","Mounting head"}};
  backend.observe(data);assert(data["receipts"][receipt.id]["state"]=="pending");
  data["toolhead_operation"]["state"]="complete";data["attachment"]["head"]="h2";backend.observe(data);assert(data["receipts"][receipt.id]["state"]=="complete");
  assert(backend.submit(take).state=="refused"); // stale attachment
  Request dock={"dock","rev","standalone",{{"head","h2"},{"attached","h2"}}};
  receipt=backend.submit(dock);assert(receipt.state=="pending");
  data["attachment"]["head"]="h0";backend.observe(data);backend.deliver(http);assert(http.posts==1);
  backend.observe(data);assert(data["receipts"][receipt.id]["state"]=="refused");
  data["toolhead_operation"]["state"]="unknown";backend.observe(data);assert(backend.submit(dock).state=="refused");
 }

 {
  Json data={{"owner","standalone"},{"fresh",true},{"session","generation-session"},{"revision","same"},{"command_generation",4},{"job",{{"state","idle"}}},{"heater_limits",{{"h2",{{"min",0},{"max",290}}}}}};
  StandaloneBackend backend;Http wire;backend.observe(data);
  auto first=backend.submit({"temperature","same","standalone",{{"head","h2"},{"target",220}}});assert(first.state=="pending");
  data["command_generation"]=5;backend.observe(data);backend.deliver(wire);assert(wire.posts==0);
  auto second=backend.submit({"temperature","same","standalone",{{"head","h2"},{"target",220}}});assert(second.state=="pending");
  backend.deliver(wire);assert(wire.posts==1);
  assert(wire.guard=="WMP_CHECK_COMMAND_GENERATION SESSION=generation-session GENERATION=5");
  assert(wire.script=="SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=220");
 }
 assert(wmp_openace::UnifiedLoopbackHttp::allowed_query("/printer/objects/list"));
 assert(wmp_openace::UnifiedLoopbackHttp::allowed_query("/printer/objects/query?webhooks&print_stats&configfile=settings&toolhead=extruder&extruder2&gcode_macro%20WMP_EXTRUDER_STEP"));
 assert(!wmp_openace::UnifiedLoopbackHttp::allowed_query("/printer/objects/query?print_stats\r\nINJECT"));
 assert(!wmp_openace::UnifiedLoopbackHttp::allowed_query("/printer/objects/query?print_stats&print_stats"));

 Json status={{"webhooks",{{"state","ready"}}},{"print_stats",{{"state","standby"}}},{"extruder2",{{"temperature",28.0},{"target",0.0}}},{"configfile",{{"settings",{{"extruder2",{{"min_temp",0},{"max_temp",290}}}}}}}};
 auto s=native::project(status,Json::object(),false,"session");assert(s["capabilities"]["temperature"]==true);
 // A current HTTP reply with standby print_stats must not hide a shutdown.
 for(const auto*state:{"shutdown","error","startup","unknown"}){
  auto raw=status;raw["webhooks"]["state"]=state;
  auto unavailable=native::project(raw,Json::object(),false,"session");
  assert(!unavailable["fresh"].get<bool>());
  StandaloneBackend backend;Http wire;backend.observe(unavailable);
  assert(backend.submit({"temperature",unavailable.at("revision"),"standalone",{{"head","h2"},{"target",220}}}).state=="refused");
  backend.deliver(wire);assert(wire.posts==0);
  // A request queued while ready must also be dropped if shutdown arrives.
  auto ready=native::project(status,Json::object(),false,"session");backend.observe(ready);
  auto receipt=backend.submit({"temperature",ready.at("revision"),"standalone",{{"head","h2"},{"target",220}}});assert(receipt.state=="pending");
  backend.observe(unavailable);backend.deliver(wire);assert(wire.posts==0);
  backend.observe(unavailable);assert(unavailable["receipts"][receipt.id]["state"]=="refused");
 }
 auto missing_ready=status;missing_ready.erase("webhooks");assert(native::project(missing_ready,Json::object(),false,"session")["fresh"]==false);
 status["configfile"]["settings"]["extruder2"]["nozzle_diameter"]=0.4;
 s=native::project(status,Json::object(),false,"session");
 assert(s["heads"][0]["nozzle"]["diameter"]=="0.4 mm"&&s["heads"][0]["nozzle"]["material"]=="Unknown");
 {
  auto raw=status;raw["wm_material"]={{"session_id","nozzle-session"},{"nozzle_settings_protocol",1},{"nozzle_revision",std::string(64,'a')},{"nozzles",{{"h2",{{"diameter",0.4},{"active_diameter",0.4},{"material","Hardened steel"},{"restart_required",false}}}}}};
  auto current=native::project(raw,Json::object(),false,"unused");
  assert(current["capabilities"]["save_nozzle"]==true);
  StandaloneBackend nozzles;Http nh;nozzles.observe(current);
  Request save={"save_nozzle",current["revision"],"standalone",{{"head","h2"},{"diameter",0.6},{"material","Stainless steel"},{"expected",std::string(64,'a')}}};
  auto result=nozzles.submit(save);assert(result.state=="pending");nozzles.deliver(nh);
  assert(nh.script=="WMP_SET_NOZZLE HEAD=2 DIAMETER=0.600000 MATERIAL=1 EXPECT="+std::string(64,'a')+" SESSION=nozzle-session ID="+result.id);
  current["nozzle_save"]={{"id",result.id},{"session","nozzle-session"},{"head","h2"},{"state","complete"}};
  nozzles.observe(current);assert(current["receipts"][result.id]["state"]=="pending"); // Receipt alone is not readback.
  current["nozzle_settings"]["h2"]={{"diameter",0.6},{"active_diameter",0.4},{"material","Stainless steel"},{"restart_required",true}};
  current["nozzle_revision"]=std::string(64,'b');nozzles.observe(current);
  assert(current["receipts"][result.id]["state"]=="complete");
  assert(current["receipts"][result.id]["message"]=="Saved. Restart Klipper to apply the diameter.");
  assert(nozzles.submit(save).state=="refused");
  save.arguments["expected"]=std::string(64,'b');save.arguments["diameter"]=0.5;
  assert(nozzles.submit(save).state=="refused"&&nh.posts==1);
 }
 for(const auto mode:{"live","pending","error"}){
  StandaloneBackend backend;Http transport;
  auto current=s;current["session"]="nozzle-live-session";current["capabilities"]["save_nozzle"]=true;
  current["nozzle_revision"]=std::string(64,'a');
  current["nozzle_settings"]["h2"]={{"diameter",0.4},{"material","Hardened steel"}};
  backend.observe(current);
  auto result=backend.submit({"save_nozzle",current["revision"],"standalone",{{"head","h2"},{"diameter",0.6},{"material","Stainless steel"},{"expected",std::string(64,'a')}}});
  assert(result.state=="pending");backend.deliver(transport);
  current["nozzle_settings"]["h2"]={{"diameter",0.6},{"active_diameter",std::string(mode)=="live"?0.6:0.4},{"material","Stainless steel"},{"restart_required",false},{"apply_pending",std::string(mode)=="pending"},{"apply_error",std::string(mode)=="error"?"planner unavailable":""}};
  current["nozzle_revision"]=std::string(64,'b');
  current["nozzle_save"]={{"id",result.id},{"session","nozzle-live-session"},{"head","h2"},{"state","complete"}};
  backend.observe(current);
  const auto message=current["receipts"][result.id]["message"].get<std::string>();
  assert(message.find("Restart")==std::string::npos);
  if(std::string(mode)=="live")assert(message=="Nozzle settings saved.");
  if(std::string(mode)=="pending")assert(message.find("idle")!=std::string::npos);
  if(std::string(mode)=="error")assert(message.find("planner unavailable")!=std::string::npos);
 }
 StandaloneBackend b;Http http;b.observe(s);
 Request r={"temperature",s.at("revision"),"standalone",{{"head","h2"},{"target",220}}};
 auto receipt=b.submit(r);assert(receipt.state=="pending"&&http.posts==0);b.deliver(http);
 assert(http.script=="SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=220");
 b.observe(s);assert(s["receipts"][receipt.id]["state"]=="pending");
 assert(b.submit(r).state=="refused");s["heads"][0]["target"]=220;b.observe(s);assert(s["receipts"][receipt.id]["state"]=="complete");
 r.arguments["target"]=291;assert(b.submit(r).state=="refused");r.arguments["target"]=-1;assert(b.submit(r).state=="refused");r.arguments["target"]=220;r.arguments["head"]="h0";assert(b.submit(r).state=="refused");r.arguments["head"]="h2\nG28";assert(b.submit(r).state=="refused");r.arguments["head"]="h2";
 r.arguments["target"]=0;receipt=b.submit(r);assert(receipt.state=="pending");s["owner"]="openace";b.observe(s);b.deliver(http);b.observe(s);assert(http.posts==1&&s["receipts"][receipt.id]["state"]=="refused");
 s["owner"]="standalone";b.observe(s);receipt=b.submit(r);b.invalidate();b.deliver(http);b.observe(s);assert(http.posts==1&&s["receipts"][receipt.id]["state"]=="refused");
 receipt=b.submit(r);http.fail=true;b.deliver(http);b.deliver(http);b.observe(s);assert(http.posts==2&&s["receipts"][receipt.id]["state"]=="unknown");
 // Heater configuration changes invalidate a rendered request, unlike telemetry.
 status["extruder2"]["temperature"]=80.0;assert(native::project(status,Json::object(),false,"session")["revision"]==s["revision"]);
 status["configfile"]["settings"]["extruder2"]["max_temp"]=280;assert(native::project(status,Json::object(),false,"session")["revision"]!=s["revision"]);

 // Physical temperature is shared across modes, with no virtual-tool command.
 // openACE manual heating is available only with explicit idle-operation evidence.
 {
  Json ace={{"session_id",42},{"operation",nullptr}};
  auto state=native::project(status,ace,true,"unused");
  assert(state["capabilities"]["temperature"]==true);
  StandaloneBackend heater;wmp_openace::UiChannel channel;OpenAceBackend acebackend(channel);
  NativeBackend routed(acebackend,heater);routed.owner("openace");heater.observe(state);Http wire;
  Request heat={"temperature",state["revision"],"openace",{{"head","h2"},{"target",215}}};
  auto result=routed.submit(heat);assert(result.state=="pending");heater.deliver(wire);
  assert(wire.script=="SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=215");
  heater.observe(state);assert(state["receipts"][result.id]["state"]=="pending");
  state["heads"][0]["target"]=215;heater.observe(state);
  assert(state["receipts"][result.id]["state"]=="complete");
  assert(state["receipts"][result.id]["owner"]=="openace");
  heat.arguments["target"]=300;assert(routed.submit(heat).state=="refused");heat.arguments["target"]=0;
  result=routed.submit(heat);assert(result.state=="pending");
  state["heater_manual_ready"]=false;heater.observe(state);heater.deliver(wire);heater.observe(state);
  assert(wire.posts==1&&state["receipts"][result.id]["state"]=="refused");
  for(const auto&operation: {Json("loading"),Json::object()}) {
   ace["operation"]=operation;auto blocked=native::project(status,ace,true,"unused");
   heater.observe(blocked);assert(!routed.unavailable("temperature").empty());
  }
  ace.erase("operation");auto missing=native::project(status,ace,true,"unused");heater.observe(missing);
  assert(!routed.unavailable("temperature").empty());
  ace["operation"]=nullptr;auto printing=status;printing["print_stats"]["state"]="printing";
  auto blocked=native::project(printing,ace,true,"unused");heater.observe(blocked);
  assert(!routed.unavailable("temperature").empty());
  state=native::project(status,ace,true,"unused");heater.observe(state);
  result=routed.submit(heat);assert(result.state=="pending");ace["session_id"]=43;
  state=native::project(status,ace,true,"unused");heater.observe(state);heater.deliver(wire);
  assert(wire.posts==1);
  Request forbidden={"step",state["revision"],"openace",{{"head","h2"},{"mm",5}}};
  assert(heater.submit(forbidden).state=="refused");
 }

 StandaloneBackend motion;Http mh;
 status["wm_material"]={{"attachment",{{"state","attached"},{"head","h2"}}}};status["toolhead"]={{"extruder","extruder2"}};status["extruder2"]["can_extrude"]=true;status["gcode_macro WMP_EXTRUDER_STEP"]=Json::object();
 auto ms=native::project(status,Json::object(),false,"session");motion.observe(ms);
 Request step={"step",ms.at("revision"),"standalone",{{"head","h2"},{"mm",-20}}};
 auto mr=motion.submit(step);assert(mr.state=="pending"&&motion.machine_request_pending());motion.deliver(mh);motion.observe(ms);
 assert(!motion.machine_request_pending());
 assert(mh.script=="WMP_EXTRUDER_STEP HEAD=2 MM=-20");assert(ms["receipts"][mr.id]["state"]=="complete");
 step.arguments["mm"]=51;assert(motion.submit(step).state=="refused");step.arguments["mm"]=20;
 ms["heads"][0]["can_extrude"]=false;motion.observe(ms);assert(motion.submit(step).state=="refused");ms["heads"][0]["can_extrude"]=true;
 ms["job"]["state"]="printing";motion.observe(ms);assert(motion.submit(step).state=="refused");
 ms["job"]["state"]="idle";motion.observe(ms);mr=motion.submit(step);assert(mr.state=="pending");ms["attachment"]["head"]="h1";motion.observe(ms);motion.deliver(mh);assert(mh.posts==1);
 ms["attachment"]["head"]="h2";ms["heads"][0]["active"]=false;motion.observe(ms);mr=motion.submit(step);assert(mr.state=="pending");motion.deliver(mh);assert(mh.posts==2);
 ms["job"]["state"]="paused";motion.observe(ms);assert(motion.submit(step).state=="refused");ms["job"]["state"]="idle";

 StandaloneBackend profiles;Http ph;
 ms["identity_revision"]=std::string(64,'a');ms["capabilities"]["save_identity"]=true;profiles.observe(ms);
 auto draft=ms["sources"][0];draft["identity"]={{"brand","Generic"},{"material","PETG"},{"color","#aabbcc"}};
 Request save={"save_identity",ms.at("revision"),"standalone",{{"draft",draft}}};
 auto pr=profiles.submit(save);assert(pr.state=="pending"&&!profiles.machine_request_pending());profiles.deliver(ph);profiles.observe(ms);
 assert(ph.script.find("WMP_SET_FILAMENT HEAD=2 EXPECT="+std::string(64,'a')+" PROFILE=")==0);
 assert(ms["receipts"][pr.id]["state"]=="pending");ms["sources"][0]["identity"]=draft["identity"];profiles.observe(ms);assert(ms["receipts"][pr.id]["state"]=="complete");
 save.arguments["draft"]["identity"]["color"]="red\nG28";assert(profiles.submit(save).state=="refused");

 // Only explicit backend evidence permits recipe changes to an unused head
 // during an active job. The ordinary editor still requires explicit Save.
 for(const auto*job:{"printing","paused"})for(int mode=0;mode<5;++mode){
  auto current=ms;current["job"]["state"]=job;
  current["filament_recipe_write_protocol"]=mode==4?2:1;
  current["filament_recipe_write"]={{"h2",{{"allowed",mode==0?Json(true):mode==3?Json("true"):Json(false)},{"reason","Head used by active print"}}}};
  if(mode==2)current.erase("filament_recipe_write_protocol");
  StandaloneBackend settings;Http wire;settings.observe(current);
  native::StockIdentityEdit editor;assert(editor.begin(current,"h2","material"));
  assert(wire.posts==0);
  auto result=editor.choose_fields(current,{{"material","ASA"},{"nozzle_temp",245}},settings);
  assert(result.state==(mode==0?"pending":"refused"));settings.deliver(wire);assert(wire.posts==(mode==0?1:0));
  if(mode==0){assert(wire.script.find("WMP_SET_FILAMENT HEAD=2")!=std::string::npos);assert(wire.script.find(" PAUSE=")==std::string::npos);}
  // A once-permitted draft cannot retain permission after current evidence changes.
  auto allowed=current;allowed["filament_recipe_write_protocol"]=1;allowed["filament_recipe_write"]["h2"]["allowed"]=true;
  native::StockIdentityEdit stale;assert(stale.begin(allowed,"h2","material"));
  allowed["filament_recipe_write"]["h2"]["allowed"]=false;
  StandaloneBackend revoked;revoked.observe(allowed);
  assert(stale.choose(allowed,"ASA",revoked).state=="refused");
 }
 // Cosmetic metadata does not reserve motion or require paused-print service.
 for(const auto*job:{"printing","paused"})for(bool recipe_change:{false,true})for(bool identifying:{false,true}){
  auto current=ms;current["job"]["state"]=job;current["filament_operation"]={{"state","running"}};
  current["identification"]={{"state",identifying?"running":"idle"}};
  auto updated=current["sources"][0];updated["identity"]["color"]="#123456";updated["identity"]["brand"]="New brand";
  if(recipe_change)updated["identity"]["nozzle_temp"]=245;
  StandaloneBackend settings;Http wire;settings.observe(current);
  auto result=settings.submit({"save_identity",current.at("revision"),"standalone",{{"draft",updated}}});
  assert(result.state==(!recipe_change&&!identifying?"pending":"refused"));
  settings.deliver(wire);assert(wire.posts==(!recipe_change&&!identifying?1:0));
  if(wire.posts)assert(wire.script.find(" PAUSE_ORIGIN=")==std::string::npos);
 }

 // Idle recipe edits conflict only with service using that same head.
 for(const auto*active_head:{"h0","h2","","bad"})for(const auto*state:{"pending","running","unknown"}){
  auto current=ms;current["job"]["state"]="idle";current["filament_operation"]={{"state",state},{"head",active_head}};
  current["toolhead_operation"]={{"state","running"},{"head","h2"}};
  auto changed=current["sources"][0];changed["identity"]["material"]="ASA";
  StandaloneBackend settings;Http wire;settings.observe(current);
  const bool blocked=std::string(state)!="unknown"&&std::string(active_head)!="h0";
  auto result=settings.submit({"save_identity",current.at("revision"),"standalone",{{"draft",changed}}});
  assert(result.state==(blocked?"refused":"pending"));settings.deliver(wire);assert(wire.posts==(blocked?0:1));
 }

 // A malformed refreshed capability must retire a queued request even if
 // validation throws before building the HTTP body. No phantom pending save.
 save.arguments["draft"]=draft;
 profiles.observe(ms);auto broken=profiles.submit(save);assert(broken.state=="pending");
 auto malformed_capabilities=ms;malformed_capabilities["capabilities"]=42;profiles.observe(malformed_capabilities);
 assert(profiles.submit(save).state=="refused");
 assert(profiles.unresolved_request_id()==broken.id); // Preserve the earlier queue.
 const auto posts_before=ph.posts;profiles.deliver(ph);profiles.observe(ms);
 assert(ph.posts==posts_before&&ms["receipts"][broken.id]["state"]=="refused");
 assert(profiles.unresolved_request_id().empty());
 assert(profiles.submit(save).state=="pending");

 status["wm_material"]={{"identity_writable",true},{"identity_revision",std::string(64,'b')},{"identities",{{"h2",draft["identity"]}}}};
 auto projected=native::project(status,Json::object(),false,"session");
 assert(projected["sources"][0]["identity"]==draft["identity"]);
 assert(projected["heads"][0]["loaded"]["state"]=="unknown");
 assert(projected["capabilities"]["save_identity"]==true);
 assert(projected["revision"]!=ms["revision"]);
 // Mapped Start is sent once through the helper, with helper and ACE sessions
 // kept separate; matching HTTP acknowledgement alone cannot admit the job.
 {
  auto context=ms;context["owner"]="openace";context["session"]="42";context["ace_session"]=42;context["ace_config_revision"]=7;
  context["print_helper_session"]="helper-1";context["openace_print_start_protocol"]=1;context["heater_manual_ready"]=true;
  context["job"]={{"state","idle"},{"id",""}};
  context["routes"]=Json::array({{{"id","T7"},{"tool",7},{"head","h2"},{"source","external:h2"},{"eligible",true},{"sliced_rows",Json::array({"0"})}}});
  context["files"]=Json::array({{{"id","part.gcode"},{"metadata_error",""},{"sliced",Json::array({{{"id","0"}}})},{"file_identity",{{"size",1234},{"modified",100.0}}}}});
  Request request={"start_print",context["revision"],"openace",{{"file","part.gcode"},{"routes",{{"0","T7"}}},{"options",{{"leveling",false},{"timelapse",true}}}}};
  StandaloneBackend transport;wmp_openace::UiChannel channel;OpenAceBackend management(channel);NativeBackend router(management,transport);router.owner("openace");
  Http wire;std::string settled;int prepared=0;
  transport.print_context([&](const Json&options){++prepared;assert(options["timelapse"]==true);return true;},[&](const std::string&state){settled=state;});
  transport.observe(context);auto result=router.submit(request);assert(result.state=="pending");transport.deliver(wire);transport.deliver(wire);
  assert(wire.posts==1&&prepared==1);const std::string prefix="WMP_START_PRINT REQUEST=";assert(wire.script.find(prefix)==0);
  std::string decoded,hex=wire.script.substr(prefix.size());for(std::size_t i=0;i<hex.size();i+=2)decoded+=char(std::stoi(hex.substr(i,2),nullptr,16));
  auto payload=Json::parse(decoded);assert(payload["pairs"]==Json::array({Json::array({0,7})}));assert(payload["session"]=="helper-1");assert(payload["ace_session"]==42);assert(!payload.contains("mapping"));
  context["print_submission"]={{"id",result.id},{"session","helper-1"},{"file","part.gcode"},{"state","submitted"}};
  context["job"]={{"state","printing"},{"id","part.gcode"}};transport.observe(context);assert(context["receipts"][result.id]["state"]=="pending");
  context["ace_job"]={{"active",true},{"source","override"},{"file","part.gcode"},{"pairs",Json::array({Json::array({0,2})})},{"config_revision",7}};
  transport.observe(context);assert(context["receipts"][result.id]["state"]=="pending");
  context["ace_job"]["pairs"]=payload["pairs"];context["ace_job"]["config_revision"]=8;
  transport.observe(context);assert(context["receipts"][result.id]["state"]=="pending");
  context["ace_job"]["config_revision"]=7;transport.observe(context);
  assert(context["receipts"][result.id]["state"]=="complete"&&settled=="complete");
  // Freeze file identity at the click even if a caller accidentally retains
  // revision while refreshing metadata. No flags or command may be staged.
  {
   auto ready=context;ready["job"]["state"]="idle";
   StandaloneBackend changed;Http no_send;int staged=0;
   changed.print_context([&](const Json&){++staged;return true;});changed.observe(ready);
   auto ticket=changed.submit(request);assert(ticket.state=="pending");
   ready["files"][0]["file_identity"]["size"]=4321;changed.observe(ready);changed.deliver(no_send);changed.observe(ready);
   assert(no_send.posts==0&&staged==0&&ready["receipts"][ticket.id]["state"]=="refused");
  }
  // Lost response remains unresolved, sends no retry, then reconciles from
  // the matching helper receipt and frozen openACE job.
  StandaloneBackend lost;Http timeout;timeout.fail=true;lost.print_context([](const Json&){return true;});
  context["job"]["state"]="idle";context["print_submission"]=Json::object();context["ace_job"]=nullptr;lost.observe(context);
  result=lost.submit(request);assert(result.state=="pending");lost.deliver(timeout);lost.deliver(timeout);lost.observe(context);
  assert(timeout.posts==1&&context["receipts"][result.id]["state"]=="unknown");assert(lost.submit(request).state=="refused");
  context["print_submission"]={{"id",result.id},{"session","helper-1"},{"file","part.gcode"},{"state","submitted"}};
  context["job"]["state"]="paused";context["ace_job"]={{"active",true},{"source","override"},{"file","part.gcode"},{"pairs",payload["pairs"]},{"config_revision",7}};
  lost.observe(context);assert(context["receipts"][result.id]["state"]=="complete");
  StandaloneBackend failed;Http error;error.fail=true;std::string terminal;
  failed.print_context([](const Json&){return true;},[&](const std::string&s){terminal=s;});
  context["job"]["state"]="idle";context["print_submission"]=Json::object();context["ace_job"]=nullptr;failed.observe(context);
  auto f=failed.submit(request);assert(f.state=="pending");failed.deliver(error);
  context["print_submission"]={{"id",f.id},{"session","42"},{"file","part.gcode"},{"state","not_started"},{"error","File changed during preparation"}};
  failed.observe(context);assert(failed.machine_request_pending()&&terminal=="unknown");
  context["print_submission"]["session"]="helper-1";failed.observe(context);
  assert(!failed.machine_request_pending()&&terminal=="refused"&&error.posts==1);
  assert(context["receipts"][f.id]["message"].get<std::string>().find("File changed during preparation")!=std::string::npos);

 }
 // Standalone Start requires an explicit native-context adapter. It resolves
 // physical heads from routes, never from the displayed virtual T alias.
 auto ps=ms;ps["capabilities"]["start_print"]=true;ps["print_start_protocol"]=1;
 ps["physical_mapping"]=Json::array({0,2,2,3});ps["job"]={{"state","idle"},{"id",""}};
 ps["routes"]=Json::array({{{"id","T1"},{"tool",1},{"head","h2"},{"source","external:h2"},{"eligible",true},{"sliced_rows",Json::array({"0"})}}});
 ps["files"]=Json::array({{{"id","part.gcode"},{"metadata_error",""},{"sliced",Json::array({{{"id","0"}}})},{"file_identity",{{"size",1234},{"modified",100.0}}}}});
 Request start={"start_print",ps.at("revision"),"standalone",{{"file","part.gcode"},{"routes",{{"0","T1"}}},{"options",{{"leveling",true},{"timelapse",false}}}}};
 for(const auto*field:{"brand","color"})for(const auto&bad:{Json(),Json(3),Json::object(),Json("not-a-color")}){
  if(std::string(field)=="brand"&&bad.is_string())continue;
  auto damaged=ps;for(auto&source:damaged["sources"])if(source["head"]=="h2")source["identity"][field]=bad;
  bool refused=false;try{standalone_print_request(damaged,start.arguments,"bad-cosmetic");}catch(const std::exception&e){refused=std::string(e.what()).find("Correct the selected filament")!=std::string::npos;}assert(refused);
 }
 // Real error-state projection feeds the ordinary Take and print-request consumers.
 for(bool sd:{false,true})for(bool paused:{false,true}){
  Json raw_error={{"webhooks",{{"state","ready"}}},{"print_stats",{{"state","error"}}},{"virtual_sdcard",{{"is_active",sd}}},{"pause_resume",{{"is_paused",paused}}}};
  auto candidate=ps;candidate["job"]=native::project(raw_error,Json::object(),false,"test")["job"];
  candidate["capabilities"]["toolhead_action"]=true;candidate["attachment"]={{"state","empty"}};
  StandaloneBackend take_backend;take_backend.observe(candidate);
  assert((take_backend.submit({"take",candidate.at("revision"),"standalone",{{"head","h2"},{"attached","none"}}}).state=="pending")==(!sd&&!paused));
  bool admitted=true;try{standalone_print_request(candidate,start.arguments,"error-retry");}catch(const std::exception&){admitted=false;}
  assert(admitted==(!sd&&!paused));
  StandaloneBackend start_backend;start_backend.print_context([](const Json&){return true;});start_backend.observe(candidate);
  assert((start_backend.submit(start).state=="pending")==(!sd&&!paused));
 }
 StandaloneBackend printing;Http sh;printing.observe(ps);assert(printing.submit(start).state=="refused");
 int preparations=0;printing.print_context([&](const Json&o){++preparations;assert(o.at("leveling")==true);assert(sh.posts==0);return true;});
 auto sr=printing.submit(start);assert(sr.state=="pending");printing.deliver(sh);assert(preparations==1&&sh.posts==1);
 const std::string prefix="WMP_START_PRINT REQUEST=";assert(sh.script.find(prefix)==0);std::string payload;
 auto encoded=sh.script.substr(prefix.size());for(std::size_t i=0;i<encoded.size();i+=2)payload+=char(std::stoi(encoded.substr(i,2),nullptr,16));auto request=Json::parse(payload);
 assert(request["mapping"]["0"]==2);assert(request["expected_mapping"]==ps["physical_mapping"]);assert(request["id"]==sr.id);
 printing.deliver(sh);assert(sh.posts==1);printing.observe(ps);assert(ps["receipts"][sr.id]["state"]=="pending");
 ps["print_submission"]={{"id",sr.id},{"session",ps["session"]},{"file","part.gcode"},{"state","submitted"}};
 ps["job"]={{"id","wrong.gcode"},{"state","printing"}};printing.observe(ps);assert(ps["receipts"][sr.id]["state"]=="pending");
 ps["job"]["id"]="part.gcode";printing.observe(ps);assert(ps["receipts"][sr.id]["state"]=="complete");
 ps["job"]["state"]="idle";printing.observe(ps);auto bad=start;bad.arguments["routes"]["0"]="T3";assert(printing.submit(bad).state=="refused");
 bad=start;bad.arguments["routes"]["1"]="T1";assert(printing.submit(bad).state=="refused");
 {
  auto ready=ps;StandaloneBackend changed;Http no_send;int staged=0;
  changed.print_context([&](const Json&){++staged;return true;});changed.observe(ready);
  auto ticket=changed.submit(start);assert(ticket.state=="pending");
  ready["files"][0]["file_identity"]["modified"]=101.0;changed.observe(ready);changed.deliver(no_send);changed.observe(ready);
  assert(no_send.posts==0&&staged==0&&ready["receipts"][ticket.id]["state"]=="refused");
 }
 StandaloneBackend refusal;Http rh;refusal.observe(ps);int settlements=0;refusal.print_context([](const Json&){return false;},[&](const std::string&){++settlements;});auto rr=refusal.submit(start);assert(rr.state=="pending");refusal.deliver(rh);refusal.observe(ps);assert(rh.posts==0&&settlements==0&&ps["receipts"][rr.id]["state"]=="refused");
 StandaloneBackend uncertain;Http uh;uncertain.observe(ps);uncertain.print_context([](const Json&){throw std::runtime_error("context uncertain");return true;});auto ur=uncertain.submit(start);uncertain.deliver(uh);uncertain.observe(ps);assert(uh.posts==0&&ps["receipts"][ur.id]["state"]=="unknown");

 // Sequenced standalone requests do not reuse identifiers against an older poll.
 {
  auto ready=ps;ready["print_sequence_protocol"]=1;ready["print_request_sequence"]=1050;
  StandaloneBackend sequenced;Http no_send;sequenced.print_context([](const Json&){return false;});sequenced.observe(ready);
  auto first=sequenced.submit(start);assert(first.id=="print_1051"&&first.state=="pending");sequenced.deliver(no_send);assert(no_send.posts==0);
  sequenced.observe(ready);auto next=sequenced.submit(start);assert(next.id=="print_1052"&&next.state=="pending");sequenced.deliver(no_send);
  ready["session"]="replacement-session";ready["print_request_sequence"]=0;sequenced.observe(ready);
  auto restarted=sequenced.submit(start);assert(restarted.id=="print_1"&&restarted.state=="pending");
 }
 // Actual native flag coordinator: preflight refuses without touching flags;
 // unknown delivery holds them until a matching refusal or admission arrives.
 unsigned char screen_flag=0,selected_flag=1,available_flag=0;
 native::PrintContext context;context.bind(&screen_flag,&selected_flag,&available_flag);
 assert(!context.prepare(Json{{"timelapse",true}}));assert(screen_flag==0&&selected_flag==1);
 available_flag=1;assert(context.prepare(Json{{"timelapse",false}}));assert(screen_flag==1&&selected_flag==0);
 context.settle("unknown");assert(context.armed());assert(!context.prepare(Json{{"timelapse",false}}));
 context.settle("refused");assert(!context.armed()&&screen_flag==0&&selected_flag==1);
 assert(context.prepare(Json{{"timelapse",false}}));screen_flag=0;context.settle("refused");assert(!context.armed()&&screen_flag==0&&selected_flag==0); // consumed: retire without restoration
 context.settle("complete");assert(!context.armed()&&selected_flag==0);
 assert(context.prepare(Json{{"timelapse",false}}));selected_flag=1;context.settle("refused");
 assert(!context.armed()&&screen_flag==1&&selected_flag==1);assert(!context.prepare(Json{{"timelapse",false}}));screen_flag=0;
 assert(context.prepare(Json{{"timelapse",true}}));assert(screen_flag==1&&selected_flag==1&&available_flag==1);
 context.settle("complete");assert(!context.armed()&&selected_flag==1);
 screen_flag=0; // Model the stock consumer taking the accepted start flag.
 StandaloneBackend late;Http lh;lh.fail=true;late.observe(ps);
 late.print_context([&](const Json&o){return context.prepare(o);},[&](const std::string&state){context.settle(state);});
 auto lr=late.submit(start);assert(lr.state=="pending");late.deliver(lh);late.observe(ps);
 assert(lh.posts==1&&context.armed()&&ps["receipts"][lr.id]["state"]=="unknown");
 ps["print_submission"]={{"id",lr.id},{"session",ps["session"]},{"file","part.gcode"},{"state","refused"}};
 late.observe(ps);assert(!context.armed()&&screen_flag==0&&ps["receipts"][lr.id]["state"]=="refused");assert(lh.posts==1);

 // A preparation error is terminal only with the exact helper receipt, even
 // after the HTTP response was lost. It never proves settings were rolled back.
 for(const char* mismatch:{"id","session","file"}){
  auto data=ps;data.erase("print_submission");StandaloneBackend prep;Http wire;wire.fail=true;
  unsigned char screen=0,selected=1,available=1;native::PrintContext flags;
  flags.bind(&screen,&selected,&available);
  prep.print_context([&](const Json&o){return flags.prepare(o);},[&](const std::string&s){flags.settle(s);});
  prep.observe(data);auto ticket=prep.submit(start);assert(ticket.state=="pending");prep.deliver(wire);
  data["print_submission"]={{"id",ticket.id},{"session",data["session"]},{"file","part.gcode"},{"state","not_started"}};
  auto wrong=data;wrong["print_submission"][mismatch]="different";prep.observe(wrong);
  assert(flags.armed()&&!prep.machine_request_pending());
  prep.observe(data);
  assert(!flags.armed()&&screen==0&&selected==1&&!prep.machine_request_pending()&&prep.unresolved_request_id().empty());
  assert(data["receipts"][ticket.id]["state"]=="refused");
  assert(data["receipts"][ticket.id]["message"].get<std::string>().find("may have changed")!=std::string::npos);
  prep.deliver(wire);assert(wire.posts==1); // No automatic retry.
  data["job"]["state"]="paused";prep.observe(data);assert(prep.submit(start).state=="refused");
  data["job"]["state"]="idle";prep.observe(data);auto next=prep.submit(start);
  assert(next.state=="pending"&&next.id!=ticket.id&&wire.posts==1);
 }

 for(bool required:{false,true}){
  auto current=ms;current["capabilities"]["confirm_filament"]=true;current["session"]="paused-check";current["job"]["state"]="paused";
  current["paused_filament"]={{"available",true},{"head",required?"h1":"h2"},{"filament_required",Json::array({"h2"})},{"origin",{{"id",std::string(32,'a')},{"head",required?"h1":"h2"},{"session","paused-check"}}}};
  StandaloneBackend checking;Http wire;checking.observe(current);
  auto receipt=checking.submit({"confirm_filament",current["revision"],"standalone",{{"head","h2"},{"state","loaded"}}});assert(receipt.state=="pending");
  checking.deliver(wire);assert(wire.posts==1&&wire.script.find("WMP_CONFIRM_FILAMENT HEAD=2 STATE=loaded")==0);
  assert(wire.script.find("EXPECT="+std::string(64,'a'))!=std::string::npos);
  for(auto&head:current["heads"])if(head["id"]=="h2")head["loaded"]={{"state","loaded"},{"evidence","operator"}};
  checking.observe(current);assert(current["receipts"][receipt.id]["state"]=="complete");
 }
 StandaloneBackend checking;Http ch;auto cs=ms;cs["capabilities"]["confirm_filament"]=true;cs["job"]["state"]="idle";cs["session"]="session-check";checking.observe(cs);
 Request check={"confirm_filament",cs["revision"],"standalone",{{"head","h2"},{"state","loaded"}}};auto cr=checking.submit(check);assert(cr.state=="pending");checking.deliver(ch);
 assert(ch.script=="WMP_CONFIRM_FILAMENT HEAD=2 STATE=loaded SESSION=session-check EXPECT="+std::string(64,'a'));
 checking.observe(cs);assert(cs["receipts"][cr.id]["state"]=="pending");cs["heads"][0]["loaded"]={{"state","loaded"},{"evidence","sensor"}};checking.observe(cs);assert(cs["receipts"][cr.id]["state"]=="complete");
 cs["job"]["state"]="paused";checking.observe(cs);assert(checking.submit(check).state=="refused");

 {
 // Helper plans become head-bound native procedures, without copying non-string metadata.
 auto exposed=status;exposed["wm_material"]={{"filament_sequence_protocol",1},{"filament_operation",Json::object()},
 {"filament_procedure_errors",{{"h2:unload","Heat Head 3 to 235 C before unload"}}},
 {"filament_procedures",Json::array({{{"head","h2"},{"action","load"},{"source","external:h2"},{"token",std::string(64,'b')},{"description","Feed 100 mm without XYZ movement"},{"target",250}}})}};
 exposed["wm_material"]["filament_materials"]=Json::array({"PLA","PC","PA"});
 exposed["wm_material"]["identities"]={{"h2",{{"brand","Maker Co"},{"material","PC"},{"color","#112233"}}}};
 auto projected=native::project(exposed,Json::object(),false,"session");
 assert(projected["materials"].size()==22);
 for(const auto*name:{"PLA","PC","PA","PCTG"})assert(std::find(projected["materials"].begin(),projected["materials"].end(),name)!=projected["materials"].end());
 assert(std::find(projected["brands"].begin(),projected["brands"].end(),"Maker Co")!=projected["brands"].end());
 auto brands=native::filament_brands(Json::array({{{"identity",{{"brand","Sunlu"}}}},{{"identity",{{"brand","a custom maker"}}}}}));
 assert(std::find(brands.begin(),brands.end(),"Sunlu")!=brands.end());
 assert(std::find(brands.begin(),brands.end(),"SUNLU")==brands.end());
 assert(std::find(brands.begin(),brands.end(),"a custom maker")!=brands.end());
 for(std::size_t i=1;i<brands.size();++i)assert(brand_sort_key(brands[i-1].get<std::string>())<brand_sort_key(brands[i].get<std::string>()));
 assert(projected["capabilities"]["load"]==true&&projected["capabilities"]["unload"]==true);
 assert(projected["procedures"][0]["revision"]==projected["revision"]);
 assert(!projected["procedures"][0].contains("target"));
 assert(projected["procedure_errors"]["h2:unload"]=="Heat Head 3 to 235 C before unload");
 assert(native::project(status,Json::object(),false,"session")["capabilities"]["load"]==false);
 // Material sequence IDs remain bounded across many requests and use the
 // advertised high-water mark, local unsent gaps, and current session.
 for(bool filament:{false,true}){
  auto data=cs;data["job"]["state"]="idle";data["material_request_sequence_protocol"]=1;
  data["filament_request_sequence"]=1050;data["toolhead_request_sequence"]=2050;
  data["capabilities"][filament?"load":"toolhead_action"]=true;
  data["attachment"]={{"state","attached"},{"head","h1"}};
  std::string procedure(64,'b');
  data["procedures"]=Json::array({{{"action","load"},{"head","h2"},{"source","external:h2"},{"token",procedure},{"revision",data["revision"]}}});
  Request request={filament?"load":"take",data["revision"],"standalone",filament?
   Json{{"head","h2"},{"source","external:h2"},{"procedure_token",procedure}}:
   Json{{"head","h2"},{"attached","h1"}}};
  StandaloneBackend backend;Http wire;const std::string kind=filament?"filament":"toolhead";
  for(int index=1;index<=3;++index){
   if(index==3){data["session"]="new-session";data["filament_request_sequence"]=0;data["toolhead_request_sequence"]=0;}
   backend.observe(data);auto receipt=backend.submit(request);
   const auto number=index==3?1:(filament?1050:2050)+index;
   assert(receipt.state=="pending"&&receipt.id==kind+"_"+std::to_string(number));
   backend.deliver(wire);
   assert(wire.script.find(" SEQUENCE="+std::to_string(number))!=std::string::npos);
   assert(wire.script.find(" SESSION="+data["session"].get<std::string>())!=std::string::npos);
   if(index==3){
    data[filament?"filament_operation":"toolhead_operation"]={{"id",receipt.id},{"session",data["session"]},{"previous_session","old-session"},{"head","h2"},{"action",filament?"load":"take"},{"state","complete"}};
    backend.observe(data);assert(data["receipts"][receipt.id]["state"]=="pending");
   }
   data[filament?"filament_operation":"toolhead_operation"]={{"id",receipt.id},{"session",data["session"]},{"head","h2"},{"action",filament?"load":"take"},{"state","complete"}};
   backend.observe(data);assert(!backend.machine_request_pending());
  }
 }
 // Sequence timeouts never resend; a later matching backend receipt reconciles.
 StandaloneBackend sequences;Http seqhttp;auto seqstate=cs;seqstate["job"]["state"]="idle";
 seqstate["capabilities"]["load"]=true;std::string token(64,'b');
 seqstate["procedures"]=Json::array({{{"action","load"},{"head","h2"},{"source","external:h2"},{"token",token},{"revision",seqstate["revision"]}}});
 sequences.observe(seqstate);Request seq={"load",seqstate["revision"],"standalone",{{"head","h2"},{"source","external:h2"},{"procedure_token",token}}};
 auto sr=sequences.submit(seq);assert(sr.state=="pending");seqhttp.fail=true;sequences.deliver(seqhttp);sequences.observe(seqstate);
 assert(seqhttp.script=="WMP_FILAMENT_SEQUENCE HEAD=2 ACTION=load ID="+sr.id+" TOKEN="+token);
 assert(seqstate["receipts"][sr.id]["state"]=="unknown");assert(!sequences.machine_request_pending());
 sequences.deliver(seqhttp);assert(seqhttp.posts==1);
 seqstate["filament_operation"]={{"id",sr.id},{"session",seqstate["session"]},{"head","h2"},{"action","load"},{"state","complete"}};
 sequences.observe(seqstate);assert(seqstate["receipts"][sr.id]["state"]=="complete");
 sr=sequences.submit(seq);assert(sr.state=="pending");sequences.deliver(seqhttp);
 seqstate["filament_operation"]["id"]=sr.id;seqstate["filament_operation"]["state"]="failed";
 sequences.observe(seqstate);assert(seqstate["receipts"][sr.id]["state"]=="failed");
 Request checked={"confirm_filament",seqstate["revision"],"standalone",{{"head","h2"},{"state","empty"}}};assert(sequences.submit(checked).state=="pending");
 seq.arguments["procedure_token"]=std::string(64,'c');assert(sequences.submit(seq).state=="refused");

 // Stop has a separate endpoint and retains the original pending receipt.
 {
  struct CancelHttp:wmp_openace::HttpPort{
   unsigned posts=0,cancels=0;Json body;bool fail=false;
   std::string get(const std::string&)override{return "{}";}
   std::string post(const std::string&path,const std::string&raw)override{
    ++posts;body=Json::parse(raw);
    if(path=="/printer/gcode/script")throw std::runtime_error("lost load response");
    assert(path=="/printer/wmp/filament/cancel");++cancels;
    if(fail)throw std::runtime_error("timeout");
    return Json{{"result",{{"id",body.at("id")},{"session",body.at("session")},{"state","requested"}}}}.dump();
   }
  } cancel_http;
  StandaloneBackend stopping;auto current=seqstate;current["filament_cancel_protocol"]=1;
  current["filament_operation"]=Json::object();seq.arguments["procedure_token"]=token;
  stopping.observe(current);auto ticket=stopping.submit(seq);assert(ticket.state=="pending");
  assert(!stopping.cancel_filament(ticket.id));stopping.deliver(cancel_http);
  stopping.observe(current);assert(current["receipts"][ticket.id]["state"]=="unknown");
  current["filament_operation"]={{"id",ticket.id},{"session",current["session"]},{"head","h2"},{"action","load"},{"state","running"}};
  stopping.observe(current);assert(current["receipts"][ticket.id]["state"]=="pending");assert(!stopping.cancel_filament("old-request"));
  assert(stopping.cancel_filament(ticket.id));assert(!stopping.cancel_filament(ticket.id));
  stopping.deliver(cancel_http);assert(cancel_http.cancels==1&&cancel_http.body.at("head")=="h2");
  stopping.observe(current);assert(current["receipts"][ticket.id]["state"]=="pending");
  assert(!stopping.cancel_filament(ticket.id));stopping.deliver(cancel_http);assert(cancel_http.cancels==1);
  current["filament_operation"]["cancel_requested"]=true;stopping.observe(current);
  assert(!stopping.cancel_filament(ticket.id));assert(current["receipts"][ticket.id]["state"]=="pending");
  current["filament_operation"]["state"]="failed";current["filament_operation"]["message"]="Cancelled; heater off";
  stopping.observe(current);assert(current["receipts"][ticket.id]["state"]=="failed");assert(!stopping.cancel_filament(ticket.id));
 }

 // Recovery retains the interrupted operation receipt and never replays load.
 {
  struct RecoveryHttp:wmp_openace::HttpPort{
   unsigned loads=0,recoveries=0;std::string last;bool fail=false;
   std::string get(const std::string&)override{return "{}";}
   std::string post(const std::string&path,const std::string&raw)override{
    assert(path=="/printer/gcode/script");last=Json::parse(raw).at("script").get<std::string>();
    assert(last.find("WMP_CHECK_COMMAND_GENERATION SESSION=")==0);auto end=last.find('\n');assert(end!=std::string::npos);last=last.substr(end+1);
    if(last.find("WMP_RECOVER_FILAMENT ")==0){++recoveries;if(fail)return R"({"error":{"message":"Not stopped"}})";}
    else {assert(last.find("WMP_FILAMENT_SEQUENCE ")==0);++loads;}
    return R"({"result":"ok"})";
   }
  } http;
  StandaloneBackend recovering;auto current=seqstate;current["filament_operation"]=Json::object();current["filament_recovery_protocol"]=1;
  seq.arguments["procedure_token"]=token;recovering.observe(current);auto ticket=recovering.submit(seq);assert(ticket.state=="pending");recovering.deliver(http);
  current["filament_operation"]={{"id",ticket.id},{"session",current["session"]},{"head","h2"},{"action","load"},{"state","unknown"},{"message","Heater stop uncertain"}};
  recovering.observe(current);assert(current["receipts"][ticket.id]["state"]=="unknown");assert(!recovering.recover_filament("old-id"));
  auto stale=current;stale["fresh"]=false;recovering.observe(stale);assert(!recovering.recover_filament(ticket.id));
  recovering.observe(current);assert(recovering.recover_filament(ticket.id));assert(!recovering.recover_filament(ticket.id));
  recovering.observe(stale);recovering.deliver(http);assert(http.recoveries==0);
  recovering.observe(current);assert(recovering.recover_filament(ticket.id));http.fail=true;recovering.deliver(http);assert(http.recoveries==1);
  recovering.observe(current);assert(recovering.recover_filament(ticket.id));http.fail=false;recovering.deliver(http);assert(http.recoveries==2);
  assert(http.last.find("ID="+ticket.id)!=std::string::npos&&http.last.find("HEAD=2")!=std::string::npos);
  assert(!recovering.recover_filament(ticket.id));recovering.observe(current);assert(current["receipts"][ticket.id]["state"]=="unknown");
  StandaloneBackend restarted;restarted.observe(current);assert(!restarted.recover_filament(ticket.id));
  assert(!restarted.resume_filament("wrong-id"));assert(restarted.resume_filament(ticket.id));
  assert(restarted.recover_filament(ticket.id));restarted.deliver(http);assert(http.recoveries==3&&http.loads==1);
  auto wrong_session=current;wrong_session["session"]="restarted-printer";
  StandaloneBackend invalid;invalid.observe(wrong_session);assert(!invalid.resume_filament(ticket.id));
  invalid.observe(stale);assert(!invalid.resume_filament(ticket.id));
  auto malformed=current;malformed["filament_operation"]["id"]="id\nG28";invalid.observe(malformed);assert(!invalid.resume_filament("id\nG28"));

  current["filament_operation"]["state"]="failed";current["filament_operation"]["recovered"]=true;current["filament_operation"]["message"]="Stopped. Unload before loading again.";
  recovering.observe(current);assert(current["receipts"][ticket.id]["state"]=="failed");assert(!recovering.recover_filament(ticket.id));assert(http.loads==1);
 }

 // Toolhead recovery can reconnect after a screen restart, but RPC success
 // is not completion and it must never replay the original tool-change macro.
 {
  Json current={{"owner","standalone"},{"fresh",true},{"session","tool-session"},{"revision","rev"},
   {"job",{{"state","idle"}}},{"toolhead_recovery_protocol",1},
   {"toolhead_operation",{{"id","interrupted-tool"},{"session","tool-session"},{"head","h2"},{"action","take"},{"state","unknown"}}}};
  StandaloneBackend recovering;Http http;recovering.observe(current);
  assert(!recovering.recover_toolhead("interrupted-tool"));
  assert(!recovering.resume_filament("interrupted-tool"));
  assert(recovering.resume_toolhead("interrupted-tool"));
  assert(!recovering.recover_filament("interrupted-tool"));
  assert(recovering.recover_toolhead("interrupted-tool"));
  assert(!recovering.recover_toolhead("interrupted-tool"));
  auto stale=current;stale["fresh"]=false;recovering.observe(stale);recovering.deliver(http);assert(http.posts==0);
  recovering.observe(current);assert(recovering.recover_toolhead("interrupted-tool"));
  http.fail=true;recovering.deliver(http);assert(http.posts==1);
  assert(recovering.recover_toolhead("interrupted-tool"));http.fail=false;recovering.deliver(http);
  assert(http.posts==2&&http.script=="WMP_RECOVER_TOOLHEAD ID=interrupted-tool SESSION=tool-session HEAD=2");
  recovering.observe(current);assert(current["receipts"]["interrupted-tool"]["state"]=="unknown");
  assert(!recovering.recover_toolhead("interrupted-tool"));
  auto replaced=current;replaced["toolhead_operation"]["id"]="other-tool";recovering.observe(replaced);
  assert(!recovering.resume_toolhead("other-tool"));
  current["toolhead_operation"]["state"]="failed";current["toolhead_operation"]["message"]="Stopped. Head 1 is mounted.";
  recovering.observe(current);assert(current["receipts"]["interrupted-tool"]["state"]=="failed");
  assert(current["receipts"]["interrupted-tool"]["message"]=="Stopped. Head 1 is mounted.");
  assert(!recovering.recover_toolhead("interrupted-tool"));
  for(const auto*mutation:{"session","head","owner","protocol","id","busy"}){
   auto bad=replaced;
   if(std::string(mutation)=="session")bad["session"]="new-session";
   if(std::string(mutation)=="head")bad["toolhead_operation"]["head"]="h9";
   if(std::string(mutation)=="owner")bad["owner"]="openace";
   if(std::string(mutation)=="protocol")bad["toolhead_recovery_protocol"]=0;
   if(std::string(mutation)=="id")bad["toolhead_operation"]["id"]="unsafe;G28";
   if(std::string(mutation)=="busy")bad["job"]["state"]="printing";
   StandaloneBackend invalid;invalid.observe(bad);
   if(invalid.resume_toolhead(bad["toolhead_operation"]["id"]))assert(!invalid.recover_toolhead(bad["toolhead_operation"]["id"]));
   invalid.deliver(http);assert(http.posts==2);
  }
 }

 // ACE unload shares only transport: public-owner work is authorized by the
 // helper token, and receipts use the helper session rather than ACE's session.
 {
  auto raw=exposed;raw["wm_material"]["openace_unload_protocol"]=1;raw["wm_material"]["session_id"]="helper-unload";
  raw["wm_material"]["filament_procedures"][0]["action"]="unload";
  raw["wm_material"]["filament_procedures"][0]["source"]="ace0:1";
  Json ace={{"session_id",42},{"config_revision",7},{"operation",nullptr}};
  auto current=native::project(raw,ace,true,"unused");
  assert(current["capabilities"]["unload"]==true&&current["capabilities"]["load"]==false);
  StandaloneBackend physical;wmp_openace::UiChannel channel;OpenAceBackend management(channel);NativeBackend router(management,physical);router.owner("openace");
  physical.observe(current);Http wire;wire.fail=true;
  Request unload={"unload",current["revision"],"openace",{{"head","h2"},{"source","ace0:1"},{"procedure_token",token}}};
  auto ticket=router.submit(unload);assert(ticket.state=="pending");physical.deliver(wire);physical.deliver(wire);physical.observe(current);
  assert(wire.posts==1&&current["receipts"][ticket.id]["state"]=="unknown");
  assert(wire.script=="WMP_FILAMENT_SEQUENCE HEAD=2 ACTION=unload ID="+ticket.id+" TOKEN="+token);
  current["filament_operation"]={{"id",ticket.id},{"session","42"},{"head","h2"},{"action","unload"},{"state","complete"}};
  physical.observe(current);assert(current["receipts"][ticket.id]["state"]=="unknown");
  current["filament_operation"]["session"]="helper-unload";physical.observe(current);
  assert(current["receipts"][ticket.id]["state"]=="complete");
  current["heater_manual_ready"]=false;physical.observe(current);assert(router.submit(unload).state=="refused");
  raw["wm_material"]["openace_load_protocol"]=1;raw["wm_material"]["filament_procedures"][0]["action"]="load";
  auto loading=native::project(raw,ace,true,"unused");assert(loading["capabilities"]["load"]==true);
  StandaloneBackend loader;NativeBackend load_router(management,loader);load_router.owner("openace");loader.observe(loading);Http load_wire;
  Request load={"load",loading["revision"],"openace",{{"head","h2"},{"source","ace0:1"},{"procedure_token",token}}};
  auto load_ticket=load_router.submit(load);assert(load_ticket.state=="pending");loader.deliver(load_wire);loader.deliver(load_wire);
  assert(load_wire.posts==1&&load_wire.script=="WMP_FILAMENT_SEQUENCE HEAD=2 ACTION=load ID="+load_ticket.id+" TOKEN="+token);
  loading["filament_cancel_protocol"]=1;
  loading["filament_operation"]={{"id",load_ticket.id},{"session","helper-unload"},{"head","h2"},{"action","load"},{"state","running"}};
  loader.observe(loading);assert(!loader.cancel_filament(load_ticket.id));
  loading["filament_operation"]["openace_cancel_supported"]=true;
  auto stale_helper=loading;stale_helper["print_helper_session"]="replacement";
  loader.observe(stale_helper);assert(!loader.cancel_filament(load_ticket.id));
  loader.observe(loading);assert(loader.cancel_filament(load_ticket.id));
  struct AceStopHttp:wmp_openace::HttpPort{
   unsigned calls=0;
   std::string get(const std::string&)override{return "{}";}
   std::string post(const std::string&path,const std::string&raw)override{
    ++calls;assert(path=="/printer/wmp/filament/cancel");auto body=Json::parse(raw);
    assert(body["session"]=="helper-unload"&&body["head"]=="h2");
    return Json{{"result",{{"id",body["id"]},{"session",body["session"]},{"state","requested"}}}}.dump();
   }
  } stop_wire;
  loader.deliver(stop_wire);assert(stop_wire.calls==1);assert(!loader.cancel_filament(load_ticket.id));
  loader.observe(loading);assert(loading["receipts"][load_ticket.id]["state"]=="pending");
  loading["filament_operation"]={{"id",load_ticket.id},{"session","helper-unload"},{"head","h2"},{"action","load"},{"state","complete"}};
  loader.observe(loading);assert(loading["receipts"][load_ticket.id]["state"]=="complete");
  assert(loading["receipts"][load_ticket.id]["message"]=="openACE verified the selected source loaded.");
  StandaloneBackend reconcile;
  loading["filament_recovery_protocol"]=1;
  loading["filament_operation"]={{"id","direct-recovery"},{"session","helper-unload"},{"head","h2"},{"action","load"},{"state","unknown"}};
  reconcile.observe(loading);assert(!reconcile.resume_filament("direct-recovery"));
  loading["filament_operation"]["openace_recovery_supported"]=true;
  reconcile.observe(loading);assert(reconcile.resume_filament("direct-recovery"));
  auto replaced=loading;replaced["print_helper_session"]="new-helper";reconcile.observe(replaced);
  assert(!reconcile.recover_filament("direct-recovery"));reconcile.observe(loading);
  assert(reconcile.recover_filament("direct-recovery"));
  Http recovery_wire;reconcile.deliver(recovery_wire);
  assert(recovery_wire.script=="WMP_RECOVER_FILAMENT ID=direct-recovery SESSION=helper-unload HEAD=2 GENERATION=0");
  reconcile.observe(loading);assert(loading["receipts"]["direct-recovery"]["state"]=="unknown");
  loading["filament_operation"]["state"]="failed";loading["filament_operation"]["message"]="Stopped; heater off.";
  reconcile.observe(loading);assert(loading["receipts"]["direct-recovery"]["state"]=="failed");
  assert(!reconcile.recover_filament("direct-recovery"));

 }

 }
}
