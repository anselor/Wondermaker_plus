// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <nlohmann/json.hpp>
#include <algorithm>
#include <functional>
#include <cmath>
#include <cstdio>
#include <iomanip>
#include <sstream>
#include <locale>
#include <map>
#include <set>
#include <string>
#include <vector>
namespace wmp_ui {
using Json = nlohmann::json;
// Backend permission for an explicit repair of this paused tool-change fault.
// Ordinary paused jobs and other owners never gain manual coupling permission.
inline bool paused_toolhead_repair_available(const Json&data){
 const auto permission=data.value("toolchange_pause",Json::object());
 return data.value("fresh",false)&&data.value("owner","")=="standalone"
  &&data.value("job",Json::object()).value("state","")=="paused"
  &&permission.is_object()&&permission.value("manual_toolhead_available",Json())==Json(true);
}

// A normal paused job permits only the head/action advertised by its captured
// pause context. The backend revalidates this observation before moving.
inline bool paused_toolhead_action_available(const Json&data,const std::string&head,const std::string&action){
 if(paused_toolhead_repair_available(data))return true;
 if(!data.value("fresh",false)||data.value("owner","")!="standalone"||data.value("job",Json::object()).value("state","")!="paused")return false;
 const auto permission=data.value("paused_toolhead_actions",Json::object());
 if(!permission.is_object()||permission.value("head","")!=head)return false;
 const auto actions=permission.value("actions",Json::array());
 return (action=="take"||action=="dock")&&actions.is_array()&&std::find(actions.begin(),actions.end(),Json(action))!=actions.end();
}

// Cosmetic text never supplies command authority. Preserve the raw JSON in
// snapshots/drafts; only rendering substitutes an unavailable display value.
inline std::string identity_display_text(const Json&row,const std::string&field,const std::string&fallback){
 if(!row.is_object()||!row.contains(field)||!row[field].is_string())return fallback;
 const auto value=row[field].get<std::string>();
 if(field=="color"&&(value.size()!=7||value[0]!='#'||value.substr(1).find_first_not_of("0123456789abcdefABCDEF")!=std::string::npos))return fallback;
 return value;
}
// Missing diagnostic text is local to its operation; never invent completion
// or lose a valid reason because a backend returned a malformed message.
inline std::string operation_display_text(const Json&row,const std::string&field,const std::string&fallback){
 if(!row.is_object()||!row.contains(field))return fallback;
 return row[field].is_string()?row[field].get<std::string>():fallback+" ["+field+" text unavailable]";
}
// Diagnostic values are bounded control-state labels, never whole payloads,
// filenames, identities, session tokens or configuration revisions.
inline std::string rejection_value(const std::string&value){
 std::string out;for(unsigned char c:value){if(out.size()==64)break;out+=c>=32&&c<127?char(c):'?';}
 return out.empty()?"<empty>":out;
}

inline std::string brand_sort_key(std::string name){
 for(auto&c:name)if(c>='A'&&c<='Z')c=char(c-'A'+'a');
 return name;
}
// Call only when a user action is refused, never from availability polling.
inline void report_rejection(const char*action,const std::string&reason){
 std::string bounded;for(unsigned char c:reason){if(bounded.size()==512)break;bounded+=c>=32&&c<127?char(c):' ';}
 std::fprintf(stderr,"WM+ rejected %s: %s\n",action,bounded.c_str());
}
// Shared by native brand dropdowns. Keep saved spelling, reject list delimiters,
// and sort only after merging so neither Generic nor the selection is pinned.
inline std::vector<std::string> brand_choices(const std::vector<std::string>&catalogue,const std::string&selected){
 std::vector<std::string> result;
 auto add=[&](const std::string&name){
  if(name.empty()||name.size()>64)return;
  for(unsigned char c:name)if(c<32||c==127)return;
  for(const auto&old:result)if(brand_sort_key(old)==brand_sort_key(name))return;
  result.push_back(name);
 };
 add(selected);add("Generic");for(const auto&name:catalogue)add(name);
 std::sort(result.begin(),result.end(),[](const std::string&a,const std::string&b){return brand_sort_key(a)<brand_sort_key(b);});
 return result;
}
// Paused filament access is scoped to the original head and recorded runout heads.
inline bool paused_filament_for(const Json&data,const std::string&head=""){
 const auto pause=data.value("paused_filament",Json::object());const auto origin=pause.value("origin",Json::object());
 const auto id=origin.value("id","");const auto physical=pause.value("head","");
 const auto required=pause.value("filament_required",Json::array());
 const bool permitted=head.empty()||head==physical||(required.is_array()&&head.size()==2&&head[0]=='h'&&head[1]>='0'&&head[1]<='3'&&std::find(required.begin(),required.end(),head)!=required.end());
 return data.value("fresh",false)&&data.value("owner","")=="standalone"&&data.value("job",Json::object()).value("state","")=="paused"&&
  pause.value("available",false)&&physical.size()==2&&physical[0]=='h'&&physical[1]>='0'&&physical[1]<='3'&&permitted&&
  origin.value("head","")==physical&&!data.value("session","").empty()&&origin.value("session","")==data.value("session","")&&
  id.size()==32&&id.find_first_not_of("0123456789abcdef")==std::string::npos;
}
inline bool filament_cosmetic_edit(const Json&before,const Json&after){
 if(!before.is_object()||!after.is_object())return false;
 auto previous=before,next=after;
 for(const auto*key:{"brand","color"}){previous.erase(key);next.erase(key);}
 return previous==next;
}
inline std::string filament_recipe_service_reason(const Json&data,const std::string&head){
 if(data.value("owner","")!="standalone")return {};
 const auto operation=data.value("filament_operation",Json::object());
 const auto state=operation.value("state","");
 if(state!="pending"&&state!="running")return {};
 const auto active=operation.value("head","");
 if(active.size()!=2||active[0]!='h'||active[1]<'0'||active[1]>'3')return "Cannot identify the head used by the active filament operation. Wait for it to finish before changing the recipe.";
 if(active==head)return "Wait for the filament operation on Head "+std::to_string(active[1]-'0'+1)+" to finish before changing its recipe.";
 return {};
}
// Backend proves this physical head is unused by the current stream. This is
// additive permission, never an inference from displayed logical mappings.
inline bool filament_recipe_write_allowed(const Json&data,const std::string&head){
 if(data.value("owner","")!="standalone"||!data.value("fresh",false)||head.size()!=2||head[0]!='h'||head[1]<'0'||head[1]>'3')return false;
 const auto protocol=data.value("filament_recipe_write_protocol",Json());
 const auto writes=data.value("filament_recipe_write",Json());
 if(!protocol.is_number_integer()||protocol!=1||!writes.is_object()||!writes.contains(head)||!writes[head].is_object())return false;
 const auto allowed=writes[head].value("allowed",Json());return allowed.is_boolean()&&allowed==true;
}
inline bool filament_identity_editable(const Json&data,const std::string&head){
 if(filament_recipe_write_allowed(data,head))return true;
 const auto job=data.value("job",Json::object()).value("state","");
 if(job=="idle"||job=="complete")return filament_recipe_service_reason(data,head).empty();
 if(!paused_filament_for(data,head))return false;
 for(const auto*key:{"filament_operation","toolhead_operation"}){const auto state=data.value(key,Json::object()).value("state","");if(state=="running"||state=="unknown")return false;}
 for(const auto&h:data.value("heads",Json::array()))if(h.value("id","")==head)return h.value("loaded",Json::object()).value("state","")=="empty";
 return false;
}
inline std::string filament_identity_reason(const Json&data,const std::string&head){
 if(filament_recipe_write_allowed(data,head))return {};
 const auto job=data.value("job",Json::object()).value("state","");
 if(job=="idle"||job=="complete")return filament_recipe_service_reason(data,head);
 if(!data.value("fresh",false))return "Paused filament edit requires fresh status.";
 if(data.value("owner","")!="standalone")return "Paused filament edit requires standalone ownership; current="+rejection_value(data.value("owner",""))+".";
 if(job!="paused")return "Filament edit requires idle, complete or captured paused job; current="+rejection_value(job)+".";
 const auto pause=data.value("paused_filament",Json::object());const auto origin=pause.value("origin",Json::object());const auto physical=pause.value("head","");
 if(!pause.value("available",false))return "Captured paused-filament context is unavailable.";
 if(physical.size()!=2||physical[0]!='h'||physical[1]<'0'||physical[1]>'3')return "Captured paused physical head is malformed.";
 const auto required=pause.value("filament_required",Json::array());
 if(!head.empty()&&head!=physical&&!(required.is_array()&&head.size()==2&&head[0]=='h'&&head[1]>='0'&&head[1]<='3'&&std::find(required.begin(),required.end(),head)!=required.end()))return "Selected head is outside the captured paused context: selected="+rejection_value(head)+", paused="+rejection_value(physical)+".";
 if(origin.value("head","")!=physical)return "Paused origin physical head changed.";
 if(data.value("session","").empty())return "Paused edit printer session is missing.";
 if(origin.value("session","")!=data.value("session",""))return "Paused origin belongs to a different printer session.";
 const auto id=origin.value("id","");if(id.size()!=32||id.find_first_not_of("0123456789abcdef")!=std::string::npos)return "Paused origin identifier is malformed.";
 for(const auto*key:{"filament_operation","toolhead_operation"}){const auto state=data.value(key,Json::object()).value("state","");if(state=="running"||state=="unknown")return std::string(key)+" prevents paused editing: state="+rejection_value(state)+".";}
 for(const auto&h:data.value("heads",Json::array()))if(h.value("id","")==head)return "Paused filament editing requires empty head; loaded.state="+rejection_value(h.value("loaded",Json::object()).value("state",""))+".";
 return "Selected physical head is unavailable: head="+rejection_value(head)+".";
}
// Slicer estimates belong to the sliced filament, regardless of its destination.
inline std::string filament_usage_text(const Json&slice){
 for(const auto*key:{"filament_used_g","filament_used_mm"}){
  if(!slice.contains(key)||!slice[key].is_number())continue;
  const auto value=slice[key].get<double>();if(!std::isfinite(value)||value<0)continue;
  std::ostringstream text;text.imbue(std::locale::classic());
  text<<std::fixed<<std::setprecision(2)<<value<<(std::string(key)=="filament_used_g"?" g":" mm");return text.str();
 }
 return "";
}
inline std::uint32_t stage_color(int index,int active,bool complete=false){return complete||index<active?0xff999999U:index==active?0xffff6600U:0xffeeeeeeU;}
struct Request { std::string action, revision, owner; Json arguments; };
struct Receipt { std::string id, state, message; }; // pending/refused/unknown; never completion by timer
struct Backend {
 virtual ~Backend() = default;
 virtual std::string unavailable(const std::string& action) const = 0;
 virtual Receipt submit(const Request&) = 0;
};
struct StubBackend : Backend {
 std::string unavailable(const std::string& action) const override {
  return "Backend support for " + action + " is not connected yet.";
 }
 Receipt submit(const Request&) override {return {"", "refused", "Backend unavailable; nothing sent."};}
};
struct Widget {
 std::string id, text, kind="label", color, reason, parent, image_path;
 int image_width=0,image_height=0;
 int x=0,y=0,w=0,h=0;
 bool enabled=true, selected=false, faded=false, busy=false;
 Json json() const {return {{"id",id},{"text",text},{"kind",kind},{"x",x},{"y",y},{"w",w},{"h",h},
  {"image_path",image_path},{"image_width",image_width},{"image_height",image_height},{"parent",parent},{"enabled",enabled},{"selected",selected},{"faded",faded},{"color",color},{"reason",reason},{"busy",busy}};}
};
class App {
public:
 explicit App(Backend& backend):backend_(backend){}
 // Called once on a native file-preview handoff, not on status refreshes.
 void print_options(bool leveling,bool timelapse,bool available){
  timelapse_available_=available;
  options_={{"leveling",leveling},{"timelapse",available&&timelapse}};
 }
 // Normalized presentation snapshot. This is a WM+ adapter contract, not an
 // assertion that openACE currently publishes these fields.
 void update(Json snapshot) {
  if (!snapshot.is_object() || !snapshot.contains("revision") || !snapshot["revision"].is_string()
      || !snapshot.contains("heads") || !snapshot["heads"].is_array()
      || !snapshot.contains("sources") || !snapshot["sources"].is_array()
      || !snapshot.contains("units") || !snapshot["units"].is_array()) {
   data_["fresh"]=false; notice_="Printer status unavailable"; return;
  }
  if(!valid(snapshot)){data_["fresh"]=false;notice_="Invalid printer status; changes disabled";return;}
  if(!data_.value("revision","").empty()&&(snapshot["revision"]!=data_["revision"]||
     snapshot.value("session","")!=data_.value("session","")||snapshot.value("owner","")!=data_.value("owner","")||
     (snapshot.value("owner","")=="standalone"&&snapshot.value("fresh",false)&&!selection_.empty()))) {
   const auto previous_selection=selection_;
   if(snapshot.value("owner","")=="standalone"&&data_.value("owner","")=="standalone"&&
      snapshot.value("session","")==data_.value("session","")&&snapshot.value("fresh",false)){
    Json kept=Json::object();
    for(auto it=selection_.begin();it!=selection_.end();++it){
     const auto before=selection_binding(data_,file_,it.key(),it.value());
     if(!before.is_null()&&before==selection_binding(snapshot,file_,it.key(),it.value()))kept[it.key()]=it.value();
    }
    selection_=std::move(kept);preview_revision_=snapshot.value("revision","");
   }else{selection_=Json::object();preview_revision_="";}
   if((modal_=="sources"||modal_=="routes")&&(snapshot["revision"]!=data_["revision"]||snapshot.value("session","")!=data_.value("session","")||snapshot.value("owner","")!=data_.value("owner","")||selection_!=previous_selection)){
    modal_.clear();picker_revision_.clear();notice_="Preview or routing changed. Reopen the source chooser and review the assignments.";
   }
  }
  data_=std::move(snapshot);
  if(busy()&&(operation_.value("owner","")!=data_.value("owner","")||operation_.value("session","")!=data_.value("session",""))) {operation_["state"]="unknown";operation_["allowed_actions"]=Json::array();notice_="Backend session changed. Operation outcome must be reconciled.";}
  if (!find("heads", head_)) head_=data_["heads"].empty()?"":data_["heads"][0].value("id", "");
  for(const auto&key:{"control_request","cancel_request"})if(operation_.contains(key)) {
   auto&control=operation_[key];if(!unresolved(control))continue;
   if(control.value("owner","")!=data_.value("owner","")||control.value("session","")!=data_.value("session","")){control["state"]="unknown";continue;}
   auto receipts=data_.value("receipts",Json::object());auto id=control.value("id","");
   if(receipts.contains(id)) {const auto&r=receipts[id];
    if(r.value("owner","")==control.value("owner","")&&r.value("session","")==control.value("session","")&&r.value("action","")==control.value("action","")) {
     auto state=r.value("state","unknown");control["state"]=(state=="complete"||state=="refused")?state:"unknown";
     control["message"]=r.value("message","");
    }
   }
  }
  // Acknowledgement alone never clears pending work; only a matching receipt.
  if (unresolved(operation_) && data_.contains("receipts") && data_["receipts"].is_object()) {
   auto id=operation_.value("id", "");
   if (data_["receipts"].contains(id)) {
    const auto&r=data_["receipts"][id];
    if (r.is_object()) {
     if(data_.value("session","")!=operation_.value("session","")||data_.value("owner","")!=operation_.value("owner","")||r.value("owner","")!=operation_.value("owner","")||r.value("session","")!=operation_.value("session","")||r.value("action","")!=operation_.value("action",""))return;
     auto result=r.value("state", "unknown");
     if(result!="pending"&&result!="partial"&&result!="unknown"&&result!="complete"&&result!="refused"&&result!="failed")result="unknown";
     // Configuration completion requires both receipt and exact readback.
     if(result=="complete"&&(operation_.value("action","")=="save_unit"||operation_.value("action","")=="save_identity")) {
      const auto&saved=operation_["arguments"]["draft"];auto current=find(operation_["action"]=="save_unit"?"units":"sources",saved.value("id",""));
      bool matches=current&&current->value("id","")==saved.value("id","");
      if(matches&&operation_["action"]=="save_identity")matches=current->value("identity",Json::object())==saved.value("identity",Json::object());
      if(matches&&operation_["action"]=="save_unit")matches=current->value("name","")==saved.value("name","")&&current->value("assignments",Json::object())==saved.value("assignments",Json::object());
      if(!matches){result="pending";}else if(draft_==saved){
       draft_=Json();baseline_=data_.value("revision","");
       if(page_=="operation"){page_=operation_.value("origin","filaments");modal_.clear();}
      }
     }
     // Adoption is complete only when the registered unit is visible. Open
     // its assignment draft once, without stealing navigation or newer edits.
     if(result=="complete"&&operation_.value("action","")=="adopt") {
      auto unit=find("units",operation_.value("arguments",Json::object()).value("logical_name",""));
      if(!unit)result="pending";
      else if(page_=="operation"&&!dirty()){
       draft_=*unit;baseline_=data_.value("revision","");draft_kind_="unit";
       origin_="filaments";modal_.clear();page_="unit";
      }
     }
     operation_["state"]=result;operation_["message"]=r.value("message", "");operation_["allowed_actions"]=r.value("allowed_actions",Json::array());
     notice_=operation_.value("action","")+" · "+result+" · "+r.value("message", "");
    }
   }
  }
 }
 const Json& data()const{return data_;}
 const Json& draft()const{return draft_;}
 const Json& operation()const{return operation_;}
 const std::string& page()const{return page_;}
 const std::string& notice()const{return notice_;}
 // Semantic preview data for the stock-widget adapter. No mock coordinates
 // or replacement-page widgets: use the same selections and admission rules
 // as the command path so the native view cannot invent a second mapping.
 Json preview_state()const {
  auto file=find("files",file_);Json rows=Json::array();
  if(file)for(const auto&slice:file->value("sliced",Json::array())){
   const auto id=slice.value("id","");
   auto route=selection_.contains(id)?find("routes",selection_[id]):nullptr;
   auto source=route?find("sources",route->value("source","")):nullptr;
   rows.push_back({{"id",id},{"sliced",slice},
    {"route",route?*route:Json()},{"source",source?*source:Json()},
    {"eligible",route&&eligible(*route,id)}});
  }
  auto reason=preview_problem();if(reason.empty())reason=unavailable("start_print");
  auto notice=notice_;
  if(notice.empty()&&reason.empty()&&file&&!file->value("usage_known",true))notice="Usage unavailable; all filament presets are shown.";
  return {{"file",file?*file:Json()}, {"rows",rows},{"mapping_summary",mapping_summary()},{"options",options_},
   {"timelapse_available",timelapse_available_},{"fresh",data_.value("fresh",false)},
   {"editable",data_.value("fresh",false)&&!busy()&&data_.value("owner","unknown")!="unknown"&&(data_.value("job",Json::object()).value("state","")=="idle"||data_.value("job",Json::object()).value("state","")=="complete")},
   {"revision",data_.value("revision","")},{"session",data_.value("session","")},
   {"can_start",page_=="preview"&&reason.empty()},
   {"reason",reason},{"notice",notice},{"operation",operation_},{"material_review",!material_review_.is_null()},{"material_warning",material_warning()}};
 }
 Json source_picker_state()const {
  Json out=data_;Json choices=Json::object();
  const bool open=modal_=="sources"||modal_=="routes";
  const bool editable=open&&picker_revision_==data_.value("revision","")&&preview_state().value("editable",false);
  if(open)for(const auto&source:data_.value("sources",Json::array())){
   Json routes=Json::array();
   for(const auto&route:data_.value("routes",Json::array()))if(route.value("source","")==source.value("id","")&&eligible(route,row_))routes.push_back(route);
   choices[source.value("id","")]=routes;
  }
  out["picker_choices"]=choices;out["picker_editable"]=editable;
  out["picker_open"]=open;out["picker_row"]=row_;
  out["picker_route_source"]=modal_=="routes"?source_:"";
  return out;
 }
 void loading_preview(const std::string&path){material_review_=Json();file_=path;selection_=Json::object();navigate("preview-loading");}
 std::string unavailable(const std::string& action) const {
  if(!data_.value("fresh",false))return "Printer status is unavailable: fresh=false. Refresh before making changes.";
  if(data_.value("owner","unknown")=="unknown")return "Printer control owner is unknown.";
  if (busy() && action!="stop" && action!="reconcile" && action!="cancel_print") return "Another operation is unresolved: action="+rejection_value(operation_.value("action",""))+", state="+rejection_value(operation_.value("state",""))+", control.state="+rejection_value(operation_.value("control_request",Json::object()).value("state",""))+", cancel.state="+rejection_value(operation_.value("cancel_request",Json::object()).value("state",""))+".";
  if(action=="cancel_print"&&unresolved(operation_)&&operation_.value("action","")=="cancel_print")return "Cancellation is already pending; wait for its result.";
  if(action=="cancel_print"&&operation_.contains("cancel_request")&&unresolved(operation_["cancel_request"]))return "Cancellation is already pending; wait for its result.";
  if((action=="stop"||action=="reconcile")&&operation_.contains("control_request")&&unresolved(operation_["control_request"]))return "A control request is already unresolved.";
  if(action=="stop"||action=="reconcile") {
   auto allowed=operation_.value("allowed_actions",Json::array());
   if(operation_.empty()||std::find(allowed.begin(),allowed.end(),action)==allowed.end())return "Backend has not permitted this action for the operation.";
  }
  if(action=="prepare"||action=="prime"||action=="confirm-material"||action=="resume") {
   auto allowed=data_.value("job",Json::object()).value("allowed_actions",Json::array());
   if(std::find(allowed.begin(),allowed.end(),action)==allowed.end())return "Recovery phase has not permitted action="+rejection_value(action)+"; job.state="+rejection_value(data_.value("job",Json::object()).value("state",""))+".";
  }
  const auto job=data_.value("job",Json::object()).value("state","unknown");
  if(action=="cancel_print"&&job!="paused"&&job!="printing")return "No active print to cancel.";
  if(action=="start_print"&&job!="idle"&&job!="complete")return "Another print is active.";
  bool cosmetic=false,recipe_write=false;
  if(action=="save_identity"&&data_.value("owner","")=="standalone"&&draft_.is_object()){
   const auto source=find("sources",draft_.value("id",""));
   recipe_write=filament_recipe_write_allowed(data_,draft_.value("head",""));
   cosmetic=source&&source->value("kind","")=="external"&&source->value("head","")==draft_.value("head","")&&filament_cosmetic_edit(source->value("identity",Json()),draft_.value("identity",Json()));
   const auto identification=data_.value("identification",Json::object()).value("state","");
   if(identification=="pending"||identification=="running")return "Wait for head identification to finish before saving filament settings: identification.state="+rejection_value(identification)+".";
   if(!cosmetic&&(job=="idle"||job=="complete")){const auto why=filament_recipe_service_reason(data_,draft_.value("head",""));if(!why.empty())return why;}
  }
  if (job=="unknown"&&!cosmetic) return "Print state is unknown.";
  if ((action=="remove_unit" || action=="save_unit" || action=="adopt" || (action=="save_identity"&&!cosmetic&&!recipe_write) || action=="import_profiles") && job!="idle" && job!="complete") return "Action="+rejection_value(action)+" requires idle or complete job; current="+rejection_value(job)+".";
  if (!data_.value("capabilities",Json::object()).value(action,false)) return "Backend capability is unavailable: "+rejection_value(action)+"=false.";
  return backend_.unavailable(action);
 }
 // UI events carry stable IDs, never raw G-code. Renderer only dispatches IDs
 // present in the current layout. Tests/adapters may call this method directly.
 void event(const std::string& id, const std::string& value="") {
  notice_.clear();
  if (id=="stay") {pending_page_.clear();modal_.clear();return;}
  if (id=="discard") {draft_=Json();modal_.clear();page_=pending_page_;pending_page_.clear();return;}
  if(id=="source-picker-back"){if(modal_=="routes"){modal_="sources";source_.clear();}return;}
  if (id=="close") {if(modal_=="unavailable"){modal_=explanation_return_;explanation_return_.clear();return;}modal_.clear();pending_page_.clear();return;}
  if(id.compare(0,8,"explain:")==0){auto view=render();for(const auto&w:view["widgets"])if(w["id"]==id.substr(8)&&w["kind"]=="button"&&w["enabled"]==false){explanation_=w.value("reason","");if(explanation_.empty())explanation_="This control is unavailable in the current state.";explanation_return_=modal_;modal_="unavailable";return;}return;}
  if (id=="nav:home" || id=="nav:files" || id=="nav:filaments" || id=="nav:tools" || id=="nav:job" || id=="nav:import") {navigate(id.substr(4));return;}
  if (id.compare(0,9,"settings:")==0) {settings_=id.substr(9);navigate(settings_=="Filament"?"filaments":"retained");return;}
  if (id.compare(0,10,"home-head:")==0) {if(find("heads",id.substr(10))){head_=id.substr(10);navigate("tools");}return;}
  if (id=="back") {navigate(origin_);return;}
  if (id.compare(0,5,"head:")==0) {if(find("heads",id.substr(5)))head_=id.substr(5);return;}
  if (id.compare(0,5,"step:")==0) {const auto s=id.substr(5);if(s=="1"||s=="5"||s=="10"||s=="25"||s=="50")step_=std::stoi(s);return;}
  if (id=="temperature") {key_target_="temperature";key_text_=std::to_string(temperature_);modal_="keypad";return;}
  if (id=="unit-name" && !draft_.is_null()) {key_target_="name";key_text_=draft_.value("name","");modal_="keyboard";return;}
  if (id.compare(0,4,"key:")==0) {auto k=id.substr(4);if(k=="backspace"){if(!key_text_.empty()){auto end=key_text_.size()-1;while(end>0&&(static_cast<unsigned char>(key_text_[end])&0xc0)==0x80)--end;key_text_.erase(end);}}else if(k=="space")key_text_+=" ";else if(key_text_.size()<48)key_text_+=k;return;}
  if (id=="key-save") {if(key_target_=="temperature") {
    try {std::size_t used=0;auto n=std::stoi(key_text_,&used);if(used!=key_text_.size()||n<0||n>350)throw std::runtime_error("range");temperature_=n;}catch(...){notice_="Enter a temperature from 0 to 350 C. The backend also checks this head's limits.";return;}
   }else if(!draft_.is_null())draft_["name"]=key_text_;modal_.clear();return;}
  if (id.compare(0,5,"unit:")==0) {if(dirty()){notice_="Save or discard the current draft first.";return;}auto p=find("units",id.substr(5));if(!p)return;origin_=page_;draft_=*p;baseline_=data_.value("revision","");draft_kind_="unit";modal_.clear();page_="unit";return;}
  if (id.compare(0,7,"assign:")==0 && draft_kind_=="unit" && !draft_.is_null()) {slot_=id.substr(7);modal_="assign";return;}
  if (id.compare(0,11,"assignment:")==0 && draft_kind_=="unit" && !draft_.is_null()) {
   auto h=id.substr(11);if(h!=""&&!find("heads",h))return;draft_["assignments"][slot_]=h;modal_.clear();return;}
  if (id=="quick-all" && draft_kind_=="unit" && !draft_.is_null()) {for(auto&s:data_["sources"])if(s.value("unit","")==draft_.value("id",""))draft_["assignments"][s["id"].get<std::string>()]=head_;return;}
  if (id=="quick-distribute" && draft_kind_=="unit" && !draft_.is_null()) {std::size_t i=0;for(auto&s:data_["sources"])if(s.value("unit","")==draft_.value("id","")&&!data_["heads"].empty())draft_["assignments"][s["id"].get<std::string>()]=data_["heads"][i++%data_["heads"].size()]["id"];return;}
  if (id.compare(0,5,"edit:")==0) {if(dirty()){notice_="Save or discard the current draft first.";return;}auto p=find("sources",id.substr(5));if(!p)return;origin_=page_;draft_=*p;baseline_=data_.value("revision","");draft_kind_="identity";modal_.clear();page_="identity";return;}
  if (id=="edit-loaded"&&data_.value("owner","")=="standalone") {auto source=external(head_);if(!source.empty())event("edit:"+source);return;}
  if (id=="edit-loaded") {auto h=find("heads",head_);if(!h)return;auto source=h->value("loaded",Json::object()).value("source","");if(source.empty()&&h->value("loaded",Json::object()).value("state","")=="empty"&&!ace_sources(head_))source=external(head_);if(source.empty()&&h->value("loaded",Json::object()).value("state","")=="empty"){modal_="edit-source";return;}if(source.empty()){notice_="Loaded source is unknown. Resolve its identity before editing.";return;}event("edit:"+source);return;}
  if (id.compare(0,9,"material:")==0 && draft_kind_=="identity" && !draft_.is_null()) {draft_["identity"]["material"]=id.substr(9);if(modal_=="materials")modal_.clear();return;}
  if(id=="brands"||id=="materials"){modal_offset_=0;modal_=id;return;}
  if (id.compare(0,6,"brand:")==0 && draft_kind_=="identity" && !draft_.is_null()) {draft_["identity"]["brand"]=id.substr(6);modal_.clear();return;}
  if (id.compare(0,6,"color:")==0 && draft_kind_=="identity" && !draft_.is_null()) {draft_["identity"]["color"]=id.substr(6);return;}
  if (id=="save") {if(draft_.is_null())return;if(baseline_!=data_.value("revision","")){notice_="Configuration changed. Keep this draft for review; reopen the editor to refresh.";return;}
   if(!assignment_problem().empty()){notice_=assignment_problem();return;}
   submit(draft_kind_=="unit"?"save_unit":"save_identity",{{"draft",draft_}},origin_);return;}
  if (id=="remove") {modal_="remove";return;}
  if (id=="remove-confirm" && !draft_.is_null()) {submit("remove_unit",{{"unit",draft_["id"]}},"filaments");return;}
  if (id=="nav:adopt") {navigate("adopt");return;}
  if (id.compare(0,6,"adopt:")==0) {candidate_=id.substr(6);modal_="adopt";return;}
  if (id=="adopt-confirm") {auto c=find("candidates",candidate_);if(c)submit("adopt",*c,"filaments");else notice_="This discovery is no longer available. Refresh the device list.";return;}
  if (id=="load") {procedure_revision_=data_.value("revision","");intent_="load";operation_origin_="tools";modal_offset_=0;modal_="load-source";return;}
  if (id=="unload") {procedure_revision_=data_.value("revision","");auto h=find("heads",head_);if(!h)return;auto loaded=h->value("loaded",Json::object());
   if(loaded.value("state","")!="loaded"){notice_="No confirmed loaded material.";return;}source_=loaded.value("source","");intent_="unload";operation_origin_="tools";review_procedure();return;}
  if (id.compare(0,12,"load-source:")==0) {auto s=find("sources",id.substr(12));if(!s||s->value("head","")!=head_||!s->value("available",false))return;source_=id.substr(12);review_procedure();return;}
  if (id=="begin") {
   if(modal_!="procedure")return;
   if(procedure().is_null()){notice_="Procedure changed or unavailable. Close and review again.";return;}
   auto bound_head=operation_origin_=="recovery"?recovery_context_.value("head",""):head_;
   if(!find("heads",bound_head)){notice_="Required head is unavailable.";return;}
   submit(intent_,{{"head",bound_head},{"source",source_},{"procedure_token",procedure().at("token")},{"job",operation_origin_=="recovery"?recovery_context_:data_.value("job",Json::object())}},operation_origin_);return;}

  if (id=="extrude" || id=="retract") {submit("step",{{"head",head_},{"mm",id=="retract"?-step_:step_}},"tools",false);return;}
  if (id=="heat" || id=="off") {submit("temperature",{{"head",head_},{"target",id=="off"?0:temperature_}},"tools",false);return;}
  if (id=="take" || id=="dock") {procedure_revision_=data_.value("revision","");intent_=id;source_.clear();operation_origin_="tools";review_procedure();return;}
  if (id=="operation") {navigate("operation");return;}
  if (id=="operation-back") {
   if(!draft_.is_null()){page_=draft_kind_=="unit"?"unit":"identity";return;}
   navigate(operation_.value("origin","tools"));return;
  }
  if (id=="reconcile") {submit("reconcile",{{"operation",operation_}},operation_.value("origin","tools"));return;}
  if (id=="stop") {submit("stop",{{"operation",operation_}},operation_.value("origin","tools"));return;}
  if (id.compare(0,5,"file:")==0) {file_=id.substr(5);selection_=Json::object();preview_revision_=data_.value("revision","");navigate("preview");return;}
  if (id=="thumbnail") {modal_="thumbnail";return;}
  if (id.compare(0,4,"map:")==0) {
   auto file=find("files",file_);bool found=false;if(file)for(const auto&row:file->value("sliced",Json::array()))if(row.value("id","")==id.substr(4))found=true;
   if(page_!="preview"||!found||!preview_state().value("editable",false))return;
   row_=id.substr(4);picker_revision_=data_.value("revision","");modal_offset_=0;modal_="sources";return;
  }
  if (id.compare(0,13,"route-source:")==0) {if(modal_!="sources"||picker_revision_!=data_.value("revision",""))return;source_=id.substr(13);modal_="routes";return;}
  if (id.compare(0,7,"choose:")==0) {if((modal_!="sources"&&modal_!="routes")||picker_revision_!=data_.value("revision","")||!preview_state().value("editable",false))return;auto r=find("routes",id.substr(7));if(!r||!eligible(*r,row_))return;selection_[row_]=r->at("id");preview_revision_=data_.value("revision","");modal_.clear();return;}
  if (id=="leveling" || id=="timelapse") {if(id=="timelapse"&&!timelapse_available_)return;options_[id]=!options_.value(id,false);return;}
  if(id=="material-review-cancel"){material_review_=Json();return;}
  if(id=="start"||id=="material-review-confirm"){
   auto reason=preview_problem();if(reason.empty())reason=unavailable("start_print");
   if(!reason.empty()){material_review_=Json();notice_=reason;return;}
   const bool confirm=id=="material-review-confirm";
   if(confirm&&(material_review_.is_null()||material_review_!=material_binding())){material_review_=Json();notice_="Print context changed. Review the filament selection again.";return;}
   if(!confirm&&(data_.value("owner","")=="standalone"||!material_warning().empty())){material_review_=material_binding();return;}
   Json args={{"file",file_},{"routes",selection_},{"options",options_}};
   if(data_.value("owner","")=="standalone"&&data_.value("print_material_confirmation_protocol",0)==1)args["material_confirmation"]=confirm;
   material_review_=Json();submit("start_print",args,"job");return;
  }
  if (id=="recovery") {navigate("recovery");return;}
  if (id=="resume" || id=="confirm-material" || id=="prepare" || id=="prime") {
   if(id=="prepare"||id=="prime") {procedure_revision_=data_.value("revision","");recovery_context_=data_.value("job",Json::object());intent_=id;operation_origin_="recovery";source_=data_.value("job",Json::object()).value("source","");review_procedure();return;}
   submit(id,{{"job",data_.value("job",Json::object())}},"recovery");return;}
  if (id=="cancel-print") {cancel_context_={{"job",data_.value("job",Json::object())},{"session",data_.value("session","")},{"owner",data_.value("owner","")}};modal_="cancel";return;}
  if (id=="cancel-confirm") {if(cancel_context_!=Json{{"job",data_.value("job",Json::object())},{"session",data_.value("session","")},{"owner",data_.value("owner","")}}){notice_="Print context changed. Review cancellation again.";return;}submit("cancel_print",{{"job",data_.value("job",Json::object())}},"job");return;}
  if (id=="import-usb") {modal_offset_=0;modal_="import-file";return;}
  if (id.compare(0,12,"import-file:")==0) {import_file_=id.substr(12);modal_="import-review";return;}
  if (id=="import-confirm") {if(!data_.value("validated_imports",Json::object()).contains(import_file_)){notice_="Import must be validated by the backend first.";return;}submit("import_profiles",{{"file",import_file_}},"filaments");return;}
  if (id=="scroll-next") {if(modal_.empty())++offset_;else ++modal_offset_;return;}
  if(id=="scroll-prev") {auto&offset=modal_.empty()?offset_:modal_offset_;if(offset)--offset;return;}
  (void)value;
 }
 Json render();
private:
 Backend& backend_;
 Json material_review_;
 Json data_={{"revision",""},{"owner","unknown"},{"fresh",false},{"heads",Json::array()},{"sources",Json::array()},{"units",Json::array()}},draft_,operation_=Json::object(),selection_=Json::object(),options_=Json::object();
 bool timelapse_available_=true;
 std::string page_="home",origin_="filaments",head_,settings_="Filament",modal_,pending_page_,notice_,draft_kind_,baseline_,slot_,key_target_,key_text_,candidate_,source_,intent_,operation_origin_,file_,row_,preview_revision_,import_file_;
 int step_=10,temperature_=220;std::size_t offset_=0,modal_offset_=0;
 std::string explanation_,explanation_return_;
 Json recovery_context_=Json::object(),cancel_context_=Json::object(),reviewed_procedure_;std::string procedure_revision_;std::string picker_revision_;
 std::vector<Widget> widgets_;
 void review_procedure(){reviewed_procedure_=current_procedure();modal_="procedure";
  auto source=find("sources",source_);
  auto job=data_.value("job",Json::object()).value("state","");
  if((job=="idle"||job=="complete")&&reviewed_procedure_.is_null()&&intent_=="load"&&operation_origin_=="tools"&&data_.value("owner","")=="openace"&&source&&source->value("kind","")=="external")modal_="external-load";
 }
 Json procedure()const {
  auto plan=current_procedure();
  return !plan.is_null()&&plan==reviewed_procedure_?plan:Json();
 }
 Json current_procedure()const {
  if(procedure_revision_!=data_.value("revision","")||(operation_origin_=="recovery"&&recovery_context_!=data_.value("job",Json::object())))return Json();
  auto head=operation_origin_=="recovery"?recovery_context_.value("head",""):head_;
  for(const auto&p:data_.value("procedures",Json::array()))if(p.value("action","")==intent_&&p.value("head","")==head&&p.value("source","")==source_&&p.value("revision","")==procedure_revision_&&!p.value("token","").empty())return p;
  return Json();
 }
 static bool valid(const Json&s) {
  try {
   if(s.value("owner","")!="unknown"&&s.value("owner","")!="standalone"&&s.value("owner","")!="openace")return false;
   if(!s.contains("session")||!s["session"].is_string()||!s.at("fresh").is_boolean()||!s.at("owner").is_string()||!s.at("job").is_object()||!s.at("job").at("state").is_string()||!s.at("capabilities").is_object())return false;
   for(const auto&v:s["capabilities"])if(!v.is_boolean())return false;
   for(const auto&key:{"heads","sources","units","routes","files","candidates"}) {
    if(!s.contains(key)){continue;}
    if(!s[key].is_array()||s[key].size()>128)return false;
    std::set<std::string>ids;
    for(const auto&row:s[key]){if(!row.is_object()||!row.contains("id")||!row["id"].is_string()||!ids.insert(row["id"].get<std::string>()).second)return false;
     for(const auto&field:{"name","head","source","unit","kind","label","context","logical_name","device_label","mounting"})if(row.contains(field)&&!row[field].is_string())return false;
     for(const auto&field:{"actual","target"})if(row.contains(field)&&!row[field].is_number_integer())return false;
     for(const auto&field:{"available","connected","eligible"})if(row.contains(field)&&!row[field].is_boolean())return false;
     if(row.value("kind","")=="ace"&&(!row.contains("slot")||!row["slot"].is_number_integer()||row["slot"].get<int>()<0||row["slot"].get<int>()>255))return false;
     if(row.contains("identity")){if(!row["identity"].is_object())return false;for(auto it=row["identity"].begin();it!=row["identity"].end();++it)if(!(s["owner"]=="standalone"&&(it.key()=="brand"||it.key()=="color"))&&!it.value().is_string()&&!((it.key()=="nozzle_temp"||it.key()=="nozzle_temp_min"||it.key()=="nozzle_temp_max"||it.key()=="bed_temp")&&it.value().is_number()))return false;}
     if(row.contains("loaded")){const auto&l=row["loaded"];if(!l.is_object()||!l.at("state").is_string())return false;if(l.contains("source")&&!l["source"].is_string())return false;if(l.contains("identity")){if(!l["identity"].is_object())return false;for(auto it=l["identity"].begin();it!=l["identity"].end();++it)if(!(s["owner"]=="standalone"&&(it.key()=="brand"||it.key()=="color"))&&!it.value().is_string()&&!((it.key()=="nozzle_temp"||it.key()=="nozzle_temp_min"||it.key()=="nozzle_temp_max"||it.key()=="bed_temp")&&it.value().is_number()))return false;}}
     if(row.contains("assignments")){if(!row["assignments"].is_object())return false;for(const auto&v:row["assignments"])if(!v.is_string())return false;}
     if(row.contains("sliced")){if(!row["sliced"].is_array())return false;for(const auto&v:row["sliced"]){if(!v.is_object())return false;for(auto it=v.begin();it!=v.end();++it){if(it.key()=="filament_used_g"||it.key()=="filament_used_mm"){if(!it.value().is_number()||!std::isfinite(it.value().get<double>())||it.value().get<double>()<0)return false;}else if(!it.value().is_string())return false;}}}
     if(row.contains("sliced_rows")){if(!row["sliced_rows"].is_array())return false;for(const auto&v:row["sliced_rows"])if(!v.is_string())return false;}
    }
   }
   if(s["heads"].size()>4)return false;
   for(const auto&field:{"name","source","head","message","hold","id","context"})if(s["job"].contains(field)&&!s["job"][field].is_string())return false;
   if(s["job"].contains("allowed_actions")){if(!s["job"]["allowed_actions"].is_array())return false;for(const auto&v:s["job"]["allowed_actions"])if(!v.is_string())return false;}
   if(s.contains("receipts")){if(!s["receipts"].is_object())return false;for(const auto&r:s["receipts"]){if(!r.is_object()||!r.at("state").is_string())return false;for(const auto&field:{"message","owner","session","action"})if(r.contains(field)&&!r[field].is_string())return false;if(r.contains("allowed_actions")){if(!r["allowed_actions"].is_array())return false;for(const auto&a:r["allowed_actions"])if(!a.is_string())return false;}}}
   for(const auto&field:{"procedures","import_files","brands","materials"})if(s.contains(field)&&!s[field].is_array())return false;
   for(const auto&v:s.value("procedures",Json::array())){if(!v.is_object())return false;for(auto it=v.begin();it!=v.end();++it){if(it.key()=="filament_used_g"||it.key()=="filament_used_mm"){if(!it.value().is_number()||!std::isfinite(it.value().get<double>())||it.value().get<double>()<0)return false;}else if(!it.value().is_string())return false;}}
   for(const auto&field:{"brands","import_files","materials"})for(const auto&v:s.value(field,Json::array()))if(!v.is_string())return false;
   if(s.contains("validated_imports")&&!s["validated_imports"].is_object())return false;
   return true;
  }catch(...){return false;}
 }
 const Json* find(const std::string& collection,const std::string& id)const {
  if(!data_.contains(collection)||!data_[collection].is_array())return nullptr;
  for(const auto&x:data_[collection])if(x.value("id","")==id)return &x;
  return nullptr;
 }
 static bool unresolved(const Json&item) {const auto s=item.value("state","");return s!=""&&s!="complete"&&s!="refused"&&s!="failed";}
 bool busy()const {
  auto active=[&](const Json&r){return unresolved(r)&&!(data_.value("owner","")=="standalone"&&r.value("state","")=="unknown"&&!r.value("delivery_pending",false));};
  return active(operation_)||(operation_.contains("control_request")&&active(operation_["control_request"]))||(operation_.contains("cancel_request")&&active(operation_["cancel_request"]));
 }
 bool ace_sources(const std::string&head)const {if(data_.value("owner","")!="openace")return false;for(const auto&s:data_["sources"])if(s.value("kind","")=="ace"&&s.value("head","")==head)return true;return false;}
 std::string assignment_problem()const {if(draft_kind_!="unit"||draft_.is_null()||data_.value("capabilities",Json::object()).value("save_assignments",false))return "";auto current=find("units",draft_.value("id",""));if(current&&current->value("assignments",Json::object())!=draft_.value("assignments",Json::object()))return "Slot assignment changes are preview only; restore the original assignments to save a name.";return "";}
 std::string external(const std::string& head)const {for(const auto&s:data_["sources"])if(s.value("kind","")=="external"&&s.value("head","")==head)return s.value("id","");return "";}
 bool dirty()const {if(draft_.is_null())return false;auto p=find(draft_kind_=="unit"?"units":"sources",draft_.value("id",""));return !p||*p!=draft_;}
 void navigate(const std::string& target) {material_review_=Json();if(dirty()){pending_page_=target;modal_="discard";return;}draft_=Json();page_=target;modal_.clear();offset_=0;}
 void submit(const std::string& action,Json args,const std::string& origin,bool progress=true) {
  auto why=unavailable(action);
  if(!why.empty()){notice_=why;return;}
  auto receipt=backend_.submit({action,data_.value("revision",""),data_.value("owner","unknown"),args});
  notice_=receipt.message;
  if(receipt.state=="refused"||receipt.id.empty())return;
  if(receipt.state!="pending"&&receipt.state!="unknown")receipt.state="unknown";
  if(action=="stop"||action=="reconcile"||(action=="cancel_print"&&busy())) {
   operation_[action=="cancel_print"?"cancel_request":"control_request"]={{"id",receipt.id},{"owner",data_.value("owner","")},{"session",data_.value("session","")},{"action",action},{"state",receipt.state}};
   notice_="Request sent; waiting for the original operation's reconciled result.";modal_.clear();page_="operation";return;
  }
  operation_={{"id",receipt.id},{"owner",data_.value("owner","")},{"session",data_.value("session","")},{"action",action},{"arguments",args},{"origin",origin},{"state",receipt.state},{"message",receipt.message}};
  modal_.clear();if(progress)page_="operation";
 }
 // A metadata revision does not invalidate unrelated selected print rows.
 // Compare the selected row's binding, not live temperature or other heads.
 static Json selection_binding(const Json&data,const std::string&file,const std::string&row,const std::string&route_id){
  auto unique=[](const Json&items,const std::string&id){Json found;for(const auto&item:items)if(item.value("id","")==id){if(!found.is_null())return Json();found=item;}return found;};
  const auto f=unique(data.value("files",Json::array()),file);
  const auto r=unique(data.value("routes",Json::array()),route_id);
  if(!f.is_object()||!r.is_object()||!r.value("eligible",false))return Json();
  const auto slice=unique(f.value("sliced",Json::array()),row);
  const auto source=unique(data.value("sources",Json::array()),r.value("source",""));
  if(!slice.is_object()||!source.is_object()||!source.value("available",false))return Json();
  const auto head=unique(data.value("heads",Json::array()),source.value("head",""));
  const auto rows=r.value("sliced_rows",Json::array());
  if(!head.is_object()||std::find(rows.begin(),rows.end(),row)==rows.end())return Json();
  auto route=r;route.erase("sliced_rows");route.erase("material_warnings");
  return {{"file",file},{"identity",f.value("file_identity",Json())},{"slice",slice},
   {"route",route},{"warning",r.value("material_warnings",Json::object()).value(row,Json())},
   {"source",source},{"head",head.value("id","")},{"loaded",head.value("loaded",Json::object())},
   {"nozzle",head.value("nozzle",Json::object())}};
 }
 std::string mapping_summary()const {
  std::string text;auto file=find("files",file_);if(!file)return text;
  for(const auto&slice:file->value("sliced",Json::array())){
   const auto id=slice.value("id","");auto route=selection_.contains(id)?find("routes",selection_[id]):nullptr;
   if(!route)continue;
   const auto head=route->value("head","");
   if(head.size()!=2||head[0]!='h'||head[1]<'0'||head[1]>'3')continue;
   if(!text.empty())text+='\n';
   text+="T"+id+": Head "+std::to_string(head[1]-'0'+1);
  }
  return text;
 }
 Json material_binding()const {auto f=find("files",file_);return {{"file",file_},{"file_identity",f?f->value("file_identity",Json()):Json()},{"routes",selection_},{"options",options_},{"revision",data_.value("revision","")},{"session",data_.value("session","")}};}
 std::string material_warning()const {
  if(data_.value("owner","")!="standalone"||data_.value("print_material_confirmation_protocol",0)!=1)return "";
  std::string text;for(auto it=selection_.begin();it!=selection_.end();++it){auto r=find("routes",it.value());if(!r)continue;auto warnings=r->value("material_warnings",Json::object());if(warnings.contains(it.key())){if(!text.empty())text+="\n";text+=warnings[it.key()].get<std::string>();}}
  return text;
 }
 bool eligible(const Json& route,const std::string& row)const {
  auto s=find("sources",route.value("source",""));
  if(!s||!s->value("available",false)||s->value("head","").empty()||!route.value("eligible",false))return false;
  auto allowed=route.value("sliced_rows",Json::array());return std::find(allowed.begin(),allowed.end(),row)!=allowed.end();
 }
 std::string preview_problem()const {
  if(preview_revision_!=data_.value("revision",""))return "Configuration changed. Review the filament mapping again.";
  auto f=find("files",file_);if(!f)return "File is unavailable.";
  if(!f->value("metadata_error","").empty())return data_.value("owner","")=="standalone"?f->value("metadata_error",""):"File metadata is unavailable. Refresh the preview before starting.";
  if(f->value("sliced",Json::array()).empty())return "No sliced filament metadata available.";
  if(data_.value("owner","")=="standalone")for(const auto&s:f->value("sliced",Json::array())){
   const auto id=s.value("id","");
   if(id.size()!=1||id[0]<'0'||id[0]>'3')return "Standalone: reslice using tools T0–T3.";
  }
  for(const auto&s:f->value("sliced",Json::array())) {auto id=s.value("id","");if(!selection_.contains(id))return f->value("usage_known",true)?"Choose a source for every sliced filament.":"Usage unavailable. Choose a source for every preset.";auto r=find("routes",selection_[id]);if(!r||!eligible(*r,id))return "A selected source is no longer eligible.";}
  return "";
 }
 Widget& add(std::string id,std::string text,int x,int y,int w,int h,std::string kind="label") {
  Widget item;item.id=std::move(id);item.text=std::move(text);item.x=x;item.y=y;item.w=w;item.h=h;item.kind=kind;widgets_.push_back(item);return widgets_.back();
 }
 void button(std::string id,std::string text,int x,int y,int w,int h=40,std::string reason="") {auto&b=add(id,text,x,y,w,h,"button");b.enabled=reason.empty();b.reason=reason;}
 void action(std::string id,std::string text,std::string command,int x,int y,int w,int h=40) {button(id,text,x,y,w,h,unavailable(command));}
 std::string head_name(const std::string& id)const {auto h=find("heads",id);return h?h->value("name",id):"Unassigned";}
 static std::string identity_text(const Json& id) {return identity_display_text(id,"brand","Generic")+"\n"+id.value("material","Unknown");}
 void tabs(int y);
 void sources(int y,bool picker=false,bool loading=false,bool editing=false);
 void identity_card(const Json& s,int x,int y,int w,int h,const std::string& click,bool faded=false);
 void modal();
};
}
