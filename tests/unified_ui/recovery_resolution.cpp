#include "native/recovery_resolution_worker.hpp"
#include <cassert>
using namespace wmp_ui;using namespace wmp_ui::native;
struct Http: wmp_openace::HttpPort {
 std::mutex mutex;std::condition_variable wake;unsigned reviews=0,commands=0;bool release=false,tickets=false;Json request;
 std::string sent_script;
 std::string get(const std::string&)override{assert(false);return {};}
 std::string post(const std::string&path,const std::string&body)override{
  auto data=Json::parse(body);
  if(path=="/printer/wmp/recovery/resolve_review"){
   std::lock_guard<std::mutex>lock(mutex);++reviews;request=data;request.erase("ticket_protocol");request["version"]=1;
   request["journal_sha256"]=std::string(64,'a');request["execution_hash"]=std::string(16,'b');
   Json result={{"request",request}};
   if(tickets){assert(data.at("ticket_protocol")=="1");request["id"]="wmp2rr_"+std::to_string(reviews);result["request"]=request;
    result["ticket"]={{"protocol",1},{"selection_id",data.at("id")},{"sequence",std::to_string(reviews)},{"token",std::string(64,'d')}};}
   return Json{{"result",result}}.dump();
  }
  assert(path=="/printer/gcode/script");assert(data.at("script").get<std::string>().find("WMP_RECOVERY_RESOLVE REQUEST=")==0);
  std::unique_lock<std::mutex>lock(mutex);sent_script=data.at("script");++commands;wake.notify_all();wake.wait(lock,[this]{return release;});
  throw std::runtime_error("lost acknowledgement");
 }
 void wait_command(){std::unique_lock<std::mutex>lock(mutex);assert(wake.wait_for(lock,std::chrono::seconds(3),[this]{return commands==1;}));}
 void finish(){std::lock_guard<std::mutex>lock(mutex);release=true;wake.notify_all();}
};
static Json wait(RecoveryResolutionWorker&w){
 const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(3);
 while(w.result().value("delivery_pending",true)&&std::chrono::steady_clock::now()<until)std::this_thread::yield();
 auto r=w.result();assert(!r.value("delivery_pending",true));return r;
}
int main(){
 Http http;RecoveryResolutionWorker worker(http);
 Json helper={{"session_id","now"},{"afc_metadata",{{"owner","standalone"}}},{"recovery_resolution_protocol",1},
  {"recovery_attempt",{{"request",{{"id","attempt"},{"session","before"},{"file","part.gcode"},{"execution_hash",std::string(16,'c')}}},
   {"state","unknown"},{"continuation",{{"state","interrupted"}}}}}};
 assert(!worker.review("abandon"));worker.observe(helper,true);assert(!worker.review("continue"));assert(worker.review("reconcile"));
 auto reviewed=wait(worker);assert(reviewed.at("state")=="reviewed");assert(http.reviews==1&&http.commands==0);
 assert(!worker.confirm("wrong"));worker.observe(helper,false);assert(!worker.confirm(reviewed.at("id")));
 worker.observe(helper,true);assert(worker.confirm(reviewed.at("id")));http.wait_command();
 assert(!worker.confirm(reviewed.at("id"))&&!worker.review("abandon"));
 auto receipt=Json{{"request",http.request},{"state","complete"},{"message","Checkpoint reconciled"}};
 helper["recovery_resolution"]=receipt;helper["recovery_resolution"]["request"]["id"]="unrelated";worker.observe(helper,true);
 assert(worker.result().at("state")=="pending");helper["recovery_resolution"]=receipt;worker.observe(helper,true);http.finish();
 assert(wait(worker).at("state")=="complete");assert(http.commands==1);
 // A delayed status snapshot cannot turn a recorded terminal result back into
 // pending, or replace it with another terminal outcome for the same request.
 for(const auto*state:{"pending","unknown","refused"}){
  helper["recovery_resolution"]["state"]=state;worker.observe(helper,true);
  assert(worker.result().at("state")=="complete");
  assert(worker.result().at("message")=="Checkpoint reconciled");
 }
 assert(http.commands==1);
 Http lost;RecoveryResolutionWorker uncertain(lost);helper.erase("recovery_resolution");uncertain.observe(helper,true);
 assert(uncertain.review("abandon"));reviewed=wait(uncertain);assert(lost.commands==0);
 assert(reviewed.at("message").get<std::string>().find("will no longer be resumable")!=std::string::npos);
 assert(uncertain.confirm(reviewed.at("id")));lost.wait_command();lost.finish();assert(wait(uncertain).at("state")=="unknown");
 assert(!uncertain.confirm(reviewed.at("id")));assert(lost.commands==1);
 // A recorded partial failure permits a NEW explicit review, not resend.
 assert(!uncertain.result().value("recorded",false));assert(uncertain.review("abandon"));
 const auto again=wait(uncertain);assert(again.at("id")!=reviewed.at("id")&&lost.commands==1&&lost.reviews==2);
 helper.erase("recovery_resolution");
 struct Refused: wmp_openace::HttpPort {
  std::string get(const std::string&)override{assert(false);return {};}
  std::string post(const std::string&path,const std::string&)override{assert(path=="/printer/wmp/recovery/resolve_review");return "{\"error\":{\"message\":\"Turn off heaters before abandoning recovery\"}}";}
 } refused_http;
 RecoveryResolutionWorker refused(refused_http);refused.observe(helper,true);assert(refused.review("abandon"));
 auto denial=wait(refused);assert(denial.at("state")=="refused"&&denial.at("message")=="Turn off heaters before abandoning recovery");
 assert(!refused.confirm(denial.at("id")));
 // Binding drift between read-only review and confirmation never sends a command.
 Http drift;RecoveryResolutionWorker changed(drift);changed.observe(helper,true);assert(changed.review("abandon"));reviewed=wait(changed);
 helper["recovery_attempt"]["request"]["id"]="another";changed.observe(helper,true);assert(!changed.confirm(reviewed.at("id"))&&drift.commands==0);
 auto request=reviewed.at("request");auto identity=request;
 for(const auto*key:{"version","journal_sha256","execution_hash"})identity.erase(key);
 for(const auto*key:{"id","attempt_id","session","action","journal_sha256","execution_hash"}){
  auto bad=request;bad[key]="bad";bool failed=false;try{recovery_resolution_script(identity,bad);}catch(...){failed=true;}assert(failed);
 }
 // Visible-page prefetch obtains both read-only alternatives without choosing
 // either mutation, and confirmation remains bound to the selected action ID.
 helper["recovery_attempt"]["request"]["id"]="automatic";
 Http automatic;RecoveryResolutionWorker choices(automatic);choices.observe(helper,true);
 assert(choices.auto_read());wait(choices);assert(choices.auto_read());
 auto options=wait(choices).at("choices");
 assert(options.at("reconcile").at("state")=="reviewed"&&options.at("abandon").at("state")=="reviewed");
 assert(options.at("reconcile").at("message").get<std::string>().find("does not move the printer or resume printing")!=std::string::npos);
 assert(!choices.auto_read()&&automatic.reviews==2&&automatic.commands==0);
 // The most recent fetch was abandon; selecting reconcile must submit its own
 // cached ticket, never whichever read happened to finish last.
 assert(choices.confirm(options.at("reconcile").at("id")));automatic.wait_command();
 assert(!choices.auto_read()&&!choices.confirm(options.at("abandon").at("id")));
 const auto expected=options.at("reconcile").at("request");auto selected_identity=expected;
 for(const auto*key:{"version","journal_sha256","execution_hash"})selected_identity.erase(key);
 assert(automatic.sent_script==recovery_resolution_script(selected_identity,expected));
 automatic.finish();assert(wait(choices).at("state")=="unknown");assert(!choices.auto_read()&&automatic.commands==1);
 // Refused reads retry at most once/action/five seconds, not once per UI frame.
 auto now=std::chrono::steady_clock::now();
 RecoveryResolutionWorker retry(refused_http,[&]{return now;});retry.observe(helper,true);
 assert(retry.auto_read());wait(retry);assert(retry.auto_read());wait(retry);
 for(int frame=0;frame<100;++frame)assert(!retry.auto_read());
 now+=std::chrono::seconds(5);assert(retry.auto_read());wait(retry);
 // A completed cached choice cannot confirm changed evidence, even when its
 // request ID has not changed. Fresh observation can trigger new read tickets.
 Http changing;RecoveryResolutionWorker refreshed(changing);refreshed.observe(helper,true);
 assert(refreshed.auto_read());auto old_choice=wait(refreshed).at("choices").at("reconcile");
 helper["recovery_attempt"]["error"]="new evidence";refreshed.observe(helper,true);
 assert(!refreshed.confirm(old_choice.at("id"))&&changing.commands==0);
 assert(refreshed.auto_read());auto new_choice=wait(refreshed).at("choices").at("reconcile");
 assert(new_choice.at("id")!=old_choice.at("id")&&changing.commands==0);
 // No discovery reads for a live job, stale status, or a non-standalone owner.
 refreshed.observe(helper,false);assert(!refreshed.auto_read());
 helper["afc_metadata"]["owner"]="openace";refreshed.observe(helper,true);assert(!refreshed.auto_read());
 helper["afc_metadata"]["owner"]="standalone";helper["recovery_attempt"]["state"]="running";
 refreshed.observe(helper,true);assert(!refreshed.auto_read());


 {
  Http modern;modern.tickets=true;RecoveryResolutionWorker flow(modern);
  auto h=helper;h["recovery_ticket_protocol"]=1;h.erase("recovery_resolution");
  h["recovery_attempt"]["state"]="unknown";h["recovery_attempt"]["continuation"]["state"]="interrupted";
  flow.observe(h,true);assert(flow.review("abandon"));auto reviewed=wait(flow);
  assert(reviewed["state"]=="reviewed"&&modern.commands==0&&reviewed["id"]!=reviewed["request"]["id"]);
  assert(flow.confirm(reviewed.at("id")));modern.wait_command();assert(modern.sent_script.find(" TICKET="+std::string(64,'d'))!=std::string::npos);
  h["recovery_resolution"]={{"request",modern.request},{"state","complete"},{"message","Done"}};
  flow.observe(h,true);modern.finish();assert(wait(flow)["state"]=="complete"&&modern.commands==1);
 }
}
