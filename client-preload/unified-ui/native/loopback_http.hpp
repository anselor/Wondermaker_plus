// SPDX-License-Identifier: GPL-3.0-or-later
// Native unified transport, derived from the frozen V14 bounded loopback transport.
#pragma once
#include "../../openace-compat/screen1113/source/client/worker_bridge.hpp"
#include "http_failure.hpp"
#include <set>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <poll.h>
#include <unistd.h>
#include <cerrno>
#include <cctype>
#include <time.h>
namespace wmp_openace {
// Worker-only HTTP/1.0 client to the existing local Moonraker endpoint. Each
// complete request has one absolute deadline, including drip-fed responses.
class UnifiedLoopbackHttp : public HttpPort {
public:
// Stock Klipper schedules object replies on a 250 ms timer. Field diagnostics
 // show valid replies approaching one second and repeated one-second timeouts.
 // Allow scheduling margin while retaining a bounded
 // request and the runtime's independent two-second freshness gate.
 explicit UnifiedLoopbackHttp(std::uint16_t port=7125,unsigned timeout_ms=1500):port_(port),timeout_(timeout_ms){
  if(!port||!timeout_ms||timeout_ms>2000)throw std::runtime_error("invalid local HTTP bound");
 }
 std::string get(const std::string&path)override {
  if(!allowed_query(path))throw std::runtime_error("unsupported UI query");
  return request("GET",path,"");
 }
 std::string post(const std::string&path,const std::string&body)override {
  const bool recovery_review=path=="/printer/wmp/recovery/review"||path=="/printer/wmp/recovery/resolve_review"||path=="/printer/wmp/recovery/retire_review"||path=="/printer/wmp/recovery/retire_result", recovery_stop=path=="/printer/wmp/recovery/stop";
  const bool print_cancel=path=="/printer/wmp/print/cancel_review"||path=="/printer/wmp/print/cancel"||path=="/printer/wmp/print/cancel_resolve_review";
  const bool clear_cancelled=path=="/printer/wmp/print/clear_cancelled";
  const bool probe_stop=path=="/printer/wmp/probe_editor/stop"||path=="/printer/wmp/calibration/cancel"||path=="/printer/wmp/identification/cancel";
  if(path!="/printer/gcode/script"&&path!="/printer/wmp/filament/cancel"&&path!="/printer/wmp/toolhead/cancel"&&!recovery_review&&!recovery_stop&&!print_cancel&&!clear_cancelled&&!probe_stop)throw std::runtime_error("unsupported UI command");
  if(body.size()>((path=="/printer/gcode/script"||print_cancel)?32768u:recovery_review?16384u:2048u))throw std::runtime_error("UI command too large");
  if(path=="/printer/gcode/script"){
   // Vendor Moonraker copies multiline Klipper errors into the HTTP reason
   // phrase on the REST route. Tornado rejects that header and drops the reply.
   // JSON-RPC keeps errors in the body. Send once; never fall back/retry REST.
   auto params=json::parse(body);
   if(!params.is_object()||params.size()!=1||!params.contains("script")||!params["script"].is_string())throw std::runtime_error("invalid UI command body");
   if(body.size()>2048){
    const auto script=params.at("script").get<std::string>();std::string prefix;
    for(const auto*candidate:{"WMP_RECOVERY_CONTINUE REQUEST=","WMP_RETIRE_RECOVERY REQUEST="})
     if(script.compare(0,std::string(candidate).size(),candidate)==0)prefix=candidate;
    if(prefix.empty())throw std::runtime_error("UI command too large");
    const auto hex=script.substr(prefix.size());
    if(hex.empty()||hex.size()>16384||hex.size()%2||hex.find_first_not_of("0123456789abcdef")!=std::string::npos)throw std::runtime_error("Invalid recovery command encoding");
   }
   auto wire=json{{"jsonrpc","2.0"},{"method","printer.gcode.script"},{"params",params},{"id",1}};
   auto result=request("POST","/server/jsonrpc",wire.dump());
   if(!ScreenModel::acceptable_payload(result))throw std::runtime_error("bounded RPC reply required");
   auto reply=json::parse(result);
   if(!reply.is_object()||reply.value("jsonrpc",std::string())!="2.0"||!reply.contains("id")||!reply["id"].is_number_integer()||reply["id"]!=1||reply.contains("result")==reply.contains("error"))throw std::runtime_error("invalid command RPC reply");
   if(reply.contains("error")){
    auto error=reply["error"];
    if(!error.is_object()||!error.contains("code")||!error["code"].is_number_integer()||!error.contains("message")||!error["message"].is_string())throw std::runtime_error("invalid command RPC error");
    return json{{"error",error}}.dump();
   }
   return json{{"result",reply["result"]}}.dump();
  }
  return request("POST",path,body);
 }
static bool allowed_query(const std::string&path){
  const std::string metadata="/server/files/metadata?filename=";
  if(path.compare(0,metadata.size(),metadata)==0){auto tail=path.substr(metadata.size());if(tail.empty()||tail.size()>3072)return false;for(unsigned char c:tail)if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='%'||c=='-'||c=='_'||c=='.'||c=='~'))return false;return true;}

