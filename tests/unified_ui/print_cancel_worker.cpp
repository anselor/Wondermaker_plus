#include "native/print_cancel_worker.hpp"
#include "native/stock_cancel_route.hpp"
#include <cassert>
using namespace wmp_ui;using namespace wmp_ui::native;
struct Http:wmp_openace::HttpPort{
 std::mutex mutex;std::condition_variable wake;bool review_block=false,review_entered=false,cancel_entered=false,released=false,lost=false,wrong=false;
 unsigned reviews=0,cancels=0,intents=0,clears=0;Json selected;
 std::string get(const std::string&)override{assert(false);return {};}
 std::string post(const std::string&path,const std::string&body)override{
  std::unique_lock<std::mutex>lock(mutex);auto request=Json::parse(body);
  if(path=="/printer/wmp/print/clear_cancelled"){
   ++clears;assert(request==Json({{"session",selected.at("session")},{"id",selected.at("id")}}));
   return Json{{"result",{{"state","complete"},{"id",request.at("id")}}}}.dump();
  }
  if(path=="/printer/gcode/script"){assert(request.at("script")=="CANCEL_PRINT");++intents;wake.notify_all();if(lost)throw std::runtime_error("lost intent response");return "{\"result\":\"ok\"}";}
  if(path=="/printer/wmp/print/cancel_review"){
   ++reviews;selected=request;review_entered=true;wake.notify_all();
   if(review_block)wake.wait(lock,[this]{return released;});
   request["token"]=std::string(32,'a');if(wrong)request["file"]="another.gcode";
   return Json{{"result",{{"request",request}}}}.dump();
  }
  assert(path=="/printer/wmp/print/cancel");++cancels;cancel_entered=true;wake.notify_all();
  wake.wait(lock,[this]{return released;});if(lost)throw std::runtime_error("lost reply");
  auto receipt=selected;receipt["state"]="pending";receipt["phase"]="stopping";
  return Json{{"result",receipt}}.dump();
 }
 void wait(bool review=false){std::unique_lock<std::mutex>lock(mutex);assert(wake.wait_for(lock,std::chrono::seconds(3),[this,review]{return review?review_entered:cancel_entered;}));}
 void release(){std::lock_guard<std::mutex>lock(mutex);released=true;wake.notify_all();}
 Json receipt(const char*state){std::lock_guard<std::mutex>lock(mutex);auto r=selected;r["state"]=state;return r;}
};
void done(PrintCancelWorker&w){auto end=std::chrono::steady_clock::now()+std::chrono::seconds(3);while(w.result().value("delivery_pending",true)&&std::chrono::steady_clock::now()<end)std::this_thread::yield();assert(!w.result().value("delivery_pending",true));}
int main(){
 unsigned routed=0;auto consume=[&]{++routed;return true;};
 for(const auto*command:{" CANCEL_PRINT\n","cancel_print","N123 CANCEL_PRINT","N123cancel_print", "CANCEL_PRINT ; stop",
     "CANCEL_PRINT OTHER=1","M400\nCANCEL_PRINT\nG28", "CANCEL_PRINT\nCANCEL_PRINT","; ignore\ncancel_print\r\n"}){
  auto before=routed;assert(route_stock_cancel(command,consume)&&routed==before+1);
  assert(!route_stock_cancel(command,[]{return false;})); // confirmed other owner retains the whole batch
 }
 const auto before=routed;
 for(const auto*command:{"M25","WMP_RECOVER_FILAMENT","","; CANCEL_PRINT","RESPOND MSG=\"CANCEL_PRINT\"",
     "CANCEL_PRINT1","MY_CANCEL_PRINT","SET_GCODE_VARIABLE MACRO=CANCEL_PRINT VARIABLE=x VALUE=1","G28 ; CANCEL_PRINT"})
  assert(!route_stock_cancel(command,consume));
 assert(routed==before);

 const Json base={{"session_id","session"},{"command_generation",0},{"afc_metadata",{{"owner","standalone"}}},{"print_cancel_protocol",1}};
 const Json stats={{"filename","folder/part.gcode"},{"state","paused"}};
 // Admission reports the exact guard without sending a request or logging on polling.
 {
  Http wire;PrintCancelWorker w(wire);assert(!w.select());assert(w.refusal().find("not fresh")!=std::string::npos);
  auto h=base;h["afc_metadata"]["owner"]="afc";w.observe(h,stats,true);assert(!w.select());assert(w.refusal().find("owner=afc")!=std::string::npos);
  h=base;h["print_cancel_protocol"]=0;w.observe(h,stats,true);assert(!w.select());assert(w.refusal().find("print_cancel_protocol=0")!=std::string::npos);
  auto idle=stats;idle["state"]="standby";w.observe(base,idle,true);assert(!w.select());assert(w.refusal().find("current=standby")!=std::string::npos);
  auto held=base;held["print_cancel"]={{"state","pending"}};w.observe(held,stats,true);assert(!w.select());assert(w.refusal().find("state=pending")!=std::string::npos);
  const auto why=w.refusal();for(int i=0;i<50;++i)w.result();assert(w.refusal()==why);
 }
 // Pending file processing has its own exact start identity; an old idle
 // filename is never used as cancellation authority for this new submission.
 {
  Http http;PrintCancelWorker worker(http);
  auto h=base;h["print_start_cancel_protocol"]=1;
  h["print_submission"]={{"id","print_8"},{"session","session"},{"file","new.gcode"},{"state","pending"}};
  Json idle={{"state","complete"},{"filename","previous.gcode"}};
  worker.observe(h,idle,true);assert(worker.select());http.wait();
  assert(http.selected.at("start")=="print_8"&&http.selected.at("file")=="new.gcode");
  h["command_generation"]=1;h["print_submission"]["state"]="not_started";h["print_cancel"]=http.receipt("complete");
  worker.observe(h,idle,true);http.release();done(worker);
  assert(worker.result().at("state")=="complete"&&http.cancels==1);
 }
 for(const auto*change:{"start","generation","file","opened","owner"}){
  Http http;http.review_block=true;PrintCancelWorker worker(http);
  auto h=base;h["print_start_cancel_protocol"]=1;
  h["print_submission"]={{"id","print_8"},{"session","session"},{"file","new.gcode"},{"state","pending"}};
  Json idle={{"state","complete"},{"filename","previous.gcode"}};
  worker.observe(h,idle,true);assert(worker.select());http.wait(true);
  const std::string field=change;
  if(field=="start")h["print_submission"]["id"]="print_9";
  if(field=="generation")h["command_generation"]=1;
  if(field=="file")h["print_submission"]["file"]="other.gcode";
  if(field=="opened"){idle["state"]="printing";idle["filename"]="new.gcode";}
  if(field=="owner")h["afc_metadata"]["owner"]="openace";
  worker.observe(h,idle,true);http.release();done(worker);assert(http.cancels==0);
 }
 // A blocked cancellation reply cannot block observation or duplicate-click handling.
 for(bool lost:{false,true}){
  Http http;http.lost=lost;PrintCancelWorker worker(http);assert(!worker.select());worker.observe(base,stats,true);assert(worker.select());http.wait();
  auto id=worker.result().at("id");assert(worker.select());assert(worker.result().at("id")==id);
  auto h=base;h["command_generation"]=1;h["print_cancel"]=http.receipt("complete");worker.observe(h,stats,true);
  assert(worker.result().at("state")=="complete");http.release();done(worker);
  assert(worker.result().at("state")=="complete");assert(http.cancels==1);
 }
 {
  Http wire;PrintCancelWorker worker(wire);worker.observe(base,stats,true);assert(worker.select());wire.wait();
  auto h=base;h["print_cancel"]=wire.receipt("complete");h["print_cancel"]["clearable"]=true;
  auto cancelled=stats;cancelled["state"]="cancelled";
  worker.observe(h,cancelled,true);wire.release();done(worker);
  assert(worker.result().at("clearable")==true);
  auto changed=h;changed["session_id"]="new-session";worker.observe(changed,cancelled,true);
  assert(!worker.request_clear());
  changed=h;changed["afc_metadata"]["owner"]="openace";changed["openace_print_control"]["protocol"]=1;
  worker.observe(changed,cancelled,true);
  assert(!worker.request_clear());
  h["print_submission"]["state"]="pending";worker.observe(h,cancelled,true);
  assert(!worker.request_clear());
  h.erase("print_submission");worker.observe(h,cancelled,true);
  assert(worker.request_clear()&&!worker.request_clear());done(worker);
  assert(worker.result().at("clear_complete")==true&&worker.result().at("clear_pending")==false&&wire.clears==1);
 }
 // Lost acknowledgement is not replayed; an unrelated status receipt cannot release it.
 {
  Http http;http.lost=true;PrintCancelWorker worker(http);worker.observe(base,stats,true);assert(worker.select());http.wait();http.release();done(worker);
  assert(worker.result().at("state")=="unknown");auto h=base;h["print_cancel"]=http.receipt("complete");h["print_cancel"]["id"]="other";
  worker.observe(h,stats,true);assert(worker.result().at("state")=="unknown");assert(http.cancels==1);
  auto old=worker.result().at("id");assert(worker.select());done(worker);
  assert(worker.result().at("id")!=old&&http.cancels==2);
 }
 // Review is read-only. Changed state before confirmation prevents intent submission.
 for(const auto*change:{"session","generation","file","owner","fresh"}){
  Http http;http.review_block=true;PrintCancelWorker worker(http);worker.observe(base,stats,true);assert(worker.select());http.wait(true);
  auto h=base,s=stats;bool fresh=true;std::string c=change;
  if(c=="session")h["session_id"]="new-session";
  if(c=="generation")h["command_generation"]=1;
  if(c=="file")s["filename"]="new.gcode";
  if(c=="owner")h["afc_metadata"]["owner"]="openace";
  if(c=="fresh")fresh=false;
  worker.observe(h,s,fresh);http.release();done(worker);assert(http.cancels==0);assert(worker.result().at("state")=="refused");
 }
 {
  Http http;http.wrong=true;PrintCancelWorker worker(http);worker.observe(base,stats,true);assert(worker.select());done(worker);
  assert(http.cancels==0&&worker.result().at("state")=="refused");
 }
 for(const auto*change:{"protocol","owner","idle","hold"}){
  Http http;PrintCancelWorker worker(http);auto h=base,s=stats;std::string c=change;
  if(c=="protocol")h["print_cancel_protocol"]=0;
  if(c=="owner")h["afc_metadata"]["owner"]="openace";
  if(c=="idle")s["state"]="standby";
  if(c=="hold")h["print_cancel"]={{"state","pending"}};
  worker.observe(h,s,true);assert(!worker.select());assert(http.reviews==0);
 }
 // Explicit standalone Stop uses package intent when status/review is unusable.
 for(bool lost:{false,true}){
  Http wire;wire.lost=lost;PrintCancelWorker w(wire,true);w.observe(base,stats,true);w.observe(Json::object(),Json::object(),false);
  assert(w.request());done(w);assert(wire.intents==1&&wire.reviews==0&&wire.cancels==0);
  assert(w.result()["state"]=="unknown");for(int i=0;i<20;++i)w.observe(base,stats,true);assert(wire.intents==1);
 }
 for(const auto*owner:{"openace","afc"}){Http wire;PrintCancelWorker w(wire,true);auto h=base;h["afc_metadata"]["owner"]=owner;w.observe(h,stats,true);assert(!w.request());assert(wire.intents==0);}
 {Http wire;wire.review_block=true;PrintCancelWorker w(wire,true);w.observe(base,stats,true);assert(w.request());wire.wait(true);
  w.observe(Json::object(),Json::object(),false);wire.release();done(w);assert(wire.intents==1&&wire.cancels==0);}

}
