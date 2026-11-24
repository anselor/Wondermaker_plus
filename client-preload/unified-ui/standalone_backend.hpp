// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "openace_backend.hpp"
#include <mutex>
#include <functional>
#include <random>
#include <limits>
#include "print_request.hpp"
namespace wmp_ui {
// One-shot native standalone requests and shared physical heater controls.
// Network I/O runs only on the worker.
// A successful RPC is not completion: the subsequent heater target must match.
class StandaloneBackend : public Backend {
 long long print_sequence_=0;std::string sequence_session_;
 long long filament_sequence_=0,toolhead_sequence_=0,material_sequence_=0;std::string material_sequence_session_;
public:
 // Must stage the stock per-print context before dispatch. A false result must
 // mean no context was changed; an exception is an uncertain outcome.
 void print_context(std::function<bool(const Json&)> prepare,std::function<void(const std::string&)> settle={}){std::lock_guard<std::mutex>lock(mutex_);prepare_print_=std::move(prepare);settle_print_=std::move(settle);}
 std::string unavailable(const std::string&action)const override {
  std::lock_guard<std::mutex> lock(mutex_);return reason(action);
 }
 Receipt submit(const Request&r)override {
  std::lock_guard<std::mutex> lock(mutex_);
  bool staging=false;
  try {
  auto why=reason(r.action);if(!why.empty())return {"","refused",why};
  if(r.owner!=snapshot_.value("owner",""))return {"","refused","Printer ownership changed: reviewed="+rejection_value(r.owner)+", current="+rejection_value(snapshot_.value("owner",""))+"."};
  if(r.revision!=snapshot_.value("revision",""))return {"","refused","Printer configuration revision changed since review."};
  auto validation=validate(r.action,r.arguments);if(!validation.empty())return {"","refused",validation};
  if(queued_||delivering_||waiting_||(owner_!="standalone"&&(action_=="start_print"||action_=="load"||action_=="unload"||action_=="take"||action_=="dock")&&receipt_.value("state","")=="unknown"))return {"","refused","Request still executing: action="+rejection_value(action_)+", state="+rejection_value(receipt_.value("state",""))+", queued="+std::to_string(queued_)+", delivering="+std::to_string(delivering_)+", waiting="+std::to_string(waiting_)+"."};
  // A fresh explicit standalone request replaces an unconfirmed old result.
  // Transport has finished; validation above checks the current job/context.
  if(owner_=="standalone"&&action_=="start_print"&&print_prepared_&&receipt_.value("state","")=="unknown"&&settle_print_)settle_print_("retired");
  staging=true;
  cancel_queued_=cancel_sent_=false;recover_queued_=recover_sent_=false;print_prepared_=false;print_ace_revision_=snapshot_.value("ace_config_revision",Json());print_pairs_=Json::array();print_helper_session_=snapshot_.value("print_helper_session","");
  if(r.action=="start_print"&&r.owner=="openace")print_pairs_=openace_helper_print_request(snapshot_,r.arguments,"preparation").at("pairs");
  arguments_=r.arguments;action_=r.action;id_=prefix_+std::to_string(++serial_);session_=snapshot_.value("session","");owner_=r.owner;revision_=r.revision;
  if(action_=="start_print"&&owner_=="standalone"&&snapshot_.value("print_sequence_protocol",0)==1){
   if(sequence_session_!=session_){sequence_session_=session_;print_sequence_=0;}
   print_sequence_=std::max(print_sequence_,snapshot_.value("print_request_sequence",0LL))+1;
   id_="print_"+std::to_string(print_sequence_);
  }
  material_sequence_=0;
  if(owner_=="standalone"&&snapshot_.value("material_request_sequence_protocol",0)==1&&
     (action_=="load"||action_=="unload"||action_=="take"||action_=="dock")){
   if(material_sequence_session_!=session_){material_sequence_session_=session_;filament_sequence_=toolhead_sequence_=0;}
   const bool filament=action_=="load"||action_=="unload";
   auto&sequence=filament?filament_sequence_:toolhead_sequence_;
   const auto observed=snapshot_.value(filament?"filament_request_sequence":"toolhead_request_sequence",0LL);
   if(observed<0||std::max(sequence,observed)==std::numeric_limits<long long>::max())throw std::runtime_error("Invalid material request sequence");
   material_sequence_=sequence=std::max(sequence,observed)+1;
   id_=std::string(filament?"filament_":"toolhead_")+std::to_string(sequence);
  }
  generation_=snapshot_.value("command_generation",0LL);
  print_request_=Json();
  if(action_=="start_print")print_request_=owner_=="openace"?openace_helper_print_request(snapshot_,arguments_,id_):standalone_print_request(snapshot_,arguments_,id_);
  receipt_={{"owner",owner_},{"session",session_},{"action",action_},{"state","pending"},{"message","Waiting for backend completion."}};
  queued_=true;return {id_,"pending",action_=="start_print"?"Submitting print.":action_=="confirm_filament"?"Recording filament check.":(action_=="load"||action_=="unload")?"Running filament procedure.":(action_=="take"||action_=="dock")?"Changing toolhead.":action_=="step"?"Moving filament.":action_=="save_identity"?"Saving filament settings.":action_=="profile_import"?"Reading filament profiles.":action_=="save_nozzle"?"Saving nozzle settings.":"Setting heater target."};
  }catch(...){
   // Submission only stages work under this lock; no transport can run until
   // it returns. Roll back a new queue, but never clear an older active one.
   if(staging){queued_=false;waiting_=false;receipt_=Json::object();}
   return {"","refused","Request could not be prepared; nothing sent."};
  }
 }
 std::string unresolved_request_id()const{
  std::lock_guard<std::mutex> lock(mutex_);
  return queued_||waiting_||receipt_.value("state","")=="unknown"?id_:"";
 }
 bool machine_request_pending()const{
  std::lock_guard<std::mutex> lock(mutex_);
  const bool retained=action_=="start_print"||action_=="load"||action_=="unload"||action_=="take"||action_=="dock";
  const bool physical=retained||action_=="step"||action_=="temperature";
  return physical&&(queued_||delivering_||waiting_||(owner_!="standalone"&&retained&&receipt_.value("state","")=="unknown"));
 }
 void observe(Json&normalized) {
  std::lock_guard<std::mutex> lock(mutex_);snapshot_=normalized;
  if(waiting_||((action_=="start_print"||action_=="load"||action_=="unload"||action_=="take"||action_=="dock")&&receipt_.value("state","")=="unknown")){
   if(snapshot_.value("owner","")!=owner_||snapshot_.value("session","")!=session_)finish("unknown","Printer ownership changed after dispatch.");
   else if(action_=="start_print"&&owner_=="openace") {
    const auto result=snapshot_.value("print_submission",Json::object());const auto job=snapshot_.at("job");const auto ace_job=snapshot_.value("ace_job",Json());
    bool matched=result.value("id","")==id_&&result.value("session","")==print_helper_session_&&result.value("file","")==arguments_.value("file","");
    auto state=job.value("state","");
    if(matched&&result.value("state","")=="refused")finish("refused","Print was refused before preparation; nothing started.");
    else if(matched&&result.value("state","")=="not_started")finish("refused",(std::string("Print was not started. Preparation failed; tool mapping or leveling settings may have changed. Review them before trying again. ")+result.value("error","").substr(0,240)).c_str());
    else if(matched&&result.value("state","")=="submitted"&&job.value("id","")==arguments_.value("file","")&&(state=="printing"||state=="paused")&&ace_job.is_object()&&ace_job.value("active",false)&&ace_job.value("source","")=="override"&&ace_job.value("file","")==arguments_.value("file","")&&ace_job.value("pairs",Json())==print_pairs_&&ace_job.value("config_revision",Json())==print_ace_revision_)finish("complete","Mapped print admitted by openACE.");
    else if((matched&&result.value("state","")=="unknown")||++readbacks_>=10)finish("unknown","Mapped print admission was not confirmed; inspect the job before retrying.");
   }
   else if(action_=="start_print") {
    const auto result=snapshot_.value("print_submission",Json::object());const auto job=snapshot_.at("job");
    bool matched=result.value("id","")==id_&&result.value("session","")==session_&&result.value("file","")==arguments_.value("file","");
    auto state=job.value("state","");
    if(matched&&result.value("state","")=="refused")finish("refused","Print was refused before preparation; nothing started.");
    else if(matched&&result.value("state","")=="not_started")finish("refused",(std::string("Print was not started. Preparation failed; tool mapping or leveling settings may have changed. Review them before trying again. ")+operation_display_text(result,"error","").substr(0,240)).c_str());
    else if(matched&&result.value("state","")=="pending"&&snapshot_.value("fresh",false)){
     // Current owned preparation is positive evidence, even for a large file.
     // Do not expire it after ten polls or resend a start whose reply was lost.
     readbacks_=0;waiting_=true;receipt_["state"]="pending";receipt_["message"]="Reading/processing G-code.";
    }
    else if(matched&&result.value("state","")=="submitted"&&job.value("id","")==arguments_.value("file","")&&(state=="printing"||state=="paused"||state=="complete"))finish("complete","Selected print admitted.");
    else if((matched&&result.value("state","")=="unknown")||++readbacks_>=10)finish("unknown","Print admission was not confirmed; inspect the job before retrying.");
   }
   else if(action_=="load"||action_=="unload") {
    auto result=snapshot_.value("filament_operation",Json::object());
    if((material_sequence_<=0||!result.contains("previous_session"))&&result.value("id","")==id_&&result.value("session","")== (owner_=="openace"?print_helper_session_:session_)&&result.value("head","")==arguments_.value("head","")&&result.value("action","")==action_){
     if(result.value("state","")=="complete")finish("complete",owner_=="openace"?(action_=="load"?"openACE verified the selected source loaded.":"openACE reports the head empty."):operation_display_text(result,"message","Filament operation complete.").c_str());
     else if(result.value("state","")=="refused")finish("refused","Procedure refused before motion; review the head and temperature.");
     else if(result.value("state","")=="failed")finish("failed",operation_display_text(result,"message","Procedure stopped.").c_str());
     else if(result.value("state","")=="running"){waiting_=true;receipt_["state"]="pending";receipt_["message"]=operation_display_text(result,"message","Preparing filament");}
     else if(result.value("state","")=="unknown")finish("unknown",operation_display_text(result,"message","Procedure interrupted; inspect filament before another operation.").c_str());
    }else if(++readbacks_>=10)finish("unknown","Procedure outcome was not confirmed; inspect the filament.");
   }
   else if(action_=="profile_import") {
    const auto result=snapshot_.value("profile_import",Json::object());
    if(result.value("id","")==id_){const auto state=result.value("state","");
     if(state=="error")finish("failed",operation_display_text(result,"message","Import failed").c_str());
     else if(state=="files"||state=="review"||state=="saved")finish("complete","Import result ready.");
    }else if(++readbacks_>=10)finish("unknown","Import result unavailable. Refresh to inspect the catalogue.");
   }
   else if(action_=="take"||action_=="dock") {
    const auto result=snapshot_.value("toolhead_operation",Json::object());
    if((material_sequence_<=0||!result.contains("previous_session"))&&result.value("id","")==id_&&result.value("session","")==session_&&result.value("head","")==arguments_.value("head","")&&result.value("action","")==action_){
     const auto state=result.value("state","");const auto message=operation_display_text(result,"message","");
     if(state=="complete"||state=="refused"||state=="unknown"||state=="failed")finish(state.c_str(),message.c_str());
     else if(state=="running"){waiting_=true;receipt_["state"]="pending";receipt_["message"]=message;}
    }else if(++readbacks_>=10)finish("unknown","Toolhead result unavailable; inspect the printer.");
   }
   else if(action_=="confirm_filament") {
    bool matched=false;for(const auto&head:snapshot_.at("heads"))if(head.at("id")==arguments_.at("head")){auto loaded=head.value("loaded",Json::object());matched=loaded.value("state","")==arguments_.at("state")&&(loaded.value("evidence","")=="operator"||loaded.value("evidence","")=="sensor");}
    if(matched)finish("complete","Operator filament check recorded.");else if(++readbacks_>=3)finish("unknown","Filament check was not confirmed.");
   }
   else if(action_=="save_nozzle") {
    const auto result=snapshot_.value("nozzle_save",Json::object());
    if(result.value("id","")==id_&&result.value("session","")==session_&&result.value("head","")==arguments_.value("head","")){
     const auto values=snapshot_.value("nozzle_settings",Json::object()).value(arguments_.at("head").get<std::string>(),Json::object());
     if(result.value("state","")=="complete"&&values.value("diameter",0.0)==arguments_.value("diameter",-1.0)&&values.value("material","")==arguments_.value("material",""))finish("complete",!values.value("apply_error",std::string()).empty()?("Saved. Diameter not applied: "+values.value("apply_error",std::string())+". Reopen and Save to retry.").c_str():values.value("apply_pending",false)?"Saved. Diameter will apply when the printer is idle.":values.value("restart_required",false)?"Saved. Restart Klipper to apply the diameter.":"Nozzle settings saved.");
     else if(result.value("state","")=="failed")finish("failed",operation_display_text(result,"message","Nozzle save failed").c_str());
     else if(++readbacks_>=3)finish("unknown","Nozzle save readback did not match; reopen the editor.");
    }else if(++readbacks_>=3)finish("unknown","Nozzle save was not confirmed; reopen the editor.");
   }
   else if(action_=="save_identity") {
    bool matched=false;const auto&draft=arguments_.at("draft");
    for(const auto&source:snapshot_.value("sources",Json::array()))if(source.value("id","")==draft.value("id",""))matched=source.value("identity",Json::object())==draft.at("identity");
    if(matched)finish("complete","Filament settings confirmed.");
    else if(++readbacks_>=3)finish("unknown","Filament settings were not confirmed; refresh before retrying.");
   }else {
    bool matched=false;for(const auto&h:snapshot_.value("heads",Json::array()))if(h.value("id","")==arguments_.value("head",""))matched=h.value("target",-1)==arguments_.value("target",-2);
    if(matched)finish("complete","Heater target confirmed.");
    else if(++readbacks_>=3)finish("unknown","Requested target was not confirmed; check the heater state.");
   }
  }
  if(!id_.empty())normalized["receipts"][id_]=receipt_;
 }
 bool cancel_filament(const std::string&id){return cancel_operation(id);}
 bool cancel_operation(const std::string&id){
  std::lock_guard<std::mutex> lock(mutex_);
  if(!can_cancel(id)){report_rejection("filament cancel",control_reason(id,false));return false;}
  if(cancel_queued_||cancel_sent_){report_rejection("filament cancel","Cancellation already queued or sent: queued="+std::to_string(cancel_queued_)+", sent="+std::to_string(cancel_sent_));return false;}
  cancel_queued_=true;receipt_["message"]="Requesting cancellation.";return true;
 }
 std::string resume_refusal()const{std::lock_guard<std::mutex>lock(mutex_);return resume_refusal_;}
 bool resume_filament(const std::string&id){return resume_operation(id,false);}
 bool resume_toolhead(const std::string&id){return resume_operation(id,true);}
private:
 bool resume_operation(const std::string&id,bool tool){
  std::lock_guard<std::mutex> lock(mutex_);
  const auto operation=snapshot_.value(tool?"toolhead_operation":"filament_operation",Json::object());
  const auto owner=snapshot_.value("owner","");
  const auto head=operation.value("head",""),action=operation.value("action",""),session=snapshot_.value(owner=="openace"?"print_helper_session":"session","");
  const bool supported=owner=="standalone"||(!tool&&owner=="openace"&&operation.value("openace_recovery_supported",false));
  const auto token=[](const std::string&s,std::size_t max){return !s.empty()&&s.size()<=max&&s.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")==std::string::npos;};
  resume_refusal_.clear();
  auto reject=[this](const std::string&why){resume_refusal_=why;report_rejection("resume operation review",why);return false;};
  if(queued_||delivering_||waiting_)return reject("Previous request pending: queued="+std::to_string(queued_)+", delivering="+std::to_string(delivering_)+", waiting="+std::to_string(waiting_)+".");
  if(!snapshot_.value("fresh",false))return reject("Printer status is not fresh.");
  if(!supported)return reject("Recovery ownership unsupported: owner="+rejection_value(owner)+", toolhead="+std::to_string(tool)+", openace_recovery_supported="+std::to_string(operation.value("openace_recovery_supported",false))+".");
  const auto protocol=tool?"toolhead_recovery_protocol":"filament_recovery_protocol";
  if(snapshot_.value(protocol,0)!=1)return reject("Unsupported "+std::string(protocol)+"="+std::to_string(snapshot_.value(protocol,0))+"; expected=1.");
  if(operation.value("state","")!="unknown")return reject("Recovery review requires unknown operation state; current="+rejection_value(operation.value("state",""))+".");
  if(operation.value("id","")!=id)return reject("Selected operation identifier changed.");
  if(operation.value("session","")!=session)return reject("Backend operation session changed.");
  if(!token(id,96))return reject("Operation identifier is missing or malformed.");
  if(!token(session,64))return reject("Printer session identifier is missing or malformed.");
  if(head.size()!=2||head[0]!='h'||head[1]<'0'||head[1]>'3')return reject("Physical head must be h0..h3; current="+rejection_value(head)+".");
  if(tool?(action!="take"&&action!="dock"):(action!="load"&&action!="unload"))return reject("Recovery action is unsupported: action="+rejection_value(action)+".");
  if(receipt_.is_object()&&receipt_.value("state","")=="unknown"&&(id_!=id||(tool?(action_!="take"&&action_!="dock"):(action_!="load"&&action_!="unload"))))return reject("Another retained operation has an unknown outcome: action="+rejection_value(action_)+", identifier_matches="+std::to_string(id_==id)+".");
  // A restored operation keeps its ID but belongs to a new backend session.
  // Reopening it permits a new explicit recovery, never an automatic retry.
  if(id_!=id||session_!=snapshot_.value("session","")||owner_!=owner||
     print_helper_session_!=snapshot_.value("print_helper_session","")){
   recover_queued_=recover_sent_=cancel_queued_=cancel_sent_=false;
  }
  material_sequence_=0; // Explicit review targets the retained operation itself.
  id_=id;session_=snapshot_.value("session","");print_helper_session_=snapshot_.value("print_helper_session","");owner_=owner;action_=action;arguments_={{"head",head}};revision_=snapshot_.value("revision","");
  receipt_={{"owner",owner_},{"session",session_},{"action",action_},{"state","unknown"},{"message",operation_display_text(operation,"message",tool?"Toolhead operation interrupted.":"Filament operation interrupted.")}};
  return true;
 }
public:
 bool recover_filament(const std::string&id){
  std::lock_guard<std::mutex> lock(mutex_);
  if((action_!="load"&&action_!="unload")){report_rejection("filament recover","Unsupported retained action="+rejection_value(action_));return false;}
  if(!can_recover(id)){report_rejection("filament recover",control_reason(id,true));return false;}
  if(recover_queued_||recover_sent_){report_rejection("filament recover","Recovery already queued or sent: queued="+std::to_string(recover_queued_)+", sent="+std::to_string(recover_sent_));return false;}
  recovery_generation_=snapshot_.value("command_generation",0LL);recover_queued_=true;receipt_["message"]="Verifying the stopped head.";return true;
 }
 bool recover_toolhead(const std::string&id){
  std::lock_guard<std::mutex> lock(mutex_);
  if((action_!="take"&&action_!="dock")){report_rejection("toolhead recover","Unsupported retained action="+rejection_value(action_));return false;}
  if(!can_recover(id)){report_rejection("toolhead recover",control_reason(id,true));return false;}
  if(recover_queued_||recover_sent_){report_rejection("toolhead recover","Recovery already queued or sent: queued="+std::to_string(recover_queued_)+", sent="+std::to_string(recover_sent_));return false;}
  recovery_generation_=snapshot_.value("command_generation",0LL);recover_queued_=true;receipt_["message"]="Checking toolhead attachment.";return true;
 }
 void invalidate(){std::lock_guard<std::mutex> lock(mutex_);snapshot_["fresh"]=false;}
 void deliver(wmp_openace::HttpPort&http) {
  deliver_cancel(http);deliver_recovery(http);
  std::string script;Json print_options;std::function<bool(const Json&)>prepare;
  bool dispatched=false,preparing=false;
  try {
  {std::lock_guard<std::mutex> lock(mutex_);if(!queued_)return;queued_=false;
   std::string dispatch_reason=reason(action_);
   if(dispatch_reason.empty()&&snapshot_.value("owner","")!=owner_)dispatch_reason="Owner changed: reviewed="+rejection_value(owner_)+", current="+rejection_value(snapshot_.value("owner",""))+".";
   if(dispatch_reason.empty()&&snapshot_.value("revision","")!=revision_)dispatch_reason="Configuration revision changed.";
   if(dispatch_reason.empty()&&snapshot_.value("session","")!=session_)dispatch_reason="Printer session changed.";
   if(dispatch_reason.empty()&&owner_=="standalone"&&snapshot_.value("command_generation",0LL)!=generation_)dispatch_reason="Command generation changed: reviewed="+std::to_string(generation_)+", current="+std::to_string(snapshot_.value("command_generation",0LL))+".";
   if(dispatch_reason.empty())dispatch_reason=validate(action_,arguments_);
   if(!dispatch_reason.empty()){finish("refused",("Printer changed before dispatch; nothing sent. "+dispatch_reason).c_str());return;}
   if(action_=="profile_import"){
    const auto action=arguments_.at("action").get<std::string>();
    script="WMP_PROFILE_IMPORT ACTION="+action+" ID="+id_;
    if(action!="scan")script+=(action=="review"?" FILE=":" TOKEN=")+arguments_.at("value").get<std::string>();
    waiting_=true;readbacks_=0;
   }else if(action_=="start_print"){auto current=owner_=="openace"?openace_helper_print_request(snapshot_,arguments_,id_):standalone_print_request(snapshot_,arguments_,id_);if(current!=print_request_){finish("refused","Reviewed print request changed before dispatch; nothing sent.");return;}auto payload=print_request_.dump();std::string hex;const char*digits="0123456789abcdef";for(unsigned char c:payload){hex+=digits[c>>4];hex+=digits[c&15];}script="WMP_START_PRINT REQUEST="+hex;print_options=arguments_.at("options");prepare=prepare_print_;waiting_=true;readbacks_=0;}else{
   auto head=action_=="save_identity"?arguments_.at("draft").at("head").get<std::string>():arguments_.at("head").get<std::string>();int index=head[1]-'0';
   waiting_=true;readbacks_=0;
   if(action_=="save_identity") {
    const auto payload=arguments_.at("draft").at("identity").dump();std::string hex;const char*digits="0123456789abcdef";for(unsigned char c:payload){hex+=digits[c>>4];hex+=digits[c&15];}
    script="WMP_SET_FILAMENT HEAD="+std::to_string(index)+" EXPECT="+snapshot_.at("identity_revision").get<std::string>()+" PROFILE="+hex;
    if(arguments_.contains("pause_origin"))script+=" PAUSE="+arguments_["pause_origin"].at("id").get<std::string>();
   }else if(action_=="save_nozzle")script="WMP_SET_NOZZLE HEAD="+std::to_string(index)+" DIAMETER="+std::to_string(arguments_.at("diameter").get<double>())+" MATERIAL="+(arguments_.at("material")=="Hardened steel"?"0":"1")+" EXPECT="+arguments_.at("expected").get<std::string>()+" SESSION="+session_+" ID="+id_;
   else if(action_=="load"||action_=="unload")script="WMP_FILAMENT_SEQUENCE HEAD="+std::to_string(index)+" ACTION="+action_+" ID="+id_+" TOKEN="+arguments_.at("procedure_token").get<std::string>();
   else if(action_=="confirm_filament")script="WMP_CONFIRM_FILAMENT HEAD="+std::to_string(index)+" STATE="+arguments_.at("state").get<std::string>()+" SESSION="+session_+" EXPECT="+snapshot_.at("identity_revision").get<std::string>();
   else if(action_=="take"||action_=="dock")script="WMP_TOOLHEAD_ACTION HEAD="+std::to_string(index)+" ACTION="+action_+" ID="+id_+" SESSION="+session_+" ATTACHED="+arguments_.at("attached").get<std::string>();
   else if(action_=="step")script="WMP_EXTRUDER_STEP HEAD="+std::to_string(index)+" MM="+std::to_string(arguments_.at("mm").get<int>());
   else script="SET_HEATER_TEMPERATURE HEATER="+(index?"extruder"+std::to_string(index):"extruder")+" TARGET="+std::to_string(arguments_.at("target").get<int>());
   }
   if(material_sequence_>0){
    script+=" SEQUENCE="+std::to_string(material_sequence_);
    if(action_=="load"||action_=="unload")script+=" SESSION="+session_;
   }
   if(owner_=="standalone")script=generation_guard(session_,generation_)+script;
   delivering_=true;
  }
   if(prepare){
    preparing=true;
    if(!prepare(print_options)){std::lock_guard<std::mutex> lock(mutex_);finish("refused","Printer screen context could not be prepared; nothing sent.");delivering_=false;return;}
    std::lock_guard<std::mutex> lock(mutex_);print_prepared_=true;
    preparing=false;
   }
   const auto body=Json{{"script",script}}.dump();
   dispatched=true;
   auto response=Json::parse(http.post("/printer/gcode/script",body));
   std::lock_guard<std::mutex> lock(mutex_);
   delivering_=false;
   if(terminal_readback())return; // Polling may settle this request before HTTP returns.
   if(response.contains("error"))finish(owner_=="standalone"?"unknown":action_=="temperature"?"refused":"unknown","Klipper reported an error; checking the operation result. Earlier commands may have executed.");
   else if(response.value("result",Json())=="ok"){if(action_=="step")finish("complete","Extruder step completed.");else {waiting_=true;readbacks_=0;}}
   else finish("unknown","Unrecognized command response; request will not be repeated.");
  }catch(...){std::lock_guard<std::mutex> lock(mutex_);delivering_=false;if(terminal_readback())return;const bool uncertain=dispatched||preparing;finish(uncertain?"unknown":"refused",uncertain?"Delivery outcome unknown; request will not be repeated.":"Request preparation failed; nothing sent.");}
 }
private:
 static bool material_operation_active(const std::string&state,const std::string&owner){
  // Standalone unknown receipts are historical outcomes, not executing work.
  // Retain external-owner semantics; actual sensor checks remain in Klipper.
  return state=="running"||(owner=="standalone"?state=="pending":state=="unknown");
 }
 bool terminal_readback()const{
  const auto state=receipt_.value("state","");return owner_=="standalone"&&!waiting_&&(state=="complete"||state=="refused"||state=="failed");
 }
 static std::string generation_guard(const std::string&session,long long generation){return "WMP_CHECK_COMMAND_GENERATION SESSION="+session+" GENERATION="+std::to_string(generation)+"\n";}
 long long recovery_generation_=0;bool recover_queued_=false,recover_sent_=false;
 std::string control_reason(const std::string&id,bool recovery)const{
  const bool tool=action_=="take"||action_=="dock";
  const auto operation=snapshot_.value(tool?"toolhead_operation":"filament_operation",Json::object());
  if(recovery&&(queued_||waiting_))return "Previous request pending: queued="+std::to_string(queued_)+", waiting="+std::to_string(waiting_)+".";
  if(!recovery&&!waiting_)return "No procedure is awaiting completion.";
  if(id!=id_)return "Selected operation identifier changed.";
  if(!tool&&action_!="load"&&action_!="unload")return "Unsupported operation action="+rejection_value(action_)+".";
  if(owner_!="standalone"){
   if(owner_!="openace"||tool)return "Operation owner is unsupported: owner="+rejection_value(owner_)+".";
   const auto key=recovery?"openace_recovery_supported":"openace_cancel_supported";
   if(!operation.value(key,false))return std::string(key)+"=false.";
   if(print_helper_session_.empty())return "openACE print helper session is missing.";
   if(snapshot_.value("print_helper_session","")!=print_helper_session_)return "openACE print helper session changed.";
  }
  if(recovery&&(!receipt_.is_object()||receipt_.value("state","")!="unknown"))return "Recovery requires an unknown receipt state; current="+rejection_value(receipt_.is_object()?receipt_.value("state",""):"missing")+".";
  if(!snapshot_.value("fresh",false))return "Printer status is not fresh.";
  if(snapshot_.value("owner","")!=owner_)return "Printer owner changed: reviewed="+rejection_value(owner_)+", current="+rejection_value(snapshot_.value("owner",""))+".";
  if(snapshot_.value("session","")!=session_)return "Printer session changed.";
  const auto protocol=recovery?(tool?"toolhead_recovery_protocol":"filament_recovery_protocol"):(tool?"toolhead_cancel_protocol":"filament_cancel_protocol");
  if(snapshot_.value(protocol,0)!=1)return "Unsupported "+std::string(protocol)+"="+std::to_string(snapshot_.value(protocol,0))+"; expected=1.";
  if(recovery){
   const auto job=snapshot_.value("job",Json::object()).value("state","");
   if(job!="idle"&&job!="complete")return "Recovery requires idle or complete job; current="+rejection_value(job)+".";
   const auto key=tool?"filament_operation":"toolhead_operation";const auto state=snapshot_.value(key,Json::object()).value("state","");
   if(material_operation_active(state,owner_))return std::string(key)+" is unresolved: state="+rejection_value(state)+".";
  }
  if(operation.value("id","")!=id_)return "Backend operation identifier changed.";
  if(operation.value("session","")!=(owner_=="openace"?print_helper_session_:session_))return "Backend operation session changed.";
  if(operation.value("head","")!=arguments_.value("head",""))return "Backend operation head changed: selected="+rejection_value(arguments_.value("head",""))+", current="+rejection_value(operation.value("head",""))+".";
  if(recovery&&operation.value("action","")!=action_)return "Backend operation action changed: selected="+rejection_value(action_)+", current="+rejection_value(operation.value("action",""))+".";
  if(operation.value("state","")!=(recovery?"unknown":"running"))return "Backend operation state must be "+std::string(recovery?"unknown":"running")+"; current="+rejection_value(operation.value("state",""))+".";
  if(!recovery&&operation.value("cancel_requested",false))return "Backend cancellation was already requested.";
  return "Operation context changed.";
 }
 bool can_recover(const std::string&id)const{
  const bool tool=action_=="take"||action_=="dock";
  const auto operation=snapshot_.value(tool?"toolhead_operation":"filament_operation",Json::object());
  const auto job=snapshot_.value("job",Json::object()).value("state","");
  const auto other=snapshot_.value(tool?"filament_operation":"toolhead_operation",Json::object()).value("state","");
  const bool supported=owner_=="standalone"||(!tool&&owner_=="openace"&&operation.value("openace_recovery_supported",false)&&!print_helper_session_.empty()&&snapshot_.value("print_helper_session","")==print_helper_session_);
  return !queued_&&!delivering_&&!waiting_&&id==id_&&(tool||action_=="load"||action_=="unload")&&supported&&
   receipt_.is_object()&&receipt_.value("state","")=="unknown"&&snapshot_.value("fresh",false)&&snapshot_.value("owner","")==owner_&&
   snapshot_.value("session","")==session_&&snapshot_.value(tool?"toolhead_recovery_protocol":"filament_recovery_protocol",0)==1&&
   (job=="idle"||job=="complete")&&!material_operation_active(other,owner_)&&operation.value("id","")==id_&&
   operation.value("session","")== (owner_=="openace"?print_helper_session_:session_)&&operation.value("head","")==arguments_.value("head","")&&operation.value("action","")==action_&&operation.value("state","")=="unknown";
 }
 void deliver_recovery(wmp_openace::HttpPort&http){
  std::string script,id,session,helper_session,owner;
  {std::lock_guard<std::mutex> lock(mutex_);if(!recover_queued_)return;recover_queued_=false;
   if(!can_recover(id_)){report_rejection("recovery dispatch",control_reason(id_,true));return;}
   if(snapshot_.value("command_generation",0LL)!=recovery_generation_){report_rejection("recovery dispatch","Command generation changed: reviewed="+std::to_string(recovery_generation_)+", current="+std::to_string(snapshot_.value("command_generation",0LL)));return;}
   id=id_;script=std::string(action_=="take"||action_=="dock"?"WMP_RECOVER_TOOLHEAD ID=":"WMP_RECOVER_FILAMENT ID=")+id_+" SESSION="+(owner_=="openace"?print_helper_session_:session_)+" HEAD="+std::to_string(arguments_.at("head").get<std::string>()[1]-'0');
   if(owner_=="openace")script+=" GENERATION="+std::to_string(recovery_generation_);else script=generation_guard(session_,recovery_generation_)+script;
   session=session_;helper_session=print_helper_session_;owner=owner_;
   recover_sent_=true;
  }
  bool accepted=false;
  try{const auto reply=Json::parse(http.post("/printer/gcode/script",Json{{"script",script}}.dump()));accepted=!reply.contains("error")&&reply.value("result",Json())=="ok";}catch(...){}
  std::lock_guard<std::mutex> lock(mutex_);
  if(id_!=id||session_!=session||print_helper_session_!=helper_session||owner_!=owner)return;
  recover_sent_=accepted;
  receipt_["message"]=accepted?"Waiting for stopped-head verification.":"Recovery not confirmed. Check the head and retry recovery.";
 }
 bool cancel_queued_=false,cancel_sent_=false;
 bool can_cancel(const std::string&id)const{
  const bool tool=action_=="take"||action_=="dock";
  const auto operation=snapshot_.value(tool?"toolhead_operation":"filament_operation",Json::object());
  const bool supported=owner_=="standalone"||(!tool&&owner_=="openace"&&operation.value("openace_cancel_supported",false)&&!print_helper_session_.empty()&&snapshot_.value("print_helper_session","")==print_helper_session_);
  return waiting_&&id==id_&&(tool||action_=="load"||action_=="unload")&&supported&&snapshot_.value("fresh",false)&&
   snapshot_.value("owner","")==owner_&&snapshot_.value("session","")==session_&&
   snapshot_.value(tool?"toolhead_cancel_protocol":"filament_cancel_protocol",0)==1&&operation.value("id","")==id_&&
   operation.value("session","")== (owner_=="openace"?print_helper_session_:session_)&&operation.value("head","")==arguments_.value("head","")&&
   (!tool||operation.value("action","")==action_)&&operation.value("state","")=="running"&&!operation.value("cancel_requested",false);
 }
 void deliver_cancel(wmp_openace::HttpPort&http){
  Json payload;std::string id,path;
  {std::lock_guard<std::mutex> lock(mutex_);if(!cancel_queued_)return;cancel_queued_=false;
   if(!can_cancel(id_)){report_rejection("filament cancel dispatch",control_reason(id_,false));return;}
   const bool tool=action_=="take"||action_=="dock";
   path=tool?"/printer/wmp/toolhead/cancel":"/printer/wmp/filament/cancel";
   id=id_;payload={{"id",id_},{"session",owner_=="openace"?print_helper_session_:session_},{"head",arguments_.at("head")}};
   if(tool)payload["action"]=action_;
   cancel_sent_=true;
  }
  bool accepted=false;
  try{auto reply=Json::parse(http.post(path,payload.dump()));
   const auto result=reply.value("result",Json::object());
   accepted=!reply.contains("error")&&result.value("id","")==id&&result.value("session","")==payload["session"]&&result.value("state","")=="requested";
  }catch(...){}
  std::lock_guard<std::mutex> lock(mutex_);if(id_!=id||!waiting_)return;
  cancel_sent_=accepted;
  receipt_["message"]=accepted?"Cancellation requested; waiting for the procedure to stop.":"Cancellation not confirmed. Check status before trying Stop again.";
 }
 static std::string instance_prefix(){std::random_device random;return "wm-"+std::to_string(random())+"-"+std::to_string(random())+"-";}
 std::string prefix_=instance_prefix();std::function<bool(const Json&)>prepare_print_;std::function<void(const std::string&)>settle_print_;
 mutable std::mutex mutex_;Json snapshot_,arguments_,receipt_,print_pairs_,print_ace_revision_,print_request_;std::string resume_refusal_,print_helper_session_,id_,session_,owner_,revision_,action_;long long generation_=0;unsigned serial_=0,readbacks_=0;bool queued_=false,waiting_=false,delivering_=false,print_prepared_=false;
 void finish(const char*state,const char*message){waiting_=false;receipt_["state"]=state;receipt_["message"]=message;if(action_=="start_print"&&print_prepared_&&settle_print_){settle_print_(state);if(std::string(state)=="complete"||std::string(state)=="refused")print_prepared_=false;}}
 std::string reason(const std::string&action)const {
  if(snapshot_.is_object()&&snapshot_.contains("printer_state")&&snapshot_.value("printer_state","")!="ready")return "Klipper is not ready: printer_state="+rejection_value(snapshot_.value("printer_state",""))+".";
  if(!snapshot_.is_object()||!snapshot_.value("fresh",false))return "Fresh printer status is required.";
  const auto owner=snapshot_.value("owner","");
  if(owner=="openace"&&action=="temperature") {
   if(!snapshot_.value("heater_manual_ready",false))return "Wait until openACE is idle before changing the heater target here.";
   return "";
  }
  if(owner=="openace"&&(action=="unload"||action=="load")) {
   if(!snapshot_.value("heater_manual_ready",false))return "Use recovery controls during a print or another operation.";
   return "";
  }
  if(owner=="openace"&&action=="start_print") {
   if(!snapshot_.value("heater_manual_ready",false))return "Wait until openACE is idle before starting a print.";
   return prepare_print_?"":"Native print context is not connected yet.";
  }
  if(owner!="standalone")return "This operation requires standalone printer ownership; current owner="+rejection_value(owner)+".";
  if(action=="start_print")return prepare_print_?"":"Native print context is not connected yet.";
  if(action!="temperature"&&action!="step"&&action!="save_identity"&&action!="save_nozzle"&&action!="confirm_filament"&&action!="load"&&action!="unload"&&action!="take"&&action!="dock"&&action!="profile_import")return "Standalone "+action+" support is not connected yet.";
  return "";
 }
 std::string validate(const std::string&action,const Json&args)const {
  if(action=="save_nozzle"){
   const auto job=snapshot_.value("job",Json::object()).value("state","");
   if(job=="printing"||job=="paused")return "Finish or cancel the print before changing nozzle settings: job.state="+rejection_value(job)+".";
   if(!snapshot_.value("capabilities",Json::object()).value("save_nozzle",false))return "Nozzle save capability is unavailable.";
   const auto identification=snapshot_.value("identification",Json::object()).value("state","");
   if(identification=="pending"||identification=="running")return "Wait for head identification to finish before saving nozzle settings: identification.state="+rejection_value(identification)+".";
   const auto head=args.value("head","");const auto expected=args.value("expected","");const auto session=snapshot_.value("session","");
   if(head.size()!=2||head[0]!='h'||head[1]<'0'||head[1]>'3'||!snapshot_.value("nozzle_settings",Json::object()).contains(head))return "Physical nozzle is unavailable.";
   if(expected.size()!=64||expected.find_first_not_of("0123456789abcdef")!=std::string::npos||expected!=snapshot_.value("nozzle_revision",""))return "Nozzle settings changed; reopen the editor.";
   if(session.empty()||session.size()>64||session.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")!=std::string::npos)return "Invalid printer session.";
   if(!args.contains("diameter")||!args["diameter"].is_number())return "Invalid nozzle diameter.";
   double diameter=args["diameter"].get<double>();if(diameter!=0.2&&diameter!=0.4&&diameter!=0.6&&diameter!=0.8)return "Unsupported nozzle diameter.";
   const auto material=args.value("material","");if(material!="Hardened steel"&&material!="Stainless steel")return "Unsupported nozzle material.";
   return "";
  }
  if(action=="profile_import"){
   const auto job=snapshot_.value("job",Json::object()).value("state","");
   if(!snapshot_.value("capabilities",Json::object()).value("profile_import",false))return "Profile import capability is unavailable.";
   if(args.value("action","")=="save"&&job!="idle"&&job!="complete")return "Import save requires an idle standalone printer; job.state="+rejection_value(job)+".";
   if(snapshot_.value("profile_import",Json::object()).value("state","")=="busy")return "Import is busy: profile_import.state=busy.";
   const auto stage=args.value("action","");if(stage!="scan"&&stage!="review"&&stage!="save")return "Invalid import action.";
   if(stage!="scan"){const auto value=args.value("value","");if(value.size()!=(stage=="review"?64u:48u)||value.find_first_not_of("0123456789abcdef")!=std::string::npos)return "Invalid import selection.";}
   if(stage=="save"&&snapshot_.value("profile_import",Json::object()).value("token","")!=args.value("value",""))return "Import review changed.";
   return "";
  }
  if(action=="take"||action=="dock"){
   if(!snapshot_.value("capabilities",Json::object()).value("toolhead_action",false))return "Toolhead control is unavailable.";
   const auto job=snapshot_.value("job",Json::object()).value("state","");
   if(job!="idle"&&job!="complete"&&!paused_toolhead_action_available(snapshot_,args.value("head",""),action)){
    const auto fault=snapshot_.value("toolchange_pause",Json::object());
    if(job=="paused"&&fault.is_object()&&fault.contains("manual_toolhead_reason")&&fault["manual_toolhead_reason"].is_string()&&!fault["manual_toolhead_reason"].get<std::string>().empty())return fault["manual_toolhead_reason"].get<std::string>();
    if(job=="paused"){
     const auto permission=snapshot_.value("paused_toolhead_actions",Json::object());
     const auto reason=permission.value("reason","");
     if(!reason.empty())return reason;
     return "Paused toolhead action unavailable: requested="+action+", head="+rejection_value(args.value("head",""))+", allowed="+permission.dump()+".";
    }
    return "Wait until the printer is idle; job.state="+rejection_value(job)+".";
   }
   const auto op=snapshot_.value("toolhead_operation",Json::object()).value("state","");
   if(op=="running"||op=="pending")return "Previous toolhead operation is unresolved: state="+rejection_value(op)+".";
   const auto filament=snapshot_.value("filament_operation",Json::object()).value("state","");
   if(filament=="running"||filament=="pending")return "Filament operation is active.";
   const auto head=args.value("head","");if(head.size()!=2||head[0]!='h'||head[1]<'0'||head[1]>'3')return "Invalid physical head.";
   const auto attachment=snapshot_.value("attachment",Json::object());const auto state=attachment.value("state","");
   if(state!="attached"&&state!="empty")return "Head attachment sensors disagree: attachment.state="+rejection_value(state)+".";
   const auto attached=state=="empty"?"none":attachment.value("head","");
   if(args.value("attached","")!=attached)return "Head attachment changed: reviewed="+rejection_value(args.value("attached",""))+", current="+rejection_value(attached)+".";
   if(action=="dock"&&attached!=head)return "Selected head is not mounted: selected="+rejection_value(head)+", attached="+rejection_value(attached)+".";
   return "";
  }
  if(action=="start_print"){
   try{auto payload=(snapshot_.value("owner","")=="openace"?openace_helper_print_request(snapshot_,args,"wm-4294967295-4294967295-4294967295"):standalone_print_request(snapshot_,args,"wm-4294967295-4294967295-4294967295")).dump();if(payload.size()*2+64>2048)return "Print request exceeds the local transport limit.";}catch(const std::exception&e){return e.what();}return "";
  }
  if(action=="load"||action=="unload"){
   if(!snapshot_.value("capabilities",Json::object()).value(action,false))return "Filament procedure helper is unavailable.";
   auto head=args.value("head","");auto token=args.value("procedure_token","");
   if(head.size()!=2||head[0]!='h'||head[1]<'0'||head[1]>'3'||token.size()!=64||token.find_first_not_of("0123456789abcdef")!=std::string::npos)return "Invalid filament procedure.";
   for(const auto&p:snapshot_.value("procedures",Json::array()))if(p.value("action","")==action&&p.value("head","")==head&&p.value("source","")==args.value("source","")&&p.value("token","")==token&&p.value("revision","")==snapshot_.value("revision",""))return "";
   return "Procedure changed; review the head and temperature before retrying.";
  }
  if(action=="confirm_filament"){
   if(!snapshot_.value("capabilities",Json::object()).value("confirm_filament",false))return "Filament confirmation helper is unavailable.";
   auto job=snapshot_.at("job").value("state","");if(job!="idle"&&job!="complete"&&!paused_filament_for(snapshot_,args.value("head","")))return "Filament checks require idle or the selected paused head; current job="+rejection_value(job)+".";
   auto state=args.value("state","");auto head=args.value("head","");auto session=snapshot_.value("session","");auto revision=snapshot_.value("identity_revision","");
   if((state!="loaded"&&state!="empty")||head.size()!=2||head[0]!='h'||head[1]<'0'||head[1]>'3'||session.empty()||session.size()>64||session.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")!=std::string::npos||revision.size()!=64||revision.find_first_not_of("0123456789abcdef")!=std::string::npos)return "Invalid filament check.";
   for(const auto&h:snapshot_.at("heads"))if(h.at("id")==head)return "";
   return "Physical head is unavailable.";
  }
  if(action=="save_identity") {
   if(!snapshot_.value("capabilities",Json::object()).value("save_identity",false))return "Filament persistence is unavailable.";

   auto revision=snapshot_.value("identity_revision","");if(revision.size()!=64||revision.find_first_not_of("0123456789abcdef")!=std::string::npos)return "Invalid settings revision.";
   if(!args.contains("draft")||!args["draft"].is_object())return "Missing filament settings.";
   const auto&draft=args["draft"];const auto identity=draft.value("identity",Json::object());
   bool cosmetic=false;
   for(const auto&source:snapshot_.value("sources",Json::array()))if(source.value("id","")==draft.value("id","")&&source.value("kind","")=="external"&&source.value("head","")==draft.value("head",""))
    cosmetic=filament_cosmetic_edit(source.value("identity",Json()),identity);
   const auto identification=snapshot_.value("identification",Json::object()).value("state","");
   if(identification=="pending"||identification=="running")return "Wait for head identification to finish before saving filament settings: identification.state="+rejection_value(identification)+".";
   if(!cosmetic&&!filament_identity_editable(snapshot_,draft.value("head","")))return filament_identity_reason(snapshot_,draft.value("head",""));
   const bool recipe_write=filament_recipe_write_allowed(snapshot_,draft.value("head",""));
   if(!cosmetic&&!recipe_write&&paused_filament_for(snapshot_,draft.value("head",""))&&args.value("pause_origin",Json())!=snapshot_["paused_filament"]["origin"])return "Paused edit context changed.";
   if(!cosmetic&&!recipe_write&&args.contains("pause_origin")&&!paused_filament_for(snapshot_,draft.value("head","")))return "Paused edit expired.";

   if(identity.size()<3||identity.size()>8)return "Filament identity field count must be 3..8; current="+std::to_string(identity.size())+".";
   for(auto it=identity.begin();it!=identity.end();++it)if(it.key()!="brand"&&it.key()!="material"&&it.key()!="color"&&it.key()!="appearance"){
    if((it.key()!="nozzle_temp"&&it.key()!="nozzle_temp_min"&&it.key()!="nozzle_temp_max"&&it.key()!="bed_temp")||!it.value().is_number())return "Invalid filament temperature.";
   }
   for(const auto&field:{"brand","material","color"})if(!identity.contains(field)||!identity[field].is_string())return "Filament identity requires text field "+std::string(field)+".";
   for(const auto&field:{"brand","material"}){auto value=identity[field].get<std::string>();if(value.empty()||value.size()>64)return "Filament "+std::string(field)+" length must be 1..64; current="+std::to_string(value.size())+".";for(unsigned char c:value)if(c<32)return "Filament "+std::string(field)+" contains a control character.";}
   if(identity.contains("appearance")){const auto a=identity["appearance"];if(!a.is_string()||(a!="standard"&&a!="translucent"&&a!="gradient"&&a!="co-extrusion"))return "Invalid filament appearance.";}
   auto color=identity["color"].get<std::string>();if(color.size()!=7||color[0]!='#'||color.substr(1).find_first_not_of("0123456789abcdefABCDEF")!=std::string::npos)return "Invalid filament color.";
   for(const auto&source:snapshot_.value("sources",Json::array()))if(source.value("id","")==draft.value("id","")&&source.value("kind","")=="external"&&source.value("head","")==draft.value("head",""))return "";
   return "Unknown external filament source.";
  }
  const std::string field=action=="step"?"mm":"target";
  if(!args.is_object()||!args.contains("head")||!args["head"].is_string()||!args.contains(field)||!args[field].is_number_integer())return "Invalid heater request.";
  auto head=args["head"].get<std::string>();if(head.size()!=2||head[0]!='h'||head[1]<'0'||head[1]>'3')return "Invalid physical head.";
  if(action=="step") {
   if(!snapshot_.value("capabilities",Json::object()).value("step",false))return "Distance-only extrusion backend is not installed.";
   auto job=snapshot_.value("job",Json::object()).value("state","");if(job!="idle"&&job!="complete"&&job!="paused")return "Pause the print before manual extrusion; job.state="+rejection_value(job)+".";
   int mm=args["mm"].get<int>();if(mm==0||mm< -50||mm>50)return "Manual extrusion requires nonzero distance in -50..50 mm; requested="+std::to_string(mm)+".";
   const auto attachment=snapshot_.value("attachment",Json::object());
   if(attachment.value("state","")!="attached"||attachment.value("head","")!=head)return "Take the selected head first: selected="+rejection_value(head)+", attachment.state="+rejection_value(attachment.value("state",""))+", attachment.head="+rejection_value(attachment.value("head",""))+".";
   for(const auto&h:snapshot_.value("heads",Json::array()))if(h.value("id","")==head){if(job=="paused"&&!h.value("active",false))return "Active extruder differs from the mounted head during a paused print.";if(!h.value("can_extrude",false))return "Heat the selected nozzle first: head="+rejection_value(head)+", can_extrude=false.";return "";}
   return "Selected head is unavailable.";
  }
  auto limits=snapshot_.value("heater_limits",Json::object());if(!limits.contains(head))return "This head's heater limits are unavailable.";
  int target=args["target"].get<int>();const auto&limit=limits[head];
  if(target!=0&&(target<limit.at("min").get<double>()||target>limit.at("max").get<double>()))return "Target is outside this heater's configured limits: requested="+std::to_string(target)+", min="+std::to_string(limit.at("min").get<double>())+", max="+std::to_string(limit.at("max").get<double>())+".";
  return "";
 }
};
class NativeBackend : public Backend {
public:
 NativeBackend(OpenAceBackend&ace,StandaloneBackend&wm):ace_(ace),wm_(wm){}
 void owner(std::string value){owner_=std::move(value);}
 std::string unavailable(const std::string&a)const override {return owner_=="standalone"||(owner_=="openace"&&(a=="temperature"||a=="start_print"||a=="unload"||a=="load"))?wm_.unavailable(a):ace_.unavailable(a);}
 Receipt submit(const Request&r)override {return r.owner=="standalone"||(r.owner=="openace"&&(r.action=="temperature"||r.action=="start_print"||r.action=="unload"||r.action=="load"))?wm_.submit(r):ace_.submit(r);}
private:OpenAceBackend&ace_;StandaloneBackend&wm_;std::string owner_;
};
}
