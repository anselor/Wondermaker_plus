// SPDX-License-Identifier: GPL-3.0-or-later
// Render actual independent screen owners; Python measures their header text
// with the pinned factory LVGL/fonts, rather than an estimated character width.
static int screen_header_contract(const char*path,const char*scenarios_path){
 std::ifstream input(path);Json base;input>>base;
 const std::string long_name(64,'W');
 auto under=[](fake::Node*n,fake::Node*parent){for(auto*p=n;p;p=p->parent){if(p->flags&1)return false;if(p==parent)return true;}return false;};
 auto bounds=[](fake::Node*n){int x=0,y=0;for(auto*p=n;p;p=p->parent){x+=p->x;y+=p->y;}return Json{{"x",x},{"y",y},{"w",n->w},{"h",n->h}};};
 std::ifstream scenarios_input(scenarios_path);Json scenarios;scenarios_input>>scenarios;
 for(const auto&item:scenarios){
  const std::string name=item;const auto separator=name.find(':');
  const auto scene=name.substr(0,separator),variant=separator==std::string::npos?std::string():name.substr(separator+1);
  auto*parent=fake::make(scene=="resume"?fake::top:fake::screen);
  parent->w=(scene.find("identification")!=std::string::npos||scene.find("calibration-result")!=std::string::npos||scene=="maintenance-active"||scene.find("scrub-")==0||scene.find("compact-")==0||scene=="runout"||scene=="temperature-header")?800:670;
  parent->h=(parent->w==800)?480:340;
  StockHomeStatus home;StockProbeEditor probe;StockIdentification identity;StockResumeProgress resume;
  StockFilamentProcedure procedure;StockCalibrationStatus calibration;StockNozzleScrub scrub;
  StockNozzleEditor nozzle;StockProfileImport importer;StockRecoveryProgress recovery;StockAceFilaments ace;
  StockPreviewControls preview_controls;SolidColourPicker colour_picker;
  StockNotice notice;StockPausePrompt pause;StockDiagnostics diagnostics;StockImagePreview image;StockTemperatureKeypad keypad;
  std::string title;std::vector<std::string>actions,body_labels;bool compact=false;int content_top=-1;
  auto find=[&](const std::string&text){for(const auto&item:fake::nodes)if(item->live&&item->is_label&&item->text==text&&under(item.get(),parent))return item.get();return static_cast<fake::Node*>(nullptr);};
  auto tap=[&](const std::string&text){auto*n=find(text);assert(n);fake::send(n->parent,7);};
  if(scene=="solid-colour"){
   assert(colour_picker.show(parent,"#ffffff"));title="Filament colour";actions={"CANCEL"};content_top=68;
  }else if(scene=="home"){
   assert(home.show(parent));home.update("Home printer","Waiting for Y reference",variant=="complete",variant.empty());title="Home printer";actions={variant=="complete"?"DONE":"CANCEL"};
  }else if(scene=="resume"){
   auto*row=fake::make(parent);row->h=140;
   auto*l=static_cast<fake::Node*>(fake::make_label(row));l->text="Resuming print...";
   resume.update({{"owner","standalone"},{"fresh",variant!="stale"},{"resume_progress",{{"phase",variant.empty()||variant=="stale"?"heating":variant}}}});
   title="Resuming paused print";
  }else if(scene=="maintenance-active"){
   auto*card=fake::make(parent);card->x=90;card->y=55;card->w=695;card->h=357;
   auto*l=static_cast<fake::Node*>(fake::make_label(card));l->x=33;l->y=12;l->font_address=MyriadPro_Regular_16;
   calibration.created(parent,false,l);calibration.begin("header-session","header-attempt");
   calibration.cancel=[]{};
   calibration.update({{"fresh",true},{"calibration_session","header-session"},{"maintenance_cancel_available",true},{"maintenance_worker_returned",false}});
   title="Calibration";actions={"CANCEL"};content_top=96;
  }else if(scene.find("calibration-result")!=std::string::npos){
   calibration.created(parent,scene=="setup-calibration-result");calibration.begin("header-session","header-attempt");
   calibration.update({{"fresh",true},{"calibration_session","header-session"},{"calibration_failed","Mount failed"},
    {"calibration_attempt",{{"session","header-session"},{"request","header-attempt"},{"state","failed"},{"error","Mount failed"}}}});
   title="Calibration";actions={"DONE"};
  }else if(scene.find("scrub-")==0){
   ScrubFacts f{};f.state=scene=="scrub-prepare"?ScrubState::Prepare:scene=="scrub-recheck"?ScrubState::Recheck:scene=="scrub-heating"?ScrubState::Heating:ScrubState::Finished;
   const std::map<std::string,ScrubState>states={{"StockChecks",ScrubState::StockChecks},{"ReturnPrompt",ScrubState::ReturnPrompt},{"Mounting",ScrubState::Mounting},{"Scrub",ScrubState::Scrub},{"Cooled",ScrubState::Cooled},{"Cancelling",ScrubState::Cancelling},{"Failed",ScrubState::Failed},{"Calibrate",ScrubState::Calibrate},{"Remeasure",ScrubState::Remeasure}};
   if(!variant.empty())f.state=states.at(variant);
   f.heads=4;f.brush=true;f.confirm_enabled=true;f.flagged={0,1,2,3};f.actual=180;f.target=200;
   const auto view=nozzle_scrub_view(f);scrub.created(parent);scrub.update(view);
   title="Nozzle offset calibration";
   if(view.cancel_visible)actions.push_back("CANCEL");
   if(view.confirm_visible)actions.push_back("CONFIRM");
   if(view.back_visible)actions.push_back("BACK");
  }else if(scene.find("filament-")==0||scene.find("compact-")==0){
   compact=scene.find("compact-")==0;const auto action=scene.substr(scene.find('-')+1);
   const bool tool=action=="take"||action=="dock";
   Json data={{"owner","standalone"},{"session","header-session"},{"revision","r"},{"identity_revision","i"},{"fresh",true},
    {"job",{{"state","idle"}}},{"capabilities",{{"load",true},{"unload",true}}},
    {"heads",Json::array({{{"id","h2"},{"loaded",{{"state",action=="unload"?"loaded":"empty"},{"source","external:h2"}}}}})},
    {"sources",Json::array({{{"id","external:h2"},{"head","h2"},{"available",true},{"name","External"}}})},
    {"procedures",Json::array({{{"head","h2"},{"source","external:h2"},{"action",action},{"revision","r"},{"token",std::string(64,'a')},{"target_temperature","210"}}})}};
   if(compact){assert(procedure.open(parent,data,"h2",action));actions={"CANCEL",action=="load"?"LOAD":"UNLOAD"};}
   else{
    procedure.cancel=[](const std::string&){return true;};procedure.recover=procedure.recover_toolhead=procedure.cancel;
    data[tool?"toolhead_cancel_protocol":"filament_cancel_protocol"]=1;
    data[tool?"toolhead_recovery_protocol":"filament_recovery_protocol"]=1;
    const auto state=variant.empty()||variant=="stopping"?"running":variant;
    data[tool?"toolhead_operation":"filament_operation"]={{"session","header-session"},{"id","header-fit"},{"head","h2"},{"action",action},{"state",state}};
    if(variant=="stopping")data[tool?"toolhead_operation":"filament_operation"]["cancel_requested"]=true;
    assert(procedure.open_tracking(parent,data,"h2",action,{"header-fit",variant.empty()||variant=="stopping"?"pending":variant,"Positioning head"}));
    actions=variant=="complete"?std::vector<std::string>{"DONE"}:variant=="unknown"?std::vector<std::string>{"CLOSE","RECOVER"}:variant.empty()?std::vector<std::string>{"CLOSE","STOP"}:std::vector<std::string>{"CLOSE"};
   }
   title=std::string(tool?(action=="take"?"Mount head":"Dock head"):(action=="load"?"Load filament":"Unload filament"))+" - Head 3";
  }else if(scene.find("probe-")==0){
   probe.created(parent);Json editor={{"available",true},{"state","editing"},{"z_position",-.145}};
   if(scene=="probe-review")editor={{"available",true},{"state","save_review"},{"save_review_required",true},{"save_review_confirmable",true},{"save_review",{{"configuration_matches",true},{"offset","-0.145"},{"loaded_offset","-0.145"}}}};
   if(variant=="retain")editor={{"available",true},{"state","save_review"},{"save_review_required",true},{"save_review_confirmable",true},{"save_retain_protocol",1},{"save_review",{{"retainable",true},{"offset","-0.145"},{"loaded_offset","-0.145"}}}};
   else if(!variant.empty()&&variant!="stale")editor["state"]=variant=="conflict"?"accepted":variant;
   if(variant=="conflict")editor["config_conflict"]={{"review",std::string(64,'a')},{"accepted_offset","-.145"},{"current_offset","-.150"}};
   probe.update({{"fresh",variant!="stale"},{"invalidated",false},{"editor",editor},{"actions",Json::object()}});
   title="Probe calibration";actions=scene=="probe-review"?std::vector<std::string>{"CLOSE","ABORT","START","CONFIRM"}:std::vector<std::string>{"CLOSE","ABORT","ACCEPT","DISCARD","SAVE"};
   if(variant=="retain")actions={"CLOSE","ABORT","START","KEEP"};
   if(variant=="conflict")actions={"CLOSE","ABORT","ACCEPT","KEEP","SAVE"};
   if(variant=="preparing")actions={"CLOSE","STOP","ACCEPT","DISCARD","SAVE"};
   if(variant=="failed")actions={"CLOSE","ABORT","START","DISCARD","SAVE"};
  }else if(scene.find("identification")!=std::string::npos){
   const bool setup=scene=="setup-identification";identity.created(parent,setup);
   const bool cancel=variant=="cancel"||variant=="cancelling";
   identity.update({{"fresh",true},{"identification",{{"state",variant=="cancelled"?"cancelled":"idle"}}}},"Ready to identify heads",variant!="running"&&variant!="cancelling",variant=="restart",variant!="running"&&!cancel,cancel);title="Extruder Setup";actions=setup?std::vector<std::string>{"START"}:std::vector<std::string>{"BACK","START"};
   if(variant=="running")actions={"START"};
   if(cancel)actions={"CANCEL"};
   if(variant=="cancelled"&&!setup)actions={"DONE","START"};
   if(variant=="restart")actions=setup?std::vector<std::string>{"RESTART"}:std::vector<std::string>{"BACK","RESTART"};
  }else if(scene=="preview"){
   parent->w=695;parent->h=357;StockPreviewWidgets w;w.page=parent;
   auto*content=fake::make(parent);content->w=695;content->h=357;w.content=content;
   auto*filename=static_cast<fake::Node*>(fake::make_label(content));w.title=filename;
   filename->text=std::string(240,'W')+".gcode";filename->x=33;filename->y=12;
   filename->w=3649;filename->h=20;filename->font_address=MyriadPro_Regular_16;
   for(unsigned i=0;i<3;++i){w.options[i]=fake::make(content);fake::bind(w.options[i],reinterpret_cast<void(*)(void*)>(preview_event),7,reinterpret_cast<void*>(i));}
   for(auto&source:w.sources)source=fake::make(content);
   for(auto&destination:w.destinations)destination=fake::make(content);
   auto*bar=fake::make(content);bar->x=bar->y=0;bar->w=695;bar->h=40;
   auto*start=fake::make(bar);start->x=555;start->y=0;start->w=128;start->h=40;w.start=start;
   auto*cancel=fake::make(bar);cancel->x=443;cancel->y=0;cancel->w=100;cancel->h=40;w.cancel=cancel;
   fake::bind(start,reinterpret_cast<void(*)(void*)>(preview_event),7,reinterpret_cast<void*>(4));
   fake::bind(cancel,reinterpret_cast<void(*)(void*)>(preview_event),7,reinterpret_cast<void*>(3));
   fake::bind(content,reinterpret_cast<void(*)(void*)>(preview_refresh_event),30,nullptr);
   const auto action=variant=="print"?"PRINT":variant=="copying"?"COPYING":variant=="copied"?"OPEN FILE":"COPY";
   for(auto pair:{std::make_pair(start,std::string(action)),std::make_pair(cancel,std::string("CANCEL"))}){
    auto*l=static_cast<fake::Node*>(fake::make_label(pair.first));l->text=pair.second;l->font_address=MyriadPro_Bold_20;
    center_button_caption(pair.first,l,pair.second);
   }
   assert(preview_controls.attach(w,{}));title=filename->text;actions={"CANCEL",action};content_top=41;
  }else if(scene=="nozzle"){
   nozzle.update({{"owner","standalone"},{"fresh",true},{"session","s"},{"nozzle_revision","r"},{"capabilities",{{"save_nozzle",true}}},
    {"nozzle_settings",{{"h3",{{"material","Hardened steel"},{"diameter",.4}}}}}});
   assert(nozzle.show(parent,3));title="Head 4 - Nozzle";actions={"BACK","SAVE"};
  }else if(scene=="import"){
   if(!variant.empty())importer.requested=[](const std::string&,const std::string&){return Receipt{"header-import","pending","Scanning"};};
   importer.update({{"owner","standalone"},{"fresh",true},{"capabilities",{{"profile_import",true}}}});
   assert(importer.show(parent));title="Import from USB";actions={"BACK","REFRESH"};
   if(!variant.empty()){
    Json result={{"id","header-import"},{"state",variant},{"message","Read failed"},{"profiles",Json::array()}};
    importer.update({{"owner","standalone"},{"fresh",true},{"capabilities",{{"profile_import",true}}},{"profile_import",result}});
    if(variant=="review")actions={"BACK","SAVE"};
    if(variant=="saved")actions={"DONE","REFRESH"};
   }
  }else if(scene=="recovery"||scene=="cancel"||scene=="discard"){
   compact=scene=="discard";Json state={{"id","audit"},{"fresh",true},{"state",scene=="cancel"?"complete":"pending"}};
   if(compact)state["retirement_mode"]=true;
   if(scene=="cancel")state["kind"]="print_cancel";
   if(!variant.empty())state["state"]=variant=="stale"?"pending":variant;
   if(variant=="stale")state["fresh"]=false;
   if(scene=="discard"&&!variant.empty())state["retirement"]={{"state",variant},{"available",true},{"fresh",true}};
   if(scene=="recovery"&&variant=="choices"){
    state["state"]="unknown";state["resolution_available"]=true;
    state["resolution"]={{"choices",{{"reconcile",{{"state","reviewed"},{"fresh",true}}},{"abandon",{{"state","reviewed"},{"fresh",true}}}}}};
   }
   if(scene=="recovery"&&(variant=="review-stop"||variant=="dispatched-stop")){
    state["state"]="pending";state["can_stop"]=true;
   }
   if(scene=="recovery"&&variant=="cancelled-early"){
    state["state"]="cancelled";state["before_execution"]=true;
   }
   assert(recovery.open(parent,state));title=compact?"Discard PLR":scene=="cancel"?"Cancel print":"Power Loss Recovery (PLR)";
   actions=scene=="cancel"?std::vector<std::string>{"DONE"}:std::vector<std::string>{"CLOSE"};
   if(scene=="cancel"&&!variant.empty())actions={"CLOSE"};
   if(scene=="recovery"&&variant=="refused")actions={"BACK"};
   if(scene=="recovery"&&(variant=="review-stop"||variant=="dispatched-stop"))actions={"CLOSE","STOP"};
   if(scene=="recovery"&&variant=="cancelled-early")actions={"DONE"};
   if(scene=="recovery"&&variant=="choices")actions={"CLOSE","USE SAVED","DISCARD"};
   if(scene=="discard"&&variant=="reviewed")actions={"CANCEL","DISCARD"};
  }else if(scene=="diagnostics"){
   diagnostics.attach(parent);diagnostics.update({{"fresh",variant!="stale"},{"owner","standalone"}});assert(diagnostics.open());
   title="WM+ diagnostics";actions={"CLOSE"};
  }else if(scene=="image-preview"){
   auto*thumbnail=fake::make(parent);thumbnail->image="/tmp/header-preview.png";
   assert(image.show(parent,thumbnail));actions={"CLOSE"};
  }else if(scene=="temperature-header"){
   // Retained constructor: root 800x425, keypad canvas x89/y34/696x357
   // (pinned client 0x52e44c..0x52e524). Only our added title is audited here.
   parent->h=425;auto*canvas=fake::make(parent);canvas->x=89;canvas->y=34;canvas->w=696;canvas->h=357;
   auto*entry=fake::make(canvas);entry->x=5;entry->y=12;entry->w=685;entry->h=44;
   fake::bind(entry,reinterpret_cast<void(*)(void*)>(number_text_event),7,nullptr);
   std::array<void*,13>keys;
   for(auto&key:keys){key=fake::make(canvas);fake::bind(key,reinterpret_cast<void(*)(void*)>(number_key_event),7,nullptr);}
   assert(keypad.attach(parent,entry,keys,220,[](int){return false;}));
   title="Target temperature (C)";content_top=canvas->y;
  }else if(scene=="notice"){
   assert(notice.show(parent,"Calibration settings changed. Review the current settings before continuing.",variant=="confirm"?"CONTINUE":""));
   actions=variant=="confirm"?std::vector<std::string>{"CANCEL","CONTINUE"}:std::vector<std::string>{"CLOSE"};
  }else if(scene=="runout"){
   // This owner attaches to the active stock screen, rather than a caller's page.
   fake::del(parent);parent=fake::screen;compact=true;
   pause.update({{"owner","standalone"},{"fresh",true},{"session","pause-session"},{"job",{{"state","paused"}}},
    {"paused_filament",{{"head","h3"},{"available",true},{"origin",{{"head","h3"},{"id",std::string(32,'a')},{"session","pause-session"}}}}},
    {"heads",Json::array({{{"id","h3"},{"loaded",{{"state","empty"}}}}})}});
   title="Filament needed - Head 4";actions={"LOAD","CANCEL"};
  }else{
   Json data=base;data["session"]="header-audit";data["job"]["state"]="idle";
   data["units"][0]["name"]=long_name;data["sources"][0]["name"]=long_name;
   data["candidates"]=Json::array({{{"id","header-candidate"},{"name",long_name},{"device_label","USB A"},{"logical_name","header-new"},{"context","audit-context"}}});
   data["capabilities"]["adopt"]=true;
   ace.mount(parent);ace.update(data,"h0",670,340);
   if(scene=="ace-source"||scene=="ace-brand"){
    assert(ace.open_head_identity("h0"));ace.update(data,"h0",670,340);
    title=long_name+" - "+long_name;actions={"BACK","SAVE"};
    if(scene=="ace-brand"){tap("Generic");ace.update(data,"h0",670,340);title="Select brand";actions={"BACK"};}
   }else if(scene=="ace-load"){
    ace.open_load(data["sources"][0].at("id"));ace.update(data,"h0",670,340);title="Load filament - "+long_name;actions={"BACK","SAVE"};
   }else if(scene=="ace-drying"){
    tap("Dryer ?");ace.update(data,"h0",670,340);title=long_name+" - Drying";actions={"CLOSE"};
   }else if(scene=="ace-unit"){
    tap("Edit unit");ace.update(data,"h0",670,340);title=long_name;actions={"Cancel","Save"};
    if(variant=="quick"||variant=="quick-stale"){
     tap("All slots to one head");ace.update(data,"h0",670,340);actions={"Cancel"};
     body_labels={"Assign all four slots to one head"};
    }else if(variant=="remove"||variant=="remove-stale"){
     tap("Remove");ace.update(data,"h0",670,340);actions={"Cancel","Remove"};
     body_labels={"Remove this ACE unit?","Preview only. Removal and new tool numbering are not available."};
    }
    if(variant.find("stale")!=std::string::npos){data["fresh"]=false;ace.update(data,"h0",670,340);if(variant=="quick-stale")body_labels={"Printer context changed - reopen unit details"};}
   }else if(scene=="ace-adoption"){
    tap("Adopt "+long_name+" - USB A");ace.update(data,"h0",670,340);title="Adopt "+long_name+"?";actions={"Cancel","Adopt"};
   }else{
    ace.picker_mode(true);data["picker_editable"]=true;ace.update(data,"h0",670,340);title="Choose filament source";actions={"CANCEL"};
    if(variant=="route"){
     const std::string id=data["sources"][0].at("id");data["picker_route_source"]=id;
     data["picker_choices"]={{id,Json::array({{{"id","r0"},{"label","T0"}},{{"id","r1"},{"label","T1"}}})}};
     ace.update(data,"h0",670,340);title="Choose tool route";
    }
   }
  }
  auto*t=title.empty()?nullptr:find(title);assert(title.empty()||t);
  Json captions=Json::array();
  for(const auto&text:actions){auto*n=find(text);assert(n);auto rect=bounds(n);rect["text"]=text;rect["font"]=n->font_address;rect["mode"]=n->label_long_mode;rect["button"]=bounds(n->parent);captions.push_back(rect);}
  unsigned titles=0;for(const auto&node:fake::nodes)if(node->live&&node->is_label&&node->text==title&&under(node.get(),parent))++titles;
  Json rect;
  if(t){rect=bounds(t);rect["text"]=title;rect["font"]=t->font_address;rect["mode"]=t->label_long_mode;}
  Json body=Json::array();for(const auto&text:body_labels){auto*n=find(text);assert(n);auto r=bounds(n);r["text"]=text;r["font"]=n->font_address;r["mode"]=n->label_long_mode;body.push_back(r);}
  std::cout<<Json{{"scene",name},{"width",parent->w},{"height",parent->h},{"title",rect},{"title_count",titles},{"actions",captions},{"compact",compact},{"body_labels",body},{"content_top",content_top}}.dump()<<std::endl;
  home.close();probe.dismiss();procedure.close();nozzle.close();importer.close();recovery.close();notice.close();pause.close();diagnostics.close();image.close();keypad.close();if(parent!=fake::screen&&parent->live)fake::del(parent);
 }
 return 0;
}
