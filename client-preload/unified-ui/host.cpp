// SPDX-License-Identifier: GPL-3.0-or-later
#include "screens.hpp"
#include <iostream>
int main() {
 wmp_ui::StubBackend backend;wmp_ui::App app(backend);std::string line;
 while(std::getline(std::cin,line)) {
  try {
   auto r=wmp_ui::Json::parse(line);
   if(r.contains("snapshot"))app.update(r["snapshot"]);
   if(r.contains("event")) {
    // Enforce the same input surface as the native renderer, including modal
    // ownership and disabled actions. No arbitrary event dispatch from browser.
    auto before=app.render();
    for(const auto&w:before["widgets"])if(w["kind"]=="button"&&w["id"]==r["event"]&&w["enabled"]==true){app.event(r["event"]);break;}
   }
   std::cout<<app.render().dump()<<std::endl;
  }catch(const std::exception&e){std::cout<<wmp_ui::Json{{"error",e.what()}}.dump()<<std::endl;}
 }
}
