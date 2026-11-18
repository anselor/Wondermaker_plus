// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "case_light_status.hpp"
#include "gui_status_snapshot.hpp"
#include "stock_api.hpp"
#include "../typed_management.hpp"
#include "home_mini.hpp"
#include "bounded_worker.hpp"
#include "http_failure.hpp"
#include "thumbnail.hpp"
#include "file_tools.hpp"
#include "print_context.hpp"
#include "stock_filament_native.hpp"
#include "stock_identity_edit.hpp"
#include "stock_palette.hpp"
#include "stock_picker_lifetime.hpp"
#include "stock_temperature_keypad.hpp"
#include "stock_nozzle_editor.hpp"
#include "stock_colour_picker.hpp"
#include "stock_preview_page.hpp"
#include "stock_usb_preview.hpp"
#include "usb_copy_worker.hpp"
#include "recovery_worker.hpp"
#include "print_cancel_worker.hpp"
#include "probe_editor_worker.hpp"
#include "stock_probe_editor.hpp"
#include "print_cancel_resolution_worker.hpp"
#include "recovery_resolution_worker.hpp"
#include "recovery_retirement_worker.hpp"
#include "stock_recovery_progress.hpp"
#include "stock_text_keyboard_host.hpp"
#include "stock_filament_procedure.hpp"
#include "stock_diagnostics.hpp"
#include "../../openace-compat/screen1113/source/client/screen_diagnostics.hpp"
#include "stock_pause_prompt.hpp"
#include "stock_resume_progress.hpp"
#include "stock_print_preparation.hpp"
#include "stock_calibration_status.hpp"
#include "stock_maintenance_command.hpp"
#include "stock_calibration_flow.hpp"
#include "stock_identification.hpp"
#include "../standalone_backend.hpp"
#include "../../openace-compat/screen1113/source/client/native_management.hpp"
#include <atomic>
#include <mutex>
namespace wmp_ui { namespace native {
class Runtime {
 struct CalibrationBinding {Runtime*owner;std::string session,request,ticket;bool sequenced=false;mutable unsigned sequence=0;
  CalibrationBinding(Runtime*o=nullptr,const std::string&s={},const std::string&r={}):owner(o),session(s),request(r){} };
 static const CalibrationBinding*&calibration_invocation(){static thread_local const CalibrationBinding*value=nullptr;return value;}
 CalibrationBinding calibration_binding_;
 bool calibration_reserved_=false,calibration_queued_=false,calibration_running_=false,calibration_save_sent_=false;

#ifdef WMP_NATIVE_TEST
 friend struct RuntimeReceiptTest;
#endif
public:
 Runtime(wmp_openace::HttpPort&http,wmp_openace::NativeUi&ui,wmp_openace::UiChannel&channel)
  :http_(http),ui_(ui),channel_(channel),worker_(http,channel),legacy_(ui,channel,false),backend_(channel),native_backend_(backend_,standalone_),app_(native_backend_),stock_preview_(app_){
   identification_panel_.back=[this]{if(!identification_blocks_navigation()&&stock_)stock_("system_page");};
   identification_panel_.submit=[this]{submit_identification();};
   calibration_status_.back=[this]{leave_stock_calibration();};
   guide_calibration_status_.back=[this]{
    // Leave the result without declaring setup complete or cancelling motion.
    calibration_flow_=StockCalibrationFlow{};guide_calibration_status_.created(nullptr);
    requested_.store(-1);if(stock_)stock_("main_page");
   };
   pause_prompt_.review=[this](unsigned head){const auto data=stock_snapshot();if(StockPausePrompt::eligible(data)&&paused_filament_for(data,"h"+std::to_string(head)))request_stock_service(head,true);};
   filament_procedure_.submit=[this](FilamentProcedureReview&review){
    auto data=stock_snapshot();
    const auto operation=app_.operation();
    std::string refusal;
    if(!tool_mode_active_&&!ace_mode_active_)refusal="Filament controls are no longer active.";
    else if(tool_mode_active_&&review.physical_head()!="h"+std::to_string(tool_head_))refusal="Selected head changed: reviewed="+rejection_value(review.physical_head())+", current=h"+std::to_string(tool_head_)+".";
    else if(!stock_filament_.visible())refusal="Filament page is no longer visible.";
    else if(!tool_receipt_.empty())refusal="Toolhead request is awaiting a receipt.";
    else if(settings_block_machine())refusal="A settings operation holds the printer.";
    else if(stock_filament_.ace_controls().adoption_unresolved())refusal="Unit adoption is unresolved.";
    else if(operation.value("state","")=="pending"||(data.value("owner","")!="standalone"&&operation.value("state","")=="unknown"))refusal="Printer operation is unresolved: action="+rejection_value(operation.value("action",""))+", state="+rejection_value(operation.value("state",""))+".";
    if(!refusal.empty()){report_rejection("filament procedure",refusal);return Receipt{"","refused",refusal+" Nothing sent."};}
    tool_busy_action_=review.action();tool_busy_head_=review.physical_head();
    try{
     const auto receipt=review.confirm(data,standalone_);
     tool_receipt_=receipt.id;stock_filament_.message(receipt.message);return receipt;
    }catch(...){
     // Retain a real queued/uncertain receipt if staging succeeded. A failure
     // before staging must not create a permanent, unresolvable machine lock.
     tool_receipt_=standalone_.unresolved_request_id();
     stock_filament_.message(tool_receipt_.empty()?"Filament request could not be prepared; nothing sent.":"Filament submission outcome unknown; inspect printer state.");throw;
    }
   };
   mini_.open_filaments=[this](){request(7);};
   filament_procedure_.cancel=[this](const std::string&id){return standalone_.cancel_filament(id);};
   filament_procedure_.recover=[this](const std::string&id){return standalone_.recover_filament(id);};
   filament_procedure_.recover_toolhead=[this](const std::string&id){return standalone_.recover_toolhead(id);};
   nozzle_editor_.submit=[this](const Json&args){const auto data=stock_snapshot();return standalone_.submit({"save_nozzle",data.value("revision",""),data.value("owner",""),args});};
   stock_preview_.closed=[this](){pending_preview_.clear();};
   usb_preview_.copy=[this]{submit_usb_copy();};
   usb_preview_.review=[this](const std::string&path){
    const auto result=usb_worker_?usb_worker_->result(usb_origin_):Json::object();
    if(result.value("state","")!="copied"||result.value("destination","")!=path||!local_preview_)return;
    local_preview_(usb_parent_,path);
   };
   stock_filament_.import_controls().requested=[this](const std::string&action,const std::string&value){
    const auto data=stock_snapshot();return standalone_.submit({"profile_import",data.value("revision",""),data.value("owner",""),{{"action",action},{"value",value}}});
   };
   stock_filament_.material_entry([this](unsigned head){return begin_stock_edit(head,"material");});
   stock_filament_.colour_entry([this](unsigned head){return begin_stock_edit(head,"color");});
   stock_filament_.brand_controls().begin=[this](unsigned head){return begin_stock_edit(head,"brand");};
   stock_filament_.brand_controls().choose=[this](unsigned head,const std::string&value){
    if(!stock_filament_.import_active()&&!filament_procedure_.active()&&head==stock_edit_head_)stock_identity_pick("brand",value);
   };
   stock_filament_.finish_setup=[this](){finish_onboarding();};
   stock_filament_.select_tool=[this](unsigned head){tool_head_=head;if(ace_mode_active_)stock_filament_.ace_mode(true,head);else stock_filament_.tool_mode(true,head);};
   stock_filament_.ace_controls().adopt=[this](const Json&candidate,const Json&context){return submit_adoption(candidate,context);};
   stock_filament_.ace_controls().action=[this](const std::string&id){
    if(id.size()==10&&id.compare(0,9,"toolhead:")==0&&id[9]>='0'&&id[9]<='3')request(1+id[9]-'0');
    else if(id.compare(0,12,"load-source:")==0||id.compare(0,14,"unload-source:")==0){
     const bool unloading=id.compare(0,14,"unload-source:")==0;
     const auto source_id=id.substr(unloading?14:12);const auto data=stock_snapshot();
     auto refuse=[&](const std::string&message,const std::string&detail){
      if(data.value("owner","")!="standalone")return;
      report_rejection(unloading?"overview unload":"overview load","source="+rejection_value(source_id)+"; "+detail);
      filament_refusal_notice_.show(stock_filament_.content(),message);
     };
     if(filament_procedure_.active()){refuse("Close the current filament dialog first.","A filament review or result dialog is already open.");return;}
     if(!tool_receipt_.empty()){
      const auto receipt=data.value("receipts",Json::object()).value(tool_receipt_,Json::object());
      refuse("Waiting for the previous operation result.","Outstanding operation receipt: action="+rejection_value(tool_busy_action_)+", id="+rejection_value(tool_receipt_)+", state="+rejection_value(receipt.value("state","unavailable")));return;
     }
     if(!stock_edit_receipt_.empty()){
      const auto operation=stock_edit_operation_.is_object()?stock_edit_operation_:Json::object();
      const auto receipt=data.value("receipts",Json::object()).value(stock_edit_receipt_,Json::object());
      refuse("Waiting for the previous settings save result.","Outstanding settings receipt: action="+rejection_value(operation.value("action",""))+", id="+rejection_value(stock_edit_receipt_)+", state="+rejection_value(receipt.value("state",operation.value("state","unavailable"))));return;
     }
     Json source;unsigned matches=0;
     for(const auto&item:data.value("sources",Json::array()))if(item.value("id","")==source_id){source=item;++matches;}
     if(matches!=1){refuse("Filament source changed. Select it again.","Selected source match count="+std::to_string(matches)+"; expected exactly one.");return;}
     if(!data.value("fresh",false)){refuse("Waiting for current printer status.","Printer status is not fresh.");return;}
     if(!unloading&&!source.value("available",false)){refuse("This filament source is unavailable.","Selected source available=false; head="+rejection_value(source.value("head","")));return;}
     if(unloading){
      bool loaded=false;Json observed;
      for(const auto&head:data.value("heads",Json::array()))if(head.value("id","")==source.value("head","")){
       observed=head.value("loaded",Json::object());loaded=observed.value("state","")=="loaded"&&observed.value("source","")==source_id;
      }
      if(!loaded){refuse("Loaded filament changed. Check this head.","Loaded source mismatch: head="+rejection_value(source.value("head",""))+", state="+rejection_value(observed.is_object()?observed.value("state",""):"head missing")+", actual_source="+rejection_value(observed.is_object()?observed.value("source",""):"")+", expected_source="+rejection_value(source_id));return;}
     }else if(source.value("kind","")=="external"){stock_filament_.ace_controls().open_load(source_id);return;}
     const bool opened=unloading?filament_procedure_.open(stock_filament_.content(),data,source.value("head",""),"unload"):
      filament_procedure_.open(stock_filament_.content(),data,source.value("head",""),"load",false,source_id);
     if(!opened){
      refuse("Cannot open the filament dialog. Try reopening Filament.",filament_procedure_.open_failure());
      if(!unloading&&data.value("owner","")!="standalone")stock_filament_.message("Loading this slot is unavailable. Check the head's filament state.");
     }
     stock_filament_.interaction_blocked(filament_procedure_.active());
    }
    else if(id=="unit-name")begin_unit_rename();
    else if(id=="unit-save")save_unit_draft();
    else if(id=="remove-confirm")stock_filament_.message("ACE removal is not connected here; nothing removed.");
    else if(id=="source-colour")begin_ace_colour();
    else if(id=="source-save")save_ace_identity();
    else if(id=="adopt-pending")stock_filament_.message("Registration outcome is pending; no repeat request will be sent.");
   };
   stock_filament_.tool_controls().action=[this](const std::string&action){tool_action(action);};
  }
 bool begin_stock_edit(unsigned head,const std::string&field){
    if(stock_filament_.import_active()||filament_procedure_.active())return false;
    update_tool_view();update_stock_edit();
    stock_picker_.retire();
    auto data=stock_snapshot();
    if(!stock_edit_receipt_.empty()){stock_filament_.message("Waiting for the previous settings save confirmation.");return false;}
    if(!stock_identity_.begin(data,"h"+std::to_string(head),field)){
     stock_filament_.message(stock_identity_.reason());return false;
    }
    stock_ace_edit_=false;stock_material_owned_=true;stock_edit_field_=field;stock_edit_head_=head;stock_filament_.message("");return true;
  }
 bool initialize(){
  if(!surface_.initialize())return false;
#if defined(__aarch64__)
  print_context_.bind(reinterpret_cast<volatile unsigned char*>(0x386ee0a),reinterpret_cast<volatile unsigned char*>(0x386ee09),reinterpret_cast<volatile unsigned char*>(0x386ea54));
  standalone_.print_context([this](const Json&o){return print_context_.prepare(o);},[this](const std::string&state){print_context_.settle(state);});
  print_context_ready_=true;
#endif
  return true;
 }
 // May be called by a stock navigation hook. Actual LVGL work stays on timer.
 // The reset worker can run off the GUI thread: enqueue presentation only.
 void request_factory_command_refusal()noexcept{
  try{auto reason=stock_maintenance_reason();if(reason.empty())reason="Factory action context changed before dispatch.";report_rejection("factory action",reason);std::lock_guard<std::mutex>lock(mutex_);factory_command_reason_=reason+" No trigger command was sent.";}
  catch(...){std::lock_guard<std::mutex>lock(mutex_);factory_command_reason_="Factory action could not verify current printer state. No command sent.";}
  factory_command_refused_.store(true);
 }
 void request_factory_reset_refusal()noexcept{report_rejection("factory reset","Factory reset is disabled by WM+ policy; no reset command sent.");factory_reset_refused_.store(true);}
 bool tools_active()const{return tool_mode_active_;}
 void open_tools(){
  unsigned head=tool_head_;
  for(const auto&item:stock_snapshot().value("heads",Json::array())){
   const auto id=item.value("id","");
   if(item.value("mounting","")=="Mounted"&&id.size()==2&&id[0]=='h'&&id[1]>='0'&&id[1]<='3')head=unsigned(id[1]-'0');
  }
  request(int(head)+1);
 }
 void request(int page){
  // Only integrated stock-page routes are accepted. In particular, old request
  // 8 must never revive the prototype's full-screen replacement preview.
  if(page==0||page==7||(page>=1&&page<=4)||(page>=9&&page<=12)){
   auto&d=wmp_openace::screen_diagnostics();d.navigation_page.store(page);d.navigation_at.store(ui_.now_ms());d.navigation_requests.fetch_add(1);
   requested_.store(page);
  }
 }
 // The legacy General nozzle page writes on selection. Standalone navigation
 // must use our draft editor; an unavailable observation never delegates writes.
 void navigation_refused(const std::string&reason){report_rejection("navigation",reason);std::lock_guard<std::mutex>lock(mutex_);maintenance_refusal_=reason;}
 bool nozzle_navigation(const char*name){
  if(!name||std::strcmp(name,"nozzle_type_page")!=0)return false;
  const auto data=stock_snapshot();
  if(!data.value("fresh",false)){navigation_refused("Nozzle settings require current printer status. Refresh and reopen.");return true;}
  if(data.value("owner","")=="openace")return false;
  if(data.value("owner","")!="standalone"){navigation_refused("Nozzle settings are unavailable for owner="+rejection_value(data.value("owner",""))+".");return true;}
  if(active()){navigation_refused("Close the current dialog before opening nozzle settings.");return true;}
  if(settings_block_machine()){navigation_refused("Wait for the current settings write before opening nozzle settings.");return true;}
  const auto settings=data.value("nozzle_settings",Json::object());
  int head=-1;
  const auto mounted=data.value("attachment",Json::object()).value("head","");
  for(int i=0;i<4;++i){const auto id="h"+std::to_string(i);
   if(!settings.contains(id))continue;
   if(head<0)head=i;
   if(id==mounted){head=i;break;}
  }
  if(head>=0)requested_.store(30+head);else report_rejection("nozzle navigation","No physical nozzle settings were advertised.");
  return true;
 }
 // Opens a review only. Machine commands remain behind the shared explicit
 // submission path; stale or superseded navigation is consumed, never replayed.
 void request_stock_service(unsigned head,bool load){
  if(head>=4){report_rejection("filament service","Physical head outside range: head="+std::to_string(head)+", allowed=0..3.");return;}
  if(active()){report_rejection("filament service","Managed UI surface is active.");return;}
  if(!tool_receipt_.empty()){report_rejection("filament service","Toolhead operation is awaiting a receipt: action="+rejection_value(tool_busy_action_));return;}
  if(settings_block_machine()){report_rejection("filament service","Settings operation holds the printer: action="+rejection_value(stock_edit_operation_.value("action","")));return;}
  const auto data=stock_snapshot();
  const auto owner=data.value("owner","");
  if(!data.value("fresh",false)){report_rejection("filament service","Printer status is not fresh.");return;}
  if(owner!="standalone"&&owner!="openace"){report_rejection("filament service","Unsupported control owner="+rejection_value(owner));return;}
  requested_.store(int(20+head+(load?0:4)));
 }
 bool settings_block_machine()const{
  // Filament metadata has its own transaction lifecycle, never a machine lock.
  if(stock_edit_receipt_.empty())return false;
  const auto action=stock_edit_operation_.value("action","");
  const bool metadata=action=="save_identity"||action=="save_unit"||action=="save_nozzle"||action=="profile_import";
  return !stock_edit_receipt_.empty()&&!(stock_edit_operation_.value("id","")==stock_edit_receipt_&&metadata);
 }
 bool stock_calibration_reserved(){std::lock_guard<std::mutex>lock(mutex_);return calibration_reserved_;}
 bool begin_stock_calibration(){
  if(!stock_maintenance_allowed())return false;
  const auto data=stock_snapshot();const auto session=data.value("calibration_session","");
  if(session.size()!=32||session.find_first_not_of("0123456789abcdef")!=std::string::npos){const std::string reason="calibration_session must be 32 lowercase hexadecimal characters.";report_rejection("calibration START",reason);std::lock_guard<std::mutex>lock(mutex_);maintenance_refusal_=reason;return false;}
  const auto ticket=data.value("calibration_ticket_protocol",0)==1?data.value("calibration_next_ticket",""):std::string();
  if(data.value("calibration_ticket_protocol",0)==1&&(ticket.empty()||ticket.size()>256||ticket[0]=='0'||ticket.find_first_not_of("0123456789")!=std::string::npos)){
   const std::string reason="Calibration ticket is unavailable. Wait for current printer status and Start again.";report_rejection("calibration START",reason);std::lock_guard<std::mutex>lock(mutex_);maintenance_refusal_=reason;return false;
  }
  std::random_device random;std::string request;constexpr char hex[]="0123456789abcdef";
  for(unsigned i=0;i<16;++i){const auto value=random()&255;request+=hex[value>>4];request+=hex[value&15];}
  {std::lock_guard<std::mutex>lock(mutex_);if(calibration_reserved_){report_rejection("calibration START","Another calibration worker was reserved before admission completed.");return false;}
   calibration_binding_={this,session,request};calibration_binding_.ticket=ticket;calibration_binding_.sequenced=!ticket.empty()||data.value("calibration_attempt_protocol",0)==1;calibration_reserved_=true;calibration_queued_=calibration_running_=calibration_save_sent_=false;}
  if(data.value("owner","")=="standalone")calibration_flow_=StockCalibrationFlow{};
  calibration_status_.begin(session,request);return true;
 }
 void stock_calibration_enqueued(){std::lock_guard<std::mutex>lock(mutex_);if(calibration_reserved_)calibration_queued_=true;}
 void stock_calibration_enqueue_failed(){std::lock_guard<std::mutex>lock(mutex_);if(!calibration_running_)calibration_reserved_=calibration_queued_=false;}
 void finish_stock_calibration_start(){std::lock_guard<std::mutex>lock(mutex_);if(!calibration_queued_&&!calibration_running_)calibration_reserved_=false;}
 void run_stock_calibration_worker(const std::function<void()>&work){
  CalibrationBinding binding;
  {std::lock_guard<std::mutex>lock(mutex_);if(calibration_reserved_&&calibration_queued_&&!calibration_running_){binding=calibration_binding_;calibration_running_=true;}}
  if(binding.owner!=this)return; // No admitted invocation; never execute a duplicate/unbound task.
  const auto*previous=calibration_invocation();calibration_invocation()=&binding;
  auto finish=[&]{calibration_invocation()=previous;std::lock_guard<std::mutex>lock(mutex_);
   if(binding.owner==this&&binding.request==calibration_binding_.request)calibration_reserved_=calibration_queued_=calibration_running_=false;};
  try{work();}catch(...){finish();throw;}finish();
 }
 std::string stock_calibration_command_for_worker(std::uintptr_t caller,const std::string&command){
  auto wrapped=stock_calibration_command(caller,command);
  const auto*b=calibration_invocation();
  const bool maintenance=caller>=0x4b7558&&caller<=0x4b869c;
  const bool bound=b&&b->owner==this&&!b->request.empty();
  if(maintenance&&bound&&b->sequenced&&wrapped.find("_WMP_CALIBRATION_COMMAND HEX=")==0)
   wrapped+=" SESSION="+b->session+" REQUEST="+b->request+" SEQUENCE="+std::to_string(b->sequence++)+(b->ticket.empty()?std::string():" TICKET="+b->ticket);
  if(caller==0x4b869c&&command=="SAVE_CONFIG"&&b&&b->owner==this&&!b->request.empty()){
   if(!b->sequenced)wrapped+=" SESSION="+b->session+" REQUEST="+b->request;
   std::lock_guard<std::mutex>lock(mutex_);if(b->request==calibration_binding_.request)calibration_save_sent_=true;
  }
  return wrapped;
 }
 void update_stock_calibration(){update_stock_calibration(stock_snapshot());}
 void update_stock_calibration(const Json&snapshot){
  auto data=snapshot;{std::lock_guard<std::mutex>lock(mutex_);data["maintenance_save_requested"]=calibration_save_sent_;}
  calibration_status_.update(data);
 }
 void leave_stock_calibration(){
  // Match the verified vendor result-OK cleanup only after its worker returned.
  // Clearing an active status would strand the worker's status switch loop.
  if(!stock_calibration_reserved()){
   auto*status=reinterpret_cast<std::uint32_t*>(0x385fc18);
#ifndef WMP_NATIVE_TEST
   if(*status==14)*status=0;
#else
   (void)status;
#endif
  }
  calibration_status_.created(nullptr);if(stock_)stock_("auto_check_prepare_page");
 }
 std::string stock_maintenance_reason(){return stock_maintenance_reason(stock_snapshot());}
 std::string stock_maintenance_reason(const Json&data){
  if(stock_calibration_reserved())return "Waiting for the calibration worker to finish.";

  // An open editor, review, file copy or terminal result is UI state, not a
  // machine reservation. Hold only actual queued/unresolved physical requests.
  const auto owner=data.value("owner","");
  auto pending=[&](const Json&r){const auto state=r.value("state","");return r.value("delivery_pending",false)||state=="pending"||state=="running"||state=="printing"||state=="paused"||(owner!="standalone"&&(state=="unknown"||state=="stopped"));};
  if(cancel_worker_&&pending(cancel_worker_->result()))return "Waiting for print cancellation: state="+rejection_value(cancel_worker_->result().value("state",""))+".";
  if(recovery_worker_&&pending(recovery_worker_->result()))return "Waiting for recovery: state="+rejection_value(recovery_worker_->result().value("state",""))+".";
  if(standalone_.machine_request_pending())return "Waiting for the previous printer operation to be confirmed.";
  const auto app_operation=app_.operation();const auto app_action=app_operation.value("action","");
  if(app_action!="save_identity"&&app_action!="save_unit"&&app_action!="save_nozzle"&&app_action!="confirm_filament"&&app_action!="profile_import"&&pending(app_operation))return "Waiting for the previous printer operation to be confirmed.";
  if(!tool_receipt_.empty())return "Waiting for toolhead receipt: action="+rejection_value(tool_busy_action_)+", head="+rejection_value(tool_busy_head_)+".";
  if(settings_block_machine())return "Waiting for settings receipt: action="+rejection_value(stock_edit_operation_.value("action",""))+", state="+rejection_value(stock_edit_operation_.value("state",""))+".";
  if(!data.value("fresh",false))return "Printer status is unavailable or stale. Wait for the printer to reconnect.";
  if(data.value("managed_operation_hold",false))return "Resolve the pending print cancellation or recovery before starting calibration.";
  if(owner!="standalone"&&!data.value("calibration_failed","").empty())return "Calibration stopped: "+data.value("calibration_failed","").substr(0,160)+"\nInspect the printer and restart Klipper before retrying.";
  if(data.value("calibration_active",false))return "A calibration or probe session is active. Finish or abort it before starting another calibration.";
  if(!AceUnitPreview::idle(data))return "Calibration requires an idle printer. Current print state: "+data.value("job",Json::object()).value("state","unknown")+".";
  if(owner!="standalone"&&owner!="openace")return "Calibration requires standalone or openACE ownership; current owner="+rejection_value(owner)+".";
  for(const auto*key:{"filament_operation","toolhead_operation","operation"}){
   const auto op=data.value(key,Json::object());const auto action=op.value("action","");if(std::string(key)=="operation"&&(action=="save_identity"||action=="save_unit"||action=="save_nozzle"||action=="profile_import"))continue;const auto state=op.value("state","");
   if(state=="pending"||state=="running"||(owner!="standalone"&&(state=="unknown"||(state=="failed"&&!op.value("recovered",false)))))return "Resolve the previous "+std::string(key==std::string("filament_operation")?"filament":key==std::string("toolhead_operation")?"toolhead":"printer")+" operation before calibration ("+state+").";
  }
  return {};
 }
 void print_preparation_navigation(const char*name){print_preparation_.navigation(name);}
 bool stock_maintenance_allowed(){return stock_maintenance_reason().empty();}
 void request_maintenance_refusal(){
  auto reason=stock_maintenance_reason();
  if(reason.empty())reason="Printer status changed. Review the printer and retry calibration.";
  report_rejection("maintenance",reason);
  std::lock_guard<std::mutex>lock(mutex_);if(maintenance_refusal_.empty())maintenance_refusal_=std::move(reason);
 }
 void update_identification(){update_identification(stock_snapshot());}
 void update_identification(const Json&data){
  identification_flow_.observe(data);
  const bool allowed=stock_maintenance_reason(data).empty();
  const bool restart=allowed&&identification_flow_.can_restart(data);
  identification_panel_.update(data,identification_flow_.message(data),restart||identification_flow_.can_start(data,allowed),restart,!identification_flow_.blocks_navigation(data));
 }
 bool identification_blocks_navigation(){const auto data=stock_snapshot();identification_flow_.observe(data);return identification_flow_.blocks_navigation(data);}
 void stock_identification_created(void*page,bool setup=false){if(setup)onboarding_=true;identification_panel_.created(page,setup);update_identification();}
 void submit_identification(){
  const auto data=stock_snapshot();identification_flow_.observe(data);std::string command;
  if(stock_maintenance_allowed()&&identification_flow_.restart(data))command="FIRMWARE_RESTART";
  else if(identification_flow_.start(data,stock_maintenance_allowed()))command=identification_flow_.command();
  else return;
  try{if(!calibration_sender_||!calibration_sender_(command))identification_flow_.send_failed();}
  catch(...){identification_flow_.send_failed();}
  update_identification();
 }
 void set_calibration_sender(std::function<bool(const std::string&)> callback){calibration_sender_=std::move(callback);}
 bool calibration_navigation(const char*name){
  if(!StockCalibrationFlow::target(name))return false;
  onboarding_=true; // Protect the marker even if setup fails before the filament page.
  std::random_device random;std::string token;constexpr char hex[]="0123456789abcdef";
  for(unsigned i=0;i<16;++i){const auto value=random()&255;token+=hex[value>>4];token+=hex[value&15];}
  if(calibration_flow_.request(name,token)){
   auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);
   guide_calibration_status_.created(screen,true);
  }
  guide_calibration_status_.update(stock_snapshot(),calibration_flow_.message());
  return true;
 }
 bool reject_action(const char*action,const std::string&why){stock_filament_.message(why);report_rejection(action,why);return false;}
 void begin_onboarding(){onboarding_=true;stock_filament_.onboarding(true);request(7);}
 // The exact stock Files shell call is suppressed while setup is managed;
 // browsing is read-only with respect to the setup-completion marker.
 bool onboarding_active()const{return onboarding_;}
 bool onboarding_file_navigation(const char*){return false;}
 void set_finish_onboarding(std::function<bool()> callback){finish_onboarding_=std::move(callback);}
 bool finish_onboarding(){
  if(!onboarding_)return reject_action("setup FINISH","Setup flow is not active.");
  if(!finish_onboarding_)return reject_action("setup FINISH","Setup completion persistence callback is unavailable.");
  if(!stock_)return reject_action("setup FINISH","Stock navigation callback is unavailable.");
  if(active())return reject_action("setup FINISH","Managed UI surface is active.");
  if(!tool_receipt_.empty())return reject_action("setup FINISH","Toolhead operation is awaiting a receipt.");
  if(!stock_edit_receipt_.empty())return reject_action("setup FINISH","Settings operation is awaiting a receipt.");
  if(stock_filament_.ace_controls().adoption_unresolved())return reject_action("setup FINISH","Unit adoption is unresolved.");
  const auto data=stock_snapshot();
  calibration_flow_.observe(data);
  if(calibration_flow_.blocked())return reject_action("setup FINISH","Setup calibration flow is blocked.");
  if(!data.value("calibration_failed","").empty())return reject_action("setup FINISH","Calibration failure remains: "+rejection_value(data.value("calibration_failed","")));
  if(data.value("calibration_active",false))return reject_action("setup FINISH","Backend calibration_active=true.");
  if(data.value("calibration_session","").empty())return reject_action("setup FINISH","Calibration session is missing.");
  if(!data.value("fresh",false))return reject_action("setup FINISH","Printer status is not fresh.");
  if(!AceUnitPreview::idle(data))return reject_action("setup FINISH","Printer job must be idle or complete; current="+rejection_value(data.value("job",Json::object()).value("state","")));
  for(const auto*key:{"filament_operation","toolhead_operation","operation"}){
   const auto op=data.value(key,Json::object());const auto state=op.value("state","");
   if(state=="pending"||state=="running"||state=="unknown"||(state=="failed"&&!op.value("recovered",false)))return reject_action("setup FINISH",std::string(key)+".state="+rejection_value(state)+", recovered="+std::to_string(op.value("recovered",false)));
  }
  if(!finish_onboarding_()){stock_filament_.message("Could not save setup completion. Try Finish again.");return false;}
  calibration_flow_=StockCalibrationFlow{};guide_calibration_status_.created(nullptr);
  onboarding_=false;requested_.store(-1);stock_filament_.onboarding(false);stock_("main_page");return true;
 }
 // Called after the original stock constructor returns, on the LVGL thread.
 void stock_filament_created(void*page){stock_identity_.cancel();stock_picker_.retire();stock_filament_.created(page);}
 void stock_calibration_created(void*page){
  calibration_status_.created(page);CalibrationBinding binding;
  {std::lock_guard<std::mutex>lock(mutex_);binding=calibration_binding_;}
  if(!binding.request.empty())calibration_status_.begin(binding.session,binding.request);
  update_stock_calibration();
 }
 void stock_about_created(void*page){diagnostics_.created(page);diagnostics_.update(stock_snapshot());}
 void stock_picker_cancel(){
  // ACE colour edits are drafts until Save filament. Closing a reopened
  // picker must not invalidate the earlier draft and leave Save inert.
  if(!stock_ace_edit_)stock_identity_.cancel();
  stock_picker_.retire();
 }
 void stock_picker_opened(void*modal){if(stock_identity_.active()&&stock_edit_field_!="brand"&&!stock_picker_.bind_owned(modal))stock_identity_.cancel();}
 // 0: vendor-owned; 1: consume stale/unbound event; 2: current WM+ modal.
 int stock_picker_gate(void*target)const{return !stock_material_owned_?0:stock_identity_.active()&&stock_picker_.accepts(target)?2:1;}
 void* stock_picker_modal()const{return stock_picker_.modal();}
 bool stock_filament_event(void*event){return stock_filament_.intercept(event);}
 // The original material callback writes the vendor INI immediately. Once
 // this picker belongs to WM+, consume it and use the typed backend instead.
 bool stock_material_pick(const std::string&material){
  return stock_identity_pick("material",material);
 }
 bool stock_colour_pick(unsigned index){
  if(!stock_material_owned_)return false;
  const auto*colour=stock_solid_colour(index);
  if(!colour){if(!stock_ace_edit_)stock_identity_.cancel();stock_filament_.message("Textured colour profiles are not supported yet; choose a solid colour.");return true;}
  if(stock_ace_edit_){
   if(!stock_identity_.active()||stock_edit_field_!="color")return true;
   stock_filament_.ace_controls().colour_draft(stock_identity_.draft().value("id",""),colour);return true;
  }
  return stock_identity_pick("color",colour);
 }
 bool stock_identity_pick(const std::string&field,const std::string&value){
  update_tool_view();update_stock_edit();
  if(!stock_material_owned_)return false;
  if(!stock_edit_receipt_.empty()||!tool_receipt_.empty()){
   stock_identity_.cancel();stock_filament_.message("Waiting for the previous operation confirmation.");return true;
  }
  if(stock_filament_.ace_controls().adoption_unresolved()){
   stock_filament_.message("ACE registration needs confirmation before another change.");return true;
  }
  if(field!=stock_edit_field_)return true;
  if(!stock_identity_.active())return true; // Do not replace a pending receipt on a duplicate click.
  auto data=stock_snapshot();
  if(stock_ace_edit_){
   Json raw;std::int64_t at;{std::lock_guard<std::mutex>lock(mutex_);data=normalized_;raw=raw_;at=at_;}
   if(!data.is_object())data=Json::object();
   data["fresh"]=data.value("fresh",false)&&at>=0&&ui_.now_ms()>=at&&ui_.now_ms()-at<=2000;
   backend_.update(raw,data.value("revision",""),data.value("fresh",false));
  }
  auto receipt=stock_identity_.choose(data,value,stock_ace_edit_?static_cast<Backend&>(backend_):static_cast<Backend&>(filament_settings_));
  {
   stock_edit_operation_={{"id",receipt.id},{"state",receipt.state},{"message",receipt.message},{"owner",data.value("owner","")},{"session",data.value("session","")},{"action","save_identity"},{"arguments",{{"draft",stock_identity_.draft()}}}};
   if(stock_ace_edit_)stock_filament_.ace_controls().colour_result(stock_identity_.draft().value("id",""),receipt.message+(receipt.state=="refused"?" Reopen Colour to review and try again.":""));
  }
  stock_edit_receipt_=receipt.id;stock_filament_.message(receipt.message);
  return true;
 }
 // Called only during bootstrap; this transport never shares the service POST.
 void enable_probe_editor(wmp_openace::HttpPort&transport,wmp_openace::HttpPort&stop){
  if(probe_editor_worker_)throw std::runtime_error("Probe editor worker already configured");
  probe_editor_worker_.reset(new ProbeEditorWorker(transport,&stop));
 }
 void open_probe_editor(){
  auto*page=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);
  probe_editor_created(page,[this]{probe_editor_panel_.dismiss();});
 }
 void probe_editor_created(void*page,std::function<void()> close){
  probe_editor_panel_.close=std::move(close);
  probe_editor_panel_.submit=[this](const std::string&action,const std::string&step){
   probe_editor_action(action,step);probe_editor_panel_.update(probe_editor_delivery());
  };
  probe_editor_panel_.created(page);probe_editor_panel_.update(probe_editor_delivery());
 }
 bool begin_probe_editor(const std::string&request){
  return probe_editor_worker_&&probe_editor_worker_->begin(request,stock_maintenance_allowed());
 }
 bool probe_editor_action(const std::string&action,const std::string&step=""){
  if(action=="START"){
   if(!step.empty())return false;
   std::random_device random;std::string request;const char*hex="0123456789abcdef";
   for(unsigned i=0;i<16;++i){const auto value=random()&255;request+=hex[value>>4];request+=hex[value&15];}
   return begin_probe_editor(request);
  }
  return probe_editor_worker_&&(action=="STOP"?probe_editor_worker_->stop():probe_editor_worker_->act(action,step));
 }
 Json probe_editor_delivery(){return probe_editor_delivery(stock_snapshot());}
 Json probe_editor_delivery(const Json&data){
  auto view=probe_editor_worker_?probe_editor_worker_->result():Json{{"invalidated",true},{"message","Probe editor transport unavailable."}};
  if(view.contains("actions")&&view["actions"].value("START",false)){
   const auto reason=stock_maintenance_reason(data);view["actions"]["START"]=reason.empty();
   if(!reason.empty())view["message"]=reason;
  }
  return view;
 }

