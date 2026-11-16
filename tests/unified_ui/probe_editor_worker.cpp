#include "native/probe_editor_worker.hpp"
#include <cassert>
using namespace wmp_ui;using namespace wmp_ui::native;
struct Http:wmp_openace::HttpPort{
 std::mutex mutex;std::condition_variable wake;bool entered=false,released=false,lost=false,error=false;unsigned calls=0;
 std::string script;
 std::string get(const std::string&)override{assert(false);return {};}
 std::string post(const std::string&path,const std::string&body)override{
  std::unique_lock<std::mutex>lock(mutex);assert(path=="/printer/gcode/script");
  ++calls;script=Json::parse(body).at("script").get<std::string>();entered=true;wake.notify_all();
  wake.wait(lock,[this]{return released;});if(lost)throw std::runtime_error("lost reply");
  return error?"{\"error\":{\"message\":\"failed\"}}":"{\"result\":\"ok\"}";
 }
 void wait(){std::unique_lock<std::mutex>lock(mutex);assert(wake.wait_for(lock,std::chrono::seconds(3),[this]{return entered;}));}
 void release(){std::lock_guard<std::mutex>lock(mutex);released=true;wake.notify_all();}
};
struct StopHttp:Http{
 Json request;
 std::string post(const std::string&path,const std::string&body)override{
  std::unique_lock<std::mutex>lock(mutex);assert(path=="/printer/wmp/probe_editor/stop");
  request=Json::parse(body);++calls;entered=true;wake.notify_all();
  wake.wait(lock,[this]{return released;});if(lost)throw std::runtime_error("lost stop reply");
  return Json{{"result",{{"session",request["session"]},{"request",request["request"]},{"state","requested"}}}}.dump();
 }
};
void stop_done(ProbeEditorWorker&w){auto end=std::chrono::steady_clock::now()+std::chrono::seconds(3);while(w.result()["stop_delivery_pending"].get<bool>()&&std::chrono::steady_clock::now()<end)std::this_thread::yield();assert(w.result()["stop_delivery_pending"]==false);}
void done(ProbeEditorWorker&w){auto end=std::chrono::steady_clock::now()+std::chrono::seconds(3);while(w.result()["delivery_pending"].get<bool>()&&std::chrono::steady_clock::now()<end)std::this_thread::yield();assert(w.result()["delivery_pending"]==false);}
int main(){
 const std::string session(32,'a'),request(32,'b'),token(32,'c');
 const Json base={{"fresh",true},{"owner","standalone"},{"calibration_session",session},{"command_generation",0},
  {"probe_editor",{{"available",true},{"session",session},{"request",""},{"state","idle"},{"sequence",-1},{"binding_valid",true}}}};
 for(bool lost:{false,true}){
  Http command;StopHttp stop;stop.lost=lost;ProbeEditorWorker worker(command,&stop);
  worker.observe(base);assert(worker.begin(request,true));command.wait();
  auto data=base;auto&o=data["probe_editor"];o["request"]=request;o["sequence"]=0;o["state"]="preparing";
  worker.observe(data);assert(!worker.stop()&&worker.result()["actions"]["STOP"]==false);
  o["stop_protocol"]=1;worker.observe(data);assert(worker.result()["actions"]["STOP"]==true);
  assert(worker.stop());stop.wait(); // separate port/thread works while BEGIN is blocked
  assert(stop.request==Json({{"session",session},{"request",request}}));
  assert(!worker.stop()&&stop.calls==1&&worker.result()["pending"]==true);
  if(lost){stop.release();stop_done(worker);assert(worker.result()["pending"]==true);
   assert(worker.result()["stop_message"].get<std::string>().find("unconfirmed")!=std::string::npos);assert(!worker.stop());}
  o["state"]="stopping";o["stop_requested"]=true;worker.observe(data);
  assert(worker.result()["stop_message"]=="Stop requested; waiting for preparation to stop.");
  assert(worker.result()["pending"]==true&&worker.result()["actions"]["STOP"]==false);
  o["state"]="aborted";worker.observe(data);assert(worker.result()["pending"]==false);
  stop.release();stop_done(worker);assert(worker.result()["stop_message"]=="");
  command.release();done(worker);assert(!worker.stop()&&stop.calls==1&&command.calls==1);
 }
 for(bool lost:{false,true}){
  Http http;http.lost=lost;ProbeEditorWorker worker(http);assert(!worker.begin(request,true));
  worker.observe(base);assert(worker.result()["actions"]["START"]==true);assert(http.calls==0);assert(!worker.begin(request,false));assert(worker.begin(request,true));http.wait();
  assert(!worker.begin(request,true)&&!worker.act("JOG","-0.1"));
  assert(worker.result()["actions"]["JOG"]==false);
  auto data=base;auto&op=data["probe_editor"];op["request"]=request;op["token"]=token;op["sequence"]=0;op["state"]="editing";
  worker.observe(data);assert(worker.result()["pending"]==false); // observation isn't blocked by POST
  http.release();done(worker);assert(worker.result()["message"]==""&&http.calls==1);
  assert(worker.result()["actions"]["JOG"]==true);
  assert(worker.result()["actions"]["ACCEPT"]==true);
  assert(worker.result()["actions"]["SAVE"]==false);
  for(int i=0;i<10;++i)assert(worker.result()["pending"]==false);
  assert(http.calls==1); // rendering permissions never submits or advances sequence
  data["fresh"]=false;worker.observe(data);assert(worker.result()["actions"]["JOG"]==false);
 }
 // Review permissions never send commands; a tap must carry the displayed token.
 {
  Http http;ProbeEditorWorker worker(http);worker.observe(base);
  assert(worker.begin(request,true));http.wait();http.release();done(worker);
  auto data=base;auto&o=data["probe_editor"];
  o["request"]=request;o["token"]=token;o["sequence"]=0;o["state"]="editing";
  worker.observe(data);assert(worker.act("ACCEPT"));done(worker);
  o["state"]="accepted";o["sequence"]=1;
  const std::string review(64,'d');o["config_conflict"]={{"accepted_offset","1.5"},{"current_offset","2.0"},{"review",review}};
  worker.observe(data);
  for(int i=0;i<10;++i){assert(worker.result()["actions"]["KEEP"]==true);assert(worker.result()["actions"]["SAVE"]==false);}
  assert(http.calls==2);
  o["config_conflict"]["review"]=std::string(64,'e');worker.observe(data);
  assert(!worker.act("KEEP",review)&&http.calls==2);
  assert(worker.act("KEEP",std::string(64,'e')));done(worker);
  assert(http.script.find(" REVIEW="+std::string(64,'e'))!=std::string::npos);
  assert(worker.result()["pending"]==true); // HTTP success alone is not a receipt
  assert(!worker.act("KEEP",std::string(64,'e'))&&http.calls==3);
  o["state"]="kept";o["sequence"]=2;o.erase("config_conflict");worker.observe(data);
  assert(worker.result()["pending"]==false&&http.calls==3);
 }
 // Visible saved-result reads are automatic but bounded and never acknowledge,
 // retain, save, or replace a pending physical command.
 {
  Http http;ProbeEditorWorker worker(http);auto d=base;auto&o=d["probe_editor"];
  o["state"]="save_review";o["request"]=request;o["sequence"]=0;o["save_review_protocol"]=2;
  o["save_review_sequence"]=0;o["save_review_required"]=true;o["save_review_confirmable"]=false;
  o["save_review"]={{"token",std::string(64,'d')},{"configuration_matches",true},{"offset","1.5"}};
  worker.observe(d);assert(http.calls==0);assert(worker.auto_review());http.wait();
  for(int i=0;i<100;++i)assert(!worker.auto_review());
  assert(http.calls==1&&http.script.find("ACTION=REVIEW")!=std::string::npos);
  http.release();done(worker);assert(!worker.auto_review());
  o["save_review_sequence"]=1;o["save_review_confirmable"]=true;
  o["save_review_result"]={{"session",session},{"request",request},{"sequence",1},{"action","REVIEW"},{"state","complete"}};
  worker.observe(d);
  for(int i=0;i<100;++i){worker.observe(d);assert(!worker.auto_review());}
  assert(http.calls==1&&worker.result()["pending"]==false);
  // Changed evidence gets another read after the bounded interval, never an ACK.
  o["save_review"]["offset"]="1.6";worker.observe(d);assert(!worker.auto_review());
  std::this_thread::sleep_for(std::chrono::milliseconds(5050));worker.observe(d);
  assert(worker.auto_review());done(worker);
  assert(http.calls==2&&http.script.find("ACTION=REVIEW")!=std::string::npos);
 }
 {
  Http http;ProbeEditorWorker worker(http);worker.observe(base);assert(worker.begin(request,true));http.wait();http.release();done(worker);
  auto d=base;auto&o=d["probe_editor"];o["state"]="save_review";o["request"]=request;o["sequence"]=0;
  o["save_review_protocol"]=2;o["save_review_sequence"]=0;o["save_review_required"]=true;
  worker.observe(d);assert(worker.result()["pending"]==true);
  assert(!worker.auto_review()&&http.calls==1); // pending BEGIN cannot become REVIEW
 }
 // Save review uses background transport and authoritative receipts, never HTTP success.
 for(bool retain:{false,true}){
  const std::string resolution=retain?"RETAIN":"ACK";
  Http http;ProbeEditorWorker worker(http);auto d=base;auto&o=d["probe_editor"];
  const std::string review(64,'d');o["state"]="save_review";o["request"]=request;o["sequence"]=0;
  o["save_review_protocol"]=2;o["save_retain_protocol"]=1;o["save_review_sequence"]=0;o["save_review_required"]=true;
  o["save_review_confirmable"]=false;o["save_review"]={{"token",review},{"configuration_matches",!retain},{"retainable",retain}};
  worker.observe(d);assert(worker.result()["actions"]["REVIEW"]==true&&http.calls==0);
  assert(worker.result()["actions"][resolution]==false);assert(worker.act("REVIEW"));http.wait();
  assert(!worker.act("REVIEW"));worker.observe(d);assert(worker.result()["pending"]==true);
  http.release();done(worker);assert(worker.result()["pending"]==true);
  o["save_review_sequence"]=1;o["save_review_confirmable"]=true;
  o["save_review_result"]={{"session",session},{"request",request},{"sequence",1},{"action","REVIEW"},{"state","complete"},{"error",""}};
  worker.observe(d);assert(worker.result()["pending"]==false&&worker.result()["actions"][resolution]==true);
  assert(!worker.act(resolution,std::string(64,'e'))&&http.calls==1);
  assert(worker.act(resolution,review));done(worker);assert(http.calls==2&&worker.result()["pending"]==true);
  assert(!worker.act(resolution,review)&&http.calls==2);
  o["save_review_sequence"]=2;o["save_review_result"]["sequence"]=2;o["save_review_result"]["action"]=resolution;
  o["state"]="save_acknowledged";o["save_review_required"]=false;
  worker.observe(d);assert(worker.result()["pending"]==false&&worker.result()["actions"]["START"]==true);
  assert(http.calls==2);
 }
 for(bool error:{false,true}){
  Http http;http.error=error;ProbeEditorWorker worker(http);worker.observe(base);assert(worker.begin(request,true));http.wait();http.release();done(worker);
  assert(worker.result()["pending"]==true); // HTTP OK/error cannot prove completion
  assert(!worker.begin(request,true)&&!worker.act("JOG","-0.1")&&http.calls==1);
  auto stale=base;stale["calibration_session"]=std::string(32,'d');worker.observe(stale);
  assert(worker.result()["invalidated"]==true);assert(!worker.act("ABORT"));
 }
 {Http http;ProbeEditorWorker worker(http);auto stale=base;stale["fresh"]=false;worker.observe(stale);assert(!worker.begin(request,true));assert(http.calls==0);}
 {Http http;ProbeEditorWorker worker(http);auto other=base;other["owner"]="openace";worker.observe(other);assert(!worker.begin(request,true));assert(http.calls==0);}
}
