// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <string>
namespace wmp_ui { namespace native {
// GUI-only acknowledgement. Never changes printer state or command admission.
class StockCompletedDisplay {
public:
 void dismiss(const std::string&state,const std::string&file){
  if(state=="complete"&&!file.empty()){dismissed_=true;file_=file;}
 }
 bool visible(bool stock_visible,const std::string&state,const std::string&file){
  if(state!="complete"||file!=file_){dismissed_=false;file_.clear();}
  return stock_visible&&!dismissed_;
 }
private:
 bool dismissed_=false;std::string file_;
};
}}
