// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <algorithm>
#include <cctype>
#include <regex>
#include <sstream>
#include <string>
namespace wmp_ui { namespace native {
// Match command names as the retained Klipper GCodeDispatch does: comments,
// case folding, optional N prefix, then its args_r token and following value.
// Do not mistake a parameter or quoted message mentioning Cancel for the command.
inline bool stock_script_has_cancel(const std::string&script){
 static const std::regex tokens("[A-Z_]+|[A-Z*/]");
 std::istringstream input(script);std::string line;
 while(std::getline(input,line)){
  line=line.substr(0,line.find(';'));
  std::transform(line.begin(),line.end(),line.begin(),[](unsigned char c){return char(std::toupper(c));});
  auto token=std::sregex_iterator(line.begin(),line.end(),tokens),end=std::sregex_iterator();
  if(token==end)continue;
  if(token->str()=="N"&&++token==end)continue;
  const auto name=token->str();const auto start=token->position()+token->length();++token;
  const auto value=line.substr(start,token==end?std::string::npos:std::size_t(token->position()-start));
  if(name=="CANCEL_PRINT"&&value.find_first_not_of(" \t\r\n")==std::string::npos)return true;
 }
 return false;
}
// Under standalone ownership a batch containing Cancel becomes a single managed
// cancellation request. Never forward its prefix/suffix as unowned cleanup.
// A confirmed other owner can decline routing and retain the original batch.
template<class Route>bool route_stock_cancel(const std::string&command,Route route){
 return stock_script_has_cancel(command)&&route();
}
}}
