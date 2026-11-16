#include "native/recovery_retirement_worker.hpp"
#include <cassert>
using namespace wmp_ui;using namespace wmp_ui::native;
struct Http: wmp_openace::HttpPort {
 std::mutex gate;std::condition_variable ready;bool block=false,entered=false,released=false;
 unsigned reviews=0,commands=0,reads=0;bool unavailable=false,corrupt=false,wrong=false,archive_failed=false;Json request;
 std::string get(const std::string&)override{assert(false);return {};}
 std::string post(const std::string&path,const std::string&body)override{
  auto args=Json::parse(body);
  if(path=="/printer/wmp/recovery/retire_review"){
   {std::unique_lock<std::mutex> lock(gate);entered=true;ready.notify_all();if(block)ready.wait(lock,[this]{return released;});}
   ++reviews;request=args;request["version"]=1;
   Json records=Json::object();
   for(const auto*name:{"job","execution","attempt","envelope","checkpoint_A","checkpoint_B","coordinates_A","coordinates_B","offer"})
    records[name]={{"present",true},{"identity",Json::array({45830,16090,1454,1794501009599255802LL,1794501009606255957LL})},{"sha256",std::string(64,'c')}};
   request["evidence"]={{"manifest",{{"version",1},{"records",records}}},{"receipt",Json::object()},{"fingerprint",std::string(64,'a')}};
   if(wrong)request["session"]="other";
   return Json{{"result",{{"file","part.gcode"},{"request",request}}}}.dump();
  }
  if(path=="/printer/gcode/script"){
   ++commands;assert(args.at("script")==recovery_retirement_script(request,request));
   throw std::runtime_error("lost command response");
  }
  assert(path=="/printer/wmp/recovery/retire_result");++reads;
  if(unavailable)throw std::runtime_error("readback unavailable");
  auto receipt=Json{{"version",2},{"id",args.at("id")},{"session",request.at("session")},{"state","complete"},{"archive",std::string(64,'b')},{"fingerprint",std::string(64,'a')},
   {"offer_after",{{"present",true},{"identity",Json::array({45830,16091,1455,1794501009599255802LL,1794501009606255957LL})},{"sha256",std::string(64,'d')}}}};
  if(archive_failed){receipt["version"]=3;receipt.erase("archive");receipt["manifest"]={{"version",1},{"records",Json::object()}};receipt["retired_manifest"]=receipt["manifest"];receipt["archive_warning"]="Storage is read-only";}
  if(corrupt)receipt["archive"]="bad";
  return Json{{"result",{{"session",args.at("session")},{"result",receipt}}}}.dump();
 }
};
static Json wait(RecoveryRetirementWorker&w){
 const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(3);
 while(w.result().value("delivery_pending",true)&&std::chrono::steady_clock::now()<end)std::this_thread::yield();
 auto result=w.result();assert(!result.value("delivery_pending",true));return result;
}
int main(){
 Json helper={{"session_id","session"},{"afc_metadata",{{"owner","standalone"}}},{"recovery_retirement_protocol",1}};
 Http http;RecoveryRetirementWorker worker(http);
 assert(!worker.review());worker.observe(helper,true);assert(http.reviews==0&&http.commands==0);
 assert(worker.auto_read());auto reviewed=wait(worker);assert(reviewed.at("state")=="reviewed"&&http.commands==0);
 for(int i=0;i<100;++i)assert(!worker.auto_read());
 assert(http.reviews==1&&http.commands==0);
 assert(reviewed.at("file")=="part.gcode");
 assert(reviewed.at("request").at("evidence").at("manifest").at("records").size()==9);
 const auto id=reviewed.at("id").get<std::string>();assert(!worker.confirm("wrong"));
 worker.observe(helper,false);assert(!worker.confirm(id));worker.observe(helper,true);
 assert(worker.confirm(id));assert(wait(worker).at("state")=="complete");
 assert(worker.result().at("receipt").at("version")==2);
 assert(worker.result().at("receipt").at("offer_after").at("sha256")==std::string(64,'d'));
 assert(http.commands==1&&http.reads==1);assert(!worker.confirm(id));
 for(int i=0;i<5;++i)worker.observe(helper,true);
 assert(http.commands==1&&http.reads==1);
 helper["session_id"]="restarted";worker.observe(helper,true);assert(!worker.confirm(id));
 assert(worker.refresh());assert(wait(worker).at("state")=="complete");assert(http.commands==1&&http.reads==2);
 Http lost;lost.unavailable=true;RecoveryRetirementWorker uncertain(lost);uncertain.observe(helper,true);
 assert(uncertain.review());reviewed=wait(uncertain);assert(uncertain.confirm(reviewed.at("id")));
 assert(wait(uncertain).at("state")=="unknown");assert(!uncertain.confirm(reviewed.at("id")));
 lost.unavailable=false;lost.corrupt=true;assert(uncertain.refresh());assert(wait(uncertain).at("state")=="unknown");
 lost.corrupt=false;assert(uncertain.refresh());assert(wait(uncertain).at("state")=="complete");assert(lost.commands==1);
 // A lost acknowledgement does not prohibit another explicit read-only review.
 {Http missing;missing.unavailable=true;RecoveryRetirementWorker retry(missing);retry.observe(helper,true);
  assert(retry.review());auto old=wait(retry);assert(retry.confirm(old.at("id")));assert(wait(retry).at("state")=="unknown");
  assert(retry.review());auto current=wait(retry);assert(current.at("state")=="reviewed"&&current.at("id")!=old.at("id"));
  assert(missing.commands==1); // Review did not replay the destructive confirmation.
 }
 Http changed;changed.wrong=true;RecoveryRetirementWorker refused(changed);refused.observe(helper,true);
 assert(refused.review());assert(wait(refused).at("state")=="refused");assert(changed.commands==0);
 Http stale;RecoveryRetirementWorker old(stale);old.observe(helper,true);assert(old.review());reviewed=wait(old);
 helper["session_id"]="another";old.observe(helper,true);assert(!old.confirm(reviewed.at("id")));assert(stale.commands==0);
 helper["afc_metadata"]["owner"]="openace";old.observe(helper,true);assert(!old.review());
 helper["afc_metadata"]["owner"]="standalone";old.observe(helper,true);assert(old.review());reviewed=wait(old);
 old.cancel_review();assert(!old.confirm(reviewed.at("id"))&&stale.commands==0);
 // Closing an in-flight review must not resurrect its result or error.
 Http delayed;delayed.block=true;RecoveryRetirementWorker cancelled(delayed);
 cancelled.observe(helper,true);assert(cancelled.review());
 {std::unique_lock<std::mutex> lock(delayed.gate);assert(delayed.ready.wait_for(lock,std::chrono::seconds(2),[&]{return delayed.entered;}));}
 cancelled.cancel_review();
 {std::lock_guard<std::mutex> lock(delayed.gate);delayed.released=true;}delayed.ready.notify_all();
 auto cancelled_result=wait(cancelled);assert(!cancelled_result.contains("state"));
 assert(delayed.commands==0);assert(cancelled.review());assert(wait(cancelled).at("state")=="reviewed");
 // A fresh screen process adopts backend-verified history without HTTP work.
 for(int version:{1,2,3}){
 Http restored_http;restored_http.request={{"session","original-session"}};
 RecoveryRetirementWorker restored(restored_http);
 helper["recovery_retirement"]={{"version",version},{"id","saved-discard"},{"session","original-session"},
  {"state","complete"},{"archive",std::string(64,'b')},{"fingerprint",std::string(64,'a')}};
 if(version==3){auto&r=helper["recovery_retirement"];r.erase("archive");r["archive_warning"]="Storage is read-only";r["manifest"]={{"version",1},{"records",Json::object()}};r["retired_manifest"]=r["manifest"];restored_http.archive_failed=true;}
 restored.observe(helper,true);assert(restored.result().value("restored",false));
 if(version==3)assert(restored.result()["message"].get<std::string>().find("not saved: Storage is read-only")!=std::string::npos);
 assert(restored_http.reviews==0&&restored_http.commands==0&&restored_http.reads==0);
 assert(!restored.confirm("saved-discard"));assert(restored.refresh());assert(wait(restored).at("state")=="complete");
 assert(restored_http.commands==0&&restored_http.reads==1);
 }
 {Http archive;archive.archive_failed=true;RecoveryRetirementWorker discard(archive);discard.observe(helper,true);
  assert(discard.review());auto review=wait(discard);assert(discard.confirm(review.at("id")));
  auto result=wait(discard);assert(result["state"]=="complete"&&result["receipt"]["version"]==3);
  assert(result["message"].get<std::string>().find("not saved: Storage is read-only")!=std::string::npos&&archive.commands==1);
 }
 Http future_http;RecoveryRetirementWorker future(future_http);
 helper["recovery_retirement"]["version"]=4;future.observe(helper,true);
 assert(!future.result().value("restored",false));assert(future_http.commands==0);
}
