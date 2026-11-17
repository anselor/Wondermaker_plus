// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "projection.hpp"
#include <set>
namespace wmp_ui { namespace native {
inline bool preview_path(const std::string&path){
 if(path.empty()||path.size()>1024||path.front()=='/'||path.back()=='/')return false;
 std::size_t at=0;while(at<path.size()){auto end=path.find('/',at);auto part=path.substr(at,end==std::string::npos?end:end-at);if(part.empty()||part=="."||part=="..")return false;if(end==std::string::npos)break;at=end+1;}
 for(unsigned char c:path)if(c<32||c==127||c=='\\')return false;
 return true;
}
inline std::string metadata_query(const std::string&path){
 if(!preview_path(path))throw std::runtime_error("Invalid selected file path");
 std::string encoded;const char*hex="0123456789ABCDEF";
 for(unsigned char c:path){if((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='-'||c=='_'||c=='.'||c=='~')encoded+=c;else{encoded+='%';encoded+=hex[c>>4];encoded+=hex[c&15];}}
 return "/server/files/metadata?filename="+encoded;
}
inline Json metadata_strings(const Json&m,const char*key){
 if(!m.contains(key)||m[key].is_null())return Json::array();
 Json values=m[key];
 if(values.is_string()){
  const auto text=values.get<std::string>();values=Json::array();
  std::size_t start=0;
  for(;;){
   const auto end=text.find(';',start);
   if(values.size()==32||(end==std::string::npos?text.size():end)-start>128)throw std::runtime_error("Unsupported filament metadata");
   values.push_back(text.substr(start,end==std::string::npos?end:end-start));
   if(end==std::string::npos)break;
   start=end+1;
  }
 }
 if(!values.is_array()||values.size()>32)throw std::runtime_error("Unsupported filament metadata");
 for(const auto&v:values)if(!v.is_string()||v.get<std::string>().size()>128)throw std::runtime_error("Invalid filament metadata");
 return values;
}
inline Json preview_file(const std::string&path,const Json&metadata,const std::string&error,bool usage_tools=false){
 Json result={{"id",path},{"name",path},{"sliced",Json::array()},{"metadata_error",error}};
 if(!error.empty())return result;
 if(!metadata.is_object()||metadata.value("filename",path)!=path)throw std::runtime_error("Metadata belongs to a different file");
 auto materials=metadata_strings(metadata,"filament_type"),colors=metadata_strings(metadata,"preset_colours"),brands=metadata_strings(metadata,"filament_vendor");
 auto count=std::max(materials.size(),colors.size());
 if(usage_tools&&count==0)for(const auto*key:{"filament_used_mm","filament_used_g"})if(metadata.contains(key)&&metadata[key].is_array()){
  if(metadata[key].size()>32)throw std::runtime_error("Unsupported filament usage metadata");
  count=std::max(count,metadata[key].size());
 }
 Json usage=Json::array();
 for(const auto*key:{"filament_used_mm","filament_used_g"})if(metadata.contains(key)&&!metadata[key].is_null()){
  const auto&values=metadata[key];
  if(!values.is_array()||values.size()!=count)throw std::runtime_error("Filament usage metadata does not match preset entries");
  if(usage.empty())usage=Json::array();
  for(std::size_t i=0;i<count;++i){
   if(!values[i].is_number()||!std::isfinite(values[i].get<double>())||values[i].get<double>()<0)throw std::runtime_error("Invalid filament usage metadata");
   if(usage.size()<=i)usage.push_back(false);
   usage[i]=usage[i].get<bool>()||values[i].get<double>()>0;
  }
 }
 for(std::size_t i=0;i<count;++i){
  if(!usage.empty()&&!usage[i].get<bool>())continue;
  std::string color=i<colors.size()?colors[i].get<std::string>():"#888888";
  if(color.size()!=7||color[0]!='#'||color.substr(1).find_first_not_of("0123456789abcdefABCDEF")!=std::string::npos)color="#888888";
  Json row={{"id",std::to_string(i)},{"color",color},{"material",i<materials.size()?materials[i].get<std::string>():"Unknown"},{"brand",i<brands.size()?brands[i].get<std::string>():""}};
  for(const auto*key:{"filament_used_mm","filament_used_g"})if(metadata.contains(key)&&metadata[key].is_array())row[key]=metadata[key][i];
  result["sliced"].push_back(row);
 }
 if(usage_tools&&result["sliced"].empty()&&metadata.contains("wmp_used_tools")){
  const auto indices=metadata.at("wmp_used_tools");if(!indices.is_array()||indices.empty()||indices.size()>4)throw std::runtime_error("Invalid inspected tool usage");
  std::set<int>seen;for(const auto&index:indices){if(!index.is_number_integer()||index.get<int>()<0||index.get<int>()>3||!seen.insert(index.get<int>()).second)throw std::runtime_error("Invalid inspected tool index");
   result["sliced"].push_back({{"id",std::to_string(index.get<int>())},{"color","#888888"},{"material","Unknown"},{"brand",""}});}
 }
 result["usage_known"]=!usage.empty()||(usage_tools&&metadata.contains("wmp_used_tools"));
 if(result["sliced"].empty())result["metadata_error"]="No used filament metadata available";
 // Keep raw file identity in the revision; a replacement file invalidates mapping.
 result["file_identity"]={{"size",metadata.value("size",Json())},{"modified",metadata.value("modified",Json())},{"uuid",metadata.value("uuid",Json())}};
 return result;
}
inline std::string material_key(std::string value){
 while(!value.empty()&&value.front()==' ')value.erase(0,1);
 while(!value.empty()&&value.back()==' ')value.pop_back();
 for(char&c:value)if(c>='a'&&c<='z')c=char(c-'a'+'A');
 // Only explicitly supported cosmetic variants share a slicing family.
 // Do not strip arbitrary suffixes: filled/high-temperature blends may differ.
 if(value=="PLA MATTE")return "PLA";
 return value;
}
inline void project_preview(Json&out,const std::string&path,const Json&metadata,const std::string&error){
 out["files"]=Json::array({preview_file(path,metadata,error,out.value("owner","")=="standalone"&&out.value("print_material_confirmation_protocol",0)==1)});
 for(auto&route:out["routes"]){route["sliced_rows"]=Json::array();if(!route.value("eligible",false))continue;
  std::string material;for(const auto&source:out["sources"])if(source.value("id","")==route.value("source",""))material=material_key(source.value("identity",Json::object()).value("material",""));
  if(out.value("owner","")=="standalone"&&out.value("print_material_confirmation_protocol",0)==1){
   route["material_warnings"]=Json::object();
   for(const auto&row:out["files"][0]["sliced"]){const auto id=row.at("id").get<std::string>();route["sliced_rows"].push_back(id);
    auto sliced=row.value("material","");auto actual=material;
    for(char&c:sliced)if(c>='a'&&c<='z')c=char(c-'a'+'A');
    // Compare full material names here; cosmetic-family equivalence is not consent.
    for(const auto&source:out["sources"])if(source.value("id","")==route.value("source","")){actual=source.value("identity",Json::object()).value("material","");for(char&c:actual)if(c>='a'&&c<='z')c=char(c-'a'+'A');}
    if(route.value("material_confirmation_required",false)||actual.empty()||actual=="UNKNOWN"||sliced.empty()||sliced=="UNKNOWN"||actual!=sliced)
     {
      const auto head=route.value("head","");
      const auto caption=head.size()==2&&head[0]=='h'&&head[1]>='0'&&head[1]<='3'
       ?"Head "+std::to_string(head[1]-'0'+1):"Tool "+id;
      route["material_warnings"][id]=caption+": file "+(sliced.empty()?"unknown":sliced)+", loaded "+(actual.empty()?"unknown":actual)+".";
     }
   }continue;
  }
  if(material.empty()||material=="UNKNOWN")continue;
  for(const auto&row:out["files"][0]["sliced"])if(material_key(row.value("material",""))==material)route["sliced_rows"].push_back(row["id"]);
 }
 out["revision"]=revision(Json{{"printer",out["revision"]},{"file",out["files"][0]}});
 // Procedures belong to this same composed snapshot. Their backend tokens
 // remain untouched; only the frontend review revision follows file metadata.
 // Otherwise opening a preview makes every later procedure fail its revision
 // check, even when the operator returns to Tools and reviews it afresh.
 if(out.contains("procedures"))for(auto&plan:out["procedures"])plan["revision"]=out["revision"];
 // Pure metadata projection cannot authorize motion. Runtime enables Start
 // only with the appropriate helper protocol and verified native context adapter.
 out["capabilities"]["start_print"]=false;
}
}}
