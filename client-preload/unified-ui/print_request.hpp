// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "model.hpp"
#include <cmath>
namespace wmp_ui {
// Pure preparation: no client flag writes, file edits, G-code or network I/O.
inline Json standalone_print_request(const Json&snapshot,const Json&args,const std::string&id){
 auto fail=[](const char*message){throw std::runtime_error(message);};
 if(snapshot.value("owner","")!="standalone"||!snapshot.value("fresh",false))fail("Fresh standalone status is required.");
 auto state=snapshot.at("job").value("state","");if(state!="idle"&&state!="complete")fail("Another print is active.");
 if(snapshot.value("print_start_protocol",0)!=1)fail("Standalone submission helper is unavailable.");
 auto revision=snapshot.value("identity_revision","");if(revision.size()!=64||revision.find_first_not_of("0123456789abcdef")!=std::string::npos)fail("Invalid filament settings revision.");
 auto existing=snapshot.at("physical_mapping");if(!existing.is_array()||existing.size()!=4)fail("Existing tool mapping is unavailable.");
 for(const auto&v:existing)if(!v.is_number_integer()||v.get<int>()<0||v.get<int>()>3)fail("Invalid existing tool mapping.");
 const auto&options=args.at("options");if(!options.is_object()||options.size()!=2||!options.at("leveling").is_boolean()||!options.at("timelapse").is_boolean())fail("Invalid print options.");
 auto path=args.at("file").get<std::string>();
 if(path.empty()||path.size()>1024||path.front()=='/'||path.back()=='/')fail("Unsupported print filename.");
 for(unsigned char c:path)if(c<32||c==127||c=='\\'||c=='"')fail("Unsupported print filename.");
 for(std::size_t at=0;at<path.size();){auto end=path.find('/',at);auto part=path.substr(at,end==std::string::npos?end:end-at);if(part.empty()||part=="."||part=="..")fail("Unsupported print filename.");if(end==std::string::npos)break;at=end+1;}
 const Json*file=nullptr;for(const auto&f:snapshot.at("files"))if(f.value("id","")==path)file=&f;
 if(!file||!file->value("metadata_error","").empty())fail("File metadata is unavailable.");
 auto identity=file->at("file_identity");
 if(!identity.at("size").is_number_integer()||identity["size"].get<long long>()<=0||!identity.at("modified").is_number()||!std::isfinite(identity["modified"].get<double>()))fail("File identity is incomplete.");
 const auto&rows=file->at("sliced");const auto&choices=args.at("routes");
 if(!rows.is_array()||rows.empty()||rows.size()>4||!choices.is_object()||choices.size()!=rows.size())fail("Choose a source for every sliced filament.");
 Json mapping=Json::object(),materials=Json::object();
 const bool consent=args.value("material_confirmation",false);
 const bool consent_protocol=snapshot.value("print_material_confirmation_protocol",0)==1;
 for(const auto&row:rows){auto sliced=row.at("id").get<std::string>();if(sliced.size()!=1||sliced[0]<'0'||sliced[0]>'3'||mapping.contains(sliced))fail("Unsupported sliced tool index.");
  const Json*route=nullptr;for(const auto&r:snapshot.at("routes"))if(r.at("id")==choices.at(sliced))route=&r;
  if(!route||!route->value("eligible",false))fail("Selected route is unavailable.");
  auto allowed=route->at("sliced_rows");if(std::find(allowed.begin(),allowed.end(),sliced)==allowed.end())fail("Selected filament is incompatible.");
  auto head=route->at("head").get<std::string>();if(head.size()!=2||head[0]!='h'||head[1]<'0'||head[1]>'3')fail("Invalid physical destination.");
  bool installed=false,available=false;
  for(const auto&h:snapshot.at("heads"))if(h.at("id")==head)installed=true;
  for(const auto&s:snapshot.at("sources"))if(s.at("id")==route->at("source")&&s.value("head","")==head&&s.value("kind","")=="external"){
   available=s.value("available",false);
   const auto identity=s.value("identity",Json::object());
   for(const auto*field:{"brand","color"})if(identity.contains(field)&&(!identity[field].is_string()||
      (std::string(field)=="color"&&identity_display_text(identity,field,"").empty())))
    throw std::runtime_error("Correct the selected filament's "+std::string(field)+" before printing.");
  }
  if(!installed||!available)fail("Selected physical head is unavailable.");
  if(consent_protocol){
   const auto warnings=route->value("material_warnings",Json::object());
   if((route->value("material_confirmation_required",false)||warnings.contains(sliced))&&!consent)fail("Confirm the selected filament before printing.");
   materials[sliced]=row.value("material","");
  }
  // A displayed T alias is not the physical index. Resolve the chosen route.
  mapping[sliced]=head[1]-'0';
 }
 Json request={{"id",id},{"session",snapshot.at("session")},{"profile_revision",revision},
  {"file",{{"path",path},{"size",identity["size"]},{"modified",identity["modified"]}}},
  {"mapping",mapping},{"expected_mapping",existing},{"leveling",options["leveling"]}};
 if(consent_protocol){request["material_confirmation"]=consent;request["sliced_materials"]=materials;}
 if(snapshot.value("print_sequence_protocol",0)==1){
  auto high=snapshot.value("print_request_sequence",0LL);if(high<0||high>=9007199254740990LL)fail("Print sequence is invalid.");
  auto next=high+1;if(id.compare(0,6,"print_")==0){const auto text=id.substr(6);if(text.empty()||text.find_first_not_of("0123456789")!=std::string::npos)fail("Invalid print sequence identifier.");next=std::stoll(text);if(next<=high||next>9007199254740991LL)fail("Print sequence is no longer current.");}
  request["sequence"]=next;request["id"]="print_"+std::to_string(next);
 }
 return request;
}

// Build the public openACE submission from the exact preview choices. This is
// preparation only: caller must revalidate status/file and stage native flags
// before dispatch, and confirm backend admission afterward.
inline Json openace_print_request(const Json&snapshot,const Json&args){
 auto fail=[](const char*message){throw std::runtime_error(message);};
 if(snapshot.value("owner","")!="openace"||!snapshot.value("fresh",false))fail("Fresh openACE status is required.");
 auto state=snapshot.at("job").value("state","");if(state!="idle"&&state!="complete")fail("Another print is active.");
 if(snapshot.value("session","").empty())fail("openACE session is unavailable.");
 const auto&options=args.at("options");if(!options.is_object()||options.size()!=2||!options.at("leveling").is_boolean()||!options.at("timelapse").is_boolean())fail("Invalid print options.");
 auto path=args.at("file").get<std::string>();
 if(path.empty()||path.size()>1024||path.front()=='/'||path.back()=='/')fail("Unsupported print filename.");
 for(unsigned char c:path)if(c<32||c==127||c=='\\'||c=='"'||c==';'||c=='#')fail("Unsupported print filename.");
 for(std::size_t at=0;at<path.size();){auto end=path.find('/',at);auto part=path.substr(at,end==std::string::npos?end:end-at);if(part.empty()||part=="."||part=="..")fail("Unsupported print filename.");if(end==std::string::npos)break;at=end+1;}
 const Json*file=nullptr;for(const auto&f:snapshot.at("files"))if(f.value("id","")==path){if(file)fail("Ambiguous file metadata.");file=&f;}
 if(!file||!file->value("metadata_error","").empty())fail("File metadata is unavailable.");
 const auto&identity=file->at("file_identity");
 if(!identity.at("size").is_number_integer()||identity["size"].get<long long>()<=0||!identity.at("modified").is_number()||!std::isfinite(identity["modified"].get<double>()))fail("File identity is incomplete.");
 const auto&rows=file->at("sliced");const auto&choices=args.at("routes");
 if(!rows.is_array()||rows.empty()||rows.size()>32||!choices.is_object()||choices.size()!=rows.size())fail("Choose a source for every sliced filament.");
 std::map<int,int>pairs;
 for(const auto&row:rows){auto sliced=row.at("id").get<std::string>();
  if(sliced.empty()||sliced.size()>2||sliced.find_first_not_of("0123456789")!=std::string::npos)fail("Invalid sliced tool index.");
  int index=std::stoi(sliced);if(index>31||std::to_string(index)!=sliced||pairs.count(index))fail("Invalid sliced tool index.");
  const Json*route=nullptr;for(const auto&r:snapshot.at("routes"))if(r.at("id")==choices.at(sliced)){if(route)fail("Ambiguous route.");route=&r;}
  if(!route||!route->value("eligible",false)||!route->contains("tool")||!(*route)["tool"].is_number_integer())fail("Selected route is unavailable.");
  int tool=(*route)["tool"].get<int>();if(tool<0||tool>31||route->at("id")!="T"+std::to_string(tool))fail("Invalid virtual tool.");
  const auto&allowed=route->at("sliced_rows");if(std::find(allowed.begin(),allowed.end(),sliced)==allowed.end())fail("Selected filament is incompatible.");
  bool installed=false,available=false;
  for(const auto&h:snapshot.at("heads"))if(h.at("id")==route->at("head"))installed=true;
  for(const auto&source:snapshot.at("sources"))if(source.at("id")==route->at("source")&&source.at("head")==route->at("head"))available=source.value("available",false);
  if(!installed||!available)fail("Selected source or physical head is unavailable.");
  pairs[index]=tool;
 }
 Json mapping=Json::array();for(const auto&pair:pairs)mapping.push_back(Json::array({pair.first,pair.second}));
 std::string command="SDCARD_PRINT_FILE FILENAME=\""+path+"\" OPENACE_MAP=\""+mapping.dump()+"\"";
 if(command.size()>2048)fail("Print request exceeds the local transport limit.");
 return {{"command",command},{"pairs",mapping},{"file",path},{"file_identity",identity},{"session",snapshot.at("session")},{"revision",snapshot.at("revision")},{"options",options}};
}

inline Json openace_helper_print_request(const Json&snapshot,const Json&args,const std::string&id){
 auto prepared=openace_print_request(snapshot,args);
 if(snapshot.value("openace_print_start_protocol",0)!=1||snapshot.value("print_helper_session","").empty())throw std::runtime_error("Mapped submission helper is unavailable.");
 for(const auto&key:{"ace_session","ace_config_revision"})if(!snapshot.contains(key)||!snapshot[key].is_number_integer()||snapshot[key].get<long long>()<0)throw std::runtime_error("openACE revision evidence is unavailable.");
 auto identity=prepared.at("file_identity");
 return {{"id",id},{"session",snapshot.at("print_helper_session")},{"owner","openace"},
  {"ace_session",snapshot.at("ace_session")},{"config_revision",snapshot.at("ace_config_revision")},
  {"pairs",prepared.at("pairs")},{"file",{{"path",prepared.at("file")},{"size",identity.at("size")},{"modified",identity.at("modified")}}},{"leveling",args.at("options").at("leveling")}};
}

}