  if(path==ScreenWorker::query()||path==ScreenWorker::management_query()||path=="/printer/objects/list"||path=="/server/files/roots"||path=="/printer/wmp/filament/details")return true;
  const std::string prefix="/printer/objects/query?";
  if(path.compare(0,prefix.size(),prefix)!=0)return false;
  const std::set<std::string>allowed={"webhooks","wmp_case_light=enabled,policy_version","gcode_button%20Door_button1=state","gcode_button%20Door_button2=state","wmp_recovery","save_variables=variables","wm_material","print_stats","virtual_sdcard=is_active","pause_resume=is_paused","configfile=settings","toolhead=extruder","extruder","extruder1","extruder2","extruder3","gcode_macro%20WMP_EXTRUDER_STEP","openace=session_id,management,heads,units,default_tool_map,inventory,loaded,devices,blocked_tools,operation,config_revision,job,material_change_prompt,manual_flow,unit_discovery,unit_settings"};
  std::set<std::string>seen;std::size_t at=prefix.size();
  while(at<path.size()){auto end=path.find('&',at);auto key=path.substr(at,end==std::string::npos?end:end-at);if(!allowed.count(key)||!seen.insert(key).second)return false;if(end==std::string::npos)return true;at=end+1;}
  return false;
 }
private:
 struct Socket{int fd;explicit Socket(int f):fd(f){}~Socket(){if(fd>=0)::close(fd);}};
 std::uint16_t port_;unsigned timeout_;
 static std::int64_t now(){timespec t{};if(clock_gettime(CLOCK_MONOTONIC,&t))throw std::runtime_error("clock unavailable");return std::int64_t(t.tv_sec)*1000+t.tv_nsec/1000000;}
 static void wait(int fd,short events,std::int64_t until){
  while(true){auto left=until-now();if(left<=0)throw HttpFailure(HttpFailureKind::Deadline,"local HTTP deadline exceeded");
   pollfd p{fd,events,0};int n=::poll(&p,1,int(left));if(n<0&&errno==EINTR)continue;
   if(n==0)throw HttpFailure(HttpFailureKind::Deadline,"local HTTP deadline exceeded");
   if(n<0||p.revents&POLLNVAL)throw HttpFailure(HttpFailureKind::Io,"local HTTP unavailable");
   if(p.revents&(events|POLLHUP|POLLERR))return;
  }
 }
 static long headers(const std::string&head,bool allow_error,bool&failure){
  auto end=head.find("\r\n");std::string status=head.substr(0,end);
  if(status.size()<12||(status.compare(0,9,"HTTP/1.0 ")&&status.compare(0,9,"HTTP/1.1 "))
      ||(status.size()>12&&status[12]!=' '))throw HttpFailure(HttpFailureKind::Response,"Moonraker HTTP failure");
  failure=status.compare(9,3,"200")!=0;
  if(failure&&(!allow_error||status[9]<'4'||status[9]>'5'||status[10]<'0'||status[10]>'9'||status[11]<'0'||status[11]>'9'))throw HttpFailure(HttpFailureKind::Response,"Moonraker HTTP failure");
  long length=-1;std::size_t start=end+2;
  while(start<head.size()){
   auto next=head.find("\r\n",start);if(next==std::string::npos)next=head.size();
   std::string line=head.substr(start,next-start);auto colon=line.find(':');
   if(colon==std::string::npos)throw HttpFailure(HttpFailureKind::Response,"malformed HTTP header");
   std::string key=line.substr(0,colon),value=line.substr(colon+1);
   for(char&c:key)c=char(std::tolower(static_cast<unsigned char>(c)));
   while(!value.empty()&&(value.front()==' '||value.front()=='\t'))value.erase(0,1);
   while(!value.empty()&&(value.back()==' '||value.back()=='\t'))value.pop_back();
   if(key=="transfer-encoding")throw HttpFailure(HttpFailureKind::Response,"unsupported HTTP transfer encoding");
   if(key=="content-length"){
    if(length>=0||value.empty()||value.size()>6)throw HttpFailure(HttpFailureKind::Response,"ambiguous HTTP size");
    length=0;for(char c:value){if(c<'0'||c>'9')throw HttpFailure(HttpFailureKind::Response,"invalid HTTP size");length=length*10+c-'0';}
    if(length>262144)throw HttpFailure(HttpFailureKind::Response,"HTTP reply too large");
   }start=next+2;
  }return length;
 }
