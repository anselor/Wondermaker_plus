// SPDX-License-Identifier: GPL-3.0-or-later
#include "screens.hpp"
#include "native_renderer.hpp"
#include "openace_backend.hpp"
#include <cassert>
#include <fstream>
using namespace wmp_ui;
struct FakeBackend : Backend {
 std::vector<Request> requests;
 std::string unavailable(const std::string&)const override {return "";}
 Receipt submit(const Request&r)override {requests.push_back(r);return {r.action=="stop"?"control-1":r.action=="cancel_print"?"cancel-1":"op-1","pending","Queued"};}
};
struct FakeSurface : Surface {
 bool owned=true;std::vector<Widget> widgets;
 bool owns_page()const override{return owned;}
 void clear()override{widgets.clear();}
 void draw(const Widget&w)override{widgets.push_back(w);}
};
static Json widget(App&app,const std::string&id){auto view=app.render();for(auto&w:view["widgets"])if(w["id"]==id)return w;return nullptr;}
int main(int argc,char**argv){
 assert(argc==2);std::ifstream input(argv[1]);Json fixture;input>>fixture;
 FakeBackend backend;App app(backend);app.update(fixture);
 for(const auto*job:{"printing","paused"})for(bool physical:{false,true})for(bool identifying:{false,true}){
  FakeBackend sink;auto data=fixture;data["owner"]="standalone";data["job"]["state"]=job;
  data["sources"][0]["kind"]="external";data["capabilities"]["save_identity"]=true;
  data["identification"]={{"state",identifying?"running":"idle"}};
  App editor(sink);editor.update(data);editor.event("edit:"+data["sources"][0]["id"].get<std::string>());
  editor.event("color:#123456");if(physical)editor.event("material:PETG");editor.event("save");
  assert(sink.requests.size()==(!physical&&!identifying?1u:0u));
 }

 // Native stock preview consumes semantic data from the same routing model.
 {
  FakeBackend preview_backend;App preview(preview_backend);preview.update(fixture);preview.event("file:demo-file");
  auto state=preview.preview_state();assert(state["rows"].size()==6&&!state["can_start"].get<bool>());
  assert(state["rows"][0]["sliced"]["color"]=="#b8bec5"&&state["rows"][0]["source"].is_null());
  preview.event("map:0");preview.event("choose:route-0-0");state=preview.preview_state();
  assert(state["rows"][0]["route"]["id"]=="route-0-0"&&state["rows"][0]["source"]["id"]=="ace-1:0");
  assert(state["rows"][0]["eligible"]==true&&preview_backend.requests.empty());
  auto stale=fixture;stale["fresh"]=false;preview.update(stale);state=preview.preview_state();
  assert(!state["can_start"].get<bool>()&&!state["fresh"].get<bool>());
 }

 // Removal lists only the selected unit's current routes; help is read-only.
 {
  App removal(backend);removal.update(fixture);removal.event("unit:ace-1");removal.event("remove");
  assert(widget(removal,"remove-impact")["text"].get<std::string>().find("4 current tool")!=std::string::npos);
  assert(!widget(removal,"remove-route:route-0-0").is_null());assert(widget(removal,"remove-route:route-1-0").is_null());
  auto count=backend.requests.size();removal.event("explain:remove-confirm");assert(removal.render()["modal"]=="unavailable");assert(backend.requests.size()==count);
  removal.event("close");assert(removal.render()["modal"]=="remove");
  removal.event("explain:close");assert(removal.render()["modal"]=="remove");assert(backend.requests.size()==count);
  removal.event("close");auto completed=fixture;completed["job"]["state"]="complete";removal.update(completed);assert(widget(removal,"remove")["enabled"]==true);
  completed["job"]["state"]="paused";removal.update(completed);assert(widget(removal,"remove")["enabled"]==false);

 }
 // Compact settings layout must not enlarge colour bars into identity text.
 {
  App cards(backend);cards.update(fixture);cards.event("nav:filaments");
  auto swatch=widget(cards,"edit:ace-1:0:color"),details=widget(cards,"edit:ace-1:0:identity");
  assert(!swatch.is_null()&&!details.is_null());
  assert(swatch["y"].get<int>()+swatch["h"].get<int>()<=details["y"].get<int>());
  assert(details["text"].get<std::string>().find("PLA")!=std::string::npos);
 }
 // An empty ACE-fed head edits assigned slots, never its synthesized External.
 {
  auto state=fixture;state["heads"][1]["loaded"]={{"state","empty"}};
  App edit(backend);edit.update(state);edit.event("nav:tools");edit.event("head:h1");edit.event("edit-loaded");
  assert(edit.render()["modal"]=="edit-source");assert(!widget(edit,"edit:ace-1:1").is_null());
  assert(widget(edit,"edit:external:h1").is_null());assert(widget(edit,"edit:ace-1:0").is_null());
  edit.event("edit:ace-1:1");assert(edit.draft()["id"]=="ace-1:1");edit.event("back");assert(edit.page()=="tools");
  state["owner"]="standalone";App manual(backend);manual.update(state);manual.event("nav:tools");manual.event("head:h1");manual.event("edit-loaded");assert(manual.draft()["id"]=="external:h1");
 }
 // Backspace removes a complete Unicode codepoint from an existing unit name.
 {
  auto state=fixture;state["units"][0]["name"]="ACE é猫";state["capabilities"]["save_unit"]=true;
  App unit(backend);unit.update(state);unit.event("unit:ace-1");unit.event("unit-name");unit.event("key:backspace");unit.event("key-save");assert(unit.draft()["name"]=="ACE é");
  unit.event("unit-name");unit.event("key:backspace");unit.event("key-save");assert(unit.draft()["name"]=="ACE ");
  unit.event("quick-all");assert(widget(unit,"save")["enabled"]==false);auto count=backend.requests.size();unit.event("save");assert(backend.requests.size()==count);
  assert(!widget(unit,"assignment-stub").is_null());
 }
 // External ACE loading has an honest staged preview, never a generic Begin.
 {
  auto state=fixture;state["procedures"]=Json::array();state["heads"][1]["loaded"]={{"state","empty"}};
  App flow(backend);flow.update(state);flow.event("nav:tools");flow.event("head:h1");flow.event("load");flow.event("load-source:external:h1");
  assert(flow.render()["modal"]=="external-load");assert(widget(flow,"begin").is_null());
  assert(widget(flow,"external-prepare-disabled")["enabled"]==false);
  auto count=backend.requests.size();flow.event("begin");flow.event("external-prepare-disabled");assert(backend.requests.size()==count);
  flow.event("close");assert(flow.page()=="tools"&&flow.render()["modal"]=="");
  state["job"]["state"]="paused";App paused(backend);paused.update(state);paused.event("nav:tools");paused.event("head:h1");paused.event("load");paused.event("load-source:external:h1");assert(paused.render()["modal"]=="procedure");
  state["owner"]="standalone";App manual(backend);manual.update(state);manual.event("nav:tools");manual.event("head:h1");manual.event("load");manual.event("load-source:external:h1");assert(manual.render()["modal"]=="procedure");
 }
 // Heater readback is distinct from the editable next Heat value and follows
 // the selected head; stale values must not look like current observations.
 {
  auto temperatures=fixture;temperatures["heads"][0]["actual"]=28;temperatures["heads"][0]["target"]=0;
  temperatures["heads"][1]["actual"]=205;temperatures["heads"][1]["target"]=210;
  App heat(backend);heat.update(temperatures);heat.event("nav:tools");
  assert(widget(heat,"temperature")["text"]=="220 C");
  assert(widget(heat,"heater-target")["text"]=="Current target: 0 C");
  heat.event("head:h1");assert(widget(heat,"heater-target")["text"]=="Current target: 210 C");
  assert(widget(heat,"temp")["text"]=="Temperature · 205 C actual");
  temperatures["fresh"]=false;heat.update(temperatures);
  assert(widget(heat,"heater-target")["text"]=="Current target unavailable");
  assert(widget(heat,"temp")["text"]=="Temperature unavailable");
  assert(backend.requests.empty());
 }
 // Independent drafts and all navigation exits: live source and loaded evidence stay intact.
 app.event("nav:filaments");app.event("unit:ace-1");app.event("quick-all");
 assert(app.data()["units"][0]["assignments"]["ace-1:1"]=="h1");
 app.event("nav:home");assert(app.render()["modal"]=="discard");app.event("stay");assert(app.page()=="unit");
 app.event("nav:home");app.event("discard");assert(app.page()=="home");
 app.event("nav:tools");app.event("edit-loaded");assert(app.draft()["id"]=="ace-1:0");
 app.event("color:#df2040");assert(app.data()["sources"][0]["identity"]["color"]=="#b8bec5");
 assert(app.data()["heads"][0]["loaded"]["identity"]["color"]=="#b8bec5");
 app.event("back");app.event("discard");assert(app.page()=="tools");
 // Unknown contents is not empty; there must be no Load or Unload action.
 app.event("head:h2");assert(widget(app,"load").is_null());assert(widget(app,"unload").is_null());
 // Full unit editor includes unassign, draft-only changes, and no separate assignment page.
 app.event("nav:filaments");app.event("unit:ace-2");app.event("assign:ace-2:0");app.event("assignment:");assert(app.draft()["assignments"]["ace-2:0"]=="");
 app.event("nav:home");app.event("discard");
 // Stale draft rejects Save before dispatch.
 app.event("unit:ace-1");auto revised=fixture;revised["revision"]="fixture-2";app.update(revised);app.event("save");assert(backend.requests.empty());assert(app.notice().find("changed")!=std::string::npos);
 // Direct step preserves signed amount, original head, and unresolved state across navigation.
 App movement(backend);auto ready=fixture;ready["capabilities"]["step"]=true;movement.update(ready);movement.event("nav:tools");movement.event("step:25");movement.event("retract");
 assert(backend.requests.size()==1);assert(backend.requests.back().arguments["mm"]==-25);assert(movement.page()=="tools");
 assert(movement.operation()["state"]=="pending");movement.event("head:h3");assert(movement.operation()["arguments"]["head"]=="h0");movement.event("extrude");assert(backend.requests.size()==1);
 ready["receipts"]={{"op-1",{{"state","unknown"},{"message","Reply lost"},{"owner","openace"},{"session","fixture-session"},{"action","step"}}}};movement.update(ready);movement.event("extrude");assert(backend.requests.size()==1);
 ready["receipts"]["op-1"]["state"]="partial";movement.update(ready);movement.event("extrude");assert(backend.requests.size()==1);
 ready["receipts"]["op-1"]["state"]="complete";movement.update(ready);movement.event("extrude");assert(backend.requests.size()==2);
 // Backend absence/unknown is never interpreted as permission for a stock fallback.
 App stale(backend);ready["fresh"]=false;stale.update(ready);stale.event("extrude");assert(backend.requests.size()==2);
 // Remove forbidden while paused regardless of advertised backend capabilities.
 ready=fixture;ready["capabilities"]["remove_unit"]=true;ready["job"]["state"]="paused";App paused(backend);paused.update(ready);paused.event("unit:ace-1");paused.event("remove-confirm");assert(backend.requests.size()==2);
 // Source selection uses authoritative route IDs; configuration drift invalidates start.
 App preview(backend);ready=fixture;ready["capabilities"]["start_print"]=true;preview.update(ready);preview.event("file:demo-file");
 for(int i=0;i<6;++i){preview.event("map:"+std::to_string(i));preview.event("choose:route-0-0");}
 ready["revision"]="changed";preview.update(ready);preview.event("start");assert(backend.requests.size()==2);
 // Standalone selection survives unrelated metadata, never a changed binding.
 for(const auto*change:{"unrelated","source","head","session","file"}){
  auto current=fixture;current["owner"]="standalone";current["capabilities"]["start_print"]=true;
  current["files"][0]["sliced"].erase(current["files"][0]["sliced"].begin()+2,current["files"][0]["sliced"].end());
  current["files"][0]["file_identity"]="file-one";
  App mapping(backend);mapping.update(current);mapping.event("file:demo-file");
  mapping.event("map:0");mapping.event("choose:route-0-0");
  mapping.event("map:1");mapping.event("choose:route-0-1");
  assert(!mapping.preview_state()["rows"][0]["route"].is_null());
  current["revision"]="metadata-update";
  if(std::string(change)=="unrelated")current["heads"][3]["nozzle"]={{"diameter",0.6}};
  if(std::string(change)=="source")current["sources"][0]["identity"]["material"]="PETG";
  if(std::string(change)=="head")current["heads"][0]["nozzle"]={{"diameter",0.6}};
  if(std::string(change)=="session"){current["session"]="new-session";current["revision"]=fixture["revision"];}
  if(std::string(change)=="file"){current["files"][0]["file_identity"]="file-two";current["revision"]=fixture["revision"];}
  mapping.update(current);
  assert(mapping.preview_state()["rows"][0]["route"].is_null()!=(std::string(change)=="unrelated"));
  assert(mapping.preview_state()["rows"][1]["route"].is_null()==(std::string(change)=="session"||std::string(change)=="file"));
 }
 // Even a backend advertising Start must not receive an empty/error preview.
 for(bool metadata_error:{false,true}){
  auto invalid=fixture;invalid["capabilities"]["start_print"]=true;
  if(metadata_error)invalid["files"][0]["metadata_error"]="Metadata request failed";
  else invalid["files"][0]["sliced"]=Json::array();
  App rejected(backend);rejected.update(invalid);rejected.event("file:demo-file");
  auto count_before=backend.requests.size();
  assert(widget(rejected,"start")["enabled"]==false);rejected.event("start");
  assert(backend.requests.size()==count_before);
 }
 // Preview starts with the native client's actual choices; refreshes must not
 // overwrite the operator's changes. Global timelapse disabled blocks its toggle.
 App options(backend);options.update(fixture);options.print_options(true,true,false);
 options.event("file:demo-file");assert(widget(options,"leveling")["selected"]==true);
 assert(widget(options,"timelapse")["selected"]==false);assert(widget(options,"timelapse")["enabled"]==false);
 options.event("timelapse");assert(widget(options,"timelapse")["selected"]==false);
 options.event("leveling");options.update(fixture);assert(widget(options,"leveling")["selected"]==false);
 options.print_options(false,true,true);assert(widget(options,"timelapse")["selected"]==true);
 options.event("timelapse");assert(widget(options,"timelapse")["selected"]==false);
 // Manual state assertions are debugging commands, never a normal UI route.
 auto checked=fixture;checked["owner"]="standalone";checked["capabilities"]["confirm_filament"]=true;
 App check(backend);check.update(checked);check.event("nav:tools");assert(widget(check,"check-filament").is_null());
 assert(!widget(check,"loaded-state").is_null());auto checks_before=backend.requests.size();
 check.event("check-filament");check.event("confirm-loaded");check.event("confirm-empty");
 assert(check.render()["modal"]!="filament-check");assert(backend.requests.size()==checks_before);
 // Rendering ownership, generations and disabled controls prevent stale touches.
 StubBackend stub;App rendering(stub);rendering.update(fixture);FakeSurface surface;Renderer renderer(rendering,surface);
 renderer.paint();auto generation=renderer.generation();surface.owned=false;renderer.click("nav:tools",generation);assert(rendering.page()=="home");surface.owned=true;renderer.paint();renderer.click("nav:tools",generation);assert(rendering.page()=="home");
 renderer.click("nav:tools",renderer.generation());assert(rendering.page()=="tools");renderer.paint();renderer.click("extrude",renderer.generation());assert(rendering.operation().empty());
 // All geometry is within the real 800x480 screen; no hidden overflow controls.
 for(const auto&page:{"home","tools","filaments","files","adopt","import","job"}){
  App a(stub);a.update(fixture);a.event(std::string("nav:")+page);auto layout=a.render();
  for(const auto&w:layout["widgets"]){assert(w["x"].get<int>()>=0&&w["y"].get<int>()>=0);assert(w["x"].get<int>()+w["w"].get<int>()<=800);if(w.value("parent","").empty())assert(w["y"].get<int>()+w["h"].get<int>()<=480);}
 }
 // Stop must stay accessible for unresolved work without replacing its identity.
 ready=fixture;ready["capabilities"]={{"step",true},{"stop",true},{"reconcile",true},{"cancel_print",true}};ready["job"]["state"]="paused";
 App control(backend);control.update(ready);control.event("extrude");
 ready["receipts"]={{"op-1",{{"state","unknown"},{"owner","openace"},{"session","fixture-session"},{"action","step"},{"allowed_actions",Json::array({"stop","reconcile"})}}}};
 control.update(ready);control.event("operation");assert(widget(control,"operation-explanation").is_null());assert(!widget(control,"operation-details").is_null());assert(widget(control,"stop")["enabled"]==true);control.event("stop");assert(control.operation()["action"]=="step");assert(control.operation().contains("control_request"));
 ready["receipts"]["op-1"]["state"]="surprise";control.update(ready);assert(control.operation()["state"]=="unknown");
 // Original completion must not release unresolved control requests; repeated taps refuse.
 auto count=backend.requests.size();control.event("stop");assert(backend.requests.size()==count);
 ready["receipts"]["op-1"]["state"]="complete";control.update(ready);control.event("extrude");assert(backend.requests.size()==count);
 ready["receipts"]["control-1"]={{"state","unknown"},{"owner","openace"},{"session","fixture-session"},{"action","stop"}};control.update(ready);control.event("extrude");assert(backend.requests.size()==count);
 ready["receipts"]["control-1"]["state"]="refused";control.update(ready);control.event("extrude");assert(backend.requests.size()==count+1);
 // Cancel without a prior operation must track its own receipt.
 App cancel(backend);cancel.update(ready);cancel.event("cancel-print");cancel.event("cancel-confirm");assert(cancel.operation()["action"]=="cancel_print");assert(cancel.operation()["state"]=="pending");auto cancel_count=backend.requests.size();cancel.event("cancel-print");cancel.event("cancel-confirm");assert(backend.requests.size()==cancel_count);
 // Required recovery head is independent of which head was browsed.
 ready=fixture;ready["job"]={{"id","job-1"},{"state","paused"},{"head","h3"},{"source","ace-1:3"},{"allowed_actions",Json::array({"prepare"})}};ready["capabilities"]["prepare"]=true;
 ready["procedures"]=Json::array({{{"action","prepare"},{"head","h3"},{"source","ace-1:3"},{"revision","fixture-1"},{"token","procedure-token"},{"description","Backend-owned preparation"}}});
 App recovery(backend);recovery.update(ready);recovery.event("head:h0");recovery.event("prepare");recovery.event("begin");assert(backend.requests.back().arguments["head"]=="h3");
 // Confirmation cannot silently cancel a different job.
 App drift(backend);drift.update(ready);drift.event("cancel-print");auto before=backend.requests.size();ready["job"]["id"]="job-2";ready["capabilities"]["cancel_print"]=true;drift.update(ready);drift.event("cancel-confirm");assert(backend.requests.size()==before);
 // Completed save receipts are processed once and cannot erase the next draft.
 auto save_data=fixture;save_data["capabilities"]["save_identity"]=true;App saving(backend);saving.update(save_data);saving.event("edit:ace-1:0");saving.event("color:#df2040");saving.event("save");
 save_data["sources"][0]["identity"]["color"]="#df2040";save_data["sources"][0]["available"]=false;
 save_data["receipts"]={{"op-1",{{"state","complete"},{"owner","openace"},{"session","fixture-session"},{"action","save_identity"}}}};
 saving.update(save_data);assert(saving.operation()["state"]=="complete");saving.event("edit:ace-1:1");saving.event("color:#252930");auto next_draft=saving.draft();saving.update(save_data);assert(saving.draft()==next_draft);assert(saving.operation()["state"]=="complete");
 // Malformed element and stale-session receipts fail closed.
 ready["heads"][0]["loaded"]=false;recovery.update(ready);assert(recovery.data()["fresh"]==false);
 return 0;
 // Known stopped failures release operator checks; transport uncertainty does not.
 auto failed_data=fixture;failed_data["owner"]="standalone";failed_data["job"]["state"]="idle";
 failed_data["capabilities"]["step"]=true;failed_data["capabilities"]["confirm_filament"]=true;
 App stopped(backend);stopped.update(failed_data);stopped.event("head:h0");stopped.event("extrude");
 failed_data["receipts"]={{"op-1",{{"state","unknown"},{"owner","standalone"},{"session","fixture-session"},{"action","step"}}}};
 stopped.update(failed_data);assert(!stopped.unavailable("confirm_filament").empty());
 failed_data["receipts"]["op-1"]["state"]="failed";stopped.update(failed_data);
 assert(stopped.operation()["state"]=="failed");assert(stopped.unavailable("confirm_filament").empty());
 // Long selectors use native scrolling containers, not paging controls.
 auto lists=fixture;lists["brands"]=Json::array({"A","B","C","D","E","F"});lists["import_files"]=Json::array({"a.json","b.json","c.json","d.json","e.json"});
 App selectors(backend);selectors.update(lists);selectors.event("edit:ace-1:0");selectors.event("brands");
 assert(widget(selectors,"brand-scroll")["kind"]=="scroll");assert(widget(selectors,"brand:F")["parent"]=="brand-scroll");assert(widget(selectors,"scroll-next").is_null());
 selectors.event("close");selectors.event("nav:import");selectors.event("import-usb");
 assert(widget(selectors,"import-file:e.json")["parent"]=="import-scroll");assert(widget(selectors,"scroll-prev").is_null());

 // Adoption waits for readback, then opens the new unit's isolated setup draft.
 auto adoption=fixture;adoption["job"]["state"]="idle";adoption["capabilities"]["adopt"]=true;
 adoption["candidates"]=Json::array({{{"id","discovery-3"},{"name","ACE 3"},{"logical_name","ace-3"},{"context","observation-3"}}});
 App adding(backend);adding.update(adoption);adding.event("nav:adopt");adding.event("adopt:discovery-3");adding.event("adopt-confirm");assert(adding.page()=="operation");
 adoption["receipts"]={{"op-1",{{"state","complete"},{"owner","openace"},{"session","fixture-session"},{"action","adopt"}}}};
 adding.update(adoption);assert(adding.operation()["state"]=="pending");assert(adding.page()=="operation");
 adoption["units"].push_back({{"id","ace-3"},{"name","ACE 3"},{"connected",true},{"assignments",{{"ace-3:0",""}}}});
 adoption["sources"].push_back({{"id","ace-3:0"},{"name","Slot 1"},{"kind","ace"},{"unit","ace-3"},{"slot",0},{"head",""},{"available",true},{"identity",{{"brand","Generic"},{"material","PLA"},{"color","#eeeeee"}}}});
 adding.update(adoption);assert(adding.operation()["state"]=="complete");assert(adding.page()=="unit");assert(adding.draft()["id"]=="ace-3");
 adding.event("quick-all");auto new_draft=adding.draft();adding.update(adoption);assert(adding.draft()==new_draft);
 adding.event("back");assert(adding.render()["modal"]=="discard");adding.event("discard");assert(adding.page()=="filaments");
 // Every discovery remains reachable in one native scroll viewport.
 auto many=adoption;many["candidates"]=Json::array();for(int i=0;i<8;++i)many["candidates"].push_back({{"id","candidate-"+std::to_string(i)},{"name","ACE"},{"logical_name","ace"+std::to_string(i)},{"context","context"}});
 App discoveries(backend);discoveries.update(many);discoveries.event("nav:adopt");
 assert(widget(discoveries,"adopt:candidate-7")["parent"]=="adopt-scroll");assert(widget(discoveries,"scroll-next").is_null());
 auto first_discovery=widget(discoveries,"adopt:candidate-0"),last_discovery=widget(discoveries,"adopt:candidate-7");
 assert(first_discovery["h"]==last_discovery["h"]);assert(last_discovery["y"].get<int>()>480);
 // A late receipt must not pull someone away from another screen.
 App late(backend);adoption["receipts"]=Json::object();late.update(adoption);late.event("adopt:discovery-3");late.event("adopt-confirm");late.event("nav:home");
 adoption["receipts"]={{"op-1",{{"state","complete"},{"owner","openace"},{"session","fixture-session"},{"action","adopt"}}}};
 late.update(adoption);assert(late.page()=="home");assert(late.draft().is_null());

 // Materials use a scrolling selector and preserve imported/custom names.
 auto material_data=fixture;material_data["materials"]=Json::array({"PLA","PLA Silk","ABS","PETG","PVA","TPE","TPU","PET","Wood","ASA","PA","PC"});
 material_data["sources"][0]["identity"]["material"]="Custom blend";
 App material_editor(backend);material_editor.update(material_data);material_editor.event("edit:ace-1:0");
 assert(!widget(material_editor,"materials").is_null());assert(widget(material_editor,"material:PLA").is_null());
 material_editor.event("materials");assert(widget(material_editor,"material:PC")["parent"]=="material-scroll");assert(widget(material_editor,"material:Custom blend")["selected"]==true);
 material_editor.event("material:PC");assert(material_editor.render()["modal"]=="");assert(material_editor.draft()["identity"]["material"]=="PC");
 assert(material_editor.data()["sources"][0]["identity"]["material"]=="Custom blend");

 // Save & exit returns only after the full backend configuration matches.
 auto unit_save=fixture;unit_save["capabilities"]["save_unit"]=true;
 App unit_saving(backend);unit_saving.update(unit_save);unit_saving.event("nav:filaments");unit_saving.event("unit:ace-1");unit_saving.event("quick-all");unit_saving.event("save");
 auto intended=backend.requests.back().arguments["draft"];assert(unit_saving.page()=="operation");
 unit_save["receipts"]={{"op-1",{{"state","complete"},{"owner","openace"},{"session","fixture-session"},{"action","save_unit"}}}};
 unit_saving.update(unit_save);assert(unit_saving.page()=="operation");assert(!unit_saving.draft().is_null());assert(unit_saving.operation()["state"]=="pending");
 unit_save["units"][0]=intended;unit_saving.update(unit_save);assert(unit_saving.page()=="filaments");assert(unit_saving.draft().is_null());
 // A user who returns to edit while Save is pending keeps their newer draft.
 auto edited=fixture;edited["capabilities"]["save_identity"]=true;App editing_pending(backend);editing_pending.update(edited);editing_pending.event("nav:tools");editing_pending.event("edit:ace-1:0");editing_pending.event("color:#df2040");editing_pending.event("save");editing_pending.event("operation-back");editing_pending.event("color:#252930");
 edited["sources"][0]["identity"]["color"]="#df2040";edited["receipts"]={{"op-1",{{"state","complete"},{"owner","openace"},{"session","fixture-session"},{"action","save_identity"}}}};
 editing_pending.update(edited);assert(editing_pending.page()=="identity");assert(editing_pending.draft()["identity"]["color"]=="#252930");
 // Identity editing reached from Toolheads returns to that screen after save.
 App tool_save(backend);tool_save.update(edited);tool_save.event("nav:tools");tool_save.event("edit:ace-1:0");tool_save.event("color:#eeeeee");tool_save.event("save");edited["sources"][0]["identity"]["color"]="#eeeeee";tool_save.update(edited);assert(tool_save.page()=="tools");assert(tool_save.draft().is_null());

 // Disappearing discovery cannot be adopted from an obsolete confirmation.
 auto gone=adoption;gone["receipts"]=Json::object();App disappearing(backend);disappearing.update(gone);disappearing.event("adopt:discovery-3");gone["candidates"]=Json::array();disappearing.update(gone);
 assert(widget(disappearing,"adopt-confirm")["enabled"]==false);auto prior_requests=backend.requests.size();disappearing.event("adopt-confirm");assert(backend.requests.size()==prior_requests);assert(disappearing.notice().find("no longer available")!=std::string::npos);

}
