// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "button_caption.hpp"
#include "stock_progress_panel.hpp"
#include "stock_header_action.hpp"
#include "stock_api.hpp"
#include "stock_dialog_backdrop.hpp"
#include "filament_procedure_review.hpp"
#include <list>
namespace wmp_ui { namespace native {
// Review and progress inside stock content; no new navigation shell.
class StockFilamentProcedure {
 struct Binding{StockFilamentProcedure*owner;void*object;void*root;std::string action;};
 StockProgressPanel progress_;
 std::vector<void*>steps_,source_buttons_;int description_y_=8;
 void*card_=nullptr,*body_=nullptr,*title_=nullptr,*rule_=nullptr;bool compact_=false;
 std::list<Binding>bindings_;void*root_=nullptr,*description_=nullptr,*begin_=nullptr,*empty_=nullptr,*close_=nullptr;
 FilamentProcedureReview review_;Json latest_,result_;bool submitted_=false,check_=false,recovering_=false,recipe_changed_=false;Json check_context_;std::string check_head_,request_id_;
 Json rendered_local_;bool rendered_=false;std::string open_failure_;
 bool open_failed(const std::string&reason){open_failure_=reason;close();return false;}
public:
 std::function<Receipt(FilamentProcedureReview&)>submit;
 std::function<bool(const std::string&)>cancel,recover,recover_toolhead;
 std::function<Receipt(const std::string&,const std::string&)>confirm_filament;
 bool check_ready(const Json&data)const{
  if(!check_||submitted_||!data.value("fresh",false)||data.value("owner","")!="standalone"||!data.value("capabilities",Json::object()).value("confirm_filament",false))return false;
  for(const auto*key:{"owner","session","revision","identity_revision"})if(data.value(key,"").empty()||data.value(key,"")!=check_context_.value(key,""))return false;
  const auto job=data.value("job",Json::object()).value("state","");if(job!="idle"&&job!="complete"&&!paused_filament_for(data,check_head_))return false;
  Json captured;for(const auto&head:check_context_.value("heads",Json::array()))if(head.value("id","")==check_head_)captured=head;
  if(!captured.is_object())return false;
  unsigned matches=0;for(const auto&head:data.value("heads",Json::array()))if(head.value("id","")==check_head_){
   if(head.value("loaded",Json::object())!=captured.value("loaded",Json::object()))return false;
   ++matches;
  }
  return matches==1;
 }
 void begin(){
  if(submitted_||!submit)return;
  if(!review_.ready(latest_)){if(review_.refresh(latest_))recipe_changed_=true;update(latest_);return;}
  submitted_=true;
  try{const auto result=submit(review_);request_id_=result.id;result_={{"state",result.state},{"message",result.message}};}
  catch(...){result_={{"state","unknown"},{"message","Loading outcome unknown"}};}
  update(latest_);
 }
 const std::string&open_failure()const{return open_failure_;}
 bool active()const{return stock_object_valid(root_);}
 bool has_result()const{return submitted_&&result_.is_object();}
 bool has_tool_result()const{return has_result()&&tool_recovery();}
 void close(){progress_.close();rendered_=false;steps_.clear();source_buttons_.clear();card_=body_=title_=rule_=nullptr;compact_=false;auto*p=root_;root_=description_=begin_=empty_=close_=nullptr;if(stock_object_valid(p))stock_function<void(*)(void*)>(lv_obj_del)(p);}
 static bool interrupted(const Json&data,bool tool=false){
  const auto op=data.value(tool?"toolhead_operation":"filament_operation",Json::object());const auto head=op.value("head","");
  return data.value("fresh",false)&&recovery_owner(data,tool)&&data.value(tool?"toolhead_recovery_protocol":"filament_recovery_protocol",0)==1&&
   op.value("state","")=="unknown"&&!op.value("id","").empty()&&!operation_session(data).empty()&&op.value("session","")==operation_session(data)&&
   head.size()==2&&head[0]=='h'&&head[1]>='0'&&head[1]<='3'&&(tool?(op.value("action","")=="take"||op.value("action","")=="dock"):(op.value("action","")=="load"||op.value("action","")=="unload"));
 }
 bool open_interrupted(void*parent,const Json&data,bool tool=false){
  if(!interrupted(data,tool))return false;
  const auto op=data.at(tool?"toolhead_operation":"filament_operation");
  if(!open(parent,data,op.at("head"),op.at("action"),true))return false;
  request_id_=op.at("id");submitted_=true;result_={{"state","unknown"},{"message",op.value("message","Filament operation interrupted.")}};update(data);return true;
 }
 bool open_tracking(void*parent,const Json&data,const std::string&head,const std::string&action,const Receipt&receipt){
  if(receipt.id.empty()||!open(parent,data,head,action,true))return false;
  request_id_=receipt.id;submitted_=true;result_={{"state",receipt.state},{"message",receipt.message}};update(data);return true;
 }
 bool reopen_result(void*parent,const Json&data){
  if(!submitted_||!result_.is_object())return false;
  const auto saved_review=review_;const auto saved_result=result_;const auto saved_request=request_id_;const bool saved_recovering=recovering_;
  const auto head=check_?check_head_:review_.physical_head();const auto action=check_?"confirm_filament":review_.action();
  const bool opened=open(parent,data,head,action,true);
  review_=saved_review;result_=saved_result;request_id_=saved_request;recovering_=saved_recovering;submitted_=true;if(opened)update(data);return opened;
 }
 bool open(void*parent,const Json&data,const std::string&head,const std::string&action,bool result_only=false,const std::string&source="")try{
  close();open_failure_.clear();
  if(!stock_object_valid(parent))return open_failed("Filament page parent is unavailable.");
  if((action=="take"||action=="dock")&&!result_only)return open_failed("Toolhead motion is not a filament review action: action="+action);
  check_=action=="confirm_filament";check_context_=data;check_head_=head;
  review_.open(data,head,action);if(!source.empty()&&!review_.select(data,source))return open_failed("Selected source could not bind to this review: source="+source+", head="+head);submitted_=false;recovering_=false;recipe_changed_=false;request_id_.clear();result_=Json();latest_=data;
  int w=stock_function<int(*)(void*)>(lv_obj_get_content_width)(parent),h=stock_function<int(*)(void*)>(lv_obj_get_content_height)(parent);
  if(w<(check_?480:400)||h<280)return open_failed("Filament page dimensions unavailable: width="+std::to_string(w)+", height="+std::to_string(h));
  if(review_.sources().size()>32)return open_failed("Filament review source count exceeds 32: count="+std::to_string(review_.sources().size()));
  root_=stock_function<void*(*)(void*)>(lv_obj_create)(parent);if(!root_)return open_failed("Filament dialog allocation failed.");
  if(!bind(root_,""))return open_failed("Filament dialog event binding failed.");
  stock_dialog_backdrop(root_);stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(root_,0xff3c3f43U,0);stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(root_,255,0);stock_object_place(root_,0,0,w,h);
  stock_function<void(*)(void*,unsigned)>(lv_obj_clear_flag)(root_,16);
  card_=stock_function<void*(*)(void*)>(lv_obj_create)(root_);if(!card_)return open_failed("Filament confirmation card allocation failed.");stock_dialog_backdrop(card_);stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(card_,1);
  title_=label(root_,(tool_recovery()?(action=="take"?"Mount head":"Dock head"):check_?"Check filament":action=="load"?"Load filament":"Unload filament")+std::string(" - Head ")+(head.size()==2?std::to_string(head[1]-'0'+1):"?"),12,2,w-(check_?370:260),28);
  auto*body=stock_function<void*(*)(void*)>(lv_obj_create)(root_);if(!body)return open_failed("Filament dialog body allocation failed.");
  body_=body;stock_dialog_backdrop(body);stock_object_place(body,8,44,w-16,h-52);stock_function<void(*)(void*,int)>(lv_obj_set_scroll_dir)(body,12);stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(body,16);
  int y=8;
  if(!result_only&&source.empty()&&review_.sources().size()>1)for(const auto&source:review_.sources()){
   source_buttons_.push_back(button(body,"source:"+source.value("id",""),source_label(data,source),8,y,w-48,66));y+=72;
  }
  description_y_=y;
  for(int i=0;i<8;++i){auto*l=label(body,"",8,y+i*30,w-48,28);steps_.push_back(l);stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(l,1);}
  description_=label(body,"",8,y,w-48,-1);
  // Content height follows wrapping; long backend descriptions stay scrollable.
  stock_function<void(*)(void*,int)>(lv_label_set_long_mode)(description_,0);
  close_=header("close",action=="unload"?"CANCEL":"CLOSE",w-(check_?360:240),104);
  if(check_)empty_=header("empty","EMPTY",w-248,112);
  begin_=header("begin",check_?"LOADED":action=="load"?"LOAD":"UNLOAD",w-128,116);
  auto*rule=stock_function<void*(*)(void*)>(lv_obj_create)(root_);stock_dialog_backdrop(rule);stock_object_place(rule,12,34,w-24,1);stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(rule,0xff55575bU,0);stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(rule,255,0);
  rule_=rule;layout(data.value("owner","")=="standalone"&&!result_only&&(check_||review_.source().is_object()));
  update(data);return true;
 }catch(const std::exception&e){return open_failed(std::string("Filament dialog rendering failed: ")+e.what());}
 catch(...){return open_failed("Filament dialog rendering failed: unknown exception.");}
 void update(const Json&data){
  const bool same_data=rendered_&&data==latest_;
  latest_=data;
  if(!submitted_&&!check_&&review_.refresh(data))recipe_changed_=true;
  // A dismissed result keeps its own receipt binding without reserving motion.
  const auto receipts=data.value("receipts",Json::object());
  if(submitted_&&data.value("fresh",false)&&!request_id_.empty()&&receipts.contains(request_id_))
   result_=receipts.at(request_id_);
  if(!active())return;
  if(compact_&&submitted_)layout(false);
  const bool ready=!submitted_&&(check_?check_ready(data):review_.ready(data));
  // A receipt, selection or callback capability can change without a new data
  // sync. Include those local inputs before skipping redundant LVGL writes.
  Json local={{"submitted",submitted_},{"recovering",recovering_},{"recipe_changed",recipe_changed_},{"result",result_},{"request",request_id_},
   {"ready",ready},{"cancel",can_cancel()},{"recover",can_recover()},
   {"source",review_.source()},{"plan",review_.plan()},{"reason",review_.reason()}};
  if(same_data&&local==rendered_local_)return;
  rendered_=false;
  // Apply the final state once. A live status refresh must not disable an
  // available STOP/RECOVER/DONE action while the user is pressing it.
  const auto result_state=submitted_?result_.value("state",std::string("unknown")):std::string();
  const bool result_action=submitted_&&!check_&&(result_state=="complete"||
    (result_state=="pending"&&can_cancel())||can_recover());
  header_enabled(begin_,ready||result_action);
  const bool complete=submitted_&&result_state=="complete";
  const bool actionable=!submitted_||(!check_&&(complete||(result_state=="pending"&&can_cancel())||can_recover()));
  stock_function<void(*)(void*,unsigned)>(actionable?lv_obj_clear_flag:lv_obj_add_flag)(begin_,1);
  stock_function<void(*)(void*,unsigned)>(complete&&!check_?lv_obj_add_flag:lv_obj_clear_flag)(close_,1);
  if(empty_)stock_function<void(*)(void*,unsigned)>(submitted_?lv_obj_add_flag:lv_obj_clear_flag)(empty_,1);
  auto*close_caption=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(close_,0);
  stock_function<void(*)(void*,const char*)>(lv_label_set_text)(close_caption,complete&&check_?"DONE":!submitted_&&(compact_||review_.action()=="unload")?"CANCEL":"CLOSE");
  if(empty_)header_enabled(empty_,ready);
  for(auto*step:steps_)stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(step,1);
  if(submitted_)stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(description_,reinterpret_cast<void*>(data.value("owner","")=="standalone"?MyriadPro_Regular_22:MyriadPro_Regular_16),0);
  stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(description_,8,description_y_);
  Json progress_view;
  stock_function<void(*)(void*,unsigned)>(lv_obj_clear_flag)(description_,1);
  std::string text;
  if(submitted_){
   const auto state=result_.value("state","unknown");
   const bool unloading=review_.action()=="unload";
   const auto tool=data.value("toolhead_operation",Json::object());
   const bool checked=recovering_||(tool.value("id","")==request_id_&&tool.value("session","")==operation_session(data)&&tool.value("recovered",false));
   text=state=="complete"?(check_?"Filament state saved.":tool_recovery()?(checked?"Head check complete.":review_.action()=="take"?"Head mounted.":"Head docked."):unloading?"Filament unloaded. Remove it from the head.":"Filament loaded."):
    state=="pending"?(tool_recovery()?(recovering_?"Checking head...":review_.action()=="take"?"Mounting head...":"Docking head..."):unloading?"Unloading filament...":"Loading filament..."):
    state=="refused"?"Could not start.":state=="failed"?"Operation stopped.":"Waiting for the operation result...";
   const auto detail=result_.value("message","");
   if(state!="complete"&&!detail.empty())text=detail;
   if(!check_){
    std::string caption=state=="pending"?(can_cancel()?"STOP":latest_.value("filament_operation",Json::object()).value("cancel_requested",false)?"STOPPING":"STOP"):can_recover()?"RECOVER":state=="complete"?"DONE":state=="refused"?"STOPPED":state=="failed"?"STOPPED":"RECOVER";
    auto*child=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(begin_,0);
    stock_function<void(*)(void*,const char*)>(lv_label_set_text)(child,caption.c_str());
    if(can_recover())text+=tool_recovery()?"\nRECOVER checks head attachment.":"\nRECOVER checks stopped motion and turns the heater off.";
    else if(state=="partial"||state=="unknown")text+="\nRecovery unavailable for this printer state.";
   }
   const auto operation=data.value(tool_recovery()?"toolhead_operation":"filament_operation",Json::object());
   if(!check_&&operation.value("id","")==request_id_&&!request_id_.empty()&&
      operation.value("session","")==operation_session(data)&&operation.value("head","")==review_.physical_head()&&
      operation.contains("steps")&&operation["steps"].is_array()){
    const auto rows=operation["steps"];int active=-1;
    for(unsigned i=0;i<rows.size();++i)if(rows[i].value("phase","")==operation.value("phase",""))active=int(i);
    const bool complete=operation.value("state","")=="complete"||operation.value("recovered",false);
    if(state=="pending"&&!complete&&active>=0&&!steps_.empty()){
     const bool numbered=data.value("owner","")=="standalone";
     if(numbered){
      progress_view={{"steps",Json::array()}};
      for(unsigned i=0;i<rows.size();++i)progress_view["steps"].push_back({{"label",rows[i].value("label","")},{"state",int(i)==active?"running":int(i)<active?"complete":"pending"}});
     }else{
      std::string line=rows[active].value("label","");
      if(rows[active].value("phase","")=="heating")
       for(const auto&head:data.value("heads",Json::array()))if(head.value("id","")==review_.physical_head())
        line+="  "+std::to_string(head.value("actual",0))+" / "+std::to_string(head.value("target",0))+" °C";
      stock_function<void(*)(void*,const char*)>(lv_label_set_text)(steps_[0],line.c_str());
      stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(steps_[0],reinterpret_cast<void*>(MyriadPro_Regular_16),0);
      stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(steps_[0],0xffeeeeeeU,0);
      stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(steps_[0],8,description_y_);
      stock_function<void(*)(void*,unsigned)>(lv_obj_clear_flag)(steps_[0],1);
      stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(description_,8,description_y_+38);
     }
    }
    const auto guidance=operation.value("message","");
    if(state=="pending"&&!guidance.empty())text=guidance;
   }
  }
  else if(check_){
   text="Is filament loaded in Head "+std::to_string(review_.physical_head()[1]-'0'+1)+"?";
   if(!ready)text+="\nStatus changed. Close and try again.";
  }else{
   if(compact_)text="";
   else if(review_.action()=="unload")text="Unload filament from Head "+std::to_string(review_.physical_head()[1]-'0'+1)+"?\n";
   else if(review_.source().is_object())text="Source: "+source_label(data,review_.source())+"\n";
   const auto plan=review_.plan();
   if(plan.is_object()&&plan.contains("target_temperature")&&plan["target_temperature"].is_string()){
    text+="Mount and heat to "+plan["target_temperature"].get<std::string>()+" C.\n";
    text+=review_.action()=="unload"?"Remove filament when unloading finishes.":"Insert filament when prompted.";
    const auto note=plan.value("transition_note","");if(!note.empty())text+="\n\n"+note;
   }else text+=plan.is_object()?plan.value("description",""):review_.reason();
   if(recipe_changed_&&ready)text+=review_.action()=="unload"?"\nSettings changed. Review and press UNLOAD.":"\nSettings changed. Review and press LOAD.";
   else if(!ready&&review_.plan().is_object())text+="\nWaiting for current procedure details.";
  }
  if(progress_view.is_object()){
   progress_view["instruction"]=text;
   const auto op=data.value("filament_operation",Json::object());
   if(op.value("phase","")=="heating")for(const auto&head:data.value("heads",Json::array()))if(head.value("id","")==review_.physical_head())
    {
     progress_view["value"]=std::to_string(head.value("actual",0))+" / "+std::to_string(head.value("target",0))+" °C";
     if(head.value("actual",0)>=50)progress_view["note"]="The nozzle is hot.";
    }
   if(!progress_.attached())progress_.attach(body_,0,description_y_,stock_function<int(*)(void*)>(lv_obj_get_content_width)(body_),stock_function<int(*)(void*)>(lv_obj_get_content_height)(body_)-description_y_);
   if(progress_.attached()){progress_.show(true);progress_.update(progress_view);stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(description_,1);}
  }else progress_.show(false);
  stock_function<void(*)(void*,const char*)>(lv_label_set_text)(description_,text.c_str());
  rendered_local_=std::move(local);rendered_=true;
 }
 void result(const Json&value){if(submitted_){result_=value;update(latest_);}}
private:
 // Only preflight choices use the compact card; running/result views retain
 // their existing scrollable workspace and the same action objects/bindings.
 void layout(bool compact){
  compact_=compact;rendered_=false;
  // LVGL defers set_size: resolve the newly created/resized backdrop before
  // measuring it, otherwise the compact card can get zero/negative geometry.
  stock_function<void(*)(void*)>(lv_obj_update_layout)(root_);
  const int fw=stock_function<int(*)(void*)>(lv_obj_get_content_width)(root_),fh=stock_function<int(*)(void*)>(lv_obj_get_content_height)(root_);
  const int w=compact?std::min(fw-32,704):fw,h=compact?std::min(fh-24,300):fh,x=(fw-w)/2,y=(fh-h)/2;
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(root_,compact?0:255,0);
  stock_function<void(*)(void*,unsigned)>(compact?lv_obj_clear_flag:lv_obj_add_flag)(card_,1);
  stock_object_place(card_,x,y,w,h);stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(card_,0xff3c3f43U,0);stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(card_,255,0);
  stock_object_place(title_,compact?x+16:12,compact?y+8:2,compact?w-32:w-(check_?370:260),compact?36:28);
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(title_,reinterpret_cast<void*>(compact?MyriadPro_Bold_24:MyriadPro_Regular_16),0);
  stock_object_place(rule_,x+12,y+(compact?50:34),w-24,1);
  stock_object_place(body_,compact?x+16:8,compact?y+60:44,w-(compact?32:16),h-(compact?140:52));
  if(compact||submitted_){description_y_=8;for(auto*b:source_buttons_)stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(b,1);}
  stock_function<void(*)(void*,int)>(lv_obj_set_width)(description_,w-(compact?64:48));
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(description_,reinterpret_cast<void*>(compact?MyriadPro_Regular_22:MyriadPro_Regular_16),0);
  for(auto*step:steps_)stock_function<void(*)(void*,int)>(lv_obj_set_width)(step,w-48);
  const int bw=compact?(check_?std::min(160,(w-48)/3):160):0;
  auto action=[&](void*b,int normal_x,int normal_w,int index){if(!b)return;
   const int count=check_?3:2;stock_object_place(b,compact?x+w-16-count*bw-(count-1)*8+index*(bw+8):normal_x,compact?y+h-72:0,compact?bw:normal_w,compact?56:34);
   auto*l=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(b,0);stock_object_place(l,4,compact?8:2,compact?bw-8:normal_w-8,compact?40:26);
   stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(l,reinterpret_cast<void*>(compact?MyriadPro_Bold_24:MyriadPro_Bold_20),0);
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_text_align)(l,compact?1:2,0);
  };
  action(close_,fw-(check_?360:240),104,0);action(empty_,fw-248,112,1);action(begin_,fw-128,116,check_?2:1);
 }
 static std::string operation_session(const Json&data){return data.value(data.value("owner","")=="openace"?"print_helper_session":"session","");}
 static bool recovery_owner(const Json&data,bool tool){return data.value("owner","")=="standalone"||(!tool&&data.value("owner","")=="openace"&&!operation_session(data).empty()&&data.value("filament_operation",Json::object()).value("openace_recovery_supported",false));}
 bool tool_recovery()const{return review_.action()=="take"||review_.action()=="dock";}
 bool can_recover()const{
  const bool is_tool=tool_recovery();
  const auto operation=latest_.value(is_tool?"toolhead_operation":"filament_operation",Json::object());
  const auto job=latest_.value("job",Json::object()).value("state","");
  const auto tool=latest_.value(is_tool?"filament_operation":"toolhead_operation",Json::object()).value("state","");
  return submitted_&&!check_&&(is_tool?bool(recover_toolhead):bool(recover))&&result_.value("state","")=="unknown"&&!request_id_.empty()&&
   latest_.value("fresh",false)&&recovery_owner(latest_,is_tool)&&latest_.value(is_tool?"toolhead_recovery_protocol":"filament_recovery_protocol",0)==1&&
   (job=="idle"||job=="complete"||(!is_tool&&paused_filament_for(latest_,review_.physical_head())))&&tool!="running"&&tool!="unknown"&&
   operation.value("session","")==operation_session(latest_)&&operation.value("id","")==request_id_&&
   operation.value("head","")==review_.physical_head()&&operation.value("state","")=="unknown";
 }
 bool can_cancel()const{
  const auto operation=latest_.value("filament_operation",Json::object());
  const auto owner=latest_.value("owner","");
  const bool supported=owner=="standalone"||(owner=="openace"&&operation.value("openace_cancel_supported",false)&&!operation_session(latest_).empty());
  return submitted_&&!check_&&!tool_recovery()&&cancel&&result_.value("state","")=="pending"&&!request_id_.empty()&&
   latest_.value("fresh",false)&&supported&&latest_.value("filament_cancel_protocol",0)==1&&
   operation.value("session","")==operation_session(latest_)&&operation.value("id","")==request_id_&&
   operation.value("head","")==review_.physical_head()&&operation.value("state","")=="running"&&!operation.value("cancel_requested",false);
 }
 static std::string source_label(const Json&data,const Json&source){
  std::string title=source.value("name",source.value("id",""));
  if(source.value("kind","")=="ace"){
   const auto id=source.value("unit","");std::string name=id;
   for(const auto&unit:data.value("units",Json::array()))if(unit.value("id","")==id)name=unit.value("name",id);
   title=name+(name==id?"":" ("+id+")")+" - Slot "+std::to_string(source.value("slot",-1)+1);
  }
  const auto identity=source.value("identity",Json::object());
  if(!identity.empty())title+="\n"+identity_display_text(identity,"brand","Generic")+" "+identity.value("material","");
  return title;
 }
 static void style(void*p,std::uintptr_t s){stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(p,reinterpret_cast<void*>(s),0);}
 void*label(void*p,const std::string&s,int x,int y,int w,int h){auto*l=stock_function<void*(*)(void*)>(lv_label_create)(p);if(!l)throw std::runtime_error("Procedure label allocation failed");stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(l,reinterpret_cast<void*>(MyriadPro_Regular_16),0);stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(l,0xffeeeeeeU,0);stock_function<void(*)(void*,const char*)>(lv_label_set_text)(l,s.c_str());if(h<0){stock_function<void(*)(void*,int,int)>(lv_obj_set_pos)(l,x,y);stock_function<void(*)(void*,int)>(lv_obj_set_width)(l,w);}else stock_object_place(l,x,y,w,h);return l;}
 bool bind(void*object,const std::string&action){bindings_.push_back({this,object,root_,action});if(stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(object,&event,0,&bindings_.back()))return true;bindings_.pop_back();return false;}
 static void header_enabled(void*object,bool enabled){
  stock_function<void(*)(void*,unsigned)>(enabled?lv_obj_clear_state:lv_obj_add_state)(object,128);
  auto*caption=stock_function<void*(*)(void*,int)>(lv_obj_get_child)(object,0);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(caption,enabled?0xffeeeeeeU:0xff888888U,0);
 }
 void*header(const std::string&id,const std::string&text,int x,int w){
  auto*b=stock_header_action(root_,text,x,0,w,34,34);if(!b)throw std::runtime_error("Procedure action allocation failed");
  if(!bind(b,id))throw std::runtime_error("Procedure action binding failed");
  return b;
 }