 void enable_print_cancel(wmp_openace::HttpPort&transport){
  if(cancel_worker_)throw std::runtime_error("Cancel worker already configured");
  cancel_worker_.reset(new PrintCancelWorker(transport,true));
 }
 // True consumes the stock command, including refusal. Never fall back after
 // an unknown delivery. A freshly confirmed openACE owner keeps its own path.
 void enable_print_cancel_resolution(wmp_openace::HttpPort&transport){
  if(cancel_resolution_worker_)throw std::runtime_error("Cancellation resolution already configured");
  cancel_resolution_worker_.reset(new PrintCancelResolutionWorker(transport));
  cancel_progress_.review_resolution=[this](const std::string&){return cancel_resolution_worker_->review();};
  cancel_progress_.confirm_resolution=[this](const std::string&id){return cancel_resolution_worker_->confirm(id);};
 }
 bool backend_runout_owned(){
  const auto data=stock_snapshot();
  return data.value("fresh",false)&&data.value("owner","")=="standalone"
   &&data.value("filament_runout_protocol",0)==1;
 }
 bool standalone_mapping_owned(){
  const auto data=stock_snapshot();
  return data.value("fresh",false)&&data.value("owner","")=="standalone";
 }
 bool route_print_cancel(){
  if(cancel_worker_&&cancel_worker_->owner()=="openace")return false;
  cancel_refused_.store(!cancel_worker_||!cancel_worker_->request());
  show_cancel_.store(true);return true;
 }
 std::string stopped_job_file(){
  const auto data=stock_snapshot();const auto job=data.value("job",Json::object());
  const auto path=job.value("id","");
  // Stock cancellation clears its browser filename before creating the
  // stopped popup. Only fresh terminal job evidence can replace that filename.
  if(!data.value("fresh",false)||job.value("state","")!="idle"||!preview_path(path))return {};
  return path;
 }
 // Called only during bootstrap, before publishing the runtime pointer.
 void enable_recovery(wmp_openace::HttpPort&command,wmp_openace::HttpPort&stop,wmp_openace::HttpPort&resolution){
  if(recovery_worker_)throw std::runtime_error("Recovery worker already configured");
  recovery_worker_.reset(new RecoveryWorker(command,stop));
  resolution_worker_.reset(new RecoveryResolutionWorker(resolution));
  retirement_worker_.reset(new RecoveryRetirementWorker(resolution));
  recovery_progress_.stop=[this]{return recovery_worker_&&recovery_worker_->stop();};
  recovery_progress_.review_resolution=[this](const std::string&action){return resolution_worker_->review(action);};
  recovery_progress_.confirm_resolution=[this](const std::string&id){return resolution_worker_->confirm(id);};
  recovery_progress_.review_retirement=[this]{
   if(!retirement_worker_->review())return false;
   retirement_view_id_=recovery_display_id_;return true;
  };
  recovery_progress_.confirm_retirement=[this](const std::string&id){return retirement_view_id_==recovery_display_id_&&retirement_worker_->confirm(id);};
  recovery_progress_.refresh_retirement=[this]{return retirement_view_id_==recovery_display_id_&&retirement_worker_->refresh();};
  recovery_progress_.cancel_retirement=[this]{retirement_worker_->cancel_review();retirement_view_id_.clear();};
  recovery_progress_.show_retirement_result=[this]{retirement_view_id_=recovery_display_id_;};
  recovery_progress_.allow_close=[this]{
   if(!native_discard_done_)return true;
   const auto r=retirement_worker_->result();
   // Closing a result is navigation, not cancellation or proof of completion.
   // Only the verified receipt below can acknowledge the vendor prompt.
   finish_native_discard(r);
   retirement_worker_->cancel_review();native_discard_done_=nullptr;
   blocked_recovery_reason_.store(0);retirement_view_id_.clear();return true;
  };
 }
 void native_continue_started(std::function<void()>done){
  native_continue_previous_id_=recovery_worker_?recovery_worker_->result().value("id",""):"";
  native_continue_done_=std::move(done);
 }
 void finish_native_continue(const Json&result,const std::string&owned_id){
  const auto receipt=result.value("receipt",Json::object());
  const auto continuation=receipt.value("continuation",Json::object()).value("state","");
  if(native_continue_done_&&result.value("fresh",false)&&!result.value("id","").empty()
     &&result.value("id","")==owned_id&&result.value("id","")!=native_continue_previous_id_&&receipt.value("state","")=="complete"
     &&(continuation=="started"||continuation=="paused"||continuation=="complete")){
   auto done=std::move(native_continue_done_);native_continue_done_=nullptr;done();
  }
 }
 bool select_recovery(unsigned version,const std::string&file,const std::string&checkpoint,
                      const std::string&checkpoint_hash,const std::string&job_hash){
  if(version!=1)return false;
  if(!recovery_worker_||!recovery_worker_->select_native(version,file,checkpoint,checkpoint_hash,job_hash))return false;
  blocked_recovery_reason_.store(0);
  show_recovery_.store(true);return true;
 }
 void finish_native_discard(const Json&r){
  if(native_discard_done_&&retirement_view_id_==recovery_display_id_&&!retirement_view_id_.empty()
     &&r.value("state","")=="complete"&&r.value("fresh",false)&&!r.value("restored",false)){
   auto done=std::move(native_discard_done_);native_discard_done_=nullptr;done();
  }
 }
 bool native_discard_active()const{return bool(native_discard_done_);}
 bool native_discard_blocks_prompt(){
  // An external LVGL teardown is not DISCARD. Once its presentation is gone,
  // a fresh explicit prompt action must not be trapped by that old UI owner.
  if(native_discard_done_&&!show_recovery_.load()&&!recovery_progress_.active()){
   retirement_worker_->cancel_review();native_discard_done_=nullptr;
   blocked_recovery_reason_.store(0);retirement_view_id_.clear();
  }
  return native_discard_active();
 }
 bool request_native_discard(std::function<void()>done){
  if(native_discard_done_)return true;
  if(!retirement_worker_)return false;
  retirement_view_id_.clear();native_discard_done_=std::move(done);
  blocked_recovery_reason_.store(3);show_recovery_.store(true);return true;
 }
 bool request_recovery_review(unsigned reason){
  if((reason!=1&&reason!=2)||!retirement_worker_||!retirement_worker_->result().value("available",false))return false;
  blocked_recovery_reason_.store(reason);show_recovery_.store(true);return true;
 }
 // Configure once before Runtime is published to GUI/status threads.
 ~Runtime(){
  {std::lock_guard<std::mutex>lock(mutex_);selected_file_.clear();++preview_generation_;}
  for(auto*worker:{preview_worker_.get(),command_worker_.get(),off_worker_.get()})if(worker)worker->request_stop();
  preview_worker_.reset();command_worker_.reset();off_worker_.reset();
 }
 void enable_background(wmp_openace::HttpPort&commands,wmp_openace::HttpPort&preview,wmp_openace::HttpPort&off){
  if(command_worker_)throw std::runtime_error("Background transports already configured");
  command_http_=&commands;preview_http_=&preview;off_http_=&off;
  command_worker_.reset(new BoundedWorker);preview_worker_.reset(new BoundedWorker);off_worker_.reset(new BoundedWorker);
 }
 void enable_usb(wmp_openace::HttpPort&transport,const std::string&root){
  if(usb_worker_)throw std::runtime_error("USB worker already configured");
  usb_root_=root;usb_worker_.reset(new UsbCopyWorker(transport));
 }
 void set_local_preview(std::function<void(void*,const std::string&)>open){local_preview_=std::move(open);}
 bool prepare_usb_preview(const std::string&path){
  if(!usb_worker_||!preview_path(path))return false;
  const auto old=app_.operation();if(stock_snapshot().value("owner","")!="standalone"&&(old.value("state","")=="pending"||old.value("state","")=="unknown"))return false;
  stock_preview_.close();usb_preview_.close();temperature_keypad_.close();text_keyboard_.close();filament_procedure_.close();filament_refusal_notice_.close();stock_picker_.close();native_preview_session_=false;pending_preview_.clear();
  {std::lock_guard<std::mutex>lock(mutex_);selected_file_.clear();}
  usb_path_=path;usb_origin_++;
  usb_error_=Json::object();
  if(!usb_worker_->inspect(usb_origin_,usb_root_,path)){
   usb_error_=usb_worker_->unresolved();
   if(usb_error_.empty())usb_error_={{"state","refused"},{"message","Another USB operation is unresolved. Close this preview and check its destination."}};
   else if(usb_error_.value("state","")!="unknown"){usb_error_["state"]="refused";usb_error_["message"]="A previous copy is still running. Reopen this preview to check it.";}
  }
  return true;
 }
 bool usb_preview_created(const StockPreviewWidgets&widgets){usb_parent_=widgets.page;return usb_preview_.attach(widgets);}
 bool prepare_stock_preview(const std::string&path,bool leveling,bool timelapse,bool available){
  if(!preview_path(path))return false;
  const auto old=app_.operation();if(stock_snapshot().value("owner","")!="standalone"&&(old.value("state","")=="pending"||old.value("state","")=="unknown"))return false;
  usb_preview_.close();
  native_previous_operation_=old.value("id","");
  stock_preview_.close();close();temperature_keypad_.close();text_keyboard_.close();filament_procedure_.close();filament_refusal_notice_.close();stock_picker_.close();
  {std::lock_guard<std::mutex>lock(mutex_);selected_file_=path;++preview_generation_;selected_options_={{"leveling",leveling},{"timelapse",timelapse},{"available",available}};}
  native_preview_session_=true;pending_preview_=path;pending_options_={{"leveling",leveling},{"timelapse",timelapse},{"available",available}};
  app_.print_options(leveling,timelapse,available);app_.loading_preview(path);return true;
 }
 bool stock_preview_created(const StockPreviewWidgets&widgets,const std::string&white){
  if(!native_preview_session_)return false;
  const bool attached=stock_preview_.attach(widgets,white);if(!attached)pending_preview_.clear();return attached;
 }
 bool active()const{return cancel_progress_.active()||recovery_progress_.active()||usb_preview_.active()||stock_preview_.active()||text_keyboard_.active()||filament_procedure_.active()||nozzle_editor_.active();}
 void set_stock_navigation(std::function<void(const char*)> fn){stock_=std::move(fn);}
 void worker_step(std::int64_t now)noexcept {
  auto&diagnostics=wmp_openace::screen_diagnostics();int poll_stage=0;const auto poll_started=ui_.now_ms();
  try {
   channel_.set_management_open(true);
   if(now-last_poll_<700)return;
   last_poll_=now;poll_stage=1;diagnostics.status_polls.fetch_add(1);
   // Object discovery is configuration, not live telemetry. Refresh after
   // schema/ownership changes; retry discovery periodically until a ready
   // helper session binds the configuration. Never renew status here.
   const bool discovered=objects_.empty()||discovery_at_<0||now<discovery_at_||(!discovery_bound_&&now-discovery_at_>=30000);
   if(discovered){
    auto list=Json::parse(http_.get("/printer/objects/list"));auto objects=list.at("result").at("objects");
    if(!objects.is_array()||objects.empty()||objects.size()>1024)throw std::runtime_error("Invalid printer object list");
    for(const auto&object:objects)if(!object.is_string()||object.get<std::string>().size()>256)throw std::runtime_error("Invalid printer object name");
    objects_=std::move(objects);discovery_at_=now;
   }
   const auto&objects=objects_;
   bool present=std::find(objects.begin(),objects.end(),"openace")!=objects.end();
   std::string query="/printer/objects/query?webhooks&print_stats&toolhead=extruder";
   for(const auto&key:{"extruder","extruder1","extruder2","extruder3"})if(std::find(objects.begin(),objects.end(),key)!=objects.end())query+="&"+std::string(key);
   if(std::find(objects.begin(),objects.end(),"wm_material")!=objects.end())query+="&wm_material";
   if(std::find(objects.begin(),objects.end(),"wmp_case_light")!=objects.end())query+="&wmp_case_light=enabled,policy_version";
   for(const auto*door:{"gcode_button Door_button1","gcode_button Door_button2"})
    if(std::find(objects.begin(),objects.end(),door)!=objects.end())query+="&gcode_button%20"+std::string(door+13)+"=state";
   if(!present){
    if(std::find(objects.begin(),objects.end(),"virtual_sdcard")!=objects.end())query+="&virtual_sdcard=is_active";
    if(std::find(objects.begin(),objects.end(),"pause_resume")!=objects.end())query+="&pause_resume=is_paused";
   }
   if(!present&&std::find(objects.begin(),objects.end(),"gcode_macro WMP_EXTRUDER_STEP")!=objects.end())query+="&gcode_macro%20WMP_EXTRUDER_STEP";
   if(std::find(objects.begin(),objects.end(),"wmp_recovery")!=objects.end())query+="&wmp_recovery";
   if(present)query+="&openace=session_id,management,heads,units,default_tool_map,inventory,loaded,devices,blocked_tools,operation,config_revision,job,material_change_prompt,manual_flow,unit_discovery,unit_settings";
   poll_stage=2;const auto query_at=ui_.now_ms();
   auto body=http_.get(query);const auto received_at=ui_.now_ms();
   const auto query_ms=received_at-query_at;if(query_ms>diagnostics.status_query_max_ms.load())diagnostics.status_query_max_ms.store(query_ms);
   poll_stage=3;if(!wmp_openace::ScreenModel::acceptable_payload(body))throw std::runtime_error("Status exceeds bounded reply limit");
   auto status=Json::parse(body).at("result").at("status");Json ace=Json::object();
   if(filament_details_needed_.load()&&status.value("wm_material",Json::object()).value("filament_details_protocol",0)==1){
    const auto details_body=http_.get("/printer/wmp/filament/details");
    if(!wmp_openace::ScreenModel::acceptable_payload(details_body))throw std::runtime_error("Filament details exceed bounded reply limit");
    auto details=Json::parse(details_body).at("result");const auto&base=status.at("wm_material");
    if(!details.is_object()||!details.value("filament_details_ready",false)||details.value("session_id","")!=base.value("session_id","")||details.value("command_generation",-1LL)!=base.value("command_generation",-2LL))throw std::runtime_error("Filament detail context changed");
    status["wm_material"]=std::move(details);
   }
   publish_case_light_status(status,received_at,case_light_status_sink());
   if(present){if(!status.contains("openace")||!status["openace"].is_object())throw std::runtime_error("openACE unavailable");ace=status["openace"];}
   const auto helper=status.value("wm_material",Json::object());
   const auto session=helper.value("session_id",Json()).dump()+"/"+ace.value("session_id",Json()).dump();
   const auto owner=helper.value("afc_metadata",Json::object()).value("owner","");
   const bool session_changed=!discovered&&!discovery_session_.empty()&&session!=discovery_session_;
   if(session_changed&&!present&&owner=="standalone"&&helper.value("session_id",Json()).is_string()&&!helper.value("session_id",std::string()).empty()){
    // A coherent new standalone session is not a failed status response.
    // Retire old command evidence, then rediscover and query once in this poll.
    // The recursive pass always discovers, so it cannot enter this branch again.
    worker_.disconnected();worker_.deliver(now);standalone_.invalidate();filament_settings_.invalidate();
    objects_=Json::array();discovery_at_=-1;discovery_bound_=false;last_poll_=now-700;
    worker_step(now);return;
   }
   if(session_changed||
      (owner=="openace"&&!present)||(owner=="standalone"&&present))
    throw std::runtime_error("Printer ownership changed; rediscover objects");
   discovery_session_=session;
   const auto helper_session=helper.value("session_id",Json());
   discovery_bound_=helper_session.is_string()&&!helper_session.get<std::string>().empty()
    &&status.value("webhooks",Json::object()).value("state","")=="ready";
   if(status.value("webhooks",Json::object()).value("state","")!="ready")objects_=Json::array();
   auto normalized=project(status,ace,present,"wm-screen-process");
   worker_.observe_status(status,received_at);poll_stage=4;
   std::string selected;std::uint64_t generation;{std::lock_guard<std::mutex>lock(mutex_);selected=selected_file_;generation=preview_generation_;}
   if(!selected.empty()){
    std::lock_guard<std::mutex>metadata_lock(mutex_);
    const bool cached=selected==metadata_path_&&generation==metadata_generation_;
    normalized["preview_generation"]=generation;
    project_preview(normalized,selected,cached?metadata_:Json::object(),cached?metadata_error_:"Loading file metadata");
    normalized["capabilities"]["start_print"]=print_context_ready_&&(present?normalized.value("openace_print_start_protocol",0)==1:normalized.value("print_start_protocol",0)==1);
    normalized["files"][0]["thumbnail"]=cached?thumbnail_:Json::object();
    normalized["files"][0]["metadata_loading"]=!cached;
   }
   if(cancel_resolution_worker_)cancel_resolution_worker_->observe(helper,status.value("webhooks",Json::object()).value("state","")=="ready");
   if(cancel_worker_)cancel_worker_->observe(helper,status.value("print_stats",Json::object()),status.value("webhooks",Json::object()).value("state","")=="ready");
   if(recovery_worker_)recovery_worker_->observe(helper,!present&&status.value("webhooks",Json::object()).value("state","")=="ready");
   if(resolution_worker_)resolution_worker_->observe(helper,!present&&status.value("webhooks",Json::object()).value("state","")=="ready");
   if(retirement_worker_)retirement_worker_->observe(helper,!present&&status.value("webhooks",Json::object()).value("state","")=="ready");
   if(probe_editor_worker_)probe_editor_worker_->observe(normalized);
   if(usb_worker_)usb_worker_->observe(normalized);
   standalone_.observe(normalized);filament_settings_.observe(normalized);
   // Publish evidence before any command wait. The original receipt timestamp
   // still expires normally; a slow POST must not hide a newly received status.
   {std::lock_guard<std::mutex>lock(mutex_);
    const auto gap=received_at-at_;if(at_>=0&&gap>diagnostics.status_gap_max_ms.load())diagnostics.status_gap_max_ms.store(gap);
    normalized_=std::move(normalized);raw_=std::move(ace);at_=received_at;++status_publication_;
   }
   diagnostics.status_received_at.store(received_at);
   poll_stage=5;worker_.deliver(received_at);
   poll_stage=6;
   if(command_worker_)command_worker_->submit(0,[this]{standalone_.deliver(*command_http_);filament_settings_.deliver(*command_http_);});
   else{standalone_.deliver(http_);filament_settings_.deliver(http_);}
   // File lookups are background work, never a prerequisite for publishing
   // printer evidence or handling queued commands. Use the result next poll.
   // Recheck selection after command waits/navigation to avoid hidden work.
   {std::lock_guard<std::mutex>lock(mutex_);selected=selected_file_;generation=preview_generation_;}
   if(!selected.empty()){
    bool refresh;{std::lock_guard<std::mutex>lock(mutex_);refresh=selected!=metadata_path_||generation!=metadata_generation_||now-metadata_at_>=5000;}
    if(refresh){auto task=[this,selected,generation,now]{refresh_preview(selected,generation,now);};
     if(preview_worker_)preview_worker_->submit(0,task);else task();}
   }

  }catch(...){
   invalidate_case_light_status(case_light_status_sink());
   // Preserve the same fail-closed path for every exception. Record only a
   // fixed transport category, never exception text from backend responses.
   int failure_kind=int(wmp_openace::HttpFailureKind::Other);bool rediscover=true;
   try{throw;}catch(const wmp_openace::HttpFailure&failure){
    failure_kind=int(failure.kind);
    // A transport failure says nothing about the configured object list. Keep
    // that cache so recovery needs one live query, not discovery plus a query.
    // Admission still fails closed below, and the next response must pass the
    // same session/owner validation before it can become fresh.
    if(poll_stage==2&&(failure.kind==wmp_openace::HttpFailureKind::Deadline||
       failure.kind==wmp_openace::HttpFailureKind::Connection||failure.kind==wmp_openace::HttpFailureKind::Io))rediscover=false;
   }catch(...){}
   diagnostics.status_failure_kind.store(failure_kind);
   diagnostics.status_failure_poll_ms.store(ui_.now_ms()-poll_started);
   if(rediscover){objects_=Json::array();discovery_at_=-1;}
   diagnostics.status_failures.fetch_add(1);diagnostics.status_failure_stage.store(poll_stage);diagnostics.status_failure_at.store(ui_.now_ms());
   // Consume any queued legacy command against disconnected evidence. It must
   // become NotSent now, never wait to dispatch after status returns.
   worker_.disconnected();worker_.deliver(now);standalone_.invalidate();filament_settings_.invalidate();
   if(cancel_resolution_worker_)cancel_resolution_worker_->observe(Json::object(),false);
   if(probe_editor_worker_)probe_editor_worker_->observe(Json{{"fresh",false}});
   if(cancel_worker_)cancel_worker_->observe(Json::object(),Json::object(),false);
   if(recovery_worker_)recovery_worker_->observe(Json::object(),false);
   if(resolution_worker_)resolution_worker_->observe(Json::object(),false);
   if(retirement_worker_)retirement_worker_->observe(Json::object(),false);
   std::lock_guard<std::mutex>lock(mutex_);if(!normalized_.is_object()||normalized_.value("fresh",false)){normalized_["fresh"]=false;++status_publication_;}
  }
 }
 void gui_step()noexcept {
  try {
   filament_details_needed_.store(stock_filament_.visible()||filament_procedure_.visible()||nozzle_editor_.visible());
   std::string maintenance_reason;
   {std::lock_guard<std::mutex>lock(mutex_);maintenance_reason.swap(maintenance_refusal_);}
   if(!maintenance_reason.empty()){
    auto*layer=stock_function<void*(*)(void*)>(lv_disp_get_layer_sys)(nullptr);
    maintenance_notice_.show(layer,maintenance_reason);
   }
   if(factory_reset_refused_.exchange(false)&&!factory_reset_notice_.active()){
    auto*layer=stock_function<void*(*)(void*)>(lv_disp_get_layer_sys)(nullptr);
    factory_reset_notice_.show(layer,"To factory reset, first uninstall WM+ with the installer, then use Factory Reset. No settings or files were changed.");
   }

   if(factory_command_refused_.exchange(false)&&!factory_reset_notice_.active()){
    auto*layer=stock_function<void*(*)(void*)>(lv_disp_get_layer_sys)(nullptr);
    std::string why;{std::lock_guard<std::mutex>lock(mutex_);why.swap(factory_command_reason_);}
    factory_reset_notice_.show(layer,why.empty()?"Factory action context changed; no trigger command was sent.":why);
   }
   if(cancel_worker_){
    auto receipt=cancel_worker_->result();
    if(cancel_refused_.load())receipt={{"id","cancel-refused"},{"state","refused"},{"message",cancel_worker_?cancel_worker_->refusal():"Print cancellation worker is unavailable."},{"fresh",false}};
    const auto resolution=cancel_resolution_worker_?cancel_resolution_worker_->result():Json::object();
    const auto record=resolution.value("cancel",Json::object());
    const bool held=record.value("state","")=="unknown"&&!record.value("id","").empty();
    (void)cancel_progress_.take_external_deletion(); // A dismissed result does not reserve the screen.
    bool show=show_cancel_.exchange(false);
    // A new explicit Stop owns its own result panel. Older saved cancellation
    // records (including stale fallbacks) cannot consume that opening request
    // or overwrite the visible newer identity while status catches up.
    const auto receipt_id=receipt.value("id","");
    const bool showing_newer=!receipt_id.empty()&&receipt_id!=record.value("id","")&&
     (show||cancel_progress_.tracks(receipt_id));
    if(!showing_newer&&resolution.value("available",false)&&(held||(record.value("id","")==cancel_hold_view_.value("id","")
       &&(receipt.value("id","").empty()||receipt.value("id","")==record.value("id","")||cancel_refused_.load())))&&!record.value("id","").empty()){
     const auto key=resolution.value("session","")+":"+record.value("id","");
     // Retain completed cleanup across late snapshots, but never across a new
     // backend session or a different cancellation identity.
     const bool completed=cancel_hold_session_==resolution.value("session","")
      &&cancel_hold_view_.value("state","")=="complete"
      &&cancel_hold_view_.value("id","")==record.value("id","")
      &&cancel_hold_view_.value("session","")==record.value("session","")
      &&cancel_hold_view_.value("file","")==record.value("file","");
     receipt=completed?cancel_hold_view_:record;receipt["fresh"]=true;cancel_hold_view_=receipt;
     cancel_hold_session_=resolution.value("session","");
     if(held&&key!=cancel_hold_shown_){show=true;cancel_hold_shown_=key;}
    }else if(!showing_newer&&!resolution.value("available",false)&&cancel_progress_.tracks(cancel_hold_view_.value("id",""))){
     receipt=cancel_hold_view_;receipt["fresh"]=false;
    }
    auto display=receipt;display["kind"]="print_cancel";display["receipt"]=receipt;
    display["resolution"]=resolution;
    display["resolution_available"]=resolution.value("available",false)&&record.value("id","")==receipt.value("id","");
    if(show){
     if(!cancel_progress_.tracks(display.value("id","")))
      if(!cancel_progress_.open(stock_function<void*(*)(void*)>(lv_disp_get_layer_top)(nullptr),display)&&held)cancel_hold_shown_.clear();
    }
    cancel_progress_.update(display);
    if(cancel_progress_.active()&&cancel_resolution_worker_)cancel_resolution_worker_->auto_review();
   }
   if(recovery_worker_){
    auto result=recovery_worker_->result();const auto resolution=resolution_worker_->result();
    const auto attempt=resolution.value("attempt",Json::object());const auto state=attempt.value("state","");
    bool show=show_recovery_.exchange(false);
    const auto attempt_request=attempt.value("request",Json::object());
    const bool held=state=="unknown"||state=="stopped";
    // Stock warnings clean the shared top layer. That is not an operator CLOSE
    // and must not permanently dismiss an unresolved recovery notice.
    if(recovery_progress_.take_external_deletion()&&held)recovery_hold_shown_.clear();
    const bool retained=!recovery_hold_view_.empty()&&attempt_request==recovery_hold_view_.value("receipt",Json::object()).value("request",Json::object());
    if(resolution.value("available",false)&&(held||retained)){
     const auto key=resolution.value("session","")+":"+attempt_request.value("id","");
     if(held&&key!=recovery_hold_shown_){show=true;recovery_hold_shown_=key;}
     if(!result.value("fresh",false)||result.value("id","").empty()||result.value("receipt",Json::object()).value("request",Json::object())!=attempt_request){
      // A held attempt takes precedence over new selection. After it resolves,
      // retain its final display until a genuinely new recovery is selected.
      if(held||result.value("id","").empty()||!result.value("fresh",false)){
       if(retained&&recovery_hold_view_.value("id","")==key&&recovery_display_terminal(recovery_hold_view_.value("state",""))){
        result=recovery_hold_view_;result["fresh"]=true;
       }else result={{"id",key},{"fresh",true},{"state",recovery_display_state(attempt)},{"receipt",attempt},{"message",attempt.value("error","")}};
       recovery_hold_view_=result;
      }
     }
    }else if(!resolution.value("available",false)&&recovery_progress_.tracks(recovery_hold_view_.value("id",""))){
     result=recovery_hold_view_;result["fresh"]=false;
    }
    result["resolution"]=resolution;
    result["resolution_available"]=resolution.value("available",false)&&attempt.value("request",Json::object())==result.value("receipt",Json::object()).value("request",Json::object());
    const auto retirement=retirement_worker_->result();
    const auto blocked_reason=blocked_recovery_reason_.load();
    if(blocked_reason&&!held){
     result={{"id","blocked_recovery_"+std::to_string(blocked_reason)},
      {"state",blocked_reason==3?"review":"refused"},{"fresh",retirement.value("available",false)},
      {"message",blocked_reason==3?"Review the saved print before discarding recovery. Closing this review keeps the saved print.":blocked_reason==2?"This legacy checkpoint has no managed job record. Recovery cannot continue. Original records are unchanged.":
       "The saved file or checkpoint selection is missing or changed. Recovery cannot continue. Original records are unchanged."}};
    }
    const auto invalid=retirement.value("restore_error","");
    if(!invalid.empty()&&retirement.value("available",false)){
     const auto key="invalid_recovery_"+retirement.value("session","");
     if(recovery_invalid_view_.value("id","")!=key)show=true;
     result={{"id",key},{"state","refused"},{"message",invalid},{"fresh",true}};
     recovery_invalid_view_=result;
    }else if(result.value("id","").empty()&&!recovery_invalid_view_.empty()){
     result=recovery_invalid_view_;result["fresh"]=retirement.value("available",false);
    }
    recovery_display_id_=result.value("id","");
    const bool retire_candidate=blocked_reason==3&&!held&&result.value("receipt",Json::object()).empty();
    if(retire_candidate||(retirement_view_id_==recovery_display_id_&&!retirement_view_id_.empty())){
     result["retirement_mode"]=true;
     if(retirement_view_id_==recovery_display_id_)result["retirement"]=retirement;
     else {
      result["retirement"]={{"available",retirement.value("available",false)}};
      result["retirement_previous"]=retirement.value("available",false)&&retirement.value("restored",false);
     }
    }
    if(show&&!recovery_progress_.tracks(result.value("id",""))){
     auto*top=stock_function<void*(*)(void*)>(lv_disp_get_layer_top)(nullptr);
     // Startup can publish the hold before LVGL has sized its overlay. A
     // failed presentation must not consume the one-time restored-hold notice.
     if(!recovery_progress_.open(top,result)&&held)recovery_hold_shown_.clear();
    }
    const bool was_active=recovery_progress_.active();
    if(was_active&&result.value("retirement_mode",false)&&retirement_worker_->auto_read())
     retirement_view_id_=recovery_display_id_;
    if(was_active&&!result.value("retirement_mode",false)&&result.value("resolution_available",false))
     resolution_worker_->auto_read();
    recovery_progress_.update(result);
    // Stock startup changes the active screen after initialization. The panel
    // closes on that transition; present the unresolved hold on the new screen.
    // An explicit CLOSE happened before this tick and must stay closed.
    if(was_active&&!recovery_progress_.active()&&held)recovery_hold_shown_.clear();
    finish_native_continue(result,recovery_worker_->result().value("id",""));
    finish_native_discard(retirement);
   }
   {std::string message;{std::lock_guard<std::mutex>lock(mutex_);message.swap(off_message_);}if(!message.empty())stock_filament_.message(message);}
   const auto&gui_data=gui_snapshot();
   auto snapshot=channel_.latest();int req=requested_.exchange(-1);
   const std::string service_action=req>=30&&req<=33?"nozzle":req>=20&&req<=27?(req<24?"load":"unload"):"";
   if(service_action=="nozzle"){
    nozzle_editor_.update(gui_data);
    auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(stock_function<void*(*)()>(lv_disp_get_default)());
    nozzle_editor_.show(screen,unsigned(req-30));
    return;
   }
   else if(!service_action.empty())req=1+(req-20)%4;
   // The shared backend publishes its latest receipt. Consume both UI owners'
   // terminal results even while their views are hidden, before another action
   // can replace that receipt.
   diagnostics_.update(gui_data);
   probe_editor_panel_.update(probe_editor_delivery(gui_data));
   if(probe_editor_worker_&&probe_editor_panel_.visible())probe_editor_worker_->auto_review();
   if(gui_status_.changed()||req>=0||calibration_flow_.blocked()){
   update_tool_view(gui_data);update_stock_edit(gui_data);
   update_stock_calibration(gui_data);
   update_identification(gui_data);
   const auto&calibration_data=gui_data;calibration_flow_.observe(calibration_data);
   if(calibration_flow_.needs_checkpoint(calibration_data)){
    calibration_flow_.sent(calibration_data);
    try{if(!calibration_sender_||!calibration_sender_(calibration_flow_.command()))calibration_flow_.send_failed();}
    catch(...){calibration_flow_.send_failed();}
   }
   const auto calibration_destination=calibration_flow_.complete(calibration_data);
   guide_calibration_status_.update(calibration_data,calibration_flow_.message());
   if(!calibration_destination.empty()){
    if(calibration_destination!="guide_calibrating_page")begin_onboarding();
    else if(stock_)stock_(calibration_destination.c_str());
   }
   resume_progress_.update(gui_data);
   print_preparation_.update(gui_data);
   pause_prompt_.update(gui_data,req<0&&!active()&&!onboarding_&&tool_receipt_.empty()&&stock_edit_receipt_.empty()&&!stock_identity_.active());
   }
   if(req>=0){usb_preview_.close();stock_preview_.close();if(native_preview_session_)pending_preview_.clear();}
   update_usb_preview();update_stock_preview();
   bool status_fresh=false,standalone_fresh=false,ace_fresh=false,standalone_known=false;
   {std::lock_guard<std::mutex>lock(mutex_);status_fresh=normalized_.is_object()&&normalized_.value("fresh",false)&&at_>=0&&ui_.now_ms()>=at_&&ui_.now_ms()-at_<=2000;
    standalone_known=at_>=0&&normalized_.value("owner","")=="standalone";
    standalone_fresh=status_fresh&&standalone_known;ace_fresh=status_fresh&&normalized_.value("owner","")=="openace";}
   // Recompose only the visible Filament page after a definitive ownership
   // change. Unknown/stale observations never imply openACE removal, and a
   // background status update must not navigate away from another stock page.
   if(req<0&&!tool_mode_active_&&stock_filament_.visible()&&
      (standalone_fresh||ace_fresh)&&filament_owner_openace_!=ace_fresh){
    stock_identity_.cancel();stock_picker_.close();temperature_keypad_.close();req=7;
   }
   // Both Filament modes use the stock constructor and head-card objects.
   // Identity editors retain the same stock Filament shell.
   // Do not turn a missing/stale observation into a replacement-screen fallback
   // or guess standalone ownership. Keep the current page; no delayed replay.
   if((req==7||(req>=1&&req<=4)||(req>=9&&req<=12))&&!status_fresh&&!standalone_known&&!(req==7&&onboarding_)){
    wmp_openace::screen_diagnostics().navigation_stale.fetch_add(1);navigation_refused("Printer status is unavailable; reconnect and reopen this page. No action was queued.");return;
   }
   if(req==7&&!standalone_known&&!ace_fresh&&!onboarding_){wmp_openace::screen_diagnostics().navigation_owner.fetch_add(1);navigation_refused("Printer control owner is unavailable; refresh before opening Filaments.");return;}
   if(!stock_filament_.visible())filament_refusal_notice_.close();
   if(req>=0){filament_refusal_notice_.close();temperature_keypad_.close();text_keyboard_.close();filament_procedure_.close();nozzle_editor_.close();}
   if(req==7){filament_owner_openace_=ace_fresh;ace_mode_active_=false;tool_mode_active_=false;stock_filament_.tool_mode(false);}
   if(req>=1&&req<=4){
    if(!stock_)return;
    tool_head_=unsigned(req-1);ace_mode_active_=false;tool_mode_active_=true;
    legacy_.management().deactivate();legacy_.material().deactivate();close();
    stock_filament_.tool_mode(true,tool_head_);stock_filament_.tool_data(gui_data,tool_step_,tool_targets_[tool_head_]);
    stock_("filament_page");stock_filament_.tick(true,true);
    if(!service_action.empty())tool_action(service_action);
    return;
   }
   if(req>=9&&req<=12){
    if(!standalone_fresh&&!ace_fresh)return;
    bool head_exists=false;for(const auto&head:gui_data.value("heads",Json::array()))
     if(head.value("id","")=="h"+std::to_string(req-9))head_exists=true;
    if(!head_exists){stock_filament_.message("This head is no longer configured.");return;}
    if(!stock_)return;
    legacy_.management().deactivate();legacy_.material().deactivate();
    if(ace_fresh||standalone_fresh){
     tool_head_=unsigned(req-9);tool_mode_active_=false;ace_mode_active_=true;
     stock_filament_.tool_mode(false);stock_filament_.identity_head(-1);
     stock_filament_.ace_mode(true,tool_head_);
     close();stock_("filament_page");stock_filament_.tick(true,true);
     if(!stock_filament_.ace_controls().open_head_identity("h"+std::to_string(tool_head_)))
      stock_filament_.message("Select a filament slot to edit for this head.");
     if(pending_external_load_=="h"+std::to_string(tool_head_)){stock_filament_.ace_controls().open_load("external:"+pending_external_load_);pending_external_load_.clear();}
     stock_filament_.ace_controls().source_origin(tool_head_);
     stock_filament_.tick(true,true);return;
    }
    ace_mode_active_=false;
    tool_mode_active_=false;stock_filament_.tool_mode(false);stock_filament_.identity_head(req-9);
    close();stock_("filament_page");stock_filament_.tick(true,true);return;
   }
   if(req==7){
    if(!stock_)return;
    legacy_.management().deactivate();legacy_.material().deactivate();
    tool_mode_active_=false;stock_filament_.tool_mode(false);
    ace_mode_active_=onboarding_||ace_fresh||standalone_fresh;stock_filament_.identity_head(-1);
    stock_filament_.ace_mode(ace_mode_active_,tool_head_);close();stock_("filament_page");stock_filament_.tick(true,true);return;
   }
   if(tool_mode_active_||ace_mode_active_)stock_filament_.tick(status_fresh,true);
   else stock_filament_.tick(standalone_fresh,standalone_fresh);
   if(req==0){close();return;}
   update_home(gui_data,gui_status_.changed());
   // Stock constructors/content adapters own all WM+ navigation. Retain the
   // installed recovery integration, but never create the prototype shell.
   if(snapshot)legacy_.tick(*snapshot);
  }catch(...){surface_.hide();}

 }
private:
 StockDiagnostics diagnostics_;
 StockPausePrompt pause_prompt_;
 StockResumeProgress resume_progress_;
 std::unique_ptr<RecoveryResolutionWorker>resolution_worker_;std::string recovery_hold_shown_;Json recovery_hold_view_=Json::object();
 std::unique_ptr<RecoveryRetirementWorker>retirement_worker_;std::string retirement_view_id_,recovery_display_id_;Json recovery_invalid_view_=Json::object();
 std::atomic<unsigned>blocked_recovery_reason_{0};
 std::function<void()>native_continue_done_;std::string native_continue_previous_id_;
 std::function<void()>native_discard_done_; // GUI-thread-only popup ownership
 std::unique_ptr<PrintCancelResolutionWorker>cancel_resolution_worker_;std::string cancel_hold_shown_,cancel_hold_session_;Json cancel_hold_view_=Json::object();
 StockProbeEditor probe_editor_panel_;
 std::unique_ptr<ProbeEditorWorker>probe_editor_worker_;
 std::unique_ptr<PrintCancelWorker>cancel_worker_;StockRecoveryProgress cancel_progress_;std::atomic<bool>show_cancel_{false},cancel_refused_{false};
 std::unique_ptr<RecoveryWorker>recovery_worker_;StockRecoveryProgress recovery_progress_;std::atomic<bool>show_recovery_{false};
 StockCalibrationStatus calibration_status_,guide_calibration_status_;
 StockPrintPreparation print_preparation_;
 StockIdentification identification_panel_;StockIdentificationFlow identification_flow_;
 StockCalibrationFlow calibration_flow_;std::function<bool(const std::string&)>calibration_sender_;
 bool onboarding_=false;std::function<bool()>finish_onboarding_;
 bool filament_owner_openace_=false;std::string pending_external_load_;
 wmp_openace::HttpPort&http_;wmp_openace::NativeUi&ui_;wmp_openace::UiChannel&channel_;
 wmp_openace::ScreenWorker worker_;wmp_openace::NativeScreen legacy_;OpenAceBackend backend_;StandaloneBackend standalone_,filament_settings_;NativeBackend native_backend_;App app_;LvglSurface surface_;HomeMini mini_;PrintContext print_context_;bool print_context_ready_=false;
 StockTextKeyboardHost text_keyboard_;
 std::unique_ptr<UsbCopyWorker>usb_worker_;StockUsbPreview usb_preview_;std::string usb_root_,usb_path_;std::uint64_t usb_origin_=0;void*usb_parent_=nullptr;
 Json usb_error_=Json::object();std::function<void(void*,const std::string&)>local_preview_;
 StockPreviewPage stock_preview_;bool native_preview_session_=false;std::string native_previous_operation_;
 StockFilamentNative stock_filament_;StockTemperatureKeypad temperature_keypad_;StockFilamentProcedure filament_procedure_;StockNozzleEditor nozzle_editor_;
 StockIdentityEdit stock_identity_;Json stock_edit_operation_;bool stock_ace_edit_=false,stock_material_owned_=false;std::string stock_edit_receipt_,stock_edit_field_;unsigned stock_edit_head_=4;
 StockPickerLifetime stock_picker_;
 bool ace_mode_active_=false,tool_mode_active_=false;unsigned tool_head_=0;int tool_step_=10;std::array<int,4>tool_targets_{{220,220,220,220}};std::string tool_receipt_,tool_busy_action_,tool_busy_head_;
 StockNotice filament_refusal_notice_;
 StockNotice maintenance_notice_;std::string maintenance_refusal_,factory_command_reason_;
 StockNotice factory_reset_notice_;std::atomic<bool>factory_reset_refused_{false},factory_command_refused_{false};
 std::atomic<int>requested_{-1};std::function<void(const char*)>stock_;
 GuiStatusSnapshot gui_status_; // GUI-only; backend publication remains under mutex_.
 std::mutex mutex_;Json normalized_,raw_,objects_=Json::array();std::atomic<bool>filament_details_needed_{false};std::uint64_t status_publication_=0;std::string discovery_session_;bool discovery_bound_=false;std::int64_t discovery_at_=-1,at_=-1,last_poll_=-1000;
 // Selection generation is protected by mutex_; metadata generation belongs to the worker.
 std::string off_message_;
 std::unique_ptr<BoundedWorker> command_worker_,preview_worker_,off_worker_;
 wmp_openace::HttpPort *command_http_=nullptr,*preview_http_=nullptr,*off_http_=nullptr;
 void refresh_preview(const std::string&selected,std::uint64_t generation,std::int64_t now){
  {std::lock_guard<std::mutex>lock(mutex_);if(selected!=selected_file_||generation!=preview_generation_)return;
   if(selected==metadata_path_&&generation==metadata_generation_&&now-metadata_at_<5000)return;}
  auto&transport=preview_http_?*preview_http_:http_;Json metadata=Json::object(),thumbnail=Json::object();std::string error,root;
  bool inspect=false;{std::lock_guard<std::mutex>lock(mutex_);inspect=normalized_.value("owner","")=="standalone"&&normalized_.value("print_material_confirmation_protocol",0)==1;}
  try{auto reply=transport.get(metadata_query(selected));if(!wmp_openace::ScreenModel::acceptable_payload(reply))throw std::runtime_error("Status reply is too large");metadata=Json::parse(reply).at("result");(void)preview_file(selected,metadata,"",true);}
  catch(...){error="File metadata unavailable";}
  try{auto roots=Json::parse(transport.get("/server/files/roots")).at("result");if(roots.is_array()&&roots.size()<32)for(const auto&entry:roots)if(entry.value("name","")=="gcodes")root=entry.at("path").get<std::string>();}catch(...){}
  if(inspect){
   bool missing=!error.empty();if(!missing)try{auto file=preview_file(selected,metadata,"",true);auto identity=file.value("file_identity",Json::object());missing=file.value("sliced",Json::array()).empty()||!identity.value("size",Json()).is_number_integer()||!identity.value("modified",Json()).is_number();}catch(...){missing=true;}
   if(missing)try{if(root.empty())throw std::runtime_error("G-code directory unavailable; reopen this file after reconnecting");
    metadata=inspect_file_tools(root,selected,[this,selected,generation]{std::lock_guard<std::mutex>lock(mutex_);return selected==selected_file_&&generation==preview_generation_;},inspected_metadata_);inspected_metadata_=metadata;error.clear();
   }catch(const std::exception&e){error=std::string(e.what())+". Review or reslice this file, then reopen it.";}
  }
  if(error.empty()&&!root.empty())try{thumbnail=thumbnails_.load(root,selected,metadata);}catch(...){}

  std::lock_guard<std::mutex>lock(mutex_);if(selected!=selected_file_||generation!=preview_generation_)return;
  metadata_path_=selected;metadata_generation_=generation;metadata_at_=now;metadata_=std::move(metadata);metadata_error_=error;thumbnail_=std::move(thumbnail);
 }
 Json inspected_metadata_; // Preview-worker-only cache; reread only after a file stat change.
 std::uint64_t preview_generation_=0,metadata_generation_=0;
 std::string selected_file_,pending_preview_,metadata_path_,metadata_error_;Json metadata_,selected_options_,pending_options_;std::int64_t metadata_at_=-10000;ThumbnailCache thumbnails_;Json thumbnail_;
 const Json&gui_snapshot(){
  std::lock_guard<std::mutex>lock(mutex_);return gui_status_.observe(normalized_,at_,ui_.now_ms(),status_publication_);
 }
 Json stock_snapshot(){
  std::lock_guard<std::mutex>lock(mutex_);auto data=normalized_;
  if(!data.is_object())return Json::object();
  const auto now=ui_.now_ms(),age=at_>=0&&now>=at_?now-at_:-1;
  data["status_age_ms"]=age;
  data["display_fresh"]=age>=0&&age<=4000&&data.value("printer_state","")=="ready";
  data["fresh"]=data.value("fresh",false)&&age>=0&&age<=2000;
  return data;
 }
 void submit_usb_copy()try{
  if(!usb_worker_||!usb_preview_.active())return;
  const auto data=stock_snapshot(),source=usb_worker_->result(usb_origin_);
  if(source.value("state","")!="ready")return;
  std::random_device random;std::string nonce;const char*hex="0123456789abcdef";
  for(unsigned n=0;n<16;++n){auto value=random()&255;nonce+=hex[value>>4];nonce+=hex[value&15];}
  if(!usb_worker_->submit(usb_origin_,data,usb_path_,nonce,source.at("size").get<std::int64_t>()))usb_error_={{"state","refused"},{"message","Copy was not queued. Close this preview and select the USB file again."}};
 }
 catch(...){usb_error_={{"state","refused"},{"message","Copy could not be queued. Close and reopen this preview."}};}
 void update_usb_preview(){
  if(!usb_worker_||!usb_preview_.active())return;
  const auto result=usb_error_.empty()?usb_worker_->result(usb_origin_):usb_error_;
  const auto state=result.value("state","");
  usb_preview_.update(result,state=="ready"||state=="copied");
 }
 void update_stock_preview(){
  if(!native_preview_session_)return;
  // A closed preview only retains ownership while its submission receipt is
  // unresolved. Otherwise it must stop updating the shared controller behind
  // subsequent stock pages or another workflow.
  const auto previous=app_.operation();
  if(!stock_preview_.active()&&previous.value("state","")!="pending"&&previous.value("state","")!="unknown"){
   native_preview_session_=false;pending_preview_.clear();
   // Retire worker-side file polling too. Otherwise a closed preview keeps
   // issuing metadata/roots requests every five seconds during head control.
   {std::lock_guard<std::mutex>lock(mutex_);selected_file_.clear();}
   return;
  }
  Json data,raw;std::int64_t at;{std::lock_guard<std::mutex>lock(mutex_);data=normalized_;raw=raw_;at=at_;}
  if(!data.is_object())return;
  // A same-file reopening is a new review, including when an old lookup was
  // still in flight. Do not let its cached rows seed the new mapping.
  if(data.value("preview_generation",std::uint64_t(0))!=preview_generation_)return;
  const bool fresh=data.value("fresh",false)&&at>=0&&ui_.now_ms()>=at&&ui_.now_ms()-at<=2000;data["fresh"]=fresh;
  native_backend_.owner(data.value("owner","unknown"));backend_.update(raw,data.value("revision",""),fresh);
  reconcile(data,channel_.latest());app_.update(data);
  if(stock_preview_.active()&&!pending_preview_.empty())for(const auto&file:data.value("files",Json::array()))if(file.value("id","")==pending_preview_&&!file.value("metadata_loading",false)){
   app_.event("file:"+pending_preview_);pending_preview_.clear();break;
  }
  const auto op=app_.operation();
  if(op.value("id","")!=native_previous_operation_&&op.value("action","")=="start_print"&&op.value("state","")=="complete"){stock_preview_.close();pending_preview_.clear();}
  else stock_preview_.tick();
 }
 void save_ace_identity(){
  update_tool_view();update_stock_edit();auto&view=stock_filament_.ace_controls();
  const auto op=app_.operation();
  if(!ace_mode_active_){reject_action("filament SAVE","ACE filament controls are not active.");return;}
  if(!stock_filament_.visible()){reject_action("filament SAVE","Filament page is not visible.");return;}
  if(!view.identity_ready()){reject_action("filament SAVE",view.identity_reason());return;}
  if(!stock_edit_receipt_.empty()){reject_action("filament SAVE","Settings receipt is pending.");return;}
  if(!tool_receipt_.empty()){reject_action("filament SAVE","Toolhead receipt is pending.");return;}
  if(view.adoption_unresolved()){reject_action("filament SAVE","Unit adoption is unresolved.");return;}
  if(op.value("state","")=="pending"||op.value("state","")=="unknown"){reject_action("filament SAVE","Printer operation is unresolved: state="+rejection_value(op.value("state","")));return;}
  Json data,raw;std::int64_t at;{std::lock_guard<std::mutex>lock(mutex_);data=normalized_;raw=raw_;at=at_;}
  if(!data.is_object()){reject_action("filament SAVE","Printer status object is unavailable.");return;}
  data["fresh"]=data.value("fresh",false)&&at>=0&&ui_.now_ms()>=at&&ui_.now_ms()-at<=2000;
  const auto context=view.selected_source_context();const auto source=view.selected_source();
  if(!filament_source_edit_context_matches(data,context,source)){reject_action("filament SAVE","Filament source or editing context changed since editor entry.");return;}
  if(!stock_identity_.begin_source(data,source.value("id",""),"brand")){reject_action("filament SAVE",stock_identity_.reason());return;}
  backend_.update(raw,data.value("revision",""),data.value("fresh",false));
  auto fields=view.draft_identity();for(auto it=fields.begin();it!=fields.end();)if(it.key()!="brand"&&it.key()!="material"&&it.key()!="color"&&(data.value("owner","")!="standalone"||(it.key()!="nozzle_temp"&&it.key()!="nozzle_temp_min"&&it.key()!="nozzle_temp_max"&&it.key()!="bed_temp")))it=fields.erase(it);else ++it;
  const auto receipt=stock_identity_.choose_fields(data,fields,data.value("owner","")=="standalone"?static_cast<Backend&>(filament_settings_):static_cast<Backend&>(backend_));
  const bool load_after_save=view.loading();
  stock_ace_edit_=true;
  stock_edit_operation_={{"id",receipt.id},{"state",receipt.state},{"message",receipt.message},{"owner",data.value("owner","")},{"session",data.value("session","")},{"action","save_identity"},{"arguments",{{"draft",stock_identity_.draft()}}}};
  stock_edit_operation_["load_after_save"]=load_after_save;
  stock_edit_operation_["load_context"]={{"job",data.value("job",Json::object())},{"paused_filament",data.value("paused_filament",Json::object())}};
  stock_edit_receipt_=receipt.id;view.colour_result(source.value("id",""),receipt.message);view.identity_pending(receipt.state=="pending"||receipt.state=="unknown");stock_filament_.message(receipt.message);
 }
 void begin_ace_colour(){
  update_tool_view();update_stock_edit();auto data=stock_snapshot();
  if(stock_filament_.ace_controls().adoption_unresolved()){stock_filament_.message("ACE registration needs confirmation before another change.");return;}
  const auto source=stock_filament_.ace_controls().selected_source();const auto context=stock_filament_.ace_controls().selected_source_context();
  if(!source.is_object()){reject_action("filament COLOUR","Filament source draft is missing.");return;}
  if(!stock_filament_.visible()){reject_action("filament COLOUR","Filament page is not visible.");return;}
  if(!stock_edit_receipt_.empty()){reject_action("filament COLOUR","Settings receipt is pending.");return;}
  if(!tool_receipt_.empty()){reject_action("filament COLOUR","Toolhead receipt is pending.");return;}
  for(const auto*key:{"owner","session","revision","identity_revision"})if(data.value(key,"")!=context.value(key,"")){reject_action("filament COLOUR",std::string(key)+" changed since editor entry.");return;}
  bool exact=false;for(const auto&s:data.value("sources",Json::array()))if(s==source)exact=true;
  if(!exact){reject_action("filament COLOUR","Reviewed filament source changed.");return;}
  if(!stock_identity_.begin_source(data,source.value("id",""),"color")){reject_action("filament COLOUR",stock_identity_.reason());return;}
  stock_picker_.close();stock_ace_edit_=true;stock_material_owned_=true;stock_edit_field_="color";
  auto colour=stock_filament_.ace_controls().draft_colour();if(colour.empty())colour=identity_display_text(source.value("identity",Json::object()),"color","");
  auto*modal=open_stock_colour_picker(stock_filament_.page(),stock_colour_index(colour));
  stock_picker_opened(modal);
  if(!stock_picker_.modal()){stock_identity_.cancel();stock_filament_.message("Stock colour picker could not be opened.");}
 }
 void save_unit_draft(){
  update_tool_view();update_stock_edit();
  auto&view=stock_filament_.ace_controls();
  if(!ace_mode_active_){reject_action("unit SAVE","ACE controls are not active.");return;}
  if(!stock_filament_.visible()){reject_action("unit SAVE","Filament page is not visible.");return;}
  const auto operation=app_.operation();
  if(!stock_edit_receipt_.empty()){reject_action("unit SAVE","Settings receipt is pending.");return;}
  if(!tool_receipt_.empty()){reject_action("unit SAVE","Toolhead receipt is pending.");return;}
  if(view.adoption_unresolved()){reject_action("unit SAVE","Unit adoption is unresolved.");return;}
  if(operation.value("state","")=="pending"||operation.value("state","")=="unknown"){reject_action("unit SAVE","Printer operation is unresolved: state="+rejection_value(operation.value("state","")));return;}
  Json data,raw;std::int64_t at;
  {std::lock_guard<std::mutex>lock(mutex_);data=normalized_;raw=raw_;at=at_;}
  if(!data.is_object()){reject_action("unit SAVE","Printer status object is unavailable.");return;}
  data["fresh"]=data.value("fresh",false)&&at>=0&&ui_.now_ms()>=at&&ui_.now_ms()-at<=2000;
  if(!view.unit_draft_valid(data)){reject_action("unit SAVE",view.unit_draft_reason(data));return;}
  const auto draft=view.unit_draft();
  backend_.update(raw,data.value("revision",""),data.value("fresh",false));
  const auto receipt=backend_.submit({"save_unit",data.value("revision",""),"openace",{{"draft",draft}}});
  stock_filament_.message(receipt.message);
  if(receipt.state!="pending"||receipt.id.empty())return;
  stock_ace_edit_=true;
  stock_edit_operation_={{"id",receipt.id},{"state",receipt.state},{"message",receipt.message},{"owner","openace"},{"session",data.value("session","")},{"action","save_unit"},{"arguments",{{"draft",draft}}}};
  stock_edit_receipt_=receipt.id;
 }
 void begin_unit_rename(){
  update_tool_view();update_stock_edit();const auto captured=stock_snapshot();
  const auto draft=stock_filament_.ace_controls().unit_draft();const auto operation=app_.operation();
  if(!ace_mode_active_){reject_action("unit RENAME","ACE controls are not active.");return;}
  if(!stock_filament_.visible()){reject_action("unit RENAME","Filament page is not visible.");return;}
  if(!draft.is_object()){reject_action("unit RENAME","Unit draft is missing.");return;}
  if(!captured.value("fresh",false)){reject_action("unit RENAME","Printer status is not fresh.");return;}
  if(captured.value("owner","")!="openace"){reject_action("unit RENAME","openACE ownership required; current="+rejection_value(captured.value("owner","")));return;}
  if(!AceUnitPreview::idle(captured)){reject_action("unit RENAME","Job must be idle or complete; current="+rejection_value(captured.value("job",Json::object()).value("state","")));return;}
  if(!tool_receipt_.empty()){reject_action("unit RENAME","Toolhead receipt is pending.");return;}
  if(!stock_edit_receipt_.empty()){reject_action("unit RENAME","Settings receipt is pending.");return;}
  if(stock_filament_.ace_controls().adoption_unresolved()){reject_action("unit RENAME","Unit adoption is unresolved.");return;}
  if(operation.value("state","")=="pending"||operation.value("state","")=="unknown"){reject_action("unit RENAME","Printer operation is unresolved: state="+rejection_value(operation.value("state","")));return;}
  if(!text_keyboard_.open(stock_filament_.page(),draft.value("name",""),[this,captured,draft](const std::string&name){
   const auto now=stock_snapshot();
   for(const auto*key:{"owner","session","revision"})if(now.value(key,"").empty()||now.value(key,"")!=captured.value(key,""))return reject_action("unit RENAME confirm",std::string(key)+" is missing or changed since keyboard entry.");
   auto&view=stock_filament_.ace_controls();
   if(!ace_mode_active_){reject_action("unit RENAME confirm","ACE controls are not active.");return false;}
  if(!stock_filament_.visible()){reject_action("unit RENAME confirm","Filament page is not visible.");return false;}
  if(!now.value("fresh",false)){reject_action("unit RENAME confirm","Printer status is not fresh.");return false;}
  if(!AceUnitPreview::idle(now)){reject_action("unit RENAME confirm","Job must be idle or complete; current="+rejection_value(now.value("job",Json::object()).value("state","")));return false;}
  if(view.unit_draft()!=draft){reject_action("unit RENAME confirm","Unit draft changed since keyboard entry.");return false;}
   if(!view.rename_draft(name)){
    if(!view.unit_draft_valid(now))return reject_action("unit RENAME confirm",view.unit_draft_reason(now));
    if(name.empty()||name.size()>64||name.find_first_not_of(' ')==std::string::npos)return reject_action("unit RENAME confirm","Unit name must contain non-space text and be1..64bytes; length="+std::to_string(name.size()));
    return reject_action("unit RENAME confirm","Unit name contains a control character.");
   }
   stock_filament_.message("Unit name edited locally. Tap Save & exit to apply.");return true;
  }))stock_filament_.message("The stock text keyboard could not be opened.");
 }
 Receipt submit_adoption(const Json&candidate,const Json&context){
  Json data,raw;std::int64_t at;
  {std::lock_guard<std::mutex>lock(mutex_);data=normalized_;raw=raw_;at=at_;}
  if(!data.is_object())return {"","refused","Printer status is unavailable."};
  data["fresh"]=data.value("fresh",false)&&at>=0&&ui_.now_ms()>=at&&ui_.now_ms()-at<=2000;
  if(!stock_edit_receipt_.empty()||!tool_receipt_.empty())return {"","refused",!stock_edit_receipt_.empty()?"Settings receipt is pending before adoption.":"Toolhead receipt is pending before adoption."};
  const auto old=app_.operation();if(old.is_object()&&(old.value("state","")=="pending"||old.value("state","")=="unknown"))return {"","refused","Operation requires reconciliation: state="+rejection_value(old.value("state",""))+"."};
  for(const auto*key:{"owner","session","revision"})if(data.value(key,"").empty()||data.value(key,"")!=context.value(key,""))return {"","refused","Adoption context "+std::string(key)+" is missing or changed."};
  if(!data.value("fresh",false))return {"","refused","Adoption requires fresh status."};
  if(data.value("owner","")!="openace")return {"","refused","Adoption requires openACE ownership; current="+rejection_value(data.value("owner",""))+"."};
  if(!AceUnitPreview::idle(data))return {"","refused","Adoption requires idle or complete job; current="+rejection_value(data.value("job",Json::object()).value("state",""))+"."};
  if(!data.value("capabilities",Json::object()).value("adopt",false))return {"","refused","Backend capability adopt=false."};
  bool observed=false;for(const auto&c:data.value("candidates",Json::array()))if(c==candidate)observed=true;
  if(!observed)return {"","refused","This discovery changed; reopen adoption."};
  backend_.update(raw,data.value("revision",""),true);
  return backend_.submit({"adopt",data.value("revision",""),"openace",candidate});
 }
 bool send_physical_off(unsigned head){
  if(head>=4)return reject_action("heater Off","Physical head must be Head 1 through Head 4.");
  if(!off_worker_)return reject_action("heater Off","Independent heater transport is unavailable.");
  off_worker_->submit(head,[this,head]{
   const auto heater=head?"extruder"+std::to_string(head):"extruder";
   std::string message="Head "+std::to_string(head+1)+" heater Off sent.";
   try{const auto reply=Json::parse(off_http_->post("/printer/gcode/script",Json{{"script","SET_HEATER_TEMPERATURE HEATER="+heater+" TARGET=0"}}.dump()));
    if(reply.contains("error"))message="Head "+std::to_string(head+1)+" heater Off returned an error; check its target.";
   }catch(...){message="Head "+std::to_string(head+1)+" heater Off outcome unconfirmed; check its target or press Off again.";}
   std::lock_guard<std::mutex>lock(mutex_);off_message_=message;
  });
  stock_filament_.message("Sending Head "+std::to_string(head+1)+" heater Off.");return true;
 }
 bool apply_tool_temperature(const Json&captured,unsigned head,int value){
    const auto now=stock_snapshot();
    if(value==0&&captured.value("owner","")=="standalone")return send_physical_off(head);
    if(!tool_mode_active_){reject_action("temperature confirm","Toolhead controls are not active.");return false;}
  if(tool_head_!=head){reject_action("temperature confirm","Selected head changed: reviewed="+std::to_string(head)+", current="+std::to_string(tool_head_));return false;}
  if(!stock_filament_.visible()){reject_action("temperature confirm","Toolhead page is not visible.");return false;}
  if(!tool_receipt_.empty()){reject_action("temperature confirm","Toolhead receipt is pending.");return false;}
  if(settings_block_machine()){reject_action("temperature confirm","Settings operation holds the printer.");return false;}
  if(!now.value("fresh",false)){reject_action("temperature confirm","Printer status is not fresh.");return false;}
  if(now.value("session","")!=captured.value("session","")){reject_action("temperature confirm","Printer session changed.");return false;}
  if(now.value("revision","")!=captured.value("revision","")){reject_action("temperature confirm","Configuration revision changed.");return false;}
  if(now.value("owner","")!=captured.value("owner","")){reject_action("temperature confirm","Control owner changed: current="+rejection_value(now.value("owner","")));return false;}
    auto limits=now.value("heater_limits",Json::object());const auto id="h"+std::to_string(head);
    if(!limits.contains(id)||!limits[id].contains("min")||!limits[id].contains("max")){
     stock_filament_.message("This head's heater limits are unavailable.");return false;
    }
    if(value!=0&&(value<limits[id]["min"].get<double>()||value>limits[id]["max"].get<double>())){
     reject_action("temperature confirm","Requested="+std::to_string(value)+", permitted min="+std::to_string(limits[id]["min"].get<double>())+", max="+std::to_string(limits[id]["max"].get<double>()));return false;
    }
    const auto receipt=standalone_.submit({"temperature",now.value("revision",""),now.value("owner",""),{{"head",id},{"target",value}}});
    stock_filament_.message(receipt.message);
    if(receipt.id.empty())return false;
    tool_targets_[tool_head_]=value;tool_receipt_=receipt.id;tool_busy_action_="temperature";tool_busy_head_=id;return true;
 }
 void tool_action(const std::string&action){
  auto reject=[this,&action](const std::string&why){stock_filament_.message(why);report_rejection(("toolhead "+rejection_value(action)).c_str(),why);};
  if(!tool_mode_active_){reject("Toolhead controls are no longer active.");return;}
  if(filament_procedure_.active()){reject("A filament procedure dialog is active; close it before using toolhead controls.");return;}
  if(nozzle_editor_.active()){reject("The nozzle editor is active; close it before using toolhead controls.");return;}
  if(!stock_filament_.visible()){reject("Toolhead page is no longer visible.");return;}
  if(action=="off"&&stock_snapshot().value("owner","")=="standalone"){send_physical_off(tool_head_);return;}
  auto held_reason=[this](){return !tool_receipt_.empty()?"Waiting for toolhead receipt: action="+rejection_value(tool_busy_action_)+", head="+rejection_value(tool_busy_head_)+".":"Waiting for settings receipt: action="+rejection_value(stock_edit_operation_.value("action",""))+", state="+rejection_value(stock_edit_operation_.value("state",""))+".";};
  update_tool_view();update_stock_edit();
  if(action=="view-operation"){
   const auto data=stock_snapshot();const auto op=data.value("filament_operation",Json::object());
   if(StockFilamentProcedure::interrupted(data)){
    if(!standalone_.resume_filament(op.value("id",""))){reject(standalone_.resume_refusal());return;}
    tool_receipt_=op.at("id");tool_busy_action_=op.at("action");tool_busy_head_=op.at("head");
    filament_procedure_.open_interrupted(stock_filament_.content(),data);
   }else if(StockFilamentProcedure::interrupted(data,true)){
    const auto tool=data.at("toolhead_operation");
    if(standalone_.resume_toolhead(tool.value("id",""))){
     tool_receipt_=tool.at("id");tool_busy_action_=tool.at("action");tool_busy_head_=tool.at("head");
     filament_procedure_.open_interrupted(stock_filament_.content(),data,true);
    }else{reject(standalone_.resume_refusal());return;}
   }else if(!tool_receipt_.empty()&&filament_procedure_.has_result())filament_procedure_.reopen_result(stock_filament_.content(),data);
   // A completed receipt is history. A late click on the former Progress
   // shortcut must not reopen an already acknowledged result.
   if(!filament_procedure_.active())return;
   stock_filament_.interaction_blocked(filament_procedure_.active());
   return;
  }
  if(action=="take-dock"){
   if(!tool_receipt_.empty()||settings_block_machine()){reject(held_reason());return;}
   const auto data=stock_snapshot();const auto mounting=StockToolheadView::mounting_for(data,tool_head_);
   if(mounting=="Attachment unknown"){reject("Head attachment is unknown: attachment.state="+rejection_value(data.value("attachment",Json::object()).value("state",""))+".");return;}
   const auto attachment=data.value("attachment",Json::object());
   const auto command=mounting=="Mounted"?"dock":"take";
   Json args={{"head","h"+std::to_string(tool_head_)},{"attached",attachment.value("state","")=="empty"?"none":attachment.value("head","")}};
   const auto receipt=standalone_.submit({command,data.value("revision",""),data.value("owner",""),args});
   tool_receipt_=receipt.id;tool_busy_action_=command;tool_busy_head_=args.at("head").get<std::string>();stock_filament_.message(receipt.message);
   filament_procedure_.open_tracking(stock_filament_.content(),data,tool_busy_head_,command,receipt);
   stock_filament_.interaction_blocked(filament_procedure_.active());return;
  }
  if(action=="filaments"){request(7);return;}
  if(action=="nozzle"){
   if(stock_snapshot().value("owner","")!="standalone"&&(!tool_receipt_.empty()||settings_block_machine())){reject(held_reason());return;}
   nozzle_editor_.update(stock_snapshot());nozzle_editor_.show(stock_filament_.content(),tool_head_);
   stock_filament_.interaction_blocked(nozzle_editor_.active());return;
  }
  if(action=="edit-filament"){request(9+int(tool_head_));return;}
  if(action.compare(0,5,"step:")==0){
   auto value=action.substr(5);if(value=="1"||value=="5"||value=="10"||value=="25"||value=="50")tool_step_=std::stoi(value);return;
  }
  if(action=="target"){
   if(!tool_receipt_.empty()||settings_block_machine()){reject(held_reason());return;}
   const auto captured=stock_snapshot();const auto head=tool_head_;
   if(!captured.value("fresh",false)){reject("Printer status is not fresh; refresh before setting a target.");return;}
   if(captured.value("session","").empty()){reject("Printer session is missing; refresh before setting a target.");return;}
   if(captured.value("revision","").empty()){reject("Configuration revision is missing; refresh before setting a target.");return;}
   int current_target=0;for(const auto&h:captured.value("heads",Json::array()))if(h.value("id","")=="h"+std::to_string(head))current_target=h.value("target",0);
   if(!temperature_keypad_.open(stock_filament_.page(),current_target,[this,captured,head](int value){
    return apply_tool_temperature(captured,head,value);
   }))stock_filament_.message("Temperature keypad could not be opened.");
   return;
  }
  if(action=="load"||action=="unload"){
   if(!tool_receipt_.empty()||settings_block_machine()){reject(held_reason());return;}
   const auto data=stock_snapshot();const auto head="h"+std::to_string(tool_head_);
   if(action=="load"&&!StockToolheadView::ace_managed(data,head)){pending_external_load_=head;request(9+int(tool_head_));return;}
   if(action=="load"&&StockToolheadView::ace_managed(data,head)){stock_filament_.message("Select an ACE slot in Filaments / slots to load.");return;}
   if(!filament_procedure_.open(stock_filament_.content(),data,head,action,false,action=="load"?"external:"+head:""))stock_filament_.message("Filament procedure review could not be opened.");
   stock_filament_.interaction_blocked(filament_procedure_.active());return;
  }
  if(action!="extrude"&&action!="retract"&&action!="off"){
   stock_filament_.message(action=="take-dock"?"Take/dock backend is not connected yet.":"Load/unload review controls are not integrated yet.");return;
  }
  auto data=stock_snapshot();
  if(!data.value("fresh",false)){stock_filament_.message("Fresh printer status is required.");return;}
  if(!tool_receipt_.empty()||settings_block_machine()){reject(held_reason());return;}
  Json args={{"head","h"+std::to_string(tool_head_)}};std::string command;
  if(action=="off"){command="temperature";args["target"]=0;}
  else{command="step";args["mm"]=action=="retract"?-tool_step_:tool_step_;}
  auto receipt=standalone_.submit({command,data.value("revision",""),data.value("owner",""),args});
  tool_receipt_=receipt.id;tool_busy_action_=action;tool_busy_head_="h"+std::to_string(tool_head_);stock_filament_.message(receipt.message);
 }
 void update_tool_view(){update_tool_view(stock_snapshot());}
 void update_tool_view(const Json&snapshot){
  auto data=snapshot;reconcile_operation(data,channel_.latest(),stock_filament_.ace_controls().adoption_operation());stock_filament_.ace_controls().observe_adoption(data);const bool interrupted=StockFilamentProcedure::interrupted(data)||StockFilamentProcedure::interrupted(data,true);data["tool_ui_busy"]={{"pending",!tool_receipt_.empty()||(data.value("owner","")!="standalone"&&interrupted)},{"action",tool_busy_action_},{"head",tool_busy_head_},{"interrupted",interrupted}};
  filament_procedure_.update(data);nozzle_editor_.update(data);stock_filament_.interaction_blocked(filament_procedure_.active()||nozzle_editor_.active());
  stock_filament_.tool_data(data,tool_step_,tool_targets_[tool_head_]);
  if(tool_receipt_.empty()||!data.value("fresh",false))return;
  auto receipts=data.value("receipts",Json::object());if(!receipts.contains(tool_receipt_))return;
  auto result=receipts.at(tool_receipt_);if(tool_mode_active_)stock_filament_.message(result.value("message","Waiting for backend."));
  if(tool_busy_action_=="load"||tool_busy_action_=="unload"||((tool_busy_action_=="take"||tool_busy_action_=="dock")&&filament_procedure_.has_tool_result()))filament_procedure_.result(result);
  auto state=result.value("state","");if(state=="complete"||state=="refused"||state=="failed"||(state=="unknown"&&(data.value("owner","")=="standalone"||(tool_busy_action_!="load"&&tool_busy_action_!="unload"&&tool_busy_action_!="take"&&tool_busy_action_!="dock"))))tool_receipt_.clear();
 }
 void update_stock_edit(){update_stock_edit(stock_snapshot());}
 void update_stock_edit(const Json&snapshot){
  if(!snapshot.value("fresh",false))return;
  Json reconciled;
  if(stock_ace_edit_){reconciled=snapshot;reconcile_operation(reconciled,channel_.latest(),stock_edit_operation_);}
  const auto&data=stock_ace_edit_?reconciled:snapshot;
  // A settings receipt belongs to one backend session. After a restart or
  // ownership change it cannot authorize readback or a deferred Load, and must
  // not keep unrelated maintenance blocked forever. Preserve the unknown
  // outcome, but discard the old draft and require an explicit new edit.
  const auto owner=data.value("owner","");const auto session=data.value("session","");
  if(stock_ace_edit_&&!stock_edit_receipt_.empty()&&stock_edit_operation_.value("id","")==stock_edit_receipt_
     &&(owner=="standalone"||owner=="openace")&&!session.empty()
     &&!stock_edit_operation_.value("session","").empty()
     &&(owner!=stock_edit_operation_.value("owner","")||session!=stock_edit_operation_.value("session",""))){
   const std::string message="Printer session changed. Previous settings save is unconfirmed; reopen settings to review.";
   stock_edit_operation_["state"]="unknown";stock_edit_operation_["message"]=message;
   stock_edit_operation_["load_after_save"]=false;
   stock_edit_receipt_.clear();stock_ace_edit_=false;
   stock_identity_.cancel();stock_picker_.close();text_keyboard_.close();
   stock_filament_.ace_controls().identity_pending(false);
   stock_filament_.ace_controls().discard_drafts();stock_filament_.message(message);
  }
  if(data.value("owner","")=="standalone"){
   std::array<std::string,4> materials;
   std::array<std::string,4> brands;std::vector<std::string>brand_catalogue=data.value("brands",Json::array()).get<std::vector<std::string>>();
   std::array<const char*,4> colours{{nullptr,nullptr,nullptr,nullptr}};
   std::array<std::uint32_t,4> tints{{0,0,0,0}};
   for(const auto&source:data.value("sources",Json::array())){
    auto head=source.value("head","");
    if(source.value("kind","")=="external"&&head.size()==2&&head[0]=='h'&&head[1]>='0'&&head[1]<='3'){
     materials[head[1]-'0']=source.value("identity",Json::object()).value("material","");
     brands[head[1]-'0']=identity_display_text(source.value("identity",Json::object()),"brand","Generic");
     brand_catalogue.push_back(brands[head[1]-'0']);
#if defined(__aarch64__)
     auto colour=identity_display_text(source.value("identity",Json::object()),"color","");
     int index=stock_colour_index(colour);
     if(index<0&&stock_rgb(colour,tints[head[1]-'0']))index=0;
     if(index>=0)colours[head[1]-'0']=reinterpret_cast<const std::string*>(0x38626e8)[index].c_str();
#endif
    }
   }
   stock_filament_.material_labels(materials);
   stock_filament_.brands(brands,brand_catalogue);
   stock_filament_.colour_sources(colours);
   stock_filament_.colour_tints(tints);
  }
  if(stock_edit_receipt_.empty())return;
  auto receipts=data.value("receipts",Json::object());if(!receipts.contains(stock_edit_receipt_))return;
  const auto&r=receipts.at(stock_edit_receipt_);auto state=r.value("state","");
  if(stock_ace_edit_){
   const auto&draft=stock_edit_operation_.at("arguments").at("draft");
   if(data.value("owner","")!=stock_edit_operation_.value("owner","")||data.value("session","")!=stock_edit_operation_.value("session",""))state="unknown";
   if(stock_edit_operation_.value("action","")=="save_unit"){
    if(state=="complete"){
     bool matched=false;
     for(const auto&unit:data.value("units",Json::array()))if(unit.value("id","")==draft.value("id","")&&unit.value("name","")==draft.value("name","")&&unit.value("assignments",Json::object())==draft.value("assignments",Json::object()))matched=true;
     if(!matched)return; // Delivery is not configuration readback.
     stock_filament_.ace_controls().unit_saved(draft);
     stock_filament_.message("Unit name saved.");
    }else stock_filament_.message(r.value("message","Waiting for unit readback."));
    stock_edit_operation_["state"]=state;
    if(state=="complete"||state=="refused"||state=="failed")stock_edit_receipt_.clear();
    return; // Unknown stays latched, preventing an unattended repeat.
   }
   if(state=="complete"){
    Json matched;
    for(const auto&source:data.value("sources",Json::array()))if(source.value("id","")==draft.value("id","")&&source.value("identity",Json::object())==draft.value("identity",Json::object())&&source.value("head","")==draft.value("head","")&&source.value("unit","")==draft.value("unit","")&&source.value("slot",-1)==draft.value("slot",-1))matched=source;
    if(!matched.is_object())return;
    stock_filament_.ace_controls().identity_pending(false);
    stock_filament_.ace_controls().colour_saved(data,matched);
    if(stock_edit_operation_.value("load_after_save",false)){
     stock_edit_operation_["load_after_save"]=false;stock_edit_receipt_.clear();
     const auto origin=stock_edit_operation_.value("load_context",Json::object());
     if(origin.value("job",Json::object())!=data.value("job",Json::object())||origin.value("paused_filament",Json::object())!=data.value("paused_filament",Json::object())){
      stock_filament_.message("Print context changed. Filament settings saved; reopen Load to continue.");return;
     }
     stock_filament_.ace_controls().discard_drafts();
     // Saving metadata never authorizes motion. Present a fresh review;
     // the user must explicitly Begin, under current operation admission.
     filament_procedure_.open(stock_filament_.content(),data,matched.value("head",""),"load",false,matched.value("id",""));
     stock_filament_.interaction_blocked(filament_procedure_.active());
    }
   }else{
    stock_filament_.ace_controls().colour_result(draft.value("id",""),r.value("message","Waiting for filament settings readback."));
    stock_filament_.ace_controls().identity_pending(state=="pending"||state=="unknown");
   }
   stock_edit_operation_["state"]=state;
   if(state=="unknown"&&owner=="standalone"&&stock_edit_operation_.value("action","")=="save_identity"){
    // Metadata readback can end without confirmation even when no physical
    // operation was dispatched. Keep the outcome unknown, cancel any deferred
    // Load, and require a new review instead of blocking all maintenance.
    const std::string message="Filament settings save is unconfirmed; reopen settings to review.";
    stock_edit_operation_["message"]=message;stock_edit_operation_["load_after_save"]=false;
    stock_edit_receipt_.clear();stock_ace_edit_=false;
    stock_identity_.cancel();stock_picker_.close();text_keyboard_.close();
    stock_filament_.ace_controls().identity_pending(false);
    stock_filament_.ace_controls().discard_drafts();stock_filament_.message(message);
    return;
   }
   if(state=="unknown")return; // An uncertain save must not be silently repeated.
  }
  if(!tool_mode_active_)stock_filament_.message(r.value("message","Waiting for filament settings confirmation."));
  if(state=="complete"||state=="refused"||state=="failed"||state=="unknown")stock_edit_receipt_.clear();
 }
 void update_home(const Json&data,bool data_changed){
#if defined(__aarch64__)
  if(!surface_.verified()||!data.is_object()){mini_.clear();return;}
  mini_.update(data,*reinterpret_cast<void*volatile*>(0x386cec0),*reinterpret_cast<void*volatile*>(0x386cfa8),data_changed);
#else
  (void)data;(void)data_changed;
#endif
 }
 void close(){surface_.close();pending_preview_.clear();}
 void reconcile(Json&out,const std::shared_ptr<const wmp_openace::UiSnapshot>&snapshot){
  reconcile_operation(out,snapshot,app_.operation());
 }
 void reconcile_operation(Json&out,const std::shared_ptr<const wmp_openace::UiSnapshot>&snapshot,const Json&op){
  if(op.empty()||!snapshot)return;
  if(op.value("id","")!=std::to_string(snapshot->delivery.ticket))return;
  std::string state="pending";
  if(snapshot->delivery.outcome==wmp_openace::Delivery::NotSent)state="refused";
  else if(snapshot->delivery.outcome==wmp_openace::Delivery::Unknown)state="unknown";
  else if(snapshot->delivery.outcome==wmp_openace::Delivery::Replied&&snapshot->status_generation>snapshot->delivery.status_generation){
   auto action=op.value("action","");
   if(action=="save_identity"||action=="save_unit")state="complete"; // App additionally requires exact config readback.
   if(action=="adopt")for(const auto&unit:out["units"])if(unit.value("id","")==op.at("arguments").value("logical_name",""))state="complete";
  }
  out["receipts"][op.value("id","")]={{"owner",out["owner"]},{"session",out["session"]},{"action",op.value("action","")},{"state",state},{"message",snapshot->delivery_message}};
 }
};
}}
