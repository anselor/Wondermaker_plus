#pragma once
#include "openace_view.hpp"
#include "delivery.hpp"
#include "management_commands.hpp"
#include "manual_flow.hpp"
#include <limits>
#include <memory>
#include <mutex>
namespace wmp_openace {
struct UiSnapshot {View view;std::int64_t received_at_ms;Delivery delivery;std::uint64_t status_generation;std::shared_ptr<const json>management;std::string delivery_message;std::shared_ptr<const json>manual_status;
 UiSnapshot(View v,std::int64_t at,Delivery d,std::uint64_t generation,std::shared_ptr<const json>m,std::string message,std::shared_ptr<const json>manual=nullptr):view(std::move(v)),received_at_ms(at),delivery(d),status_generation(generation),management(std::move(m)),delivery_message(std::move(message)),manual_status(std::move(manual)){}
};
struct QueuedCommand {enum Kind{Confirmation,Management,ManualFlow};Kind kind=Confirmation;std::string manual_action;std::uint64_t ticket=0;std::string command;bool management=false;json request;std::int64_t session=-1;};
class UiChannel {
public:
 std::uint64_t enqueue(const std::string&command){
  if(!valid_confirmation(command))return 0;
  QueuedCommand item;item.command=command;return put(std::move(item));
 }
 std::uint64_t enqueue_management(const json&request,const std::string&command,std::int64_t session){
  static const std::set<std::string>actions={"scan","unit_add","unit_accept","unit_set","unit_remove","unit_rename","map_tool","unmap_tool","source_set","source_reset","head_set","head_reset","set_filament"};
  if(!request.is_object()||!request.contains("action")||!request["action"].is_string()
    ||!actions.count(request["action"].get<std::string>())||request.dump().size()>2048||command.size()>384||session<0)return 0;
  QueuedCommand item;item.command=command;item.request=request;item.management=true;item.kind=QueuedCommand::Management;item.session=session;return put(std::move(item));
 }
 std::uint64_t enqueue_manual(const std::string&action,const std::string&command,std::int64_t session){
  if((action!="prepare"&&action!="plan"&&action!="done")||command.size()>256||session<0)return 0;
  QueuedCommand item;item.kind=QueuedCommand::ManualFlow;item.manual_action=action;item.command=command;item.session=session;return put(std::move(item));
 }
 void set_management_open(bool value){std::lock_guard<std::mutex>lock(mutex_);management_open_=value;}
 bool management_open(){std::lock_guard<std::mutex>lock(mutex_);return management_open_;}

