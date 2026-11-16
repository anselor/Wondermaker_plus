// SPDX-License-Identifier: GPL-3.0-or-later
// Uses the existing fake LVGL only for widgets. Python answers measure requests
// by executing the factory lv_txt_get_size against its actual font data.
#include "native/stock_option_row.hpp"
#include "native/stock_header_action.hpp"
static int progress_ui_contract(const char*path){
 using namespace wmp_ui;using namespace wmp_ui::native;
 std::ifstream input(path);Json cases;input>>cases;
 fake::layout_hook=[](fake::Node*n){
  if(!n->is_label||n->height_fixed||n->label_long_mode!=0)return;
  std::cout<<Json{{"measure",n->text},{"font",n->font_address},{"width",n->w}}.dump()<<std::endl;
  std::string line;assert(bool(std::getline(std::cin,line)));n->h=Json::parse(line).at("height");
 };
 for(const auto&scenario:cases){
  auto*parent=fake::make(fake::screen);parent->w=scenario.at("width");parent->h=scenario.at("height");
  StockProgressPanel panel;StockFilamentProcedure procedure;StockCalibrationStatus calibration;
  const auto consumer=scenario.value("consumer","");
  if(consumer.empty()||consumer=="resume")assert(panel.attach(parent,0,0,parent->w,parent->h));
  StockOptionRow first,second;
  if(scenario.value("scrub_options",false)){
   first=StockOptionRow::create(panel.choices_parent(),"Wire brush","Scrub each heated nozzle by hand. Have a wire brush ready.",0,0,400);
   second=StockOptionRow::create(panel.choices_parent(),"Printed blob","Every head must be loaded with filament.",0,112,400);
   assert(first.object&&second.object);first.select(true);
  }
  auto view=scenario.at("view");
  if(consumer=="filament"){
   const auto snapshot=scenario.at("status");
   assert(procedure.open_tracking(parent,snapshot,"h2","load",{"fit-load","pending","Insert filament when prompted."}));
  }else if(consumer=="calibration"){
   calibration.created(parent);calibration.begin("fit-session","fit-attempt");calibration.update(scenario.at("status"));
  }else if(consumer=="resume"){
   view=resume_progress_view(scenario.at("status"));panel.update(view);
  }else panel.update(view);
  if(scenario.at("name").get<std::string>().find("scrub-state-")==0){
   auto*cancel=stock_header_action(parent,"CANCEL",parent->w-240,0,116,64,40);
   auto*confirm=stock_header_action(parent,"CONFIRM",parent->w-116,0,116,64,40);
   assert(cancel&&confirm);auto*caption=static_cast<fake::Node*>(fake::child(confirm,0));
   assert(caption->h==25&&caption->y+caption->h<=40&&fake::height(confirm)==64);
  }
  if(first.object){const int w=fake::width(panel.choices_parent());first.layout(0,0,w,104);second.layout(0,112,w,104);}
  const auto rect=[](fake::Node*n){int x=0,y=0;for(auto*p=n;p;p=p->parent){x+=p->x;y+=p->y;}return Json{{"x",x},{"y",y},{"w",n->w},{"h",n->h}};};
  Json labels=Json::array();
  for(const auto&node:fake::nodes){
   auto*n=node.get();if(!n->live||!n->is_label||n->text.empty())continue;
   bool shown=true,under=false;for(auto*p=n;p;p=p->parent){if(p->flags&1)shown=false;if(p==parent){under=true;break;}}
   if(!shown||!under)continue;
   auto data=rect(n);data["text"]=n->text;data["font"]=n->font_address;data["mode"]=n->label_long_mode;
   data["parent"]=rect(n->parent);labels.push_back(data);
  }
  std::cout<<Json{{"snapshot",scenario.at("name")},{"width",parent->w},{"height",parent->h},
   {"fits",consumer=="filament"||consumer=="calibration"?Json():Json(panel.content_fits())},{"expected_fit",scenario.value("fit",true)},
   {"note",view.value("note","")},{"labels",labels}}.dump()<<std::endl;
  // Value updates must retain the decision widgets and step layout. They
  // cannot turn selection into a printer command or replace a pressed target.
  const auto nodes=fake::nodes.size();auto*choice=first.object;
  const auto writes=fake::text_writes;
  view["value"]=scenario.at("view").value("value","");
  if(!view["value"].get<std::string>().empty())view["value"]=view["value"].get<std::string>()+" ";
  if(!scenario.at("view").value("value","").empty()){
   panel.update(view);assert(fake::text_writes==writes+1&&fake::nodes.size()==nodes&&first.object==choice);
  }
  procedure.close();panel.close();fake::del(parent);
 }
 fake::layout_hook={};
 return 0;
}