 void*button(void*p,const std::string&id,const std::string&s,int x,int y,int w,int h){auto*b=stock_function<void*(*)(void*)>(lv_btn_create)(p);if(!b)throw std::runtime_error("Procedure button allocation failed");style(b,0x463c8e8);stock_object_place(b,x,y,w,h);auto*l=label(b,s,8,8,w-16,h-16);center_button_caption(b,l,s);if(!bind(b,id))throw std::runtime_error("Procedure button binding failed");return b;}
 static void event(void*e)noexcept{try{
  auto*b=static_cast<Binding*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(!b)return;auto*o=b->owner;
  const int code=stock_function<int(*)(void*)>(lv_event_get_code)(e);
  if(code==33){if(b->object==o->root_)o->root_=o->description_=o->begin_=o->empty_=o->close_=nullptr;for(auto i=o->bindings_.begin();i!=o->bindings_.end();++i)if(&*i==b){o->bindings_.erase(i);break;}return;}
  if(code!=7||b->root!=o->root_||!o->active()||stock_function<void*(*)(void*)>(lv_event_get_target)(e)!=b->object)return;
  auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(stock_function<void*(*)()>(lv_disp_get_default)());bool visible=false;
  for(void*p=o->root_;p;p=stock_function<void*(*)(void*)>(lv_obj_get_parent)(p)){if(!stock_object_valid(p)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return;if(p==screen){visible=true;break;}}
  if(!visible)return;
  const auto action=b->action;
  if(action=="close"){o->close();return;}
  if(o->submitted_){if(action=="begin"){
   if(o->result_.value("state","")=="complete"){o->close();return;}
   if(o->can_cancel()){if(o->cancel(o->request_id_))o->result_["message"]="Requesting cancellation.";}
   else if(o->can_recover()){if((o->tool_recovery()?o->recover_toolhead:o->recover)(o->request_id_)){o->recovering_=o->tool_recovery();o->result_["message"]=o->tool_recovery()?"Checking head attachment...":"Verifying the stopped head.";}}
   o->update(o->latest_);
  }return;}
  if(o->check_&&(action=="begin"||action=="empty")){
   if(!o->check_ready(o->latest_)||!o->confirm_filament)return;
   try{const auto result=o->confirm_filament(o->check_head_,action=="begin"?"loaded":"empty");o->result_={{"state",result.state},{"message",result.message}};}
   catch(...){o->result_={{"state","unknown"},{"message","Confirmation outcome unknown. Inspect printer state."}};}
   o->submitted_=true;o->update(o->latest_);return;
  }
  if(action.compare(0,7,"source:")==0){if(o->review_.select(o->latest_,action.substr(7))&&o->latest_.value("owner","")=="standalone")o->layout(true);o->update(o->latest_);return;}
  if(action=="begin"&&o->review_.ready(o->latest_)&&o->submit){
   o->submitted_=true;
   try{const auto result=o->submit(o->review_);o->request_id_=result.id;o->result_={{"state",result.state},{"message",result.message}};}
   catch(...){o->result_={{"state","unknown"},{"message","Submission outcome is unknown. Inspect printer state before retrying."}};}
   o->update(o->latest_);
  }
 }catch(...){} }
};
}}
