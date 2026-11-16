// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "button_caption.hpp"
#include "stock_progress_panel.hpp"
#include "plr_progress_steps.hpp"
#include "stock_dialog_backdrop.hpp"
#include "../model.hpp"
#include <cmath>
#include <functional>
#include <map>
#include <string>
#include <vector>
namespace wmp_ui { namespace native {
// GUI-thread only. Status updates retain every widget and the scroll position.
// Closing this view never stops or repeats an operation.
class StockRecoveryProgress {
 StockProgressPanel progress_;
 void*root_=nullptr,*screen_=nullptr,*stop_=nullptr,*review_=nullptr,*summary_=nullptr,*close_=nullptr,*title_=nullptr;
 bool compact_=false;int dialog_x_=0,dialog_y_=0,dialog_h_=0;
 Json result_=Json::object();std::string id_;bool cancel_mode_=false,externally_deleted_=false,rendered_=false;
 template<class F>static F fn(std::uintptr_t a){return dialog_function<F>(a);}
 static bool valid(void*p){return p&&fn<bool(*)(void*)>(lv_obj_is_valid)(p);}
 static void place(void*p,int x,int y,int w,int h){fn<void(*)(void*,int,int)>(lv_obj_set_size)(p,w,h);fn<void(*)(void*,int,int,int)>(lv_obj_align)(p,1,x,y);}
 static void text(void*p,const std::string&s){fn<void(*)(void*,const char*)>(lv_label_set_text)(p,s.c_str());}
 static void colour(void*p,std::uint32_t c){fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(p,c,0);}
 void*label(void*parent,const std::string&s,int x,int y,int w,int h){
  auto*l=fn<void*(*)(void*)>(lv_label_create)(parent);text(l,s);
  // Negative height requests wrapping with the label's native content height,
  // not a literal negative LVGL size (which collapses the status summary).
  if(h<0){fn<void(*)(void*,int)>(lv_obj_set_width)(l,w);fn<void(*)(void*,int,int,int)>(lv_obj_align)(l,1,x,y);}
  else place(l,x,y,w,h);
  // Overlay parents can inherit the stock theme's dark foreground. Give all
  // captions/status text a readable default; stage states override it below.
  colour(l,0xffeeeeeeU);
  fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(l,reinterpret_cast<void*>(compact_?0x34b82a8:0x26297a0),0);return l;
 }
 void center_caption(void*button,void*label,const std::string&value){
  center_button_caption(button,label,value);
  if(compact_){fn<void(*)(void*,int,int)>(lv_obj_set_size)(label,148,40);
   fn<void(*)(void*,int,int,int)>(lv_obj_align)(label,1,6,8);}
 }
 void*button(const char*s,int x){auto*b=fn<void*(*)(void*)>(lv_obj_create)(root_);stock_dialog_backdrop(b);place(b,dialog_x_+x,compact_?dialog_y_+dialog_h_-72:0,compact_?160:110,compact_?56:40);
  auto*l=label(b,s,0,0,compact_?160:110,compact_?56:40);center_caption(b,l,s);
  fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(l,reinterpret_cast<void*>(compact_?0x1a57128:0xf84928),0);
  fn<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(b,&pressed,7,this);return b;
 }
 bool can_stop()const{const auto state=result_.value("receipt",Json::object()).value("state","");
  return !cancel_mode_&&result_.value("fresh",false)&&!result_.contains("stop")&&(state=="pending"||state=="running");}
 bool can_review()const{
  const auto state=result_.value("receipt",Json::object()).value("state","");
  const auto resolution=result_.value("resolution",Json::object());const auto phase=resolution.value("state","");
  return result_.value("fresh",false)&&result_.value("resolution_available",false)
   &&(state=="unknown"||state=="stopped")&&!resolution.value("delivery_pending",false)
   &&phase!="pending"&&(phase!="unknown"||resolution.value("recorded",false))&&phase!="reviewing";
 }
 bool can_confirm()const{const auto resolution=result_.value("resolution",Json::object());
  return can_review()&&resolution.value("fresh",false)&&resolution.value("state","")=="reviewed";}
 bool can_reconcile()const{return can_review()&&result_.value("receipt",Json::object()).value("continuation",Json::object()).value("state","")=="interrupted";}
 Json resolution_choice(const char*action)const{
  // A delayed snapshot must not restore actions on a retained terminal result.
  const auto state=result_.value("state","");
  if(state!="stopped"&&state!="unknown"&&state!="failed"&&state!="refused")return Json::object();
  const auto r=result_.value("resolution",Json::object());
  if(!result_.value("fresh",false)||!result_.value("resolution_available",false)||r.value("delivery_pending",false))return Json::object();
  const auto choice=r.value("choices",Json::object()).value(action,Json::object());
  return choice.value("fresh",false)&&choice.value("state","")=="reviewed"?choice:Json::object();
 }
 std::string retirement_action()const{
  const auto r=result_.value("retirement",Json::object());
  if(!result_.value("retirement_mode",false)||!r.value("available",false)||r.value("delivery_pending",false))return "";
  const auto state=r.value("state","");
  if(state=="reviewed")return r.value("fresh",false)?"DISCARD":"REVIEW";
  if(state=="unknown")return "REFRESH";
  if(state=="complete"&&r.value("restored",false))return "REFRESH";
  if(state.empty()||state=="refused"||state=="superseded")return "REVIEW";
  return "";
 }
 bool cancel_verified()const{
  const auto resolution=result_.value("resolution",Json::object());
  return result_.value("state","")=="complete"||(can_confirm()&&
   resolution.value("request",Json::object()).value("action","")=="acknowledge_complete");
 }
 void update_cancel(){
  const auto resolution=result_.value("resolution",Json::object());
  const auto state=result_.value("state","unknown");
  const auto action=resolution.value("request",Json::object()).value("action","");
  const bool verified=cancel_verified(), actionable=can_confirm()&&!verified;
  text(title_,"Cancel print");
  auto*close_caption=fn<void*(*)(void*,int)>(lv_obj_get_child)(close_,0);
  text(close_caption,verified?"DONE":"CLOSE");center_caption(close_,close_caption,verified?"DONE":"CLOSE");
  fn<void(*)(void*,unsigned)>(lv_obj_add_flag)(review_,1);
  text(fn<void*(*)(void*,int)>(lv_obj_get_child)(review_,0),"");
  fn<void(*)(void*,unsigned)>(actionable?lv_obj_clear_flag:lv_obj_add_flag)(stop_,1);
  fn<void(*)(void*,unsigned)>(actionable?lv_obj_clear_state:lv_obj_add_state)(stop_,128);
  auto*caption=fn<void*(*)(void*,int)>(lv_obj_get_child)(stop_,0);
  const char*button=action=="discard_saved_job"?"DISCARD":"FINISH";
  text(caption,button);center_caption(stop_,caption,button);
  std::string summary;
  if(verified)summary="Print cancelled.";
  else if(!result_.value("fresh",false))summary="Waiting for printer status...";
  else if(state=="pending"||state=="running")summary="Cancelling...";
  else {
   summary=state=="refused"?"Could not cancel the print.":"Cancellation could not be confirmed.";
   const auto message=result_.value("message","");
   if(!message.empty())summary+="\n"+message;
  }
  if(actionable){
   if(action=="discard_saved_job")summary+="\nPress DISCARD to remove the saved resume point.";
   else summary+="\nPress FINISH to turn heaters off and clear the paused state.";
  }
  text(summary_,summary);
  if(progress_.attached()){progress_.update({{"instruction",summary},{"steps",Json::array()}});fn<void(*)(void*,unsigned)>(lv_obj_add_flag)(summary_,1);}
 }
public:
 std::function<bool()>stop;
 std::function<bool()>allow_close;
 std::function<bool()>review_retirement,refresh_retirement;
 std::function<void()>cancel_retirement;
 std::function<void()>show_retirement_result;
 std::function<bool(const std::string&)>confirm_retirement;
 std::function<bool(const std::string&)>review_resolution,confirm_resolution;
 bool active()const{return valid(root_);}
 bool take_external_deletion(){const bool deleted=externally_deleted_;externally_deleted_=false;return deleted;}
 bool tracks(const std::string&id)const{return active()&&id_==id;}
 void close(){progress_.close();rendered_=false;externally_deleted_=false;auto*p=root_;root_=screen_=stop_=review_=summary_=title_=nullptr;id_.clear();if(valid(p))fn<void(*)(void*)>(lv_obj_del)(p);}
 bool open(void*parent,const Json&result){
  close();if(!valid(parent)||result.value("id","").empty())return false;
  const int full_w=fn<int(*)(void*)>(lv_obj_get_content_width)(parent),full_h=fn<int(*)(void*)>(lv_obj_get_content_height)(parent);
  if(full_w<400||full_h<280)return false;
  compact_=result.value("retirement_mode",false);
  const int w=compact_?std::min(full_w-48,704):full_w,h=compact_?260:full_h;
  dialog_x_=compact_?(full_w-w)/2:0;dialog_y_=compact_?(full_h-h)/2:0;dialog_h_=h;
  cancel_mode_=result.value("kind","")=="print_cancel";
  screen_=fn<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);id_=result.at("id");
  root_=fn<void*(*)(void*)>(lv_obj_create)(parent);stock_dialog_backdrop(root_);place(root_,0,0,full_w,full_h);
  fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(root_,0xff3c3f43U,0);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(root_,compact_?0:255,0);
  if(compact_){auto*card=fn<void*(*)(void*)>(lv_obj_create)(root_);stock_dialog_backdrop(card);
   place(card,dialog_x_,dialog_y_,w,h);
   fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(card,0xff3c3f43U,0);
   fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(card,255,0);
  }
  if(!fn<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(root_,&deleted,33,this)){close();return false;}
  title_=label(root_,"",dialog_x_+(compact_?16:12),dialog_y_+(compact_?8:4),compact_?w-32:w-360,compact_?36:30);
  close_=button("CLOSE",w-(compact_?360:348));review_=button("REVIEW",w-232);stop_=button("STOP",w-(compact_?180:116));
  auto*rule=fn<void*(*)(void*)>(lv_obj_create)(root_);stock_dialog_backdrop(rule);place(rule,dialog_x_+12,dialog_y_+(compact_?48:40),w-24,1);
  fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(rule,0xff606060U,0);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(rule,255,0);
  auto*body=fn<void*(*)(void*)>(lv_obj_create)(root_);stock_dialog_backdrop(body);place(body,dialog_x_+(compact_?16:8),dialog_y_+(compact_?64:48),w-(compact_?32:16),compact_?h-144:h-56);
  fn<void(*)(void*,unsigned)>(lv_obj_add_flag)(body,16);fn<void(*)(void*,int)>(lv_obj_set_scroll_dir)(body,12);
  summary_=label(body,"",8,0,w-(compact_?64:48),-1);fn<void(*)(void*,int)>(lv_label_set_long_mode)(summary_,0);
  // Stock popup dismissal hides this shared overlay before handing off.
  // Reveal it only after our opaque managed panel has been constructed.
  fn<void(*)(void*,unsigned)>(lv_obj_clear_flag)(parent,1);
  if(!compact_)progress_.attach(body,0,0,w-16,h-56);
  update(result);return true;
 }
 void update(const Json&result){
  if(!active())return;
  if(screen_!=fn<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr)){close();return;}
  if(result.value("id","")!=id_)return;
  // Identical syncs must not invalidate text/layout or compete with input.
  // Check screen lifetime first; a new screen still closes this panel.
  if(rendered_&&result==result_)return;
  rendered_=true;result_=result;const auto resolution=result.value("resolution",Json::object());
  if(cancel_mode_){update_cancel();return;}
  fn<void(*)(void*,unsigned)>(cancel_mode_&&!can_review()?lv_obj_add_flag:lv_obj_clear_flag)(stop_,1);
  if(cancel_mode_)text(fn<void*(*)(void*,int)>(lv_obj_get_child)(review_,0),"");
  const bool confirm=can_confirm();const bool discard=can_review()&&!confirm;
  const bool retiring=result.value("retirement_mode",false);const auto retire_action=retirement_action();
  const bool recovery_refused=retiring&&result.value("state","")=="refused"
   &&result.value("retirement",Json::object()).value("state","")!="complete";
  text(title_,retiring&&!recovery_refused?"Discard PLR":cancel_mode_?"Cancel print":"Power Loss Recovery (PLR)");
  auto*close_caption=fn<void*(*)(void*,int)>(lv_obj_get_child)(close_,0);
  const bool refused_selection=!retiring&&result.value("state","")=="refused"&&result.value("receipt",Json::object()).empty();
  const char*close_text=refused_selection?"BACK":retiring&&!recovery_refused&&retire_action=="DISCARD"?"CANCEL":"CLOSE";
  text(close_caption,close_text);center_caption(close_,close_caption,close_text);
  const bool ready=retiring?retire_action=="DISCARD":confirm||discard||can_stop();
  if(retiring)fn<void(*)(void*,unsigned)>(retire_action=="DISCARD"?lv_obj_clear_flag:lv_obj_add_flag)(stop_,1);
  auto*caption=fn<void*(*)(void*,int)>(lv_obj_get_child)(stop_,0);
  const char*action=retiring?(retire_action.empty()?"DISCARD":retire_action.c_str()):confirm?"CONFIRM":discard?(cancel_mode_?"REVIEW":"DISCARD"):"STOP";text(caption,action);center_caption(stop_,caption,action);
  // Read-only resolution runs automatically; expose only actionable choices below.
  fn<void(*)(void*,unsigned)>(lv_obj_add_flag)(review_,1);
  if(retiring)fn<void(*)(void*,unsigned)>(lv_obj_add_flag)(review_,1);
  fn<void(*)(void*,unsigned)>(ready?lv_obj_clear_state:lv_obj_add_state)(stop_,128);
  colour(fn<void*(*)(void*,int)>(lv_obj_get_child)(stop_,0),ready?0xffeeeeeeU:0xff888888U);
  if(!retiring&&(resolution.contains("choices")||!confirm)){
   const bool use=!resolution_choice("reconcile").empty(),discard_ready=!resolution_choice("abandon").empty();
   fn<void(*)(void*,unsigned)>(use?lv_obj_clear_flag:lv_obj_add_flag)(review_,1);
   auto*use_caption=fn<void*(*)(void*,int)>(lv_obj_get_child)(review_,0);
   text(use_caption,"USE SAVED");center_caption(review_,use_caption,"USE SAVED");
   fn<void(*)(void*,unsigned)>(discard_ready||can_stop()?lv_obj_clear_flag:lv_obj_add_flag)(stop_,1);
   fn<void(*)(void*,unsigned)>(discard_ready||can_stop()?lv_obj_clear_state:lv_obj_add_state)(stop_,128);
   text(caption,discard_ready?"DISCARD":"STOP");center_caption(stop_,caption,discard_ready?"DISCARD":"STOP");
  }
  const auto retirement=result.value("retirement",Json::object());
  const auto phase=retiring?retirement.value("state",result.value("state","unknown")):result.value("state","unknown");
  const bool failed=phase=="failed"||phase=="refused"||phase=="unknown"||phase=="stopped";
  std::string summary;
  // A recorded terminal outcome is history, not a grant to act on stale status.
  // Keep it visible while live observations recover; action gates above stay fresh.
  if(retiring&&phase=="complete")summary="Saved print discarded.";
  else if(!retiring&&phase=="complete")summary="PLR complete.";
  else if(!retiring&&phase=="abandoned")summary="Saved PLR discarded.";
  else if(!result.value("fresh",false))summary="Waiting for printer status...";
  else if(retiring){
   if(phase=="complete")summary="Saved print discarded.";
   else if(phase=="reviewed")summary="Discard the saved print? It will no longer be resumable.";
   else if(failed)summary="Could not confirm the saved print was discarded.";
   else summary="Checking saved print...";
  }else{
   if(phase=="complete")summary="PLR complete.";
   else if(phase=="abandoned")summary="Saved PLR discarded.";
   else if(phase=="printing")summary="Print resumed.";
   else if(phase=="paused")summary="Print paused.";
   else if(refused_selection)summary="PLR could not start.";
   else if(failed)summary="PLR stopped.";
   else summary="Power Loss Recovery in progress...";
  }
  if(recovery_refused){
   summary="PLR could not start.";
   const auto reason=result.value("message","");if(!reason.empty())summary+="\n"+reason;
   if(phase=="reviewed")summary+="\nDISCARD removes this saved PLR; CLOSE keeps it.";
  }
  if(failed&&result.value("fresh",false)&&!recovery_refused){
   const auto message=retiring?retirement.value("message",result.value("message","")):result.value("message","");
   if(!message.empty())summary+="\n"+message;
  }
  // Informational fallback from the automatic review after Continue. It does
  // not add an acknowledgment step or alter the operation's available actions.
  const auto fan_warnings=result.value("review",Json::object()).value("fan_warnings",Json::array());
  if(!retiring&&fan_warnings.is_array()&&std::any_of(fan_warnings.begin(),fan_warnings.end(),[](const Json&warning){return warning.is_string()&&!warning.get<std::string>().empty();}))
   summary+="\nOptional cooling fans unavailable; their settings will not be restored.";
  if(!retiring&&!resolution_choice("reconcile").empty())
   summary+="\nUSE SAVED keeps the newer checkpoint without resuming the print.";
  if(!retiring&&!resolution_choice("abandon").empty())
   summary+="\nDISCARD removes the saved PLR.";
  const auto receipt=result.value("receipt",Json::object());auto stages=Json::array();
  if(retiring){
   const auto phase=retirement.value("state","");
   const bool reviewed=retirement.contains("request")||retirement.contains("receipt"),done=phase=="complete";
   stages.push_back({{"name","Checking saved print..."},{"state",reviewed?"complete":phase=="reviewing"?"running":"future"}});
   stages.push_back({{"name","Discard saved PLR"},{"state",done?"complete":phase=="pending"?"running":"future"}});
   stages.push_back({{"name","Verify archived result"},{"state",done?"complete":phase=="unknown"?"running":"future"}});
  }else if(!cancel_mode_){
   const bool reviewed=!receipt.empty()||result.contains("review");
   const bool refused=result.value("state","")=="refused";
   stages.push_back({{"name",!reviewed&&refused?"review_blocked":"review"},
                     {"state",reviewed?"complete":refused?"failed":"running"}});
   if(reviewed&&receipt.empty())stages.push_back({{"name","await_preparation"},
                     {"state",refused?"failed":"running"}});
  }
  // Resolution verifies the terminal outcome; it does not claim the interrupted
  // execution stages ran. Replace that historical queue with the completed review.
  bool unfinished=false;for(const auto&stage:receipt.value("stages",Json::array()))
   if(stage.value("state","")!="complete")unfinished=true;
  if(cancel_mode_&&result.value("state","")=="complete"&&(resolution.value("state","")=="complete"||unfinished)){
   stages=Json::array({{{"name","Review interrupted cancellation"},{"state","complete"}},
                       {{"name","Verify cancellation resolved"},{"state","complete"}}});
  }else for(const auto&stage:receipt.value("stages",Json::array()))stages.push_back(stage);
  const auto temperatures=result.value("temperatures",Json::object());
  for(const auto&stage:stages){
   const auto name=stage.value("name","");const auto state=stage.value("state","");
   if(name=="heating"&&state=="running")for(const auto&heater:temperatures.items()){
    const auto v=heater.value();if(!v.contains("temperature")||!v.contains("target")||!v["temperature"].is_number()||!v["target"].is_number())continue;
    const double current=v["temperature"],target=v["target"];
    std::string label;
    if(heater.key()=="heater_bed")label="Bed";
    else if(heater.key()=="extruder")label="Head 1";
    else if(heater.key().size()==9&&heater.key().compare(0,8,"extruder")==0&&heater.key()[8]>='1'&&heater.key()[8]<='3')label="Head "+std::to_string(heater.key()[8]-'0'+1);
    if(!label.empty()&&std::isfinite(current)&&std::isfinite(target)&&current>=-100&&current<=1000&&target>0&&target<=1000)
     summary+="\n"+label+": "+std::to_string(int(std::round(current)))+" / "+std::to_string(int(std::round(target)))+" C";
   }
  }
  text(summary_,summary);
  if(progress_.attached()){
   const bool terminal=failed||phase=="complete"||phase=="abandoned"||phase=="printing"||phase=="paused";
   progress_.update({{"instruction",summary},{"steps",terminal?Json::array():plr_progress_steps(stages)}});
   fn<void(*)(void*,unsigned)>(lv_obj_add_flag)(summary_,1);
    return;
  }

 }
private:
 static void deleted(void*e)noexcept{auto*o=static_cast<StockRecoveryProgress*>(fn<void*(*)(void*)>(lv_event_get_user_data)(e));
  if(o&&fn<void*(*)(void*)>(lv_event_get_target)(e)==o->root_){o->externally_deleted_=true;o->root_=o->screen_=o->stop_=o->review_=o->summary_=o->title_=nullptr;o->id_.clear();}}
 static void pressed(void*e)noexcept{try{
  auto*o=static_cast<StockRecoveryProgress*>(fn<void*(*)(void*)>(lv_event_get_user_data)(e));if(!o||!o->active())return;
  if(o->screen_!=fn<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr)){o->close();return;}
  auto*target=fn<void*(*)(void*)>(lv_event_get_target)(e);
  if(target!=o->stop_&&target!=o->review_){
   if(o->allow_close&&!o->allow_close())return;
   if(o->result_.value("retirement_mode",false)&&o->retirement_action()=="DISCARD"&&o->cancel_retirement)o->cancel_retirement();
   o->close();return;}
  auto next=o->result_;
  if(next.value("retirement_mode",false)){
   if(target==o->review_&&next.value("retirement_previous",false)&&o->show_retirement_result){o->show_retirement_result();return;}
   if(target!=o->stop_)return;
   const auto action=o->retirement_action();bool queued=false;
   if(action=="REVIEW"&&o->review_retirement)queued=o->review_retirement();
   else if(action=="DISCARD"&&o->confirm_retirement)queued=o->confirm_retirement(next.value("retirement",Json::object()).value("id",""));
   else if(action=="REFRESH"&&o->refresh_retirement)queued=o->refresh_retirement();
   if(queued){next["retirement"]["delivery_pending"]=true;o->update(next);}return;
  }
  if(!o->cancel_mode_&&next.value("resolution",Json::object()).contains("choices")){
   const auto choice=o->resolution_choice(target==o->review_?"reconcile":"abandon");
   if(!choice.empty()&&o->confirm_resolution&&o->confirm_resolution(choice.value("id",""))){
    next["resolution"]["delivery_pending"]=true;o->update(next);
   }else if(target==o->stop_&&o->can_stop()&&o->stop&&o->stop()){
    next["stop"]="queued";o->update(next);
   }
   return;
  }
  if(target==o->review_){
   if(o->can_reconcile()&&o->review_resolution&&o->review_resolution("reconcile")){next["resolution"]={{"state","reviewing"},{"message","Checking PLR checkpoint"}};o->update(next);}return;
  }
  if(o->cancel_mode_&&(!o->can_confirm()||o->cancel_verified()))return;
  if(o->can_confirm()){
   if(o->confirm_resolution&&o->confirm_resolution(next["resolution"].value("id",""))){next["resolution"]["state"]="pending";o->update(next);}return;
  }
  if(o->can_review()){
   if(o->review_resolution&&o->review_resolution(o->cancel_mode_?"resolve":"abandon")){next["resolution"]={{"state","reviewing"},{"message",o->cancel_mode_?"Reviewing cancellation cleanup":"Discarding saved PLR"}};o->update(next);}return;
  }
  if(o->can_stop()&&o->stop&&o->stop()){next["stop"]="queued";o->update(next);}
 }catch(...){} }
};
}}
