#pragma once
#include "management_commands.hpp"
#include "delivery.hpp"
#include <functional>
#include <limits>
namespace wmp_openace {
inline const json&manual_scope(const json&status){
 const auto&f=status.at("manual_flow");
 if(!f.is_object()||!f.contains("version")||!f["version"].is_number_integer()||f["version"]!=1
   ||!f.at("available").is_boolean()||!f.at("available").get<bool>())throw std::runtime_error("Paused manual loading is unavailable");
 auto context=exact_text(f,"context");
 if(context.size()!=64||!std::all_of(context.begin(),context.end(),[](char c){return (c>='0'&&c<='9')||(c>='a'&&c<='f');}))throw std::runtime_error("Current manual context is unavailable");
 if(exact_text(f,"head")!=exact_text(f,"source"))throw std::runtime_error("Not a direct-head source");
 (void)exact_integer(f,"tool",31);(void)safe_gcode_literal(exact_text(f,"head"));return f;
}
inline int manual_mm(const json&v){
 if(!v.is_number()||v.is_boolean())throw std::runtime_error("An explicit whole-millimetre procedure is required");
 const double n=v.get<double>();if(!std::isfinite(n)||n<0||n>5000||std::floor(n)!=n)throw std::runtime_error("This screen cannot request a fractional or unsupported procedure");return int(n);
}
inline std::string manual_command(const json&status,const std::string&action){
 const auto&f=manual_scope(status);
 if(f.at("operation")!="idle"||!f.at("correction_required").is_boolean()||f["correction_required"].get<bool>())throw std::runtime_error("Existing work or physical correction must be settled first");
 const auto&p=f.at("purge");if(!p.at("receipt_write_pending").is_boolean()||p["receipt_write_pending"].get<bool>())throw std::runtime_error("A physical receipt still needs reconciliation");
 std::string out;
 if(action=="prepare")out="OPENACE_LOAD_DIRECT HEAD="+safe_gcode_literal(exact_text(f,"head"));
 else if(action=="plan"){
  if(!p.at("declared_mm").is_null())throw std::runtime_error("A procedure is already declared");
  const int mm=manual_mm(f.at("target_prime_mm"));if(!mm)throw std::runtime_error("No positive target procedure is declared");
  out="OPENACE_CHANGE_PLAN TOOL="+std::to_string(exact_integer(f,"tool",31))+" PURGE_MM="+std::to_string(mm);
 }else if(action=="done"){
  if(p.at("declared_mm").is_null()||p.at("state")=="invalidated")throw std::runtime_error("Review a current declared procedure first");
  const int mm=manual_mm(p.at("remaining_mm"));if(!mm&&p.at("state")!="pending")throw std::runtime_error("The current procedure is already complete");
  out="OPENACE_LOAD_DIRECT HEAD="+safe_gcode_literal(exact_text(f,"head"))+" DONE=1 PRIME="+std::to_string(mm);
 }else throw std::runtime_error("Unsupported manual action");
 return out+" EXPECT_CONTEXT="+exact_text(f,"context");
}
struct ManualFlowView {
 bool visible=false;std::uint64_t serial=0;std::string title,detail;
 std::vector<std::pair<std::string,std::string>>buttons;
};
// Ephemeral presentation and exact delivery correlation, never physical authority.
// current_review_ allows a newly reviewed current request; it is NOT a prepared fact.
class ManualFlowModel {
public:
 using Queue=std::function<std::uint64_t(const std::string&,const std::string&,std::int64_t)>;
 void update(const json&status,bool current,std::uint64_t generation,const Delivery&delivery,const std::string&reason){
  current_=current;status_=status;
  try{
   const auto&f=manual_scope(status_);auto session=exact_integer(status_,"session_id",std::numeric_limits<int>::max());
   auto context=exact_text(f,"context");
   if(session_!=session){current_review_=false;pending_=0;review_.clear();message_.clear();}
   else if(context_!=context&&!pending_){current_review_=false;review_.clear();}
   session_=session;context_=context;
   if(pending_&&(scope(f)!=pending_scope_||(!pending_change_.is_null()&&f.at("change_id")!=pending_change_)))pending_scope_lost_=true;
   if(pending_&&delivery.ticket==pending_&&delivery.outcome!=Delivery::None&&generation>delivery.status_generation&&current_){
    pending_=0;review_.clear();
    if(pending_scope_lost_){
     current_review_=false;message_="An earlier request belongs to a different tool, head or assignment. No current preparation is inferred; review a NEW preparation.";
    }else if(delivery.outcome==Delivery::Replied){
     if(pending_action_=="prepare")current_review_=true;
     message_=pending_action_=="prepare"?"Earlier preparation request returned. Review a NEW current insertion request; this view does not record preparation completion.":"Earlier command returned; review current physical progress below.";
    }else{
     current_review_=false;
     message_=delivery.outcome==Delivery::NotSent?"Request was not sent. Review a new request.":"Outcome unknown. No physical command will be replayed. Review current facts; a new preparation is a separate request.";
    }
    if(!reason.empty()&&reason.size()<=400)message_=reason+"\n"+message_;
   }
  }catch(...){current_review_=false;review_.clear();}
  rebuild();
 }
 const ManualFlowView&view()const{return view_;}
 std::string command(const std::string&action)const{return manual_command(status_,action);}
 bool press(const std::string&id,std::uint64_t serial,const Queue&queue){
  if(!current_||serial!=view_.serial||pending_)return false;
  if(std::none_of(view_.buttons.begin(),view_.buttons.end(),[&](const std::pair<std::string,std::string>&b){return b.first==id;}))return false;
  try{
   if(id=="back"){review_.clear();}
   else if(id=="apply"){
    auto command=manual_command(status_,review_);if(command!=review_command_)throw std::runtime_error("The shown manual request changed; review again");
    auto ticket=queue(review_,command,session_);if(!ticket)throw std::runtime_error("Another request is pending");pending_=ticket;pending_action_=review_;const auto&flow=manual_scope(status_);pending_scope_=scope(flow);pending_change_=flow.at("change_id");pending_scope_lost_=false;
   }else{review_=id;review_command_=manual_command(status_,id);}
   rebuild();return true;
  }catch(const std::exception&e){message_=e.what();review_.clear();rebuild();return false;}
 }
private:
 json status_,pending_change_;bool current_=false,current_review_=false,pending_scope_lost_=false,render_current_=false;std::int64_t session_=-1;std::uint64_t pending_=0;
 std::string context_,pending_scope_,render_context_;std::int64_t render_session_=-1;
 std::string pending_action_,review_,review_command_,message_;ManualFlowView view_;
 static std::string scope(const json&f){return json::array({f.at("tool"),f.at("head"),f.at("source"),f.at("identity"),f.at("temperature")}).dump();}
 static std::string text(const json&v){if(v.is_null())return "unknown";auto s=v.is_string()?v.get<std::string>():v.dump();if(s.size()>256)throw std::runtime_error("Manual label exceeds screen limit");for(unsigned char c:s)if(c<32||c==127)throw std::runtime_error("Manual label contains unsupported controls");return s;}
 void rebuild(){
  ManualFlowView next;
  try{
   const auto&f=manual_scope(status_);next.visible=true;next.title="Load T"+text(f.at("tool"))+" / "+text(f.at("head"));
   next.detail="Assigned: "+(f.at("identity").is_null()?"unknown":text(f["identity"].at("material"))+" "+text(f["identity"].at("color")))+"\n";
   const auto&loaded=f.at("loaded");next.detail+="Loaded record: "+(loaded.is_null()?std::string("unknown"):loaded.at("state")=="loaded"&&loaded.at("verified")==true?text(loaded.at("material"))+" "+text(loaded.at("color")):std::string("not verified"))+"\n";
   next.detail+="Print / procedure C: "+text(f.at("temperature").at("print_c"))+" / "+text(f["temperature"].at("procedure_c"));
   next.detail+="\nSensor: "+text(f.at("presence"))+"; mounted: "+text(f.at("mounted"));
   const auto&p=f.at("purge");next.detail+="\nPurge completed / remaining: "+text(p.at("completed_mm"))+" / "+text(p.at("remaining_mm"));
   if(p.at("remaining_mm").is_number()){double n=p["remaining_mm"].get<double>();if(!std::isfinite(n)||n<0||n>5000||std::floor(n)!=n)next.detail+="\nThis screen cannot request this fractional or unsupported purge; use a supported owner procedure.";}
   if(!message_.empty())next.detail+="\n"+message_;
   if(!current_)next.detail+="\nStatus unavailable; no physical action enabled";
   else if(pending_)next.detail+="\nWaiting for delivery and current status";
   else if(!review_.empty()){
    (void)manual_command(status_,review_);
    next.detail+="\nReview "+review_+" on this head";
    if(review_=="prepare")next.detail+=". May select, park, heat and clear old filament.";
    else if(review_=="plan")next.detail+=": target procedure "+text(f.at("target_prime_mm"))+"mm, not a universal colour flush.";
    else next.detail+=". I inserted filament; request "+text(p.at("remaining_mm"))+"mm.";
    next.buttons={{"apply",review_=="prepare"?"Prepare head":review_=="plan"?"Declare procedure":"Inserted — prime"},{"back","Cancel"}};
   }else{
    for(const auto&action:std::vector<std::string>{"prepare","plan","done"}){
     if(action=="done"&&!current_review_&&!p.value("known_partial_continuation",false))continue;
     try{(void)manual_command(status_,action);next.buttons.emplace_back(action,action=="prepare"?"Review NEW preparation":action=="plan"?"Review target procedure":"Inserted / prime");}catch(const std::exception&){}
    }
    if(f.at("correction_required").get<bool>())next.detail+="\n"+text(f.at("correction_reason"));
   }
   if(next.detail.size()>2048)throw std::runtime_error("Manual view exceeds screen limit");
  }catch(const std::exception&e){next.visible=status_.contains("manual_flow")&&status_["manual_flow"].is_object()&&status_["manual_flow"].contains("available")&&status_["manual_flow"]["available"].is_boolean()&&status_["manual_flow"]["available"].get<bool>();next.title="Manual load unavailable";next.detail=e.what();next.buttons.clear();}
  auto signature=[](const ManualFlowView&v){std::string s=v.title+v.detail;for(const auto&b:v.buttons)s+=b.first+b.second;return s;};
  next.serial=view_.serial+(signature(next)!=signature(view_)||context_!=render_context_||session_!=render_session_||current_!=render_current_);render_context_=context_;render_session_=session_;render_current_=current_;view_=std::move(next);
 }
};
}
