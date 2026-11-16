#include "native/usb_import.hpp"
#include "native/usb_copy_http.hpp"
#include <cassert>
using namespace wmp_ui;
using namespace wmp_ui::native;
struct Http: wmp_openace::HttpPort {
 std::vector<std::pair<std::string,Json>> calls;
 std::string fault;unsigned reads=0;Json destination_metadata;
 std::string get(const std::string&path)override{assert(UsbCopyHttp::allowed_get(path));++reads;return Json{{"result",destination_metadata}}.dump();}
 std::string post(const std::string&path,const std::string&body)override{
  assert(UsbCopyHttp::allowed(path,body));
  const auto args=Json::parse(body);calls.push_back({path,args});
  if(fault=="timeout"&&calls.size()==2)throw std::runtime_error("Lost reply");
  if(fault=="collision"&&calls.size()==1)return "{\"error\":\"already exists\"}";
  const bool directory=path=="/server/files/directory";
  assert(directory||path=="/server/files/copy");
  auto relative=args.at(directory?"path":"dest").get<std::string>().substr(7);
  if(fault=="wrong-path"&&calls.size()==2)relative="another.gcode";
  Json result={{"action",directory?"create_dir":fault=="overwrite"?"modify_file":"create_file"},
   {"item",{{"root","gcodes"},{"path",relative},{"size",fault=="wrong-size"?11:12}}}};
  return Json{{"result",result}}.dump();
 }
};
int main(){
 const Json data={{"fresh",true},{"owner","openace"},{"session","s"},{"revision","r"},{"job",{{"state","idle"}}}};
 const std::string nonce(32,'a');
 const auto destination="gcodes/WM_USB_"+nonce+"/part.gcode";
 const Json request={{"source","gcodes/USB/folder/part.gcode"},{"dest",destination}};
 assert(UsbCopyHttp::allowed("/server/files/copy",request.dump()));
 for(const auto*source:{"gcodes/local.gcode","gcodes/USB/../part.gcode","config/printer.cfg","gcodes/USB/other.gcode"}){
  auto bad=request;bad["source"]=source;assert(!UsbCopyHttp::allowed("/server/files/copy",bad.dump()));
 }
 for(const auto*dest:{"gcodes/part.gcode","config/printer.cfg","gcodes/WM_USB_bad/part.gcode"}){
  auto bad=request;bad["dest"]=dest;assert(!UsbCopyHttp::allowed("/server/files/copy",bad.dump()));
 }
 auto extra=request;extra["print"]=true;assert(!UsbCopyHttp::allowed("/server/files/copy",extra.dump()));
 assert(!UsbCopyHttp::allowed("/printer/gcode/script","{\"script\":\"G28\"}"));
 assert(!UsbCopyHttp::allowed("/server/files/delete",request.dump()));
 assert(!UsbCopyHttp::allowed("/server/files/directory","{\"path\":\"gcodes\"}"));
 assert(!UsbCopyHttp::allowed("/server/files/copy","not json"));
 UsbCopyHttp copy_transport;
 bool refused=false;try{copy_transport.post("/printer/gcode/script","{\"script\":\"G28\"}");}catch(...){refused=true;}
 assert(refused); // Rejected before any socket can be opened.
 for(const auto*owner:{"openace","standalone"}){
  auto current=data;current["owner"]=owner;UsbImport copy;Http http;
  assert(copy.begin(current,"folder/part with space.gcode",nonce,12));
  assert(!copy.begin(current,"other.gcode",nonce,12));
  copy.run(http,current);assert(copy.result()["state"]=="copied");
  assert(http.calls.size()==2&&http.calls[0].second["path"]=="gcodes/WM_USB_"+nonce);
  assert(http.calls[1].second["source"]=="gcodes/USB/folder/part with space.gcode");
  assert(http.calls[1].second["dest"]=="gcodes/WM_USB_"+nonce+"/part with space.gcode");
  copy.run(http,current);assert(http.calls.size()==2); // no automatic copy or print repeat
 }
 for(const auto*path:{"","/absolute.gcode","../escape.gcode","nested/../escape.gcode","a\\b","a\nb","a//b"}){
  UsbImport copy;assert(!copy.begin(data,path,nonce,12));
 }
 // Copying files is independent of print state, settings or telemetry.
 for(const auto*state:{"printing","paused","error","idle"}){
  UsbImport copy;Http http;auto changed=data;changed["job"]["state"]=state;changed["revision"]="new";changed["session"]="restarted";changed["fresh"]=false;changed["owner"]="unknown";
  assert(copy.begin(Json::object(),"part.gcode",nonce,12));copy.run(http,changed);
  assert(copy.result()["state"]=="copied"&&http.calls.size()==2);
 }
 // Only a confirmed private reservation + matching destination + unchanged USB
 // source can turn a lost response into a confirmed copied file. Never replay.
 for(const auto*condition:{"match","size","path","source","collision","missing"}){
  UsbImport copy;Http http;const std::string kind=condition;http.fault=kind=="collision"?"collision":"timeout";
  http.destination_metadata={{"filename","WM_USB_"+nonce+"/part.gcode"},{"size",12}};
  if(kind=="size")http.destination_metadata["size"]=11;
  if(kind=="path")http.destination_metadata["filename"]="other.gcode";
  if(kind=="missing")http.destination_metadata=Json::object();
  assert(copy.begin(data,"part.gcode",nonce,12));copy.run(http,data,[&]{return kind!="source";});
  assert(copy.result()["state"]==(kind=="match"?"copied":"unknown"));
  assert(http.reads==(kind=="collision"?0:1));const auto writes=http.calls.size();copy.run(http,data,[]{return true;});assert(http.calls.size()==writes&&http.reads==(kind=="collision"?0:1));
 }
 assert(!UsbCopyHttp::allowed_get(std::string(5000,'a')));
 assert(UsbCopyHttp::allowed_get(metadata_query("WM_USB_"+nonce+"/part #1.gcode")));
 for(const auto*query:{"/printer/objects/query?print_stats","/server/files/metadata?filename=printer.cfg","/server/files/metadata?filename=WM_USB_bad%2Fpart.gcode","/server/files/metadata?filename=WM_USB_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa%2F..%2Fpart.gcode","/server/files/metadata?filename=WM_USB_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa%2Fpart.gcode&root=config"})assert(!UsbCopyHttp::allowed_get(query));
 for(const auto*fault:{"collision","timeout","wrong-path","wrong-size","overwrite"}){
  UsbImport copy;Http http;http.fault=fault;assert(copy.begin(data,"part.gcode",nonce,12));copy.run(http,data);
  assert(copy.result()["state"]=="unknown");const auto count=http.calls.size();
  assert(count==(http.fault=="collision"?1:2));copy.run(http,data);assert(http.calls.size()==count);
 }
 UsbImport unavailable;
 assert(!unavailable.begin(data,"part.gcode","bad",12));assert(!unavailable.begin(data,"part.gcode",nonce,0));
}
