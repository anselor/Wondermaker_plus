#include "native/print_cancel_resolution_worker.hpp"
#include <cassert>
using namespace wmp_ui;using namespace wmp_ui::native;
struct Http:wmp_openace::HttpPort{
 std::mutex mutex;std::condition_variable wake;bool entered=false,released=false,lost=false,wrong=false,block_review=false;
 unsigned reviews=0,commands=0;Json request;
 std::string get(const std::string&)override{assert(false);return {};}
 std::string post(const std::string&path,const std::string&body)override{
  std::unique_lock<std::mutex>lock(mutex);
  if(path=="/printer/wmp/print/cancel_resolve_review"){
   ++reviews;if(block_review){entered=true;wake.notify_all();wake.wait(lock,[this]{return released;});}request=Json::parse(body);request["token"]=std::string(32,'a');request["action"]="finish_cleanup";request["job_id"]="";
   if(wrong)request["cancel_id"]="other";
   return Json{{"result",{{"request",request},{"file","part.gcode"},{"message","Finish cancelling original print"}}}}.dump();
  }
  assert(path=="/printer/gcode/script");assert(Json::parse(body).at("script")==print_cancel_resolution_script(
   Json{{"id",request.at("id")},{"session",request.at("session")},{"cancel_id",request.at("cancel_id")}},request));
  ++commands;entered=true;wake.notify_all();wake.wait(lock,[this]{return released;});
  if(lost)throw std::runtime_error("lost reply");
  return "{}";
 }
 void wait(){std::unique_lock<std::mutex>lock(mutex);assert(wake.wait_for(lock,std::chrono::seconds(3),[this]{return entered;}));}
 void release(){std::lock_guard<std::mutex>lock(mutex);released=true;wake.notify_all();}
 Json receipt(const char*state){std::lock_guard<std::mutex>lock(mutex);auto r=request;r["state"]=state;r["message"]="recorded";return r;}
};
void done(PrintCancelResolutionWorker&w){auto end=std::chrono::steady_clock::now()+std::chrono::seconds(3);while(w.result().value("delivery_pending",true)&&std::chrono::steady_clock::now()<end)std::this_thread::yield();assert(!w.result().value("delivery_pending",true));}
int main(){
 const Json base={{"session_id","current"},{"afc_metadata",{{"owner","standalone"}}},{"print_cancel_resolution_protocol",1},
  {"print_cancel",{{"id","cancel"},{"session","original"},{"file","part.gcode"},{"state","unknown"}}}};
 // Visible-result refresh is bounded, single-flight and strictly read-only.
 {
  Http http;http.block_review=true;PrintCancelResolutionWorker w(http);w.observe(base,true);
  assert(w.auto_review());http.wait();for(int i=0;i<100;++i)assert(!w.auto_review());
  http.release();done(w);assert(http.reviews==1&&http.commands==0);
  const auto reviewed=w.result();for(int i=0;i<100;++i){w.observe(base,true);assert(!w.auto_review());}
  assert(w.result().at("id")==reviewed.at("id")&&http.reviews==1&&http.commands==0);
 }
 // A failed automatic read does not become a tight retry loop or a command.
 {
  Http http;http.wrong=true;PrintCancelResolutionWorker w(http);w.observe(base,true);
  assert(w.auto_review());done(w);for(int i=0;i<100;++i)assert(!w.auto_review());
  assert(http.reviews==1&&http.commands==0);
 }
 // Restored holds only become commands after review AND confirmation. Observation
 // remains available during a blocked POST; completion cannot be downgraded.
 for(bool lost:{false,true}){
  Http http;http.lost=lost;PrintCancelResolutionWorker w(http);w.observe(base,true);assert(http.commands==0&&http.reviews==0);
  assert(w.review());done(w);assert(w.result().at("state")=="reviewed"&&http.commands==0);
  auto id=w.result().at("id").get<std::string>();assert(!w.confirm("other"));assert(w.confirm(id));http.wait();assert(!w.confirm(id)&&!w.review());
  auto h=base;h["print_cancel"]["state"]="complete";h["print_cancel_resolution"]=http.receipt("complete");w.observe(h,true);
  assert(w.result().at("state")=="complete");h["print_cancel_resolution"]["state"]="pending";w.observe(h,true);
  http.release();done(w);assert(w.result().at("state")=="complete"&&http.commands==1);
 }
 // A lost reply is not success; explicit read-only review can obtain a new confirmation.
 {
  Http http;http.lost=true;PrintCancelResolutionWorker w(http);w.observe(base,true);assert(w.review());done(w);
  assert(w.confirm(w.result().at("id")));http.wait();http.release();done(w);assert(w.result().at("state")=="unknown");
  auto h=base;h["print_cancel_resolution"]=http.receipt("complete");h["print_cancel_resolution"]["token"]=std::string(32,'b');w.observe(h,true);
  assert(w.result().at("state")=="unknown");assert(w.review());done(w);assert(http.commands==1);
  h["session_id"]="restarted";w.observe(h,true);assert(w.result().value("state","").empty());assert(http.commands==1);
  assert(w.review());done(w);assert(http.commands==1); // new review is still read-only
 }
 // A delayed review reply must not resurrect confirmation after ownership or
 // the retained cancellation changes while the HTTP request is in flight.
 for(const auto*change:{"session","record","owner","fresh","protocol"}){
  Http http;http.block_review=true;PrintCancelResolutionWorker w(http);w.observe(base,true);
  assert(w.review());http.wait();auto h=base;bool fresh=true;std::string c=change;
  if(c=="session")h["session_id"]="new";
  if(c=="record")h["print_cancel"]["id"]="replacement";
  if(c=="owner")h["afc_metadata"]["owner"]="openace";
  if(c=="fresh")fresh=false;
  if(c=="protocol")h["print_cancel_resolution_protocol"]=0;
  w.observe(h,fresh);http.release();done(w);
  assert(w.result().at("state")=="refused");
  assert(!w.confirm(w.result().at("id"))&&http.commands==0&&http.reviews==1);
 }
 for(const auto*change:{"session","record","owner","fresh","protocol"}){
  Http http;PrintCancelResolutionWorker w(http);w.observe(base,true);assert(w.review());done(w);auto id=w.result().at("id").get<std::string>();
  auto h=base;bool fresh=true;std::string c=change;
  if(c=="session")h["session_id"]="new";
  if(c=="record")h["print_cancel"]["message"]="changed";
  if(c=="owner")h["afc_metadata"]["owner"]="openace";
  if(c=="fresh")fresh=false;
  if(c=="protocol")h["print_cancel_resolution_protocol"]=0;
  w.observe(h,fresh);assert(!w.confirm(id)&&http.commands==0);
 }
 {Http http;http.wrong=true;PrintCancelResolutionWorker w(http);w.observe(base,true);assert(w.review());done(w);assert(w.result().at("state")=="refused"&&http.commands==0);}
 Json identity={{"id","resolve"},{"session","session"},{"cancel_id","cancel"}};
 auto request=identity;request["token"]=std::string(32,'a');request["job_id"]="job";
 for(const auto*action:{"finish_cleanup","finish_idle_cleanup","discard_saved_job","acknowledge_complete"}){
  request["action"]=action;assert(print_cancel_resolution_script(identity,request).find("WMP_RESOLVE_PRINT_CANCEL REQUEST=")==0);
 }
 for(const auto*key:{"id","session","cancel_id","token","action","extra"}){
  auto bad=request;bad[key]="bad";bool refused=false;try{print_cancel_resolution_script(identity,bad);}catch(...){refused=true;}assert(refused);
 }
}
