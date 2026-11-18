// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../model.hpp"
namespace wmp_ui { namespace native {
// GUI-thread view of one backend publication. Age changes do not recopy the
// payload, but crossing either freshness boundary invalidates dependent views.
class GuiStatusSnapshot {
 Json source_,view_=Json::object();std::int64_t received_=-1;std::uint64_t publication_=0;bool initialized_=false,changed_=false;
public:
 // The publisher advances this generation for every payload change, including
 // disconnects. GUI timer ticks need no recursive comparison of the payload.
 const Json&observe(const Json&source,std::int64_t received,std::int64_t now,std::uint64_t publication){
  changed_=!initialized_||received!=received_||publication!=publication_;
  if(changed_){source_=source;view_=source.is_object()?source:Json::object();received_=received;publication_=publication;initialized_=true;}
  const auto age=received>=0&&now>=received?now-received:-1;
  const bool fresh=source_.is_object()&&source_.value("fresh",false)&&age>=0&&age<=2000;
  const bool display=age>=0&&age<=4000&&view_.value("printer_state","")=="ready";
  changed_=changed_||fresh!=view_.value("fresh",false)||display!=view_.value("display_fresh",false);
  view_["status_age_ms"]=age;view_["fresh"]=fresh;view_["display_fresh"]=display;
  return view_;
 }
 bool changed()const{return changed_;}
};
}}
