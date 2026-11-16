#include "native/recovery_worker.hpp"
#include <cassert>
using namespace wmp_ui;using namespace wmp_ui::native;
struct Http: wmp_openace::HttpPort {
 std::mutex mutex;std::condition_variable wake;bool entered=false,released=false;unsigned posts=0,issued=0;bool tickets=false;Json request,selected;
 std::string get(const std::string&)override{assert(false);return {};}
 std::string post(const std::string&path,const std::string&body)override{
  auto args=Json::parse(body);
  if(path=="/printer/wmp/recovery/review"){
   selected=args;request=args;request.erase("ticket_protocol");request["version"]=1;request["owner"]="standalone";
   request["execution_hash"]=std::string(16,'c');request["deposition_sha256"]=std::string(64,'d');
   Json result={{"selected_file",args.at("file")},{"request",request},
    {"execution",{{"file",{{"path",args.at("file")}}},{"job_fingerprint",args.at("job_hash")}}}};
   if(tickets){assert(args.at("ticket_protocol")=="1");request["id"]="wmp2rc_"+std::to_string(++issued);result["request"]=request;
    result["ticket"]={{"protocol",1},{"selection_id",args.at("id")},{"sequence",std::to_string(issued)},{"token",std::string(64,'e')}};}
   return Json{{"result",result}}.dump();
  }
  assert(path=="/printer/gcode/script");assert(args.at("script").get<std::string>().find("WMP_RECOVERY_CONTINUE REQUEST=")==0);
  std::unique_lock<std::mutex>lock(mutex);posts++;entered=true;wake.notify_all();wake.wait(lock,[this]{return released;});
  throw std::runtime_error("lost acknowledgement");
 }
 void wait(){std::unique_lock<std::mutex>lock(mutex);assert(wake.wait_for(lock,std::chrono::seconds(3),[this]{return entered;}));}
 void release(){std::lock_guard<std::mutex>lock(mutex);released=true;wake.notify_all();}
};
struct Stop: wmp_openace::HttpPort{
 std::mutex mutex;std::condition_variable wake;unsigned posts=0;Json last;
 std::string get(const std::string&)override{assert(false);return {};}
 std::string post(const std::string&path,const std::string&body)override{
  assert(path=="/printer/wmp/recovery/stop");auto args=Json::parse(body);
  {std::lock_guard<std::mutex>lock(mutex);posts++;last=args;wake.notify_all();}
  args["state"]="requested";return Json{{"result",args}}.dump();
 }
 void wait(){std::unique_lock<std::mutex>lock(mutex);assert(wake.wait_for(lock,std::chrono::seconds(3),[this]{return posts==1;}));}
};
int main(){
 Http http;Stop control;RecoveryWorker worker(http,control);
 Json helper={{"session_id","session"},{"afc_metadata",{{"owner","standalone"}}},{"recovery_review_protocol",1},{"recovery_continue_protocol",1},{"recovery_stop_protocol",1}};
 auto selected=native_recovery_selection("attempt","session","part.gcode","plr_dataB.ini",std::string(16,'a'),std::string(16,'b'));
 for(bool malformed:{false,true}){
  struct RefusalHttp:wmp_openace::HttpPort{bool malformed;unsigned scripts=0;
   explicit RefusalHttp(bool value):malformed(value){}
   std::string get(const std::string&)override{assert(false);return {};}
   std::string post(const std::string&path,const std::string&)override{
    if(path!="/printer/wmp/recovery/review"){++scripts;assert(false);}
    return malformed?"not-json":"{\"error\":{\"message\":\"Exact checkpoint binding refusal\"}}";
   }
  } wire(malformed);
  RecoveryWorker failed(wire,control);failed.observe(helper,true);assert(failed.select(selected));
  const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(3);
  while(failed.result().value("delivery_pending",true)&&std::chrono::steady_clock::now()<until)std::this_thread::yield();
  const auto result=failed.result();assert(result.at("state")=="refused"&&wire.scripts==0);
  const auto message=result.value("message","");
  assert(message.find(malformed?"parse_error":"Exact checkpoint binding refusal")!=std::string::npos);
 }
 assert(!worker.select(selected));worker.observe(helper,true);assert(worker.select(selected));http.wait();
 assert(!worker.select(selected));assert(!worker.stop()); // no matching backend receipt yet
 Json receipt={{"request",{{"id","attempt"},{"session","session"},{"file","part.gcode"},{"execution_hash",std::string(16,'c')}}},{"state","running"},{"error",""},{"stages",Json::array({{{"name","heating"},{"state","running"}}})}};
 helper["recovery_attempt"]=receipt;worker.observe(helper,true);assert(worker.stop());control.wait();assert(!worker.stop());
 // Status observation and STOP both proceed while command acknowledgement blocks.
 assert(worker.result().at("receipt").at("state")=="running");
 helper["recovery_attempt"]["state"]="stopped";worker.observe(helper,true);http.release();
 const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(3);
 while(worker.result().value("stop","")!="requested"&&std::chrono::steady_clock::now()<until)std::this_thread::yield();
 assert(worker.result().value("state","")=="stopped");assert(worker.result().value("stop","")=="requested");
 helper["session_id"]="new-session";worker.observe(helper,true);assert(!worker.result().value("fresh",true));assert(!worker.stop());
 Http lost;Stop second_control;RecoveryWorker second(lost,second_control);
 helper["session_id"]="session";helper.erase("recovery_attempt");second.observe(helper,true);assert(second.select(selected));lost.wait();
 auto wrong=receipt;wrong["request"]["execution_hash"]=std::string(16,'f');helper["recovery_attempt"]=wrong;
 second.observe(helper,true);assert(!second.stop());assert(!second.result().contains("receipt"));
 lost.release();const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
 while(second.result().value("delivery_pending",true)&&std::chrono::steady_clock::now()<deadline)std::this_thread::yield();
 assert(!second.result().value("delivery_pending",true));assert(second.result().value("state","")=="unknown");
 assert(!second.select(selected));assert(lost.posts==1);
 receipt["state"]="complete";receipt["continuation"]={{"state","scheduled"}};helper["recovery_attempt"]=receipt;
 second.observe(helper,true);assert(second.result().value("state","")=="pending");assert(!second.select(selected));
 helper["recovery_attempt"]["continuation"]["state"]="started";second.observe(helper,true);
 assert(second.result().value("state","")=="printing");assert(!second.stop());
 auto another=selected;another["id"]="another";assert(!second.select(another));
 helper["recovery_attempt"]["continuation"]["state"]="paused";second.observe(helper,true);
 assert(second.result().value("state","")=="paused");assert(!second.select(another));
 helper["recovery_attempt"]["continuation"]["state"]="started";second.observe(helper,true);
 assert(second.result().value("state","")=="printing"); // pause is not terminal
 helper["recovery_attempt"]["continuation"]={{"state","unknown"},{"error","Continuation failed"}};second.observe(helper,true);
 assert(second.result().value("state","")=="unknown"&&second.result().value("message","")=="Continuation failed");
 helper["recovery_attempt"]["continuation"]["state"]="complete";second.observe(helper,true);
 assert(second.result().value("state","")=="complete");assert(!second.select(selected)); // never reuse a consumed request ID
 const auto completed=second.result();
 for(const auto*state:{"pending","running","unknown","stopped"}){
  helper["recovery_attempt"]=receipt;helper["recovery_attempt"]["state"]=state;
  second.observe(helper,true);
  assert(second.result().at("state")=="complete");
  assert(second.result().at("receipt")==completed.at("receipt"));
  assert(!second.stop()&&lost.posts==1);
 }
 Http refused_http;Stop refused_stop;RecoveryWorker refused(refused_http,refused_stop);
 helper.erase("recovery_attempt");refused.observe(helper,true);assert(refused.select(selected));refused_http.wait();
 auto submission=Json{{"request",receipt.at("request")},{"state","refused"},{"message","Clearance changed; no preparation started."}};
 submission["request"]["id"]="different";helper["recovery_submission"]=submission;
 refused.observe(helper,true);assert(refused.result().value("state","")!="refused");
 helper["recovery_submission"]["request"]["id"]="attempt";refused.observe(helper,true);refused_http.release();
 const auto refusal_deadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
 while(refused.result().value("delivery_pending",true)&&std::chrono::steady_clock::now()<refusal_deadline)std::this_thread::yield();
 assert(refused.result().value("state","")=="refused");assert(refused.result().value("message","")==submission.at("message"));
 assert(!refused.stop());assert(refused_http.posts==1);
 Http native_http;Stop native_stop;RecoveryWorker native(native_http,native_stop);
 const std::string chash(16,'a'),jhash(16,'b');
 assert(!native.select_native(1,"part.gcode","plr_dataB.ini",chash,jhash));
 helper.erase("recovery_submission");helper["afc_metadata"]["owner"]="openace";native.observe(helper,true);
 assert(!native.select_native(1,"part.gcode","plr_dataB.ini",chash,jhash));
 helper["afc_metadata"]["owner"]="standalone";native.observe(helper,true);
 assert(!native.select_native(2,"part.gcode","plr_dataB.ini",chash,jhash));
 assert(!native.select_native(1,"part.gcode","plr_dataB.ini","bad",jhash));
 assert(native.select_native(1,"part.gcode","plr_dataB.ini",chash,jhash));native_http.wait();
 const auto native_id=native.result().at("id");
 assert(native.select_native(1,"part.gcode","plr_dataB.ini",chash,jhash));
 assert(native.result().at("id")==native_id&&native_http.posts==1);
 assert(!native.select_native(1,"other.gcode","plr_dataB.ini",chash,jhash));
 native_http.release();
 const auto native_deadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
 while(native.result().value("delivery_pending",true)&&std::chrono::steady_clock::now()<native_deadline)std::this_thread::yield();
 assert(native.result().value("state","")=="unknown");
 assert(native_http.posts==1&&native.result().at("id")==native_id);
 Json resolved_request={{"id",native_id},{"session","session"},{"file","part.gcode"},{"execution_hash",std::string(16,'c')}};
 helper["session_id"]="after-restart";helper["recovery_attempt"]={{"request",resolved_request},{"state","unknown"}};
 native.observe(helper,true);assert(native.result().value("state","")=="unknown");
 helper["recovery_attempt"]["state"]="complete";helper["recovery_attempt"]["continuation"]={{"state","checkpointed"}};
 native.observe(helper,true);assert(native.result().value("state","")=="reconciled");
 auto fresh_selection=native_recovery_selection("new-attempt","after-restart","part.gcode","plr_dataA.ini",chash,jhash);
 assert(native.select(fresh_selection));

 // Lost outcome is retained until a user starts a new attempt, not a permanent lock.
 {
  Http retry_http;retry_http.released=true;Stop stop;RecoveryWorker retry(retry_http,stop);
  auto current=helper;current["session_id"]="session";current.erase("recovery_attempt");retry.observe(current,true);
  assert(retry.select_native(1,"part.gcode","plr_dataB.ini",chash,jhash));retry_http.wait();
  auto until=std::chrono::steady_clock::now()+std::chrono::seconds(3);
  while(retry.result().value("delivery_pending",true)&&std::chrono::steady_clock::now()<until)std::this_thread::yield();
  const auto old=retry.result().at("id");assert(retry.result()["state"]=="unknown");
  assert(retry.select_native(1,"part.gcode","plr_dataB.ini",chash,jhash));
  until=std::chrono::steady_clock::now()+std::chrono::seconds(3);
  while(retry.result().value("delivery_pending",true)&&std::chrono::steady_clock::now()<until)std::this_thread::yield();
  assert(retry.result().at("id")!=old&&retry_http.posts==2);
 }


 // Restart retires a matched live local state only after HTTP has returned.
 for(bool during_http:{false,true})for(const auto*old_state:{"pending","running"}){
  Http transport;Stop stop;RecoveryWorker restarted(transport,stop);
  auto current=helper;current["session_id"]="session";current.erase("recovery_attempt");current.erase("recovery_submission");
  restarted.observe(current,true);assert(restarted.select(selected));transport.wait();
  auto old_receipt=Json{{"request",{{"id","attempt"},{"session","session"},{"file","part.gcode"},{"execution_hash",std::string(16,'c')}}},{"state",old_state}};
  current["recovery_attempt"]=old_receipt;restarted.observe(current,true);
  auto next=native_recovery_selection("after-restart-attempt","after-restart","part.gcode","plr_dataB.ini",chash,jhash);
  auto changed=current;changed["session_id"]="after-restart";changed["recovery_attempt"]["state"]="unknown";
  if(during_http){restarted.observe(changed,true);assert(restarted.result()["state"]==old_state);assert(!restarted.select(next));}
  transport.release();auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
  while(restarted.result().value("delivery_pending",true)&&std::chrono::steady_clock::now()<deadline)std::this_thread::yield();
  if(!during_http)restarted.observe(changed,true);
  assert(restarted.result()["state"]=="unknown"&&restarted.result()["id"]=="attempt");
  assert(transport.posts==1);assert(restarted.select(next));
  deadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
  while(restarted.result().value("delivery_pending",true)&&std::chrono::steady_clock::now()<deadline)std::this_thread::yield();
  old_receipt["state"]="complete";old_receipt["continuation"]={{"state","complete"}};changed["recovery_attempt"]=old_receipt;
  restarted.observe(changed,true);assert(restarted.result()["id"]=="after-restart-attempt"&&restarted.result()["state"]=="unknown");
  assert(transport.posts==2); // New explicit request, never replayed old work.
 }

 struct Denied: wmp_openace::HttpPort {
  std::string get(const std::string&)override{assert(false);return {};}
  std::string post(const std::string&path,const std::string&)override{assert(path=="/printer/wmp/recovery/review");
   return "{\"error\":{\"message\":\"Saved recovery format 3 lacks print accounting\"}}";}
 } denied_http;
 Stop denied_stop;RecoveryWorker denied(denied_http,denied_stop);
 helper["session_id"]="session";helper.erase("recovery_attempt");denied.observe(helper,true);assert(denied.select(selected));
 const auto denied_deadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
 while(denied.result().value("delivery_pending",true)&&std::chrono::steady_clock::now()<denied_deadline)std::this_thread::yield();
 assert(denied.result().value("state","")=="refused");
 assert(denied.result().value("message","")=="Saved recovery format 3 lacks print accounting");
 assert(!denied.stop()&&!denied.select(selected));


 // Modern server IDs bind actual receipts/STOP; repeated terminal selections
 // use bounded server tickets, not a lifetime UI request-ID set.
 {
  Http modern;modern.tickets=true;Stop stop;RecoveryWorker flow(modern,stop);
  auto h=helper;h["session_id"]="modern";h["recovery_ticket_protocol"]=1;h.erase("recovery_attempt");
  auto pick=native_recovery_selection("local-choice","modern","part.gcode","plr_dataB.ini",std::string(16,'a'),std::string(16,'b'));
  flow.observe(h,true);assert(flow.select(pick));modern.wait();
  h["recovery_attempt"]={{"request",{{"id",modern.request.at("id")},{"session","modern"},{"file","part.gcode"},{"execution_hash",std::string(16,'c')}}},{"state","running"}};
  flow.observe(h,true);assert(flow.stop());stop.wait();assert(stop.last.at("id")=="wmp2rc_1");
  h["recovery_attempt"]["state"]="stopped";flow.observe(h,true);modern.release();
  auto done=[&]{const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(3);while(flow.result().value("delivery_pending",true)&&std::chrono::steady_clock::now()<end)std::this_thread::yield();assert(!flow.result().value("delivery_pending",true));};
  done();const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(3);while(flow.result().value("stop","")!="requested"&&std::chrono::steady_clock::now()<end)std::this_thread::yield();
  for(int i=0;i<1100;++i){h.erase("recovery_attempt");flow.observe(h,true);assert(flow.select(pick));done();assert(flow.result().value("state","")=="unknown");}
  assert(modern.posts==1101&&modern.issued==1101); // lost HTTP never auto-retries
 }
}
