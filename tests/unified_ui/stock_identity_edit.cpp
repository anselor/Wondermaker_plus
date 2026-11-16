// SPDX-License-Identifier: GPL-3.0-or-later
#include "native/stock_identity_edit.hpp"
#include "native/stock_palette.hpp"
#include <cassert>
using namespace wmp_ui;
struct Capture : Backend {
 int count=0;Request request;
 std::string unavailable(const std::string&)const override{return "";}
 Receipt submit(const Request&r)override{++count;request=r;return {"edit-1","pending","Saving"};}
};
int main(){
 assert(std::string(native::stock_solid_colour(14))=="#cd001a");
 for(unsigned i=0;i<16;++i)assert(native::stock_colour_index(native::stock_solid_colour(i))==int(i));
 assert(!native::stock_solid_colour(16)&&!native::stock_solid_colour(21));
 assert(native::stock_colour_index("#123456")==-1);
 assert(native::stock_colour_index("#FFFFFF")==0);
 std::uint32_t rgb=0;
 assert(native::stock_rgb("#12AbEF",rgb)&&rgb==0xff12abefU);
 assert(native::stock_rgb("#000000",rgb)&&rgb==0xff000000U);
 assert(!native::stock_rgb("#12345g",rgb));
 assert(!native::stock_rgb("#12345",rgb));
 assert(!native::stock_rgb("123456",rgb));
 Json source={{"id","external:h1"},{"kind","external"},{"head","h1"},
  {"identity",{{"brand","Generic"},{"material","PLA"},{"color","#123456"}}}};
 Json s={{"fresh",true},{"owner","standalone"},{"revision","r1"},{"session","s1"},
  {"identity_revision","i1"},{"job",{{"state","idle"}}},{"sources",Json::array({source})}};
 native::StockIdentityEdit edit;Capture backend;
 assert(edit.begin(s,"h1","color"));
 assert(edit.choose(s,"#abcdef",backend).state=="pending");
 assert(backend.count==1&&backend.request.arguments["draft"]["head"]=="h1");
 assert(backend.request.arguments["draft"]["identity"]["material"]=="PLA");
 assert(backend.request.arguments["draft"]["identity"]["color"]=="#abcdef");
 assert(edit.choose(s,"#ffffff",backend).state=="refused"&&backend.count==1);
 for(const auto&field:{"session","revision","identity_revision","owner"}){
  assert(edit.begin(s,"h1","material"));auto changed=s;changed[field]="changed";
  assert(edit.choose(changed,"PETG",backend).state=="refused");
 }
 assert(edit.begin(s,"h1","material"));auto stale=s;stale["fresh"]=false;
 assert(edit.choose(stale,"PETG",backend).state=="refused");
 assert(edit.begin(s,"h1","material"));auto moved=s;moved["sources"][0]["head"]="h2";
 assert(edit.choose(moved,"PETG",backend).state=="refused");
 assert(edit.begin(s,"h1","material"));auto paused=s;paused["job"]["state"]="paused";
 assert(edit.choose(paused,"PETG",backend).state=="refused");
 {Capture cosmetic;assert(edit.begin(paused,"h1","color"));assert(edit.choose(paused,"#abcdef",cosmetic).state=="pending"&&cosmetic.count==1&&backend.count==1);}
 for(const auto*job:{"printing","paused"})for(bool physical:{false,true}){
  Capture sink;assert(edit.begin(s,"h1","color"));auto current=s;current["job"]["state"]=job;
  current["filament_operation"]={{"state","running"}};current["toolhead_operation"]={{"state","pending"}};
  const auto fields=physical?Json{{"color","#abcdef"},{"nozzle_temp",240}}:Json{{"color","#abcdef"},{"brand","New brand"}};
  assert(edit.choose_fields(current,fields,sink).state==(physical?"refused":"pending"));assert(sink.count==(physical?0:1));
  if(!physical)assert(!sink.request.arguments.contains("pause_origin"));
 }
 for(const auto*state:{"pending","running"}){Capture sink;assert(edit.begin(s,"h1","color"));auto current=s;current["identification"]={{"state",state}};assert(edit.choose(current,"#abcdef",sink).state=="refused"&&sink.count==0);}
 for(const auto*active_head:{"h0","h1","","bad"})for(const auto*state:{"pending","running","unknown"}){
  Capture sink;auto current=s;current["filament_operation"]={{"state",state},{"head",active_head}};
  current["toolhead_operation"]={{"state","running"}};
  assert(edit.begin(current,"h1","material"));
  const bool blocked=std::string(state)!="unknown"&&std::string(active_head)!="h0";
  assert(edit.choose(current,"ASA",sink).state==(blocked?"refused":"pending"));assert(sink.count==(blocked?0:1));
 }
 auto duplicate=s;duplicate["sources"].push_back(source);
 assert(!edit.begin(duplicate,"h1","color"));
 assert(!edit.begin(s,"h2","color"));
 assert(edit.begin(s,"h1","material"));edit.cancel();
 assert(edit.choose(s,"PETG",backend).state=="refused"&&backend.count==1);
 assert(edit.begin(s,"h1","material"));
 assert(edit.choose(s,"PETG",backend).state=="pending"&&backend.count==2);
 assert(backend.request.arguments["draft"]["identity"]["color"]=="#123456");
 // Several ACE slots feed the same physical head. Picker edits must retain
 // the selected source, never resolve it from the head or current loaded lane.
 auto ace=s;ace["owner"]="openace";
 auto first=source;first["id"]="ace0:0";first["kind"]="ace";first["unit"]="ace0";first["slot"]=0;
 auto second=first;second["id"]="ace0:1";second["slot"]=1;second["identity"]["color"]="#445566";
 ace["sources"]=Json::array({first,second,source});
 assert(!edit.begin(ace,"h1","color")); // no ambiguous physical-head fallback
 assert(edit.begin_source(ace,"ace0:1","color"));
 assert(edit.choose(ace,"#abcdef",backend).state=="pending");
 assert(backend.request.owner=="openace"&&backend.request.arguments["draft"]["slot"]==1);
 assert(backend.request.arguments["draft"]["unit"]=="ace0"&&backend.request.arguments["draft"]["head"]=="h1");
 assert(ace["sources"][0]["identity"]["color"]=="#123456"&&ace["sources"][1]["identity"]["color"]=="#445566");
 const auto prior=backend.count;
 for(const auto&field:{"session","revision","identity_revision","owner"}){
  assert(edit.begin_source(ace,"ace0:1","brand"));auto changed=ace;changed[field]="changed";
  assert(edit.choose(changed,"Example",backend).state=="refused");
 }
 assert(edit.begin_source(ace,"ace0:1","brand"));auto reassigned=ace;reassigned["sources"][1]["head"]="h2";
 assert(edit.choose(reassigned,"Example",backend).state=="refused"&&backend.count==prior);
 auto doubled=ace;doubled["sources"].push_back(second);assert(!edit.begin_source(doubled,"ace0:1","color"));
 assert(!edit.begin_source(ace,"missing","color"));
 // Standalone cards use the same source-specific editor as ACE cards.
 assert(edit.begin_source(s,"external:h1","color"));
 assert(edit.choose(s,"#987654",backend).state=="pending");
 assert(backend.request.owner=="standalone");
 assert(backend.request.arguments["draft"]["id"]=="external:h1");
 assert(backend.request.arguments["draft"]["identity"]["color"]=="#987654");
 assert(!edit.begin_source(ace,"ace0:1","head")); // assignment is not an identity field
 assert(edit.begin_source(ace,"external:h1","brand"));assert(edit.choose(ace,"Generic",backend).state=="pending");
 assert(backend.request.arguments["draft"]["kind"]=="external");

 // A paused replacement editor is tied to its original print, even if a
 // caller has not yet refreshed the broad configuration revision.
 auto replacement=s;replacement["job"]["state"]="paused";
 replacement["filament_recipe_write_protocol"]=1;replacement["filament_recipe_write"]={{"h1",{{"allowed",false},{"reason","Head used by print"}}}};
 replacement["heads"]=Json::array({{{"id","h1"},{"loaded",{{"state","empty"}}}}});
 replacement["paused_filament"]={{"available",true},{"head","h1"},
  {"origin",{{"head","h1"},{"session","s1"},{"id",std::string(32,'a')},{"file_position",120}}}};
 assert(edit.begin_source(replacement,"external:h1","material"));
 assert(edit.choose(replacement,"PETG",backend).state=="pending");
 assert(backend.request.arguments["pause_origin"]==replacement["paused_filament"]["origin"]);
 const auto paused_count=backend.count;
 for(const auto*change:{"origin","position","cancelled","loaded","running","owner","session","head","unavailable"}){
  assert(edit.begin_source(replacement,"external:h1","material"));auto changed=replacement;
  const std::string c=change;
  if(c=="origin")changed["paused_filament"]["origin"]["id"]=std::string(32,'b');
  if(c=="position")changed["paused_filament"]["origin"]["file_position"]=121;
  if(c=="cancelled")changed["job"]["state"]="idle";
  if(c=="loaded")changed["heads"][0]["loaded"]["state"]="loaded";
  if(c=="running")changed["filament_operation"]["state"]="running";
  if(c=="owner")changed["owner"]="openace";
  if(c=="session")changed["session"]="new-session";
  if(c=="head")changed["paused_filament"]["head"]="h2";
  if(c=="unavailable")changed["paused_filament"]["available"]=false;
  assert(edit.choose(changed,"PETG",backend).state=="refused"&&backend.count==paused_count);
 }
 assert(!edit.begin(replacement,"h2","material"));
 auto occupied=replacement;occupied["heads"][0]["loaded"]["state"]="loaded";
 assert(edit.begin(occupied,"h1","material"));assert(edit.choose(occupied,"PETG",backend).state=="refused"&&backend.count==paused_count);
 assert(edit.begin(replacement,"h1","material"));edit.cancel();
 assert(edit.choose(replacement,"PETG",backend).state=="refused"&&backend.count==paused_count);
 auto cross=replacement;cross["paused_filament"]["head"]="h2";
 cross["paused_filament"]["origin"]["head"]="h2";
 assert(edit.begin_source(cross,"external:h1","material"));assert(edit.choose(cross,"PETG",backend).state=="refused"&&backend.count==paused_count);
 cross["paused_filament"]["filament_required"]=Json::array({"h1"});
 assert(edit.begin_source(cross,"external:h1","material"));
 assert(edit.choose(cross,"PETG",backend).state=="pending");
 assert(backend.request.arguments["draft"]["head"]=="h1");
 assert(backend.request.arguments["pause_origin"]["head"]=="h2");


}