 QueuedCommand take(){std::lock_guard<std::mutex>lock(mutex_);QueuedCommand r=std::move(pending_);pending_=QueuedCommand();if(r.ticket)in_flight_=r.ticket;return r;}
 void settle(std::uint64_t ticket){std::lock_guard<std::mutex>lock(mutex_);if(in_flight_==ticket)in_flight_=0;}
 void publish(std::shared_ptr<const UiSnapshot>value){std::lock_guard<std::mutex>lock(mutex_);snapshot_=std::move(value);}
 std::shared_ptr<const UiSnapshot>latest(){std::lock_guard<std::mutex>lock(mutex_);return snapshot_;}
 static bool valid_confirmation(const std::string&command){
  const std::string prefix="OPENACE_CONFIRM_CHANGE TOOL=",middle=" CONFIRM=1 EXPECT_CONTEXT=";
  if(command.size()>160||command.compare(0,prefix.size(),prefix))return false;
  const auto split=command.find(middle,prefix.size());if(split==std::string::npos)return false;
  auto number=command.substr(prefix.size(),split-prefix.size());
  if(number.empty()||number.size()>2||!std::all_of(number.begin(),number.end(),[](char c){return c>='0'&&c<='9';}))return false;
  int tool=std::stoi(number);if(tool>31||std::to_string(tool)!=number)return false;
  const auto digest=command.substr(split+middle.size());return digest.size()==64
   &&std::all_of(digest.begin(),digest.end(),[](char c){return(c>='0'&&c<='9')||(c>='a'&&c<='f');});
 }
private:
 std::uint64_t put(QueuedCommand item){
  std::lock_guard<std::mutex>lock(mutex_);
  if(pending_.ticket||in_flight_||next_ticket_==std::numeric_limits<std::uint64_t>::max())return 0;
  item.ticket=++next_ticket_;pending_=std::move(item);return pending_.ticket;
 }
 std::mutex mutex_;QueuedCommand pending_;std::uint64_t next_ticket_=0,in_flight_=0;bool management_open_=false;std::shared_ptr<const UiSnapshot>snapshot_;
};
struct HttpPort {
 virtual ~HttpPort(){}
 virtual std::string get(const std::string&path)=0;
 virtual std::string post(const std::string&path,const std::string&json_body)=0;
};
// Called only by the worker. No LVGL pointer, callback or native command ABI.
class ScreenWorker {
public:
 ScreenWorker(HttpPort&http,UiChannel&channel):http_(http),channel_(channel){}
 static const char*query(){return "/printer/objects/query?openace=session_id,material_change_prompt,loaded,manual_flow";}
 static const char*management_query(){return "/printer/objects/query?openace=session_id,material_change_prompt,loaded,manual_flow,management,unit_discovery,unit_settings,heads,units,default_tool_map,inventory";}
 void poll(std::int64_t now)noexcept {
  status_at_=now;
  try{
   auto body=http_.get(channel_.management_open()?management_query():query());
   if(!ScreenModel::acceptable_payload(body))throw std::runtime_error("bounded reply required");
   auto reply=json::parse(body);
   if(!reply.is_object()||reply.contains("error")||!reply.contains("result")||!reply["result"].is_object()
      ||!reply["result"].contains("status")||!reply["result"]["status"].is_object())throw std::runtime_error("invalid object query reply");
   observe_status(reply["result"]["status"],now);
  }catch(...){disconnected();}
 }
 // Unified screens already fetched this status. Reuse that observation so
 // legacy prompts and native controls share one response and receipt time.
 void observe_status(const json&status,std::int64_t now)noexcept {
  status_at_=now;
  try{
   if(!status.is_object())throw std::runtime_error("invalid shared status");
   if(!status.contains("openace"))model_.update("",false,now);
   else model_.update(status["openace"].dump(),true,now);
   manual_.reset();if(status.contains("openace")&&status["openace"].is_object()&&status["openace"].contains("manual_flow"))manual_=std::make_shared<const json>(status["openace"]);
   management_.reset();
   if(channel_.management_open()&&status.contains("openace")&&status["openace"].is_object())management_=std::make_shared<const json>(status["openace"]);
   ++status_generation_;publish();
  }catch(...){disconnected();}
 }
 void disconnected()noexcept {
  model_.disconnected();manual_.reset();management_.reset();
  try{publish();}catch(...){}
 }
 void deliver(std::int64_t now)noexcept {
  QueuedCommand queued;bool attempted=false,replied=false;
  try{
   queued=channel_.take();if(!queued.ticket)return;
   delivery_message_.clear();
   auto post=[&](const std::string&command){
    attempted=true;
    auto body=http_.post("/printer/gcode/script",json{{"script",command}}.dump());
    if(!ScreenModel::acceptable_payload(body))return false;
    auto reply=json::parse(body);
    replied=reply.is_object()&&!reply.contains("error")&&reply.contains("result")&&reply["result"]=="ok";
    if(!replied)delivery_message_=backend_error(reply);
    return replied;
   };
   if(queued.kind==QueuedCommand::ManualFlow){
    if(manual_&&model_.view().connected&&model_.view().data_current&&status_at_>=0&&now>=status_at_&&now-status_at_<=2000
       &&manual_->at("session_id")==queued.session){
     const auto command=manual_command(*manual_,queued.manual_action);if(command==queued.command)post(command);
    }
   }else if(queued.management){
    if(channel_.management_open()&&management_&&model_.view().connected&&model_.view().data_current
      &&status_at_>=0&&now>=status_at_&&now-status_at_<=2000
      &&management_->at("session_id")==queued.session){
     const auto current=management_command(*management_,queued.request);
     if(current==queued.command)post(current);
    }
   }else{
    model_.click_confirm(model_.view().serial,now,[&](const std::string&current){
     return current==queued.command?post(current):false;
    });
   }

   delivery_.ticket=queued.ticket;delivery_.status_generation=status_generation_;
   delivery_.outcome=!attempted?Delivery::NotSent:replied?Delivery::Replied:Delivery::Unknown;
   if(attempted&&model_.view().confirm_enabled)model_.command_failed();
   channel_.settle(queued.ticket);
   publish(); // Completion is delivery only, never approval or a retry request.
  }catch(...){
   if(queued.ticket){delivery_.ticket=queued.ticket;delivery_.status_generation=status_generation_;delivery_.outcome=attempted?Delivery::Unknown:Delivery::NotSent;}
   delivery_message_=attempted?"Outcome unknown; refresh current values before another explicit action":"Request not sent; refresh and review the selected setting";
   if(queued.ticket)channel_.settle(queued.ticket);
   model_.command_failed();try{publish();}catch(...){}
  }
 }

private:
 HttpPort&http_;UiChannel&channel_;ScreenModel model_;Delivery delivery_;std::shared_ptr<const json>management_,manual_;std::string delivery_message_;
 std::uint64_t status_generation_=0;std::int64_t status_at_=-1;
 static std::string backend_error(const json&reply){
  const std::string fallback="Command reported an error; review current values before retrying";
  if(!reply.is_object()||!reply.contains("error")||!reply["error"].is_object()
    ||!reply["error"].contains("message")||!reply["error"]["message"].is_string())return fallback;
  auto text=reply["error"]["message"].get<std::string>();if(text.empty())return fallback;
  if(text.size()>256){std::size_t n=256;while(n&&(static_cast<unsigned char>(text[n])&0xc0)==0x80)--n;text=text.substr(0,n)+"...";}
  bool controls=false;for(unsigned char c:text)if(c<32||c==127)controls=true;
  if(controls)text=json(text).dump();
  if(text.size()>384)return fallback;
  return "Backend: "+text;
 }
 void publish(){channel_.publish(std::make_shared<const UiSnapshot>(UiSnapshot{model_.view(),status_at_,delivery_,status_generation_,management_,delivery_message_,manual_}));}
};
}
