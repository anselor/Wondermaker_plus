#pragma once
#include "management_commands.hpp"
#include "delivery.hpp"
#include <memory>
#include <vector>
namespace wmp_openace {
struct ManagementPanel {
 std::string title,detail;
 std::vector<std::pair<std::string,std::string>>buttons;
 std::uint64_t serial=0;
};
// Ephemeral fixed setup pages/drafts only. No print, recovery or configuration
// authority lives here; the backend remains the owner of every Apply.
class ManagementPanelModel {
public:
 using Queue=std::function<std::uint64_t(const json&,const std::string&,std::int64_t)>;
 void open(){open_=true;page_=Home;error_.clear();rebuild();}
 void close(){open_=false;identity_request_=json();request_=json();draft_.clear();expected_.clear();error_.clear();}
 bool opened()const{return open_;}
 const ManagementPanel&view()const{return panel_;}
 void update(std::shared_ptr<const json>status,bool current,std::uint64_t generation,const Delivery&delivery,const std::string&delivery_message=""){
  current_=current;status_=std::move(status);
  if(status_&&status_->contains("session_id")&&(*status_)["session_id"].is_number_integer()){
   auto session=(*status_)["session_id"].get<std::int64_t>();
   if(session_!=-1&&session_!=session){page_=Home;request_=json();identity_request_=json();draft_.clear();expected_.clear();pending_=0;error_="Printer restarted; review current settings";}
   session_=session;
  }
  if(pending_&&delivery.ticket==pending_&&delivery.outcome!=Delivery::None&&generation>delivery.status_generation&&current_){
   pending_=0;error_=delivery.outcome==Delivery::NotSent?"Request was not sent; review the current selection":delivery.outcome==Delivery::Unknown?"Outcome unknown; review current values before another Apply":"Command delivered; current backend values shown";
   if(!delivery_message.empty()&&delivery_message.size()<=400)error_=delivery_message+"\n"+error_;
  }
  rebuild();
 }
 bool press(const std::string&id,std::uint64_t serial,const Queue&queue){
  if(!open_||serial!=panel_.serial)return false;
  if(std::none_of(panel_.buttons.begin(),panel_.buttons.end(),[&](const std::pair<std::string,std::string>&b){return b.first==id;}))return false;
  try{
   error_.clear();
   if(id=="close"){close();return true;}
   if(id=="back"){page_=Home;request_=json();identity_request_=json();}
   else if(id=="devices"){page_=Devices;index_=0;}
   else if(id=="tools"){page_=Tools;index_=0;tool_head_=0;tool_source_=0;}
   else if(id=="sources"){page_=Sources;index_=0;field_=0;}
   else if(id=="heads"){page_=Heads;index_=0;field_=0;}
   else if(id=="filament"){page_=Identity;index_=0;field_=0;identity_request_=json();}
   else if(id=="prev"||id=="next"){if(id=="next")++index_;else if(index_)--index_;field_=0;identity_request_=json();}
   else if(id=="field"){++field_;}
   else if(id=="scan"){prepare(json{{"action","scan"}});}
   else if(id=="add"){
    auto row=device_rows().at(index_%device_rows().size());
    request_=json{{"action","unit_add"},{"unit",suggest_unit()},{"context",row.at("expect_context")}};
    edit_key_="unit";draft_=request_["unit"];alphabet_=letters();keys_=0;page_=Input;
   }else if(id=="accept"){
    auto row=device_rows().at(index_%device_rows().size());auto unit=row.at("unit").get<std::string>();
    prepare(json{{"action","unit_accept"},{"unit",unit},{"context",m().at("units").at(unit).at("accept_context")}});
   }else if(id=="unit_fields"){
    auto row=device_rows().at(index_%device_rows().size());unit_=row.at("unit").get<std::string>();page_=UnitFields;field_=0;
   }else if(id=="remove"){
    auto row=device_rows().at(index_%device_rows().size());prepare(json{{"action","unit_remove"},{"unit",row.at("unit")}});
   }else if(id=="rename"){
    auto row=device_rows().at(index_%device_rows().size());request_=json{{"action","unit_rename"},{"unit",row.at("unit")}};
    edit_key_="name";draft_=row.value("name",row.at("unit").get<std::string>());alphabet_=letters();keys_=0;page_=Input;
   }else if(id=="head_cycle"){++tool_head_;}
   else if(id=="source_cycle"){++tool_source_;}
   else if(id=="map"){
    auto heads=head_keys();if(heads.empty())throw std::runtime_error("No configured heads");
    json r{{"action","map_tool"},{"tool",int(index_%32)},{"head",heads[tool_head_%heads.size()]}};
    auto sources=source_keys();if(!sources.empty()&&tool_source_%(sources.size()+1))address(r,sources[(tool_source_-1)%sources.size()]);
    prepare(r);
   }else if(id=="unmap"){prepare(json{{"action","unmap_tool"},{"tool",int(index_%32)}});}
   else if(id=="edit"){start_edit();}
   else if(id=="assignment_review"){if(identity_request_.is_null())throw std::runtime_error("Edit assignment values first");prepare(identity_request_);}
   else if(id=="discard_draft"){identity_request_=json();}
   else if(id=="reset"){auto r=current_request();r["action"]=page_==Heads?"head_reset":"source_reset";r["fields"]=json::array({field_name()});prepare(r);}
   else if(id=="key_next"){keys_=(keys_+5)%alphabet_.size();}
   else if(id=="erase"){if(!draft_.empty()){auto n=draft_.size()-1;while(n&&((static_cast<unsigned char>(draft_[n])&0xc0)==0x80))--n;draft_.erase(n);}}
   else if(id.compare(0,4,"key:")==0){if(draft_.size()>=256)throw std::runtime_error("Input is too long for this editor");draft_+=id.substr(4);}
   else if(id=="review"){
    auto r=request_;
    if(edit_key_=="unit"||edit_key_=="name")r[edit_key_]=draft_;
    else r["fields"][edit_key_]=draft_;
    if(edit_from_==Identity){identity_request_=r;page_=Identity;}
    else prepare(r);
   }else if(id=="apply"){
    if(pending_)throw std::runtime_error("A request is still awaiting delivery and refreshed status");
    const auto now=management_command(*status_,request_);
    if(now!=expected_)throw std::runtime_error("Selection changed; open and review this setting again");
    auto ticket=queue(request_,expected_,session_);if(!ticket)throw std::runtime_error("A request is already queued; nothing else was sent");pending_=ticket;
   }
   rebuild();return true;
  }catch(const std::exception&e){error_=e.what();rebuild();return false;}
  catch(...){error_="This setup action is unavailable; nothing was sent";rebuild();return false;}
 }
private:
 enum Page{Home,Devices,Tools,Sources,Heads,Identity,UnitFields,Input,Review};
 Page page_=Home,edit_from_=Home;bool open_=false,current_=false;std::shared_ptr<const json>status_;std::int64_t session_=-1;
 std::size_t index_=0,field_=0,tool_head_=0,tool_source_=0,keys_=0;std::uint64_t pending_=0;
 ManagementPanel panel_;json request_,identity_request_;std::string expected_,error_,unit_,edit_key_,draft_,alphabet_;
 static std::string letters(){return "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-./'";}
 static std::string shown(const json&v){
  if(v.is_null())return "unset";
  if(!v.is_string())return v.dump();
  const auto value=v.get<std::string>();
  for(unsigned char c:value)if(c<32||c==127)return v.dump();
  return value;
 }
 const json&m()const{
  if(!current_||!status_||!status_->contains("management"))throw std::runtime_error("Setup status is loading or unavailable");
  const auto&v=(*status_)["management"];
  if(!management_capability(v,"version"))throw std::runtime_error("This backend does not support these setup pages");
  return v;
 }
 static std::vector<std::string>keys(const json&v){std::vector<std::string>out;if(!v.is_object())return out;for(auto it=v.begin();it!=v.end();++it)out.push_back(it.key());return out;}
 std::vector<std::string>head_keys()const{return keys(m().at("head_settings"));}
 std::vector<std::string>source_keys()const{return keys(m().at("source_settings"));}
 std::vector<std::string>identity_keys()const{if(m().contains("identity_settings"))return keys(m()["identity_settings"]);auto out=head_keys(),sources=source_keys();out.insert(out.end(),sources.begin(),sources.end());return out;}
 std::string selected_key()const{auto list=page_==Heads?head_keys():page_==Identity?identity_keys():source_keys();if(list.empty())throw std::runtime_error("No configured items on this page");return list[index_%list.size()];}
 std::vector<json>device_rows()const{
  std::vector<json>rows;
  if(m().contains("add_candidates"))for(const auto&r:m()["add_candidates"])rows.push_back(r);
  for(auto it=m().at("units").begin();it!=m().at("units").end();++it){auto row=it.value();row["unit"]=it.key();
   if(status_->contains("units"))for(const auto&u:(*status_)["units"])if(u.value("id","")==it.key())row["name"]=u.value("name",it.key());
   rows.push_back(row);
  }
  if(status_->contains("unit_discovery"))for(const auto&row:(*status_)["unit_discovery"]){
   if(!row.value("claimed_by",json()).is_null())continue;
   if(std::none_of(rows.begin(),rows.end(),[&](const json&r){return r.value("device","")==row.value("device","");}))rows.push_back(row);
  }return rows;
 }
 std::string suggest_unit()const{for(int n=0;n<1000;++n){auto name="ace"+std::to_string(n);if(!m()["units"].contains(name))return name;}throw std::runtime_error("Enter an unused unit name");}
 static void address(json&r,const std::string&key){auto colon=key.rfind(':');if(colon==std::string::npos){r["head"]=key;return;}r["unit"]=key.substr(0,colon);r["slot"]=std::stoi(key.substr(colon+1));}
 std::vector<std::string>fields()const{
  if(page_==Heads)return {"capture_mm","capture_step_mm"};
  if(page_==Identity)return {"material","nozzle_temp","color"};
  if(page_==UnitFields)return {"feed_speed","retract_speed","max_feed_mm","assist_mode","stop_survives_disconnect","slots","generation","usb_serial","usb_path"};
  return {"path_clear_mm","unload_mode","feeder_hold_mm","feeder_to_inlet_mm","feed_timeout_s","feed_to_sensor_mm"};
 }
 std::string field_name()const{auto list=fields();return list[field_%list.size()];}
 json current_request()const{
  json r{{"action",page_==Identity?"set_filament":page_==Heads?"head_set":page_==UnitFields?"unit_set":"source_set"},{"fields",json::object()}};
  if(page_==UnitFields)r["unit"]=unit_;else address(r,selected_key());return r;
 }
 const json&value_row()const{
  if(page_==UnitFields)return status_->at("unit_settings").at(unit_);
  if(page_==Identity){
   if(m().contains("identity_settings"))return m().at("identity_settings").at(selected_key());
   if(!status_->contains("inventory")||!status_->at("inventory").is_object()||status_->at("inventory").contains(selected_key()))throw std::runtime_error("This backend cannot preserve recorded identity names; editing is disabled");
   static const json empty=nullptr;return empty;
  }
  return m().at(page_==Heads?"head_settings":"source_settings").at(selected_key());
 }
 void start_edit(){
  edit_from_=page_;request_=page_==Identity&&!identity_request_.is_null()?identity_request_:current_request();edit_key_=field_name();const auto&row=value_row();json value=nullptr;
  if(!row.is_null())value=row.at(page_==Identity?"values":"effective").at(edit_key_);
  if(page_==Identity&&!identity_request_.is_null()&&identity_request_.at("fields").contains(edit_key_))value=identity_request_["fields"][edit_key_];
  draft_=value.is_null()?"":value.is_string()?value.get<std::string>():value.dump();
  if(edit_key_=="color"&&draft_.size()==7&&draft_[0]=='#')draft_=draft_.substr(1);
  const bool text=edit_key_=="material"||edit_key_=="assist_mode"||edit_key_=="unload_mode"||edit_key_=="generation"||edit_key_=="usb_serial"||edit_key_=="usb_path"||edit_key_=="stop_survives_disconnect";
  alphabet_=edit_key_=="color"?"0123456789ABCDEF":text?letters():"0123456789.-";keys_=0;page_=Input;
 }
 void prepare(const json&r){expected_=management_command(*status_,r);request_=r;page_=Review;}
 static std::string field_label(std::string name){std::replace(name.begin(),name.end(),'_',' ');return name;}
 static std::string route_label(const json&r){
  if(r.is_null())return "unassigned";
  return (r.at("unit").is_null()?"manual":r.at("unit").get<std::string>()+":"+shown(r.at("slot")))+" -> "+r.at("head").get<std::string>();
 }
 std::string review_text()const{
  auto action=request_.at("action").get<std::string>();std::string text;
  if(action=="unit_add"){
   text="Register "+request_.at("unit").get<std::string>();
   for(const auto&r:m().at("add_candidates"))if(r.at("expect_context")==request_.at("context"))text+="\nObserved device: "+r.value("device_identity","unknown")+"\nBinding: "+shown(r.value("usb_serial",r.value("usb_path",json())));
  }else if(action=="unit_accept"){
   auto unit=request_.at("unit").get<std::string>();const auto&r=m().at("units").at(unit);
   text="Accept replacement for "+unit+"\nAccepted: "+shown(r.at("accepted_identity").value("device",json()))+"\nObserved: "+shown(r.at("observed_identity").value("device",json()));
  }else if(action=="map_tool"){
   auto route=request_;if(!route.contains("unit")){route["unit"]=nullptr;route["slot"]=nullptr;}
   text="Assign T"+shown(request_.at("tool"))+": "+route_label(route);
  }else if(action=="unmap_tool")text="Unassign T"+shown(request_.at("tool"));
  else if(action=="scan")text="Refresh USB observations; no unit is registered automatically";
  else{
   text=field_label(action)+"\n"+(request_.contains("head")?shown(request_["head"]):shown(request_.at("unit")));
   if(request_.contains("slot"))text+=":"+shown(request_["slot"]);
   if(request_.contains("name"))text+="\nName: "+shown(request_["name"]);
   if(request_.contains("fields")){
    const auto&values=request_["fields"];
    if(values.is_array())for(const auto&field:values)text+="\nReset "+field_label(field.get<std::string>());
    else for(auto it=values.begin();it!=values.end();++it)text+="\n"+field_label(it.key())+": "+shown(it.value());
   }
  }
  return text+"\nOnly Apply sends this change";
 }
 void rebuild(){
  if(!open_)return;
  ManagementPanel next;next.title="openACE setup";
  auto button=[&](const std::string&id,const std::string&text){next.buttons.emplace_back(id,text);};
  try{
   (void)m();
   if(page_==Home){next.detail="Choose a setting. Apply saves configuration only; it does not load filament.";button("devices","Devices");button("tools","Tools");button("sources","Sources");button("heads","Heads");button("filament","Filament");button("close","Close");}
   else if(page_==Devices){
    auto rows=device_rows();next.title="Devices";
    if(rows.empty())next.detail="No USB candidates or registered units";
    else{const auto&r=rows[index_%rows.size()];
     if(r.contains("unit")){auto uid=r["unit"].get<std::string>();next.detail=shown(r.value("name",json(uid)))+" ("+uid+")\nRegistered binding: "+shown(r["binding"])+"\nAccepted: "+shown(r["accepted_identity"].value("device",json()));
      if(!r["observed_identity"].is_null())next.detail+="\nObserved replacement: "+shown(r["observed_identity"].value("device",json()));
      if(r["accept_context"].is_string())button("accept","Review replacement");
      button("unit_fields","Unit settings");button("rename","Rename");button("remove","Review removal");
     }else{next.detail="USB: "+shown(r.value("device",json("")))+"\nIdentity: "+shown(r.value("device_identity",json("unknown")))+"\nFirmware: "+shown(r.value("firmware",json("unknown")))+"\nState: "+shown(r.value("identification",json("candidate")));if(r.contains("expect_context"))button("add","Register selected");}
     button("prev","Previous");button("next","Next");
    }button("scan","Scan");button("back","Back");
   }else if(page_==Tools){
    auto heads=head_keys(),sources=source_keys();if(heads.empty())throw std::runtime_error("No configured heads");
    auto tool=std::to_string(index_%32);next.title="Tool T"+tool;
    next.detail="Current: "+(status_->at("default_tool_map").contains(tool)?route_label(status_->at("default_tool_map")[tool]):"unassigned")+"\nProposed head: "+heads[tool_head_%heads.size()]+"\nProposed source: "+(sources.empty()||tool_source_%(sources.size()+1)==0?"manual":sources[(tool_source_-1)%sources.size()]);
    button("prev","Previous tool");button("next","Next tool");button("head_cycle","Choose head");button("source_cycle","Choose source");button("map","Review route");button("unmap","Review unmap");button("back","Back");
   }else if(page_==Sources||page_==Heads||page_==Identity||page_==UnitFields){
    auto key=page_==UnitFields?unit_:selected_key();auto field=field_name();next.title=key+" settings";
    const auto&row=value_row();json value=nullptr;
    if(!row.is_null())value=row.at(page_==Identity?"values":"effective").at(field);
    bool draft=page_==Identity&&!identity_request_.is_null()&&identity_request_.at("fields").contains(field);
    if(draft)value=identity_request_["fields"][field];
    next.detail=field_label(field)+": "+shown(value)+(draft?" (not saved)":"");
    if(page_==Identity){next.detail+="\nA Save is a user assignment; device weight/provenance are read-only.";if(!row.is_null())next.detail+="\n"+shown(row.at("display_name"));}
    else{next.detail+="\nOrigin: "+row.at("origins").value(field,"unknown");if(page_==Sources)next.detail+="\nGeometry values are declarations, not measured position.";}
    button("field","Next field");button("edit","Edit value");if(page_==Sources||page_==Heads)button("reset","Review reset");
    if(page_==Identity&&!identity_request_.is_null()){button("assignment_review","Review assignment");button("discard_draft","Discard draft");}
    if(page_!=UnitFields){button("prev","Previous item");button("next","Next item");}button("back","Back");
   }else if(page_==Input){
    next.title="Edit "+edit_key_;next.detail=draft_.empty()?"(empty)":shown(json(draft_));
    for(std::size_t i=0;i<5;++i){char c=alphabet_[(keys_+i)%alphabet_.size()];button(std::string("key:")+c,c==' '?"space":std::string(1,c));}
    button("key_next","More keys");button("erase","Backspace");button("review","Review");button("back","Cancel");
   }else if(page_==Review){
    next.title="Review explicit change";next.detail=review_text();
    if(!pending_)button("apply","Apply");else next.detail+="\nWaiting for delivery and current status";
    button("back","Cancel / Back");
   }
   if(!error_.empty())next.detail+="\n"+error_;
   for(const auto&label:std::vector<std::string>{next.title,next.detail})
    for(unsigned char c:label)if((c<32&&c!='\n')||c==127)throw std::runtime_error("Selected text contains unsupported control characters; no action enabled");
   if(next.detail.size()>2048)throw std::runtime_error("Selected data is too large for this screen; no action enabled");
  }catch(const std::exception&e){next.title="openACE setup";next.detail=e.what();next.buttons.clear();button("back","Back");button("close","Close");}
  std::string before=panel_.title+panel_.detail,after=next.title+next.detail;
  for(const auto&b:panel_.buttons)before+=b.first+b.second;
  for(const auto&b:next.buttons)after+=b.first+b.second;
  next.serial=panel_.serial+(before==after?0:1);panel_=std::move(next);
 }
};
}
