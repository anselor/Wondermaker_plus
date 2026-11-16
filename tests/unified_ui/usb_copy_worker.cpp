#include "native/usb_copy_worker.hpp"
#include <cassert>
#include <future>
#include <fstream>
using namespace wmp_ui;
using namespace wmp_ui::native;
struct CopyHttp: wmp_openace::HttpPort {
 std::mutex mutex;std::condition_variable entered,release;
 bool copying=false,proceed=false,fail=false,readback=false;unsigned calls=0;std::string destination,change_source;
 std::string get(const std::string&)override{
  if(!change_source.empty()){std::ofstream file(change_source,std::ios::app);file<<"changed";}
  return readback?Json{{"result",{{"filename",destination},{"size",12}}}}.dump():"{}";
 }
 std::string post(const std::string&path,const std::string&body)override{
  const auto args=Json::parse(body);const bool dir=path=="/server/files/directory";
  assert(dir||path=="/server/files/copy");
  {std::unique_lock<std::mutex>lock(mutex);++calls;
   if(!dir){copying=true;entered.notify_one();release.wait(lock,[this]{return proceed;});}
  }
  if(!dir)destination=args.at("dest").get<std::string>().substr(7);
  if(!dir&&fail)throw std::runtime_error("lost reply");
  return Json{{"result",{{"action",dir?"create_dir":"create_file"},{"item",{{"root","gcodes"},{"path",args.at(dir?"path":"dest").get<std::string>().substr(7)},{"size",12}}}}}}.dump();
 }
 void wait_for_copy(){std::unique_lock<std::mutex>lock(mutex);assert(entered.wait_for(lock,std::chrono::seconds(3),[this]{return copying;}));}
 void unblock(){std::lock_guard<std::mutex>lock(mutex);proceed=true;release.notify_one();}
};
Json await_result(UsbCopyWorker&worker,unsigned origin){
 const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(3);
 while(std::chrono::steady_clock::now()<until){auto result=worker.result(origin);auto state=result.value("state","");
  if(state=="copied"||state=="refused"||state=="unknown"||state=="ready"||state=="unavailable")return result;
  std::this_thread::yield();
 }
 assert(false);return Json();
}
int main(){
 const Json data={{"fresh",true},{"owner","standalone"},{"session","s"},{"revision","r"},{"job",{{"state","idle"}}}};
 const std::string nonce(32,'a');
 for(bool fail:{false,true}){
  CopyHttp http;http.fail=fail;UsbCopyWorker worker(http);worker.observe(data);
  assert(worker.submit(1,data,"part.gcode",nonce,12));http.wait_for_copy();
  // GUI reads/status publication must complete while copy HTTP is blocked.
  auto gui=std::async(std::launch::async,[&]{worker.observe(data);return worker.result(1);});
  assert(gui.wait_for(std::chrono::seconds(1))==std::future_status::ready);
  assert(gui.get()["state"]=="copying");assert(worker.result(2).empty());
  assert(!worker.submit(1,data,"part.gcode",nonce,12));
  assert(!worker.submit(2,data,"other.gcode",nonce,12));
  http.unblock();assert(await_result(worker,1)["state"]==(fail?"unknown":"copied"));
  assert(!worker.submit(1,data,"part.gcode",nonce,12));
  if(fail){
   // A new explicit preview can copy to a fresh directory. The old request is
   // never retried and one unknown result cannot disable every later import.
   assert(worker.unresolved().empty());
   assert(worker.submit(2,data,"part.gcode",std::string(32,'b'),12));
   assert(await_result(worker,2)["state"]=="unknown");assert(http.calls==4);
  }else assert(http.calls==2);
 }
 {CopyHttp http;http.proceed=true;UsbCopyWorker worker(http);auto changed=data;changed["session"]="new";changed["job"]["state"]="printing";worker.observe(changed);
  assert(worker.submit(1,data,"part.gcode",nonce,12));assert(await_result(worker,1)["state"]=="copied");assert(http.calls==2);
 }
 {CopyHttp http;http.proceed=true;UsbCopyWorker worker(http); // No printer snapshot needed for a file copy.
  assert(worker.submit(1,data,"part.gcode",nonce,12));assert(await_result(worker,1)["state"]=="copied");assert(http.calls==2);
 }
 char directory[]="/tmp/wmp-usb-source-XXXXXX";assert(::mkdtemp(directory));
 const std::string root=directory;
 {std::ofstream file(root+"/part.gcode");file<<"G1 X1\nG1 X2\n";}
 {CopyHttp http;http.proceed=true;UsbCopyWorker worker(http);worker.observe(data);
  assert(worker.inspect(10,root,"part.gcode"));auto source=await_result(worker,10);
  assert(source["size"]==12&&worker.result(11).empty());
  assert(!worker.submit(10,data,"other.gcode",nonce,12));
  assert(!worker.submit(10,data,"part.gcode",nonce,11));
  assert(worker.submit(10,data,"part.gcode",nonce,12));assert(await_result(worker,10)["state"]=="copied");
 }
 // Destination readback is accepted only while the actual inspected USB file
 // still has its original stat identity, including size and modification time.
 for(bool changed:{false,true}){
  CopyHttp http;http.proceed=true;http.fail=true;http.readback=true;
  if(changed)http.change_source=root+"/part.gcode";
  UsbCopyWorker worker(http);assert(worker.inspect(20,root,"part.gcode"));assert(await_result(worker,20)["state"]=="ready");
  assert(worker.submit(20,Json::object(),"part.gcode",nonce,12));
  assert(await_result(worker,20)["state"]==(changed?"unknown":"copied"));
  assert(http.calls==2);
  if(changed){assert(worker.inspect(21,root,"part.gcode"));assert(await_result(worker,21)["state"]=="ready");assert(http.calls==2);}
 }
 {std::ofstream file(root+"/part.gcode");file<<"G1 X1\nG1 X2\n";}
 {CopyHttp http;UsbCopyWorker worker(http);worker.observe(data);
  assert(worker.inspect(11,root,"part.gcode"));assert(await_result(worker,11)["state"]=="ready");
  {std::ofstream file(root+"/part.gcode",std::ios::app);file<<"changed";}
  assert(worker.submit(11,data,"part.gcode",nonce,12));assert(await_result(worker,11)["state"]=="refused");assert(http.calls==0);
 }
 assert(::symlink("part.gcode",(root+"/link.gcode").c_str())==0);
 assert(::mkfifo((root+"/pipe.gcode").c_str(),0600)==0);
 for(const auto*path:{"link.gcode","pipe.gcode","missing.gcode","../outside.gcode"}){
  bool rejected=false;try{inspect_usb_source(root,path);}catch(...){rejected=true;}assert(rejected);
 }
 ::unlink((root+"/part.gcode").c_str());::unlink((root+"/link.gcode").c_str());::unlink((root+"/pipe.gcode").c_str());::rmdir(root.c_str());
}
