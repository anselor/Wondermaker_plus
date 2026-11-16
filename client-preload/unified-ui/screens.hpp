// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "model.hpp"
namespace wmp_ui {
inline void App::tabs(int y) {
 int n=int(data_["heads"].size());if(!n)return;
 int width=684/n;
 for(int i=0;i<n;++i){auto&h=data_["heads"][i];auto id=h.value("id","");button("head:"+id,h.value("name",id),92+i*width,y,width-6);widgets_.back().selected=id==head_;}
}
inline void App::identity_card(const Json&s,int x,int y,int w,int h,const std::string&click,bool faded) {
 auto identity=s.value("identity",Json::object());
 button(click,s.value("name",s.value("id","")),x,y,w,h);
 widgets_.back().faded=faded;
 auto&swatch=add(click+":color","",x+8,y+29,w-16,13,"swatch");swatch.color=identity_display_text(identity,"color","#888888");swatch.faded=faded;
 auto&details=add(click+":identity",identity_text(identity)+"\n"+head_name(s.value("head","")),x+8,y+51,w-16,h-55);details.faded=faded;
}
inline void App::sources(int y,bool picker,bool loading,bool editing) {
 // Units occupy one native scrolling viewport. Every unit stays reachable,
 // including disconnected/unassigned units.
 const bool ace=data_.value("owner","")=="openace";
 Json groups=Json::array();
 if(ace)for(const auto&u:data_["units"]){bool matches=!editing;for(const auto&s:data_["sources"])if(s.value("unit","")==u.value("id","")&&s.value("head","")==head_)matches=true;if(matches)groups.push_back(u);}
 Json external_sources=Json::array();
 for(const auto&s:data_["sources"])if(s.value("kind","")=="external") {
  bool assigned=false;if(ace)for(const auto&other:data_["sources"])if(other.value("kind","")=="ace"&&other.value("head","")==s.value("head",""))assigned=true;
  if(!assigned||picker||loading)external_sources.push_back(s);
 }
 if(!editing&&!external_sources.empty())groups.push_back({{"id","external"},{"name","External"}});
 if(groups.empty()){add("empty","No filament sources configured",100,y+20,650,50);return;}
 const int viewport_y=y;
 add("source-scroll","",92,viewport_y,684,424-viewport_y,"scroll");
 for(std::size_t index=0;index<groups.size();++index) {
  const auto first=widgets_.size();
auto group=groups[index];auto uid=group.value("id","");
 add("group",group.value("name",uid)+(uid=="external"?"":group.value("connected",false)?" · connected":" · disconnected"),100,y,490,30);
 if(!picker&&!loading&&!editing&&uid!="external")button("unit:"+uid,"Edit unit",632,y,135,34);
 Json entries=Json::array();for(const auto&s:data_["sources"])if((uid=="external"&&std::find(external_sources.begin(),external_sources.end(),s)!=external_sources.end())||s.value("unit","")==uid)if(!editing||s.value("head","")==head_)entries.push_back(s);
 if(entries.empty())add("no-slots","No slots reported",100,y+45,660,80);
 // Four visible slots; extra slots are not silently invented.
 for(std::size_t i=0;i<entries.size()&&i<4;++i){const auto&s=entries[i];auto sid=s.value("id","");std::string click="edit:"+sid;
  std::string reason;
  if(loading){click="load-source:"+sid;if(s.value("head","")!=head_||!s.value("available",false))reason="Not an available source for this head.";}
  if(picker){click="unavailable-source:"+sid;reason="No eligible tool route for this sliced filament.";
   std::vector<std::string> routes;for(const auto&r:data_.value("routes",Json::array()))if(r.value("source","")==sid&&eligible(r,row_))routes.push_back(r.value("id",""));
   // Ambiguous aliases need an explicit backend-selected route; do not choose by array order.
   if(routes.size()==1){click="choose:"+routes.front();reason.clear();}else if(routes.size()>1){click="route-source:"+sid;reason.clear();}
  }
  const int card_height=!ace&&!picker&&!loading?236:126;
  const auto before=widgets_.size();identity_card(s,100+int(i)*169,y+40,162,card_height,click,ace&&!picker&&!head_.empty()&&s.value("head","")!=head_);
  widgets_[before].enabled=reason.empty();widgets_[before].reason=reason;
 }

  for(std::size_t i=first;i<widgets_.size();++i)widgets_[i].parent="source-scroll";
  y+=!ace&&!picker&&!loading?290:180;
 }

}
inline Json App::render() {
 widgets_.clear();
 const bool ace=data_.value("owner","")=="openace";
 add("background","",0,0,800,480,"panel");
 add("topbar","WM+"+(data_.value("owner","unknown")=="openace"?std::string("   openACE"):std::string()),0,0,800,36,"bar");
 add("connection",data_.value("fresh",false)?data_.value("job",Json::object()).value("state","unknown"):"Status unavailable",560,4,230,28);
 button("nav:home","Home",6,66,72,55);button("nav:files","Files",6,211,72,55);button("nav:filaments","Settings",6,356,72,55);
 const bool settings=page_=="filaments"||page_=="retained";
 if(settings){const std::vector<std::string> names={"XYZ","Filament","Video","Wi-Fi","General"};for(std::size_t i=0;i<names.size();++i){button("settings:"+names[i],names[i],92+int(i)*138,43,132,37);widgets_.back().selected=settings_==names[i];}}
 int title_y=settings?86:48;
 const std::map<std::string,std::string> titles={{"home","State"},{"tools","Toolhead management"},{"filaments",ace?"Filaments / ACE slots":"Filaments"},{"unit","ACE unit"},{"identity","Filament settings"},{"adopt","New ACE units"},{"import","Import filament profiles"},{"files","Print files"},{"preview","Print preview"},{"preview-loading","Print preview"},{"job","Current print"},{"recovery","Filament recovery"},{"operation","Operation"},{"retained",settings_}};
 add("title",titles.count(page_)?titles.at(page_):"Unavailable",96,title_y,655,32,"heading");
 if(page_=="home") {
  button("nav:files","Print files",96,100,285,260);
  for(std::size_t i=0;i<data_["heads"].size()&&i<4;++i){const auto&h=data_["heads"][i];button("home-head:"+h.value("id",""),h.value("name","")+"   "+std::to_string(h.value("actual",0))+" / "+std::to_string(h.value("target",0))+" C",402,100+int(i)*48,365,43);}
  button("nav:tools","Toolheads",402,303,174,52);button("nav:job","Current print",586,303,181,52);
  button("nav:filaments","Filaments"+(data_.value("candidates",Json::array()).empty()?std::string():"  ! New ACE"),402,367,365,62);
  int x=410;for(const auto&u:data_["units"]){if(x>696)break;add("mini-unit:"+u.value("id",""),"",x,399,78,22,"card");int sx=x+4;for(const auto&s:data_["sources"])if(s.value("unit","")==u.value("id","")){auto&w=add("mini:"+s.value("id",""),"",sx,403,14,14,"swatch");w.color=identity_display_text(s.value("identity",Json::object()),"color","#888888");sx+=18;if(sx>x+74)break;}x+=86;}
  if(data_["units"].empty()){int sx=416;for(const auto&s:data_["sources"]){auto&w=add("mini:"+s.value("id",""),"",sx,402,24,16,"swatch");w.color=identity_display_text(s.value("identity",Json::object()),"color","#888888");sx+=38;}}
 }else if(page_=="tools") {
  tabs(91);auto h=find("heads",head_);add("mounting",data_.value("fresh",false)&&h?h->value("mounting","Attachment unknown"):"Attachment unknown",520,55,245,24);auto loaded=h?h->value("loaded",Json::object()):Json::object();auto state=loaded.value("state","unknown");
  auto source=find("sources",state=="loaded"?loaded.value("source",""):ace_sources(head_)?"":external(head_));
  Json identity=state=="loaded"?loaded.value("identity",Json::object()):source?source->value("identity",Json::object()):Json::object();
  add("loaded-card","",96,145,190,264,"card");add("loaded-state",state,106,150,135,30);button("edit-loaded","Edit",237,150,42,32);
  auto&w=add("loaded-color","",154,192,72,44,"swatch");w.color=identity_display_text(identity,"color","#888888");
  add("loaded-identity",state!="loaded"&&ace_sources(head_)?(state=="empty"?"Choose an ACE slot\nto edit filament":"Loaded source\nunknown"):identity_text(identity),108,249,165,70);add("source-provenance",state=="loaded"?loaded.value("source","Unknown source"):ace_sources(head_)?"ACE filament sources":"Configured filament",106,319,172,35);
  if(state=="loaded")button("unload","Unload",108,360,165);
  else if(state=="empty")button("load","Load",108,360,165);
  else add("unknown-loaded","Confirm loaded state\nbefore Load / Unload",106,355,174,48);
  add("settings-card","",298,145,315,264,"card");add("distance","Distance · mm of filament",310,157,290,30);
  const int steps[]={1,5,10,25,50};for(int i=0;i<5;++i){button("step:"+std::to_string(steps[i]),std::to_string(steps[i]),310+i*57,198,50,40);widgets_.back().selected=step_==steps[i];}
  const bool heater_fresh=data_.value("fresh",false)&&h;
  add("temp",heater_fresh?"Temperature · "+std::to_string(h->value("actual",0))+" C actual":"Temperature unavailable",310,259,289,30);button("temperature",std::to_string(temperature_)+" C",310,302,92,45);
  add("heater-target",heater_fresh?"Current target: "+std::to_string(h->value("target",0))+" C":"Current target unavailable",310,354,289,24);
  add("heat-hint","Set value above, then tap Heat",310,381,289,22);
  action("heat","Heat","temperature",410,302,82,45);action("off","Off","temperature",500,302,82,45);
  action("retract","↑ Retract","step",630,159,137,90);add("step",std::to_string(step_)+" mm",645,266,113,30);action("extrude","↓ Extrude","step",630,308,137,90);
  if(busy()&&operation_.value("action","")=="step"&&operation_.value("arguments",Json::object()).value("head","")==head_)for(auto&b:widgets_)if(b.id==(operation_["arguments"].value("mm",0)<0?"retract":"extrude")){b.busy=true;b.text="Working…";}
  button("take","Take head",96,431,140,38);button("dock","Dock head",246,431,140,38);button("nav:filaments",ace?"Filaments / slots":"Filaments",600,431,167,38);
 }else if(page_=="filaments") {
  const bool discovered=ace&&!data_.value("candidates",Json::array()).empty();
  if(ace)tabs(126);
  if(discovered)button("nav:adopt","New ACE detected · Adopt",100,175,667,34);
  sources(ace?(discovered?212:178):126);
  button("nav:tools","Toolheads",96,432,160,36);button("nav:import","Import profiles",590,432,177,36);
 }else if(page_=="unit" && !draft_.is_null()) {
  add("unit-id","ID "+draft_.value("id",""),100,86,440,28);button("remove","Remove",638,49,129,34,(data_.value("job",Json::object()).value("state","")=="idle"||data_.value("job",Json::object()).value("state","")=="complete")?"":"Only available while idle.");
  button("unit-name",draft_.value("name","")+"  ✎",100,122,667,40);tabs(171);
  button("quick-all","All slots → "+head_name(head_),100,220,326,34);button("quick-distribute","Auto-distribute",438,220,329,34);
  int i=0;for(const auto&s:data_["sources"])if(s.value("unit","")==draft_.value("id","")&&i<4){auto copy=s;copy["head"]=draft_.value("assignments",Json::object()).value(s.value("id",""),"");identity_card(copy,100+i++*169,264,162,128,"assign:"+s.value("id",""));}
  button("back","Back",96,432,110,36);action("save","Save & exit","save_unit",604,432,163,36);if(!assignment_problem().empty()){widgets_.back().enabled=false;widgets_.back().reason=assignment_problem();}
  if(!data_.value("capabilities",Json::object()).value("save_assignments",false))add("assignment-stub","Slot assignments: preview only. Keep original assignments to save a name.",100,399,667,25);
 }else if(page_=="identity" && !draft_.is_null()) {
  add("identity-source",draft_.value("name","")+" · source settings",100,86,660,30);
  auto identity=draft_.value("identity",Json::object());
  add("brand-label","Brand",100,120,200,24);button("brands",identity_display_text(identity,"brand","Generic")+" ▾",100,150,320,40);
  add("material-label","Material",440,120,300,24);
  button("materials",identity.value("material","Unknown")+" ▾",440,150,327,40);
  add("colour-label","Colour · custom values are retained until you choose a swatch",100,214,660,32);
  std::vector<std::string> colors={"#eeeeee","#252930","#b8bec5","#df2040","#ef8a2c","#e6ca58","#60b87f","#3fb4c4","#407cc9","#997eb7","#d878b4","#906445"};
  for(std::size_t i=0;i<colors.size();++i){button("color:"+colors[i],identity_display_text(identity,"color","")==colors[i]?"✓":"",100+int(i%6)*113,260+int(i/6)*54,105,45);widgets_.back().color=colors[i];}
  add("custom-colour",data_.value("identity_edit_note","Current: "+identity_display_text(identity,"color","Unknown")+" · edits change source settings, not loaded evidence"),100,366,660,43);
  button("back","Back",96,432,110,36);action("save","Save filament","save_identity",604,432,163,36);
 }else if(page_=="adopt") {
  auto candidates=data_.value("candidates",Json::array());if(candidates.empty())add("none","No new ACE units detected",100,125,650,50);
  if(!candidates.empty()){add("adopt-scroll","",92,108,684,310,"scroll");
   for(std::size_t i=0;i<candidates.size();++i){const auto&c=candidates[i];button("adopt:"+c.value("id",""),c.value("name","New ACE")+" · "+c.value("device_label","Device identity unavailable"),100,115+int(i)*92,660,80);widgets_.back().parent="adopt-scroll";}
  }
  button("nav:filaments","Back",96,432,110,36);
 }else if(page_=="import") {
  add("import-info","Import filament profiles from USB or a command upload.\nSupported format and conflict policy are awaiting a backend contract.",100,120,650,100);
  button("import-usb","Choose USB file",100,250,300,60);add("upload","Command upload\nNot connected yet",430,250,330,70,"card");button("nav:filaments","Back",96,432,110,36);
 }else if(page_=="files") {
  add("files-note","Existing printer file browser is retained. These entries come from the file adapter.",100,89,650,46);
  auto files=data_.value("files",Json::array());for(std::size_t i=offset_;i<files.size()&&i<offset_+4;++i)button("file:"+files[i].value("id",""),files[i].value("name",""),100,143+int(i-offset_)*58,667,48);
  if(files.empty()){add("no-files","File browser adapter unavailable",100,160,660,60);}
  button("scroll-prev","Previous",100,432,145,36);button("scroll-next","Next",622,432,145,36);
 }else if(page_=="preview-loading") {
  add("preview-loading-file",file_,100,145,660,75);
  add("preview-loading-message",data_.value("fresh",false)?"Loading file information...":"Waiting for printer status...",100,240,660,65);
  button("nav:files","Files",96,432,100,36);
 }else if(page_=="preview") {
  auto f=find("files",file_);button("thumbnail","Preview\nexpand",100,92,84,60);if(f&&f->contains("thumbnail")&&!f->at("thumbnail").empty()){auto&t=widgets_.back();const auto&image=f->at("thumbnail");t.image_path=image.value("path","");t.image_width=image.value("width",0);t.image_height=image.value("height",0);}add("filename",f?f->value("name",""):"File unavailable",200,94,560,50);
  button("leveling","Leveling",480,151,135,32);widgets_.back().selected=options_.value("leveling",false);button("timelapse","Timelapse",630,151,137,32,timelapse_available_?"":"Enable timelapse in Video settings first.");widgets_.back().selected=options_.value("timelapse",false);
  if(f&&!f->value("metadata_error","").empty())add("metadata-error",f->value("metadata_error",""),100,198,650,90);
  auto sliced=f?f->value("sliced",Json::array()):Json::array();
  if(!sliced.empty())add("preview-rows","",92,194,684,230,"scroll");
  for(std::size_t i=0;i<sliced.size();++i){const auto first=widgets_.size();const auto&s=sliced[i];int y=194+int(i)*63;auto&w=add("slice-color:"+s.value("id",""),"",100,y+9,32,32,"swatch");w.color=identity_display_text(s,"color","#888888");add("slice:"+s.value("id",""),s.value("material","")+"  "+identity_display_text(s,"brand","")+(filament_usage_text(s).empty()?"":"\n"+filament_usage_text(s)),144,y,260,52);
   auto r=selection_.contains(s.value("id",""))?find("routes",selection_[s.value("id","")]):nullptr;auto source=r?find("sources",r->value("source","")):nullptr;
   button("map:"+s.value("id",""),r?r->value("label",""):"Choose source",449,y,318,54);auto&sw=add("selected-color:"+s.value("id",""),"",412,y+9,28,32,"swatch");sw.color=source?identity_display_text(source->value("identity",Json::object()),"color","#888888"):"#555555";
   for(std::size_t j=first;j<widgets_.size();++j)widgets_[j].parent="preview-rows";
  }
  button("nav:files","Files",96,432,100,36);
  auto why=preview_problem();if(why.empty())why=unavailable("start_print");button("start","Start print",600,432,167,36,why);
 }else if(page_=="job"||page_=="recovery") {
  auto job=data_.value("job",Json::object());add("job-details",job.value("name","No active print")+"\n"+job.value("message","")+"\nRequired source: "+job.value("source","Unknown"),100,100,660,110);
  if(page_=="job"){button("recovery","Filament recovery",100,250,315,55,job.value("state","")=="paused"?"":"Print is not paused.");button("cancel-print","Cancel print",450,250,317,55);}
  else {action("prepare","Prepare","prepare",100,230,315,50);action("prime","Prime","prime",450,230,317,50);action("confirm-material","Confirm material","confirm-material",100,295,315,50);action("resume","Resume","resume",450,295,317,50);add("hold",job.value("hold","Waiting for backend recovery status"),100,358,660,55);button("nav:job","Back to print",100,432,200,36);}
 }else if(page_=="operation") {
  add("operation-details",operation_.value("action","No operation")+" · "+operation_.value("state","none")+"\n"+operation_.value("message","")+"\nHead: "+operation_.value("arguments",Json::object()).value("head",""),100,120,660,110);
  for(const auto&key:{"control_request","cancel_request"})if(operation_.contains(key)){const auto&c=operation_[key];add(key,c.value("action","")+" · "+c.value("state","")+" · "+c.value("message",""),100,key==std::string("control_request")?218:249,660,28);}
  action("stop","Stop","stop",100,340,310,50);action("reconcile","Refresh result","reconcile",450,340,317,50);button("operation-back","Back",100,432,150,36);
 }else if(page_=="retained") {
  add("retained-page",settings_+" uses the existing Wondermaker screen.\nThe navigation handoff is not connected in this development renderer.",100,150,660,130);button("nav:filaments","Filaments",100,350,200,50);
 }
 if(busy()&&page_!="operation")button("operation","Operation · "+operation_.value("state",""),530,4,260,28);
 if(!notice_.empty())add("notice",notice_,90,410,690,22,"notice");
 // Nested management screens retain the stock Settings tabs. Compress only
 // their content area; footer and modal touch targets keep their own geometry.
 if(page_=="tools"||page_=="unit"||page_=="identity"||page_=="adopt"||page_=="import") {
  for(auto&w:widgets_)if(w.x>=90&&w.y>=40&&(w.y<410||!w.parent.empty())){w.y=84+(w.y-40)*326/370;w.h=std::max(w.kind=="swatch"?1:24,w.h*326/370);}
  const std::vector<std::string> names={"XYZ","Filament","Video","Wi-Fi","General"};
  for(std::size_t i=0;i<names.size();++i){button("settings:"+names[i],names[i],92+int(i)*138,43,132,37);widgets_.back().selected=names[i]=="Filament";}
 }
 if(!modal_.empty())modal();
 Json result={{"page",page_},{"modal",modal_},{"notice",notice_},{"width",800},{"height",480},{"widgets",Json::array()}};
 for(const auto&w:widgets_){result["widgets"].push_back(w.json());}
 return result;
}
inline void App::modal() {
 // Modal replaces input targets: widgets underneath cannot receive a click.
 widgets_.clear();add("modal-bg","",84,40,710,434,"panel");button("close","X",724,48,54,36);
 auto title=[&](const std::string&t){add("modal-title",t,100,52,600,35,"heading");};
 if(modal_=="unavailable") {title("Control unavailable");add("unavailable-reason",explanation_,100,140,650,200);button("close","Back",100,414,200,45);}
 else if(modal_=="discard") {title("Discard unsaved changes?");add("discard-info","Your edits have not been sent to the printer.",100,150,650,60);button("stay","Keep editing",100,280,315,60);button("discard","Discard changes",450,280,317,60);}
 else if(modal_=="keypad"||modal_=="keyboard") {title(key_target_=="temperature"?"Target temperature":"Unit name");add("key-text",key_text_,100,94,660,40,"card");std::string keys=modal_=="keypad"?"1234567890":"1234567890QWERTYUIOPASDFGHJKLZXCVBNM";
  for(std::size_t i=0;i<keys.size();++i)button(std::string("key:")+keys[i],std::string(1,keys[i]),100+int(i%10)*67,147+int(i/10)*51,61,44);
  button("key:backspace","⌫",100,360,150,44);if(modal_=="keyboard")button("key:space","Space",265,360,220,44);button("key-save","Done",607,414,160,45);
 }else if(modal_=="brands") {title("Select brand");auto brands=data_.value("brands",Json::array());if(std::find(brands.begin(),brands.end(),"Generic")==brands.end())brands.insert(brands.begin(),"Generic");
  add("brand-scroll","",92,108,684,310,"scroll");
  for(std::size_t i=0;i<brands.size();++i){auto brand=brands[i].get<std::string>();button("brand:"+brand,brand,100,115+int(i)*58,660,49);widgets_.back().parent="brand-scroll";}
 }
 else if(modal_=="materials") {title("Select material");auto materials=data_.value("materials",Json::array());if(materials.empty())materials=Json::array({"PLA","PETG","ABS","ASA","TPU"});
  auto current=draft_.value("identity",Json::object()).value("material","");if(!current.empty()&&std::find(materials.begin(),materials.end(),current)==materials.end())materials.insert(materials.begin(),current);
  add("material-scroll","",92,108,684,310,"scroll");for(std::size_t i=0;i<materials.size();++i){auto material=materials[i].get<std::string>();button("material:"+material,material,100,115+int(i)*58,660,49);widgets_.back().parent="material-scroll";widgets_.back().selected=material==current;}
 }
 else if(modal_=="edit-source") {title("Choose a source to edit");sources(105,false,false,true);}
 else if(modal_=="assign") {title("Assign this slot to a head");int i=0;for(const auto&h:data_["heads"]){button("assignment:"+h.value("id",""),h.value("name",""),100+(i%2)*345,140+(i/2)*68,320,54);++i;}button("assignment:","Unassigned",100,320,667,54);}
 else if(modal_=="remove") {
  title("Remove ACE unit?");auto uid=draft_.value("id","");auto current=find("units",uid);
  add("remove-unit",(current?current->value("name",uid):uid)+" · ID "+uid,100,100,650,35);
  Json affected=Json::array();for(const auto&r:data_.value("routes",Json::array())){auto source=find("sources",r.value("source",""));if(source&&source->value("unit","")==uid)affected.push_back(r);}
  add("remove-impact",std::to_string(affected.size())+" current tool route(s) reference this unit.\nRemoval and the renumbering preview are not available yet.\nLoaded filament and recovery records must be retained.",100,145,650,65);
  add("remove-routes","",100,220,667,170,"scroll");
  if(affected.empty()){add("remove-no-routes","No current tool routes reference this unit.",108,228,640,45);widgets_.back().parent="remove-routes";}
  for(std::size_t i=0;i<affected.size();++i){const auto&r=affected[i];add("remove-route:"+r.value("id",""),r.value("label",r.value("id","")),108,228+int(i)*55,640,50);widgets_.back().parent="remove-routes";}
  action("remove-confirm","Remove unit","remove_unit",430,414,337,45);button("close","Cancel",100,414,280,45);
 }
 else if(modal_=="adopt") {title("Adopt new ACE unit");auto candidate=find("candidates",candidate_);add("candidate",(candidate?candidate->value("name","New ACE")+"\n"+candidate->value("device_label","Device identity unavailable"):"Discovery no longer available")+"\nRegister this observed unit? Review its slots in Unit details afterward.",100,140,650,100);action("adopt-confirm","Adopt","adopt",430,340,337,60);if(!candidate){widgets_.back().enabled=false;widgets_.back().reason="This discovery is no longer available. Refresh the device list.";}button("close","Cancel",100,340,280,60);}
 else if(modal_=="load-source"||modal_=="sources") {title(modal_=="sources"?"Choose filament source":"Load from which source?");sources(105,modal_=="sources",modal_=="load-source");}
 else if(modal_=="routes") {title("Choose tool route");add("route-scroll","",92,108,684,310,"scroll");int y=115;for(const auto&r:data_.value("routes",Json::array()))if(r.value("source","")==source_&&eligible(r,row_)){button("choose:"+r.value("id",""),r.value("label",""),100,y,660,48);widgets_.back().parent="route-scroll";y+=56;}}
 else if(modal_=="external-load") {
  title("External Load · "+head_name(head_));auto source=find("sources",source_);
  add("external-profile",source?identity_text(source->value("identity",Json::object())):"Filament profile unavailable",100,100,650,45);
  add("external-prepare","1. Prepare head\nSelect, park and heat through openACE.",100,155,650,55,"card");
  add("external-insert","2. Insert filament\nWait for preparation to finish before inserting filament.",100,219,650,55,"card");
  add("external-prime","3. Confirm insertion and prime\nopenACE will check the result and report any remaining work.",100,283,650,55,"card");
  add("external-unavailable","Flow preview only. External Load is not connected in this screen yet.",100,350,650,40);
  button("close","Back",100,414,200,45);
  button("external-prepare-disabled","Prepare head",430,414,337,45,"External Load integration is unavailable.");
 }
 else if(modal_=="procedure") {title(intent_+" · "+head_name(operation_origin_=="recovery"?data_.value("job",Json::object()).value("head",""):head_));auto plan=procedure();auto procedure=plan.is_null()?std::string():plan.value("description","");auto missing=data_.value("procedure_errors",Json::object()).value(head_+":"+intent_,"Procedure details are unavailable. Nothing will move.");add("procedure",source_+"\n"+(procedure.empty()?missing:procedure),100,125,650,140);
  action("begin","Begin",""+intent_,430,340,337,60);if(procedure.empty()){widgets_.back().enabled=false;widgets_.back().reason="Backend procedure description is required.";}button("close","Cancel",100,340,280,60);
 }else if(modal_=="thumbnail") {title("Print preview");auto f=find("files",file_);auto image=f?f->value("thumbnail",Json::object()):Json::object();
  if(image.empty())add("thumbnail-missing","No thumbnail available for this file",100,140,660,230,"card");
  else {auto&w=add("expanded-thumbnail","",100,100,667,315,"image");w.image_path=image.value("path","");w.image_width=image.value("width",0);w.image_height=image.value("height",0);}
 }
 else if(modal_=="cancel") {title("Cancel this print?");add("cancel-detail",cancel_context_.value("job",Json::object()).value("name","Current print")+"\nCancellation ends this print. It is not a pause.",100,150,650,70);action("cancel-confirm","Cancel print","cancel_print",430,340,337,60);button("close","Keep print",100,340,280,60);}
 else if(modal_=="import-file") {title("USB profile files");auto files=data_.value("import_files",Json::array());if(files.empty())add("import-none","USB file enumeration is not connected yet.",100,150,650,70);
  else {add("import-scroll","",92,108,684,310,"scroll");for(std::size_t i=0;i<files.size();++i){auto f=files[i].get<std::string>();button("import-file:"+f,f,100,115+int(i)*64,660,56);widgets_.back().parent="import-scroll";}}
 }
 else if(modal_=="import-review") {title("Review profile import");add("import-review",import_file_+"\nFormat validation and conflict preview are unavailable.",100,140,650,100);action("import-confirm","Import","import_profiles",430,340,337,60);if(!data_.value("validated_imports",Json::object()).contains(import_file_)){widgets_.back().enabled=false;widgets_.back().reason="Backend import validation is required.";}}
 if(modal_!="cancel"&&(data_.value("job",Json::object()).value("state","")=="paused"||data_.value("job",Json::object()).value("state","")=="printing"))button("cancel-print","Cancel print",560,48,150,36);
 if(!notice_.empty())add("modal-notice",notice_,100,410,650,55,"notice");
}
}
