#pragma once
#include "worker_bridge.hpp"
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
class LoopbackHttp : public HttpPort {
public:
 explicit LoopbackHttp(std::uint16_t port=7125,unsigned timeout_ms=500):port_(port),timeout_(timeout_ms){
  if(!port||!timeout_ms||timeout_ms>2000)throw std::runtime_error("invalid local HTTP bound");
 }
 std::string get(const std::string&path)override {
  if(path!=ScreenWorker::query()&&path!=ScreenWorker::management_query())throw std::runtime_error("unsupported UI query");
  return request("GET",path,"");
 }
 std::string post(const std::string&path,const std::string&body)override {
  if(path!="/printer/gcode/script"||body.size()>512)throw std::runtime_error("unsupported UI command");
  return request("POST",path,body);
 }
private:
 struct Socket{int fd;explicit Socket(int f):fd(f){}~Socket(){if(fd>=0)::close(fd);}};
 std::uint16_t port_;unsigned timeout_;
 static std::int64_t now(){timespec t{};if(clock_gettime(CLOCK_MONOTONIC,&t))throw std::runtime_error("clock unavailable");return std::int64_t(t.tv_sec)*1000+t.tv_nsec/1000000;}
 static void wait(int fd,short events,std::int64_t until){
  while(true){auto left=until-now();if(left<=0)throw std::runtime_error("local HTTP deadline exceeded");
   pollfd p{fd,events,0};int n=::poll(&p,1,int(left));if(n<0&&errno==EINTR)continue;
   if(n<=0||p.revents&POLLNVAL)throw std::runtime_error("local HTTP unavailable");
   if(p.revents&(events|POLLHUP|POLLERR))return;
  }
 }
 static long headers(const std::string&head,bool allow_error,bool&failure){
  auto end=head.find("\r\n");std::string status=head.substr(0,end);
  if(status.size()<12||(status.compare(0,9,"HTTP/1.0 ")&&status.compare(0,9,"HTTP/1.1 "))
      ||(status.size()>12&&status[12]!=' '))throw std::runtime_error("Moonraker HTTP failure");
  failure=status.compare(9,3,"200")!=0;
  if(failure&&(!allow_error||status[9]<'4'||status[9]>'5'||status[10]<'0'||status[10]>'9'||status[11]<'0'||status[11]>'9'))throw std::runtime_error("Moonraker HTTP failure");
  long length=-1;std::size_t start=end+2;
  while(start<head.size()){
   auto next=head.find("\r\n",start);if(next==std::string::npos)next=head.size();
   std::string line=head.substr(start,next-start);auto colon=line.find(':');
   if(colon==std::string::npos)throw std::runtime_error("malformed HTTP header");
   std::string key=line.substr(0,colon),value=line.substr(colon+1);
   for(char&c:key)c=char(std::tolower(static_cast<unsigned char>(c)));
   while(!value.empty()&&(value.front()==' '||value.front()=='\t'))value.erase(0,1);
   while(!value.empty()&&(value.back()==' '||value.back()=='\t'))value.pop_back();
   if(key=="transfer-encoding")throw std::runtime_error("unsupported HTTP transfer encoding");
   if(key=="content-length"){
    if(length>=0||value.empty()||value.size()>6)throw std::runtime_error("ambiguous HTTP size");
    length=0;for(char c:value){if(c<'0'||c>'9')throw std::runtime_error("invalid HTTP size");length=length*10+c-'0';}
    if(length>262144)throw std::runtime_error("HTTP reply too large");
   }start=next+2;
  }return length;
 }
 std::string request(const std::string&method,const std::string&path,const std::string&body){
  const auto until=now()+timeout_;Socket socket(::socket(AF_INET,SOCK_STREAM|SOCK_CLOEXEC|SOCK_NONBLOCK,0));
  if(socket.fd<0)throw std::runtime_error("local HTTP socket unavailable");
  sockaddr_in address{};address.sin_family=AF_INET;address.sin_port=htons(port_);address.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
  if(::connect(socket.fd,reinterpret_cast<sockaddr*>(&address),sizeof(address))){
   if(errno!=EINPROGRESS)throw std::runtime_error("local Moonraker unavailable");
   wait(socket.fd,POLLOUT,until);int problem=0;socklen_t size=sizeof(problem);
   if(getsockopt(socket.fd,SOL_SOCKET,SO_ERROR,&problem,&size)||problem)throw std::runtime_error("local Moonraker unavailable");
  }
  std::string bytes=method+" "+path+" HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n";
  if(method=="POST")bytes+="Content-Type: application/json\r\nContent-Length: "+std::to_string(body.size())+"\r\n";
  bytes+="\r\n"+body;
  for(std::size_t sent=0;sent<bytes.size();){wait(socket.fd,POLLOUT,until);
   auto n=::send(socket.fd,bytes.data()+sent,bytes.size()-sent,MSG_NOSIGNAL);
   if(n<0&&(errno==EAGAIN||errno==EWOULDBLOCK||errno==EINTR))continue;
   if(n<=0)throw std::runtime_error("local HTTP send failed");
   sent+=std::size_t(n);
  }
  std::string reply;std::size_t separator=std::string::npos;long length=-1;bool failure=false;
  while(true){
   if(separator!=std::string::npos&&length>=0&&reply.size()>=separator+4+std::size_t(length))break;
   wait(socket.fd,POLLIN,until);char buffer[8192];auto n=::recv(socket.fd,buffer,sizeof(buffer),0);
   if(n<0&&(errno==EAGAIN||errno==EWOULDBLOCK||errno==EINTR))continue;
   if(n<0)throw std::runtime_error("local HTTP read failed");
   if(n==0)break;
   reply.append(buffer,std::size_t(n));if(reply.size()>262144+8192)throw std::runtime_error("HTTP reply too large");
   if(separator==std::string::npos){separator=reply.find("\r\n\r\n");
    if(separator==std::string::npos){if(reply.size()>8192)throw std::runtime_error("HTTP headers too large");}
    else{if(separator>8192)throw std::runtime_error("HTTP headers too large");length=headers(reply.substr(0,separator),method=="POST",failure);}
   }
  }
  if(separator==std::string::npos)throw std::runtime_error("incomplete HTTP headers");
  auto result=reply.substr(separator+4);
  if(result.size()>262144||(length>=0&&std::size_t(length)!=result.size()))throw std::runtime_error("incomplete HTTP body");
  if(failure){if(!ScreenModel::acceptable_payload(result))throw std::runtime_error("bounded error reply required");auto parsed=json::parse(result);if(!parsed.is_object()||!parsed.contains("error"))throw std::runtime_error("Moonraker HTTP failure");}
  return result;
 }
};
}
