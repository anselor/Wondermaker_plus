#include "native/probe_editor_flow.hpp"
#include <cassert>
using namespace wmp_ui;
using native::ProbeEditorFlow;
int main(){
 const std::string session(32,'a'),request(32,'b'),token(32,'c');
 Json data={{"fresh",true},{"owner","standalone"},{"calibration_session",session},
  {"probe_editor",{{"available",true},{"session",session},{"request",""},{"state","idle"},{"sequence",-1},{"binding_valid",true}}}};
 auto held=data;held["probe_editor"]["save_review_required"]=true;
 ProbeEditorFlow held_flow;assert(!held_flow.begin(held,request,true).empty());
 ProbeEditorFlow flow;
 assert(flow.begin(data,request,false).empty());assert(flow.message().find("not admitted")!=std::string::npos);
 auto stale=data;stale["fresh"]=false;assert(flow.begin(stale,request,true).empty());assert(flow.message().find("fresh")!=std::string::npos);
 auto foreign=data;foreign["owner"]="afc";assert(flow.begin(foreign,request,true).empty());assert(flow.message().find("current=afc")!=std::string::npos);
 auto bad=data;bad["calibration_session"]="bad\nG28";
 assert(flow.begin(bad,request,true).empty());assert(flow.message().find("malformed")!=std::string::npos);assert(flow.message().find("G28")==std::string::npos);
 auto begin=flow.begin(data,request,true);
 assert(begin=="_WMP_PROBE_EDITOR SESSION="+session+" REQUEST="+request+" SEQ=0 ACTION=BEGIN");
 assert(flow.begin(data,request,true).empty()&&flow.pending());
 // Known not-sent BEGIN retires only the attempted local request. An unknown
 // delivery in the same session must still wait for backend evidence.
 {
  ProbeEditorFlow f;assert(!f.begin(data,request,true).empty());
  f.delivery_refused();assert(!f.pending());
  assert(!f.begin(data,std::string(32,'d'),true).empty());
  f.delivery_unknown();assert(!f.begin(data,std::string(32,'e'),true).empty());
 }
 // A backend restart with a clean idle editor permits a new explicit START;
 // observing it cannot replay the previous action or skip a saved-result hold.
 for(const auto*blocked:{"none","stale","owner","review","request","sequence","binding","active"}){
  ProbeEditorFlow f;assert(!f.begin(data,request,true).empty());f.delivery_unknown();
  auto restarted=data;const std::string next_session(32,'e');
  restarted["calibration_session"]=next_session;auto&o=restarted["probe_editor"];o["session"]=next_session;
  const std::string change=blocked;
  if(change=="stale")restarted["fresh"]=false;
  if(change=="owner")restarted["owner"]="openace";
  if(change=="review")o["save_review_required"]=true;
  if(change=="request")o["request"]=request;
  if(change=="sequence")o["sequence"]=0;
  if(change=="binding")o["binding_valid"]=false;
  if(change=="active")o["state"]="preparing";
  f.observe(restarted);assert(f.pending());
  const auto command=f.begin(restarted,std::string(32,'f'),true);
  assert(command.empty()==(change=="stale"||change=="owner"||change=="active"));
  if(!command.empty())assert(command.find("SESSION="+next_session)!=std::string::npos&&command.find("SEQ=0 ACTION=BEGIN")!=std::string::npos);
 }
 flow.delivery_unknown();flow.observe(data);assert(flow.pending());
 assert(flow.message().find("unknown")!=std::string::npos);
 auto&op=data["probe_editor"];op["request"]=request;op["token"]=token;op["sequence"]=0;op["state"]="preparing";
 auto stale_preparing=data;stale_preparing["fresh"]=false;flow.observe(stale_preparing);
 assert(flow.message().find("unknown")!=std::string::npos);
 flow.observe(data);assert(flow.pending()&&flow.message().empty());
 flow.delivery_unknown();assert(flow.pending()&&flow.message().empty());
 op["state"]="editing";flow.observe(data);assert(!flow.pending());
 flow.delivery_unknown();assert(flow.message().empty()); // late failure cannot downgrade receipt
 assert(flow.act(data,"JOG","-0.1").find("SEQ=1 ACTION=JOG TOKEN="+token+" Z=-0.1")!=std::string::npos);
 assert(flow.act(data,"JOG","-0.1").empty());
 flow.delivery_unknown();assert(flow.message().find("unknown")!=std::string::npos);
 flow.observe(data);assert(flow.pending()); // old status cannot acknowledge the new jog
 assert(flow.message().find("unknown")!=std::string::npos);
 op["sequence"]=1;op["state"]="jogging";flow.observe(data);assert(flow.pending());
 assert(flow.message().empty());flow.delivery_unknown();assert(flow.message().empty());
 op["state"]="editing";flow.observe(data);assert(!flow.pending());
 assert(flow.act(data,"JOG","10").empty()&&flow.act(data,"SAVE").empty());
 assert(!flow.act(data,"ACCEPT").empty());
 op["sequence"]=2;op["state"]="accepted";flow.observe(data);assert(!flow.pending());
 assert(!flow.act(data,"DISCARD").empty());
 op["sequence"]=3;op["state"]="discarded";flow.observe(data);assert(!flow.pending());
 assert(flow.act(data,"SAVE").empty());
 // Stock ACCEPT can reject an unadjusted position by finalizing with no value.
 // Explain that outcome without turning it into a successful calibration.
 {
  auto d=data;auto&o=d["probe_editor"];o["state"]="idle";o["request"]="";o["sequence"]=-1;
  ProbeEditorFlow f;assert(!f.begin(d,request,true).empty());
  o["request"]=request;o["sequence"]=0;o["state"]="editing";f.observe(d);
  assert(!f.act(d,"ACCEPT").empty());o["sequence"]=1;o["state"]="aborted";f.observe(d);
  assert(!f.pending()&&f.message().find("not accepted")!=std::string::npos);
  const auto explanation=f.message();f.observe(d);f.delivery_unknown();assert(f.message()==explanation);
  assert(f.act(d,"SAVE").empty());
 }
 // After ACCEPT, queued SAVE/DISCARD clicks must recheck current authority.
 // Rejection must not consume a sequence or prevent the legitimate action
 // when freshness/ownership returns; a restarted session stays invalidated.
 for(const auto*action:{"SAVE","DISCARD"})for(const auto*change:{"fresh","owner","session","token","sequence"}){
  auto d=data;auto&o=d["probe_editor"];o["state"]="idle";o["request"]="";o["sequence"]=-1;
  ProbeEditorFlow f;assert(!f.begin(d,request,true).empty());
  o["request"]=request;o["state"]="editing";o["sequence"]=0;f.observe(d);
  assert(!f.act(d,"ACCEPT").empty());o["state"]="accepted";o["sequence"]=1;f.observe(d);
  auto stale=d;std::string c=change;
  if(c=="fresh")stale["fresh"]=false;
  if(c=="owner")stale["owner"]="openace";
  if(c=="session")stale["calibration_session"]=std::string(32,'e');
  if(c=="token")stale["probe_editor"]["token"]="";
  if(c=="sequence")stale["probe_editor"]["sequence"]=0;
  assert(f.act(stale,action).empty()&&!f.pending());
  if(c=="session"){assert(f.invalidated()&&f.act(d,action).empty());continue;}
  auto command=f.act(d,action);assert(command.find("SEQ=2 ACTION="+std::string(action))!=std::string::npos);
  assert(f.act(d,action).empty()); // double tap cannot submit twice
  f.delivery_unknown();f.observe(d);assert(f.pending()); // old ACCEPT is not acknowledgement
  o["sequence"]=2;o["state"]=std::string(action)=="SAVE"?"saved":"discarded";
  f.observe(d);assert(!f.pending());f.delivery_unknown();assert(f.message().empty());
 }
 // KEEP uses the displayed review, never a newer background snapshot.
 {
  auto d=data;auto&o=d["probe_editor"];o["state"]="idle";o["sequence"]=-1;o["request"]="";
  ProbeEditorFlow f;assert(!f.begin(d,request,true).empty());
  o["state"]="editing";o["sequence"]=0;o["request"]=request;f.observe(d);
  assert(!f.act(d,"ACCEPT").empty());o["state"]="accepted";o["sequence"]=1;f.observe(d);
  const std::string review(64,'d');o["config_conflict"]={{"review",review}};
  assert(f.act(d,"SAVE").empty());assert(f.act(d,"KEEP").empty());
  assert(f.act(d,"KEEP",std::string(64,'e')).empty());
  auto cmd=f.act(d,"KEEP",review);assert(cmd.find(" REVIEW="+review)!=std::string::npos&&cmd.find(" Z=")==std::string::npos);
  assert(f.act(d,"KEEP",review).empty());o["state"]="kept";o["sequence"]=2;f.observe(d);
  assert(!f.pending()&&!f.invalidated());assert(!f.begin(d,std::string(32,'f'),true).empty());
 }
 // Restarted saves require a new explicit review and an exact result receipt.
 for(bool retain:{false,true}){
  ProbeEditorFlow f;auto d=data;auto&o=d["probe_editor"];
  o["state"]="idle";o["request"]="";o["sequence"]=-1;
  assert(!f.begin(d,request,true).empty());
  const std::string resolution=retain?"RETAIN":"ACK";
  const std::string next_session(32,'d'),review_token(64,'e');
  d["calibration_session"]=next_session;o["session"]=next_session;o["request"]=request;
  o["state"]="save_review";o["sequence"]=0;o["binding_valid"]=false;
  o["save_review_required"]=true;o["save_review_protocol"]=2;o["save_review_sequence"]=0;
  o["save_retain_protocol"]=1;o["save_review_confirmable"]=true;o["save_review"]={{"token",review_token},{"configuration_matches",!retain},{"retainable",retain}};
  f.observe(d);assert(f.invalidated());
  assert(f.act(d,resolution,review_token).empty());
  assert(f.act(d,"REVIEW").find("SEQ=1 ACTION=REVIEW")!=std::string::npos);
  assert(!f.invalidated()&&f.pending());
  f.observe(d);assert(f.pending()); // cached confirmable review is not this receipt
  f.delivery_unknown();assert(f.pending());
  o["save_review_result"]={{"session",next_session},{"request",request},{"sequence",1},{"action","ACK"},{"state","complete"},{"error",""}};
  f.observe(d);assert(f.pending());
  o["save_review_result"]["action"]="REVIEW";o["save_review_sequence"]=1;
  f.observe(d);assert(!f.pending());
  assert(f.act(d,resolution,std::string(64,'f')).empty());
  assert(f.act(d,resolution,review_token).find("SEQ=2 ACTION="+resolution+" REVIEW="+review_token)!=std::string::npos);
  f.observe(d);assert(f.pending());
  o["save_review_result"]["action"]=resolution;o["save_review_result"]["sequence"]=2;
  o["save_review_sequence"]=2;o["state"]="save_acknowledged";o["save_review_required"]=false;
  f.observe(d);assert(!f.pending());
  assert(!f.begin(d,std::string(32,'f'),true).empty());
  assert(f.begin(d,std::string(32,'f'),true).empty());
 }
 // A completed editor can be opened again explicitly, never by sync or
 // by a duplicate request; unresolved/stale operations cannot be replaced.
 for(const auto*terminal:{"aborted","saved","discarded"}){
  auto initial=data;auto&o=initial["probe_editor"];
  o["state"]="idle";o["request"]="";o["sequence"]=-1;
  ProbeEditorFlow reopened;assert(!reopened.begin(initial,request,true).empty());
  o["request"]=request;o["sequence"]=0;o["state"]="editing";
  reopened.observe(initial);
  const std::string next(32,'e');
  assert(reopened.begin(initial,next,true).empty());
  if(std::string(terminal)=="aborted")assert(!reopened.act(initial,"ABORT").empty());
  else{
   assert(!reopened.act(initial,"ACCEPT").empty());
   o["sequence"]=1;o["state"]="accepted";reopened.observe(initial);
   assert(!reopened.act(initial,std::string(terminal)=="saved"?"SAVE":"DISCARD").empty());
  }
  o["sequence"]=std::string(terminal)=="aborted"?1:2;o["state"]=terminal;
  auto stale=initial;stale["fresh"]=false;
  assert(reopened.begin(stale,next,true).empty());
  assert(reopened.begin(initial,request,true).empty());
  assert(!reopened.begin(initial,next,true).empty());
  assert(reopened.pending()&&reopened.begin(initial,next,true).empty());
 }
 // A stop during BEGIN has no editing helper/token but still settles BEGIN.
 {
  auto stopped=data;auto&o=stopped["probe_editor"];
  o["state"]="idle";o["request"]="";o["sequence"]=-1;o.erase("token");
  ProbeEditorFlow preparing;assert(!preparing.begin(stopped,request,true).empty());
  o["request"]=request;o["sequence"]=0;o["state"]="stopping";
  preparing.observe(stopped);assert(preparing.pending());
  o["state"]="aborted";preparing.observe(stopped);assert(!preparing.pending());
  assert(!preparing.begin(stopped,std::string(32,'f'),true).empty());
 }
 // Failed preparation offers only the backend-advertised bound cleanup.
 for(bool available:{false,true}){
  auto failed=data;auto&o=failed["probe_editor"];
  o["state"]="idle";o["request"]="";o["sequence"]=-1;
  ProbeEditorFlow cleanup;assert(!cleanup.begin(failed,request,true).empty());
  o["request"]=request;o["sequence"]=0;o["state"]="failed";
  o["receipt_state"]="preparation_failed";o["cleanup_available"]=available;
  cleanup.observe(failed);assert(!cleanup.pending());
  assert(cleanup.act(failed,"ACCEPT").empty()&&cleanup.act(failed,"SAVE").empty()&&cleanup.act(failed,"JOG","0.1").empty());
  assert(cleanup.act(failed,"ABORT").empty()==!available);
 }
 // No-helper failure discard requires explicit backend evidence and a token.
 for(bool available:{false,true}){
  auto failed=data;auto&o=failed["probe_editor"];
  o["state"]="idle";o["request"]="";o["sequence"]=-1;
  ProbeEditorFlow resolution;assert(!resolution.begin(failed,request,true).empty());
  o["request"]=request;o["sequence"]=0;o["state"]="failed";
  o["failure_discard_available"]=available;resolution.observe(failed);
  assert(resolution.act(failed,"SAVE").empty()&&resolution.act(failed,"ABORT").empty());
  assert(resolution.act(failed,"DISCARD").empty()==!available);
 }
 // A matching refusal settles the action without changing the editor phase.
 {
  auto refused=data;auto&o=refused["probe_editor"];
  o["state"]="idle";o["request"]="";o["sequence"]=-1;
  ProbeEditorFlow f;assert(!f.begin(refused,request,true).empty());
  o["request"]=request;o["sequence"]=0;o["state"]="rejected";o["action_refused"]=true;o["error"]="busy";
  f.observe(refused);assert(!f.pending()&&f.message()=="busy");
  auto next=std::string(32,'f');assert(!f.begin(refused,next,true).empty());
  o["request"]=next;o["state"]="editing";o["action_refused"]=false;o["error"]="";f.observe(refused);
  assert(!f.act(refused,"ACCEPT").empty());
  o["sequence"]=1;o["action_refused"]=true;o["error"]="admission changed";f.observe(refused);
  assert(!f.pending()&&!f.invalidated()&&f.message()=="admission changed");
  f.delivery_unknown();assert(f.message()=="admission changed");
  assert(!f.act(refused,"ABORT").empty());
 }
 // Unknown command outcome permits ABORT only while the backend receipt
 // still identifies an editing helper, not after uncertain save/finalization.
 for(const auto*receipt:{"editing","accepted","unknown","aborted"}){
  auto other=data;other["probe_editor"]["state"]="idle";other["probe_editor"]["request"]="";
  ProbeEditorFlow recovery;assert(!recovery.begin(other,request,true).empty());
  auto&r=other["probe_editor"];r["request"]=request;r["sequence"]=0;r["state"]="editing";
  recovery.observe(other);assert(!recovery.act(other,"JOG","-0.1").empty());
  r["sequence"]=1;r["state"]="unknown";r["receipt_state"]=receipt;
  recovery.observe(other);assert(!recovery.pending());
  assert(recovery.act(other,"ABORT").empty()==(std::string(receipt)!="editing"));
 }
 data["calibration_session"]=std::string(32,'d');flow.observe(data);assert(flow.invalidated());
 assert(flow.act(data,"ABORT").empty());
}
