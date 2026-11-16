// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "screens.hpp"
#include <cstdint>
namespace wmp_ui {
// Adapter boundary for a WM+-owned native content page. Unlike the old small
// recovery overlay, this needs verified ownership of a full page. It must not
// draw over vendor Stop/Cancel, other modals, or an unrecognized stock screen.
// Production port implementation is deliberately separate from the sealed V14
// Native1113Port, which supports only small protected overlays and 48 bindings.
struct Surface {
 virtual ~Surface()=default;
 virtual bool owns_page()const=0;
 virtual void clear()=0;
 virtual void draw(const Widget&)=0;
 virtual void finish(){}
};
class Renderer {
public:
 Renderer(App&app,Surface&surface):app_(app),surface_(surface){}
 Json paint(){
  if(!surface_.owns_page()){targets_.clear();return Json();}
  auto layout=app_.render();surface_.clear();targets_.clear();
  for(const auto&j:layout["widgets"]){Widget w;w.id=j["id"];w.text=j["text"];w.kind=j["kind"];w.color=j["color"];w.reason=j["reason"];w.parent=j.value("parent","");w.image_path=j.value("image_path","");w.image_width=j.value("image_width",0);w.image_height=j.value("image_height",0);w.x=j["x"];w.y=j["y"];w.w=j["w"];w.h=j["h"];w.enabled=j["enabled"];w.selected=j["selected"];w.faded=j["faded"];w.busy=j["busy"];
   surface_.draw(w);if(w.kind=="button"&&w.enabled)targets_[w.id]=true;
  }
  surface_.finish();++generation_;return layout;
 }
 std::uint64_t generation()const{return generation_;}
 void click(const std::string&id,std::uint64_t generation){
  if(generation!=generation_||!surface_.owns_page()||!targets_.count(id))return;
  // Check current capabilities/ownership even if an old frame is still visible.
  auto current=app_.render();bool allowed=false;for(const auto&w:current["widgets"])if(w["id"]==id&&w["kind"]=="button"&&w["enabled"]==true)allowed=true;
  if(!allowed)return;
  targets_.clear();++generation_;app_.event(id);
 }
private:
 App&app_;Surface&surface_;std::map<std::string,bool>targets_;std::uint64_t generation_=0;
};
}
