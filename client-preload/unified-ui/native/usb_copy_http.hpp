// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "loopback_http.hpp"
#include "preview.hpp"
namespace wmp_ui { namespace native {
// A separate transport for the copy worker. It cannot issue printer commands,
// delete files, or copy to arbitrary existing destinations.
class UsbCopyHttp : public wmp_openace::UnifiedLoopbackHttp {
 static bool directory(const std::string&path){
  const std::string prefix="gcodes/WM_USB_";
  return path.size()==prefix.size()+32&&path.compare(0,prefix.size(),prefix)==0&&
   path.substr(prefix.size()).find_first_not_of("0123456789abcdef")==std::string::npos;
 }
public:
 explicit UsbCopyHttp(std::uint16_t port=7125):UnifiedLoopbackHttp(port){}
 static bool allowed_get(const std::string&path)noexcept{
  try{
   const std::string prefix="/server/files/metadata?filename=";
   if(path.size()>4096||path.compare(0,prefix.size(),prefix)!=0)return false;
   std::string decoded;
   for(std::size_t i=prefix.size();i<path.size();++i){
    if(path[i]!='%'){decoded+=path[i];continue;}
    if(i+2>=path.size())return false;
    const auto digit=[](char c){return c>='0'&&c<='9'?c-'0':c>='A'&&c<='F'?c-'A'+10:-1;};
    const int hi=digit(path[++i]),lo=digit(path[++i]);if(hi<0||lo<0)return false;
    decoded+=char(hi*16+lo);
   }
   const auto split=decoded.find('/');
   return split!=std::string::npos&&directory("gcodes/"+decoded.substr(0,split))&&
    decoded.find('/',split+1)==std::string::npos&&preview_path(decoded.substr(split+1))&&metadata_query(decoded)==path;
  }catch(...){return false;}
 }
 std::string get(const std::string&path)override{
  if(!allowed_get(path))throw std::runtime_error("Unsupported USB destination query");
  return request("GET",path,"");
 }
 static bool allowed(const std::string&path,const std::string&body)noexcept{
  try{
   if(body.empty()||body.size()>4096)return false;
   const auto args=Json::parse(body);if(!args.is_object())return false;
   if(path=="/server/files/directory")return args.size()==1&&args.at("path").is_string()&&directory(args.at("path").get<std::string>());
   if(path!="/server/files/copy"||args.size()!=2||!args.at("source").is_string()||!args.at("dest").is_string())return false;
   const auto source=args.at("source").get<std::string>(),dest=args.at("dest").get<std::string>();
   const std::string prefix="gcodes/USB/";
   if(source.compare(0,prefix.size(),prefix)!=0||!preview_path(source.substr(prefix.size())))return false;
   const auto split=dest.find_last_of('/');if(split==std::string::npos||!directory(dest.substr(0,split)))return false;
   const auto name=dest.substr(split+1);
   return preview_path(name)&&name==source.substr(source.find_last_of('/')+1);
  }catch(...){return false;}
 }
 std::string post(const std::string&path,const std::string&body)override{
  if(!allowed(path,body))throw std::runtime_error("Unsupported USB copy request");
  return request("POST",path,body);
 }
};
}}
