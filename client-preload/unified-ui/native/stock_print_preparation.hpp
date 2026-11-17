// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_progress_panel.hpp"
#include "stock_header_action.hpp"
#include <cstring>
namespace wmp_ui { namespace native {
inline Json print_preparation_view(const Json&data){
 const auto preparation=data.value("print_preparation",Json::object());
 const auto phase=preparation.value("phase","");bool reached=false;
 Json view={{"title","Preparing print"},{"steps",Json::array()},
  {"instruction",preparation.value("instruction","")},{"note",preparation.value("note","")}};
 for(const auto&step:preparation.value("steps",Json::array())){
  const bool current=step.value("phase","")==phase;
  view["steps"].push_back({{"label",step.value("label","")},{"state",current?"running":reached?"pending":"complete"}});
  if(current){view["heading"]=step.value("label","");reached=true;}
 }
 std::string values;
 auto append=[&](const std::string&label,double actual,double target){if(!values.empty())values+='\n';values+=label+": "+std::to_string(int(actual))+" / "+std::to_string(int(target))+" C";};
 if(phase=="bed"||phase=="chamber"||phase=="stabilizing"){
  const auto temperatures=preparation.value("temperatures",Json::object());
  for(const auto*key:{"bed","chamber"}){
   const auto t=temperatures.value(key,Json::object());
   if(t.value("actual",Json()).is_number()&&t.value("target",0.)>0)append(std::strcmp(key,"bed")==0?"Bed":"Chamber",t["actual"].get<double>(),t["target"].get<double>());
  }
  if(phase=="stabilizing")values+="\nHold: "+std::to_string(int(preparation.value("hold_remaining",0.)+.9))+" s";
 }else if(phase=="mesh"){
  const auto mesh=preparation.value("mesh_progress",Json::object());
  const int point=mesh.value("point",0),total=mesh.value("total",0);
  if(point>0&&point<=total)values="Probing point "+std::to_string(point)+" of "+std::to_string(total);
 }else if(phase=="preheat"||phase=="nozzle"){
  for(const auto&head:data.value("heads",Json::array()))if(head.value("target",0.)>0){
   const auto id=head.value("id","");if(id.size()==2)append("Head "+std::to_string(id[1]-'0'+1),head.value("actual",0.),head.value("target",0.));
  }
 }
 view["value"]=values;return view;
}
// Home-content overlay only. Sidebar navigation and existing cancellation
// remain available; closing this view sends no command and holds no operation.
class StockPrintPreparation {
 StockProgressPanel progress_;void*root_=nullptr;bool home_=false;std::string dismissed_,id_;
public:
 ~StockPrintPreparation(){close();}
 void navigation(const char*name){home_=name&&std::strcmp(name,"main_page")==0;if(!home_)close();}
 void close(){progress_.close();if(stock_object_valid(root_))stock_function<void(*)(void*)>(lv_obj_del)(root_);root_=nullptr;}
 void update(const Json&data){
  const auto preparation=data.value("print_preparation",Json::object());const auto id=preparation.value("id","");
  if(!home_||data.value("owner","")!="standalone"||!data.value("fresh",false)||!preparation.value("active",false)||id.empty()||id==dismissed_){close();return;}
  if(!stock_object_valid(root_)){
   root_=nullptr;auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);
   if(!stock_object_valid(screen))return;
   const int width=stock_function<int(*)(void*)>(lv_obj_get_content_width)(screen);
   const int height=stock_function<int(*)(void*)>(lv_obj_get_content_height)(screen);
   if(width<600||height<360)return;
   root_=stock_function<void*(*)(void*)>(lv_obj_create)(screen);if(!root_)return;
   stock_dialog_backdrop(root_);stock_object_place(root_,90,110,width-104,height-122);
   stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(root_,0xff3c3f43U,0);
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(root_,255,0);
   if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(root_,&deleted,33,this)){close();return;}
   auto*button=stock_header_action(root_,"CLOSE",width-230,0,112);
   if(!button||!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(button,&pressed,7,this)){close();return;}
   if(!progress_.attach(root_,0,40,width-104,height-164)){close();return;}
  }
  id_=id;progress_.update(print_preparation_view(data));
 }
private:
 static void deleted(void*event)noexcept{try{
  auto*self=static_cast<StockPrintPreparation*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(event));
  if(self&&stock_function<void*(*)(void*)>(lv_event_get_target)(event)==self->root_)self->root_=nullptr;
 }catch(...){} }
 static void pressed(void*event)noexcept{try{
  auto*self=static_cast<StockPrintPreparation*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(event));
  auto*target=stock_function<void*(*)(void*)>(lv_event_get_target)(event);
  if(!self||!stock_object_valid(self->root_)||!stock_object_valid(target)||stock_function<void*(*)(void*)>(lv_obj_get_parent)(target)!=self->root_)return;
  self->dismissed_=self->id_;self->close();
 }catch(...){} }
};
}}