protected:
 std::string request(const std::string&method,const std::string&path,const std::string&body){
  const auto until=now()+(method=="POST"?15000:timeout_);Socket socket(::socket(AF_INET,SOCK_STREAM|SOCK_CLOEXEC|SOCK_NONBLOCK,0));
  if(socket.fd<0)throw HttpFailure(HttpFailureKind::Connection,"local HTTP socket unavailable");
  sockaddr_in address{};address.sin_family=AF_INET;address.sin_port=htons(port_);address.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
  if(::connect(socket.fd,reinterpret_cast<sockaddr*>(&address),sizeof(address))){
   if(errno!=EINPROGRESS)throw HttpFailure(HttpFailureKind::Connection,"local Moonraker unavailable");
   wait(socket.fd,POLLOUT,until);int problem=0;socklen_t size=sizeof(problem);
   if(getsockopt(socket.fd,SOL_SOCKET,SO_ERROR,&problem,&size)||problem)throw HttpFailure(HttpFailureKind::Connection,"local Moonraker unavailable");
  }
  std::string bytes=method+" "+path+" HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n";
  if(method=="POST")bytes+="Content-Type: application/json\r\nContent-Length: "+std::to_string(body.size())+"\r\n";
  bytes+="\r\n"+body;
  for(std::size_t sent=0;sent<bytes.size();){wait(socket.fd,POLLOUT,until);
   auto n=::send(socket.fd,bytes.data()+sent,bytes.size()-sent,MSG_NOSIGNAL);
   if(n<0&&(errno==EAGAIN||errno==EWOULDBLOCK||errno==EINTR))continue;
   if(n<=0)throw HttpFailure(HttpFailureKind::Io,"local HTTP send failed");
   sent+=std::size_t(n);
  }
  std::string reply;std::size_t separator=std::string::npos;long length=-1;bool failure=false;
  while(true){
   if(separator!=std::string::npos&&length>=0&&reply.size()>=separator+4+std::size_t(length))break;
   wait(socket.fd,POLLIN,until);char buffer[8192];auto n=::recv(socket.fd,buffer,sizeof(buffer),0);
   if(n<0&&(errno==EAGAIN||errno==EWOULDBLOCK||errno==EINTR))continue;
   if(n<0)throw HttpFailure(HttpFailureKind::Io,"local HTTP read failed");
   if(n==0)break;
   reply.append(buffer,std::size_t(n));if(reply.size()>262144+8192)throw HttpFailure(HttpFailureKind::Response,"HTTP reply too large");
   if(separator==std::string::npos){separator=reply.find("\r\n\r\n");
    if(separator==std::string::npos){if(reply.size()>8192)throw HttpFailure(HttpFailureKind::Response,"HTTP headers too large");}
    else{if(separator>8192)throw HttpFailure(HttpFailureKind::Response,"HTTP headers too large");length=headers(reply.substr(0,separator),method=="POST",failure);}
   }
  }
  if(separator==std::string::npos)throw HttpFailure(HttpFailureKind::Response,"incomplete HTTP headers");
  auto result=reply.substr(separator+4);
  if(result.size()>262144||(length>=0&&std::size_t(length)!=result.size()))throw HttpFailure(HttpFailureKind::Response,"incomplete HTTP body");
  if(failure){if(!ScreenModel::acceptable_payload(result))throw HttpFailure(HttpFailureKind::Response,"bounded error reply required");auto parsed=json::parse(result);if(!parsed.is_object()||!parsed.contains("error"))throw HttpFailure(HttpFailureKind::Response,"Moonraker HTTP failure");}
  return result;
 }
};
}
