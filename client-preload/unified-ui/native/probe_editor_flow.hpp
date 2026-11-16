// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../model.hpp"
namespace wmp_ui { namespace native {
// Action state serialized by the independent transport worker.
// Reading status only reconciles receipts. It never emits or replays commands.
class ProbeEditorFlow {
 std::string session_,request_,action_,message_;
 long long sequence_=-1,review_sequence_=0;
 bool pending_=false,invalidated_=false,receipt_observed_=false;
 std::string reject(const std::string&reason){message_=reason;return {};}
 static bool hex(const std::string&v){if(v.size()!=32)return false;for(char c:v)if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')))return false;return true;}
 static bool current(const Json&data){return data.value("fresh",false)&&data.value("owner","")=="standalone";}
 static bool settled(const std::string&action,const std::string&state){
  if(state=="failed"||state=="unknown")return true;
  if(action=="BEGIN")return state=="editing"||state=="aborted"||state=="rejected";
  if(action=="JOG")return state=="editing";
  if(action=="ACCEPT")return state=="accepted"||state=="aborted";
  if(action=="ABORT")return state=="aborted";
  if(action=="SAVE")return state=="saved";
  if(action=="DISCARD")return state=="discarded";
  if(action=="KEEP")return state=="kept";
  return false;
 }
 bool matches(const Json&op)const{return op.value("available",false)&&op.value("session","")==session_&&op.value("request","")==request_;}
 std::string command(const std::string&action,const std::string&token,const std::string&step){
  action_=action;pending_=true;receipt_observed_=false;message_="Waiting for the printer.";
  std::string value="_WMP_PROBE_EDITOR SESSION="+session_+" REQUEST="+request_+" SEQ="+std::to_string(sequence_)+" ACTION="+action;
  if(!token.empty())value+=" TOKEN="+token;
  if(!step.empty())value+=(action=="KEEP"?" REVIEW=":" Z=")+step;
  return value;
 }
public:
 std::string begin(const Json&data,const std::string&request,bool admitted){
  if(!admitted)return reject("Probe START was not admitted by maintenance controls.");
  if(!data.value("fresh",false))return reject("Probe START requires fresh status.");
  if(data.value("owner","")!="standalone")return reject("Probe START requires standalone ownership; current="+rejection_value(data.value("owner",""))+".");
  if(!hex(request))return reject("Probe START request identifier must be 32 lowercase hexadecimal characters.");
  const auto op=data.value("probe_editor",Json::object());
  const auto session=data.value("calibration_session","");
  const auto state=op.value("state","");
  if(!hex(session))return reject("Probe calibration session identifier is missing or malformed.");
  if(!op.value("available",false))return reject("Probe editor protocol is unavailable.");
  if(op.value("session","")!=session)return reject("Probe editor belongs to a different calibration session.");
  if(data.value("calibration_active",false)||state=="preparing"||state=="editing"||state=="jogging"||state=="accepting"||state=="aborting"||state=="stopping"||state=="saving"||state=="discarding"||state=="keeping")
   return reject("Probe START conflicts with active calibration: editor.state="+rejection_value(state)+".");
  if(request==request_)return reject("Probe START request was already used; duplicate prevented.");
  // Explicit START replaces history, never replays its JOG/SAVE or token.
  // The worker separately excludes queued or executing transport requests.
  session_=session;request_=request;sequence_=0;
  pending_=invalidated_=receipt_observed_=false;
  return command("BEGIN","","");
 }
 void observe(const Json&data){
  if(request_.empty()||!current(data))return;
  if(data.value("calibration_session","")!=session_){invalidated_=true;message_="Printer restarted; review the calibration result.";return;}
  const auto op=data.value("probe_editor",Json::object());
  if(!matches(op))return;
  if(action_=="REVIEW"||action_=="ACK"||action_=="RETAIN"){
   const auto r=op.value("save_review_result",Json::object());
   if(r.value("session","")!=session_||r.value("request","")!=request_||r.value("sequence",-1LL)!=review_sequence_||r.value("action","")!=action_)return;
   const auto state=r.value("state","");
   if(state=="complete"||state=="refused"||state=="unknown"){
    pending_=false;message_=r.value("error","");
    if(state=="unknown"&&message_.empty())message_="Save review outcome unknown; review the retained evidence.";
   }
   return;
  }
  const auto observed=op.value("sequence",-1LL);
  if(observed>sequence_){invalidated_=true;message_="Probe editor changed elsewhere.";return;}
  if(observed!=sequence_)return;
  if(!op.value("binding_valid",false)){invalidated_=true;message_="Probe editor session changed.";return;}
  const auto state=op.value("state","");
  if(pending_&&(op.value("action_refused",false)||settled(action_,state))){
   receipt_observed_=true;pending_=false;message_=op.value("error","");
   if(action_=="ACCEPT"&&state=="aborted"&&message_.empty())
    message_="Probe position was not accepted. Start again and adjust Z below its starting position before ACCEPT.";
  }else if(pending_&&((action_=="BEGIN"&&(state=="preparing"||state=="stopping"))
    ||(action_=="JOG"&&state=="jogging")||(action_=="ACCEPT"&&state=="accepting")
    ||(action_=="ABORT"&&state=="aborting")||(action_=="SAVE"&&state=="saving")
    ||(action_=="DISCARD"&&state=="discarding")||(action_=="KEEP"&&state=="keeping"))){
   // The matching live receipt confirms delivery, not completion. A later
   // transport timeout must not replace that evidence with "unknown".
   receipt_observed_=true;message_="";
  }
 }
 std::string act(const Json&data,const std::string&action,const std::string&step=""){
  if(action=="REVIEW"||action=="ACK"||action=="RETAIN")return review(data,action,step);
  observe(data);
  if(request_.empty())return reject("No probe operation has been started.");
  if(pending_)return reject("Previous probe command is awaiting its receipt.");
  if(invalidated_)return reject("Probe operation context was invalidated.");
  if(!data.value("fresh",false))return reject("Probe action requires fresh status.");
  if(data.value("owner","")!="standalone")return reject("Probe action requires standalone ownership; current="+rejection_value(data.value("owner",""))+".");
  const auto op=data.value("probe_editor",Json::object());
  if(!matches(op))return reject("Probe editor session or request differs from the retained operation.");
  if(!op.value("binding_valid",false))return reject("Probe editor binding_valid=false.");
  if(op.value("sequence",-1LL)!=sequence_)return reject("Probe sequence changed: expected="+std::to_string(sequence_)+", current="+std::to_string(op.value("sequence",-1LL))+".");
  const auto token=op.value("token","");if(!hex(token))return reject("Probe action token is missing or malformed.");
  const auto state=op.value("state","");
  if(action=="JOG"){
   bool valid=false;for(const auto*v:{"1","-1","0.1","-0.1","0.05","-0.05","0.025","-0.025","0.01","-0.01","0.005","-0.005"})if(step==v)valid=true;
   if(!valid)return reject("Unsupported probe jog step="+rejection_value(step)+".");
   if(state!="editing")return reject("Probe JOG requires editing state; current="+rejection_value(state)+".");
  }else{
   if(!step.empty()&&action!="KEEP")return reject("Unexpected parameter for probe action="+rejection_value(action)+".");
   if(action=="ACCEPT"){if(state!="editing")return reject("Probe ACCEPT requires editing state; current="+rejection_value(state)+".");}
   else if(action=="ABORT"){
    const bool cleanup=state=="failed"&&op.value("receipt_state","")=="preparation_failed"&&op.value("cleanup_available",false);
    if(!cleanup&&state!="editing"&&(state!="unknown"||op.value("receipt_state","")!="editing"))return reject("Probe ABORT unavailable: state="+rejection_value(state)+", receipt_state="+rejection_value(op.value("receipt_state",""))+", cleanup_available="+std::to_string(op.value("cleanup_available",false))+".");
   }
   else if(action=="KEEP"){
    const auto conflict=op.value("config_conflict",Json());
    if(state!="accepted")return reject("Probe KEEP requires accepted state; current="+rejection_value(state)+".");
    if(!conflict.is_object())return reject("Probe KEEP requires a configuration conflict review.");
    if(step.size()!=64||!hex(step.substr(0,32))||!hex(step.substr(32)))return reject("Probe KEEP review token is malformed.");
    if(conflict.value("review","")!=step)return reject("Probe KEEP review token changed.");
   }
   else if(action=="SAVE"){if(state!="accepted")return reject("Probe SAVE requires accepted state; current="+rejection_value(state)+".");if(op.value("config_conflict",Json()).is_object())return reject("Probe SAVE requires resolving the configuration conflict.");}
   else if(action=="DISCARD"){if(state!="accepted"&&(state!="failed"||!op.value("failure_discard_available",false)))return reject("Probe DISCARD unavailable: state="+rejection_value(state)+", failure_discard_available="+std::to_string(op.value("failure_discard_available",false))+".");}
   else return reject("Unsupported probe action="+rejection_value(action)+".");
  }
  if(sequence_>=1000000000)return reject("Probe sequence limit reached: sequence="+std::to_string(sequence_)+".");
  ++sequence_;return command(action,token,step);
 }
 std::string review(const Json&data,const std::string&action,const std::string&token){
  if(!data.value("fresh",false))return reject("Probe save review requires fresh status.");
  if(data.value("owner","")!="standalone")return reject("Probe save review requires standalone ownership; current="+rejection_value(data.value("owner",""))+".");
  const auto op=data.value("probe_editor",Json::object());
  const auto session=data.value("calibration_session",""),request=op.value("request","");
  const auto state=op.value("state","");
  if(!hex(session)||!hex(request))return reject("Probe save review session or request identifier is malformed.");
  if(!op.value("available",false))return reject("Probe editor protocol is unavailable.");
  if(op.value("session","")!=session)return reject("Probe save review belongs to another calibration session.");
  if(op.value("save_review_protocol",0)!=2)return reject("Unsupported probe save_review_protocol="+std::to_string(op.value("save_review_protocol",0))+"; expected=2.");
  if(!op.value("save_review_required",false))return reject("No probe saved-settings review is required.");
  if(state!="save_review"&&state!="unknown"&&state!="saved")return reject("Probe saved-settings review unavailable: state="+rejection_value(state)+".");
  observe(data);
  if(pending_&&session_==session)return reject("Previous probe save-review command is awaiting its receipt.");
  if(action=="REVIEW"){if(!token.empty())return reject("Probe REVIEW does not accept a confirmation token.");}
  else if(action=="ACK"||action=="RETAIN"){
   const auto r=op.value("save_review",Json::object());
   if(action=="RETAIN"&&op.value("save_retain_protocol",0)!=1)return reject("Unsupported probe save_retain_protocol="+std::to_string(op.value("save_retain_protocol",0))+"; expected=1.");
   if(invalidated_)return reject("Probe save review context was invalidated.");
   if(session_!=session)return reject("Probe save review calibration session changed.");
   if(request_!=request)return reject("Probe save review request changed.");
   if(!op.value("save_review_confirmable",false))return reject("Probe save_review_confirmable=false.");
   if(!(action=="RETAIN"?r.value("retainable",false):r.value("configuration_matches",false)))return reject(action=="RETAIN"?"Probe saved settings are not retainable.":"Probe saved configuration does not match the reviewed values.");
   if(token.size()!=64||!hex(token.substr(0,32))||!hex(token.substr(32)))return reject("Probe save-review token is malformed.");
   if(r.value("token","")!=token)return reject("Probe save-review token changed.");
  }else return reject("Unsupported probe review action="+rejection_value(action)+".");
  const auto seq=op.value("save_review_sequence",-1LL);if(seq<0||seq>=999999999)return reject("Probe save-review sequence outside range: current="+std::to_string(seq)+", allowed=0..999999998.");
  session_=session;request_=request;sequence_=op.value("sequence",-1LL);review_sequence_=seq+1;
  invalidated_=false;pending_=true;receipt_observed_=false;action_=action;message_="Waiting for save review result.";
  return "_WMP_PROBE_SAVE_REVIEW SESSION="+session+" REQUEST="+request+" SEQ="+std::to_string(review_sequence_)+" ACTION="+action+(token.empty()?"":" REVIEW="+token);
 }
 std::string stop_reason(const Json&data)const{
  const auto op=data.value("probe_editor",Json::object());
  if(!data.value("fresh",false))return "Probe STOP requires fresh status.";
  if(data.value("owner","")!="standalone")return "Probe STOP requires standalone ownership; current="+rejection_value(data.value("owner",""))+".";
  if(invalidated_)return "Probe STOP context was invalidated.";
  if(!pending_)return "No probe command is pending.";
  if(action_!="BEGIN")return "Probe STOP requires pending BEGIN; action="+rejection_value(action_)+".";
  if(data.value("calibration_session","")!=session_)return "Probe STOP calibration session changed.";
  if(!matches(op))return "Probe STOP editor session or request changed.";
  if(op.value("sequence",-1LL)!=sequence_)return "Probe STOP sequence changed: expected="+std::to_string(sequence_)+", current="+std::to_string(op.value("sequence",-1LL))+".";
  if(op.value("state","")!="preparing")return "Probe STOP requires preparing state; current="+rejection_value(op.value("state",""))+".";
  if(!op.value("binding_valid",false))return "Probe STOP binding_valid=false.";
  if(op.value("stop_protocol",0)!=1)return "Unsupported probe stop_protocol="+std::to_string(op.value("stop_protocol",0))+"; expected=1.";
  if(op.value("stop_requested",false))return "Probe STOP was already requested by the backend.";
  return {};
 }
 Json stop_request(const Json&data)const{
  const auto op=data.value("probe_editor",Json::object());
  if(!current(data)||invalidated_||!pending_||action_!="BEGIN"
    ||data.value("calibration_session","")!=session_||!matches(op)
    ||op.value("sequence",-1LL)!=sequence_||op.value("state","")!="preparing"
    ||!op.value("binding_valid",false)||op.value("stop_protocol",0)!=1
    ||op.value("stop_requested",false))return Json();
  return {{"session",session_},{"request",request_}};
 }
 void delivery_refused(){
  pending_=false;invalidated_=true;message_="Probe editor changed before delivery; no command sent.";
  if(action_=="BEGIN"){
   // The worker proves it did not dispatch this preparation. Do not strand an
   // idle backend behind a local attempted request that can never get a receipt.
   request_.clear();session_.clear();sequence_=-1;invalidated_=false;
  }
 }
 void delivery_unknown(){if(pending_&&!receipt_observed_)message_="Command outcome unknown. Waiting for its recorded result; it will not be repeated.";}
 // Only an automatic read may be superseded. Motion, SAVE and explicit
 // acknowledgement keep their original receipt binding until resolved.
 bool release_pending_review(){if(!pending_)return true;if(action_!="REVIEW")return false;pending_=false;return true;}
 bool pending()const{return pending_;}
 bool invalidated()const{return invalidated_;}
 const std::string&message()const{return message_;}
};
}}
