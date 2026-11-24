// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "button_caption.hpp"
#include "profile1113.hpp"
#include "stock_palette.hpp"
#include "stock_dialog_backdrop.hpp"
#include "ace_unit_preview.hpp"
#include "ace_adoption.hpp"
#include "../model.hpp"
#include <list>
#include <map>
#include <tuple>
#include <exception>
namespace wmp_ui { namespace native {
#ifdef WMP_NATIVE_TEST
void* test_resolve(std::uintptr_t);
#endif
// ACE content only. Parent is the existing stock Filament content object;
// stock sidebar, status area, Settings tabs and head tabs remain outside this
// scroll pane. No command dispatch: actions carry exact source/unit IDs.
class StockAceFilaments {
 struct Binding{StockAceFilaments*owner;void*object;std::uint64_t generation;std::string action;bool pressed=false;std::string pressed_action,pressed_context;};
 // Keys describe widget identity, not current telemetry. A render updates the
 // existing tree; only widgets absent from the new view are retired.
 struct Widget {void*object=nullptr;unsigned frame=0;std::string text,options;bool text_set=false;std::vector<std::pair<std::uintptr_t,unsigned>>styles;};
 using WidgetKey=std::tuple<void*,std::uintptr_t,std::string>;
 std::map<WidgetKey,Widget>widgets_;unsigned frame_=0;std::string view_;
 struct RenderFrame {
  StockAceFilaments&owner;int scroll;
  RenderFrame(StockAceFilaments&o,int target_scroll):owner(o),scroll(target_scroll){++owner.frame_;}
  ~RenderFrame(){
   // A partial render must not become the cached final layout. Keep existing
   // widgets until a successful retry can decide which ones are obsolete.
   if(std::uncaught_exception()){owner.layout_.clear();owner.pending_scroll_=scroll;return;}
   owner.retire_widgets();
  }
 };
 std::list<Binding>bindings_;void*pane_=nullptr;std::uint64_t generation_=0;
 AceAdoption adoption_;bool adoption_visible_=false;
 Json source_editor_,source_context_,profile_draft_;std::string profile_name_;std::vector<Json>profile_options_;std::string source_brand_;bool identity_busy_=false;std::vector<std::string>brand_options_,material_options_;std::string source_colour_,source_notice_,source_material_;void*choice_armed_=nullptr;bool colour_save_ready_=false;
 AceUnitPreview unit_preview_;Json snapshot_;std::string selected_head_;
 int overview_scroll_=0,detail_scroll_=0,pending_scroll_=-1;
 bool remove_confirm_=false,quick_assign_=false,material_preview_=false;
 bool loading_=false,brand_picker_=false;unsigned brand_page_=0;
 bool blocked_=false;int source_origin_head_=-1;std::string slot_menu_,dryer_unit_;void*slot_menu_object_=nullptr;
 bool picker_=false;std::string picker_route_;int picker_overview_scroll_=0;
 bool fresh_=false;std::string layout_;int width_=0,height_=0;
public:
 // Navigation discards local editor state, never an operation/receipt. This
 // also covers stock pages hidden and later reused without reconstruction.
 bool modal_active()const{return source_editor_.is_object()||unit_preview_.active()||adoption_visible_||!dryer_unit_.empty();}
 bool loading()const{return loading_;}
 void open_load(const std::string&id){activate("edit:"+id);loading_=source_editor_.is_object();colour_save_ready_=true;layout_.clear();}
 void discard_drafts(){
  loading_=false;brand_picker_=false;
  if(!dryer_unit_.empty()){dryer_unit_.clear();pending_scroll_=overview_scroll_;layout_.clear();}
  if(!slot_menu_.empty()){slot_menu_.clear();layout_.clear();}
  if(!source_editor_.is_object()&&!unit_preview_.active()&&!adoption_visible_)return;
  source_editor_=Json();source_context_=Json();profile_draft_=Json();profile_name_.clear();source_colour_.clear();source_brand_.clear();source_material_.clear();source_notice_.clear();
  colour_save_ready_=false;source_origin_head_=-1;material_preview_=false;
  unit_preview_.clear();quick_assign_=false;remove_confirm_=false;adoption_visible_=false;
  pending_scroll_=overview_scroll_;layout_.clear();
 }
 // Open a head's identity only when its source is unambiguous. Never pick
 // the first ACE slot merely because multiple slots share a physical head.
 bool open_head_identity(const std::string&head){
  if(!fresh_||blocked_||picker_||!valid(pane_))return false;
  Json selected_head;unsigned heads=0;
  for(const auto&h:snapshot_.value("heads",Json::array()))if(h.value("id","")==head){selected_head=h;++heads;}
  if(heads!=1)return false;
  const auto loaded=selected_head.value("loaded",Json::object());
  const auto state=loaded.value("state","");
  const auto source_id=loaded.value("source","");
  if(state!="empty"&&(state!="loaded"||source_id.empty()))return false;
  Json selected;unsigned matches=0;
  for(const auto&source:snapshot_.value("sources",Json::array())){
   if(source.value("head","")!=head)continue;
   if(state=="loaded"&&source.value("id","")!=source_id)continue;
   selected=source;++matches;
  }
  if(matches!=1||selected.value("id","").empty())return false;
  activate("edit:"+selected.value("id",""));
  return source_editor_==selected;
 }
 void source_origin(unsigned head){source_origin_head_=head<4?int(head):-1;layout_.clear();}
 void interaction_blocked(bool value){blocked_=value;}
 void picker_mode(bool enabled){if(picker_==enabled)return;picker_=enabled;source_editor_=Json();unit_preview_.clear();quick_assign_=false;layout_.clear();}
 Json unit_draft()const{return unit_preview_.draft();}
 bool unit_draft_valid(const Json&data)const{return unit_preview_.valid(data)&&AceUnitPreview::idle(data);}
 void unit_saved(const Json&draft){
  if(unit_preview_.draft()!=draft)return; // Never close a different editor or discard newer edits.
  unit_preview_.clear();quick_assign_=false;remove_confirm_=false;pending_scroll_=overview_scroll_;layout_.clear();
 }
 bool rename_draft(const std::string&name){if(!unit_preview_.rename(snapshot_,name))return false;layout_.clear();return true;}
 const Json&selected_source()const{return source_editor_;}
 const Json&selected_source_context()const{return source_context_;}
 Json draft_identity()const{auto identity=source_editor_.value("identity",Json::object());if(profile_draft_.is_object()){for(const auto*key:{"nozzle_temp","nozzle_temp_min","nozzle_temp_max","bed_temp"})identity.erase(key);for(auto it=profile_draft_.begin();it!=profile_draft_.end();++it)identity[it.key()]=it.value();}if(!source_brand_.empty())identity["brand"]=source_brand_;if(!source_colour_.empty())identity["color"]=source_colour_;if(!source_material_.empty()){if(identity.value("material","")!=source_material_)for(const auto*key:{"nozzle_temp","nozzle_temp_min","nozzle_temp_max","bed_temp"})identity.erase(key);identity["material"]=source_material_;}return identity;}
 void identity_pending(bool value){identity_busy_=value;layout_.clear();}
 std::string unit_draft_reason(const Json&data)const{auto why=unit_preview_.invalid_reason(data);if(!why.empty())return why;return "Unit editing requires idle or complete job; current="+rejection_value(data.value("job",Json::object()).value("state",""))+".";}
 std::string identity_reason()const{
  if(!load_position_ready())return "Filament load position is not ready.";
  if(loading_&&(draft_identity().value("material","")=="Unknown"||draft_identity().value("material","").empty()))return "Loading requires a known filament material.";
  if(identity_busy_)return "Filament identity save is pending.";
  if(!source_editor_.is_object())return "Filament editor has no source draft.";
  if(!fresh_)return "Filament editor requires fresh status.";
  if(!filament_identity_editable(snapshot_,source_editor_.value("head","")))return filament_identity_reason(snapshot_,source_editor_.value("head",""));
  if(!filament_source_edit_context_matches(snapshot_,source_context_,source_editor_))return "Filament source or editing context changed.";
  if(!colour_save_ready_)return "Filament colour save is not ready.";
  return "Filament identity has no pending edits.";
 }
 bool identity_ready()const{return load_position_ready()&&(!loading_||(draft_identity().value("material","")!="Unknown"&&!draft_identity().value("material","").empty()))&&!identity_busy_&&source_editor_valid()&&colour_save_ready_&&(loading_||profile_draft_.is_object()||!source_brand_.empty()||!source_colour_.empty()||!source_material_.empty());}
 const std::string&draft_colour()const{return source_colour_;}
 void colour_draft(const std::string&id,const std::string&colour){if(source_editor_.is_object()&&source_editor_.value("id","")==id){colour_save_ready_=true;source_colour_=colour;source_notice_="Unsaved changes";layout_.clear();}}
 void colour_result(const std::string&id,const std::string&message){if(source_editor_.is_object()&&source_editor_.value("id","")==id){colour_save_ready_=false;source_notice_=message;layout_.clear();}}
 void colour_saved(const Json&data,const Json&source){if(source_editor_.is_object()&&source_editor_.value("id","")==source.value("id","")){identity_busy_=false;if(data.value("owner","")=="standalone"&&!loading_){brand_picker_=false;material_preview_=false;activate("source-back");return;}source_editor_=source;source_context_=data;profile_draft_=Json();profile_name_.clear();source_colour_.clear();source_brand_.clear();source_material_.clear();source_notice_="Filament settings saved.";layout_.clear();}}
 std::function<void(unsigned)>focus_head;
 std::function<void(const std::string&)>action;
 std::function<Receipt(const Json&,const Json&)>adopt;
 void observe_adoption(const Json&data){adoption_.observe(data);}
 bool adoption_unresolved()const{const auto&op=adoption_.operation();return op.is_object()&&(op.value("state","")=="pending"||op.value("state","")=="unknown");}
 const Json&adoption_operation()const{return adoption_.operation();}
 void mount(void*content){
  if(valid(pane_)&&fn<void*(*)(void*)>(lv_obj_get_parent)(pane_)==content)return;
  if(valid(pane_))fn<void(*)(void*,unsigned)>(lv_obj_add_flag)(pane_,1);
  widgets_.clear();view_.clear();pane_=nullptr;slot_menu_object_=nullptr;slot_menu_.clear();dryer_unit_.clear();layout_.clear();brand_picker_=false;material_preview_=false;source_origin_head_=-1;adoption_visible_=false;unit_preview_.clear();source_editor_=Json();source_context_=Json();profile_draft_=Json();profile_name_.clear();source_colour_.clear();source_brand_.clear();source_material_.clear();source_notice_.clear();remove_confirm_=false;quick_assign_=false;overview_scroll_=detail_scroll_=0;pending_scroll_=-1;++generation_;
  if(!valid(content))return;
  pane_=fn<void*(*)(void*)>(lv_obj_create)(content);
  if(!pane_)return;
  style(pane_,0x463c8d8);bind(pane_,"");
  fn<void(*)(void*,int)>(lv_obj_set_scroll_dir)(pane_,12);
  fn<void(*)(void*,int)>(lv_obj_set_scrollbar_mode)(pane_,3);
 }
 void update(const Json&data,const std::string&head,int width,int height,int footer=0){
  if(picker_&&valid(pane_)){
   const auto route=data.value("picker_route_source","");
   if(route!=picker_route_){
    if(picker_route_.empty())picker_overview_scroll_=fn<int(*)(void*)>(lv_obj_get_scroll_y)(pane_);
    pending_scroll_=route.empty()?picker_overview_scroll_:0;picker_route_=route;
   }
  }
  snapshot_=data;selected_head_=head;adoption_.observe(data);
  fresh_=data.value("fresh",false)&&(data.value("owner","")=="openace"||data.value("owner","")=="standalone");
  if(picker_)fresh_=fresh_&&data.value("picker_editable",false);
  if(!valid(pane_)||width<640||height<300)return;
  const bool modal=!picker_&&modal_active();
  stock_dialog_backdrop(pane_);
  fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(pane_,0xff3c3e42U,0);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(pane_,255,0);
  fn<void(*)(void*,unsigned)>(modal&&!remove_confirm_?lv_obj_clear_flag:lv_obj_add_flag)(pane_,16);
  const bool head_tabs=data.value("head_tabs_visible",true);
  rect(pane_,modal?8:0,modal?8:picker_||!head_tabs?0:52,modal?width-16:width,modal?height-16:height-(picker_||!head_tabs?4:56)-footer);
  if(modal)width-=16;
  fit_open_lists();
  auto units=data.value("units",Json::array()),sources=data.value("sources",Json::array()),candidates=data.value("candidates",Json::array());
  if(picker_&&data.value("owner","")!="openace")units=Json::array();
  Json presence=Json::object();for(const auto&h:data.value("heads",Json::array()))presence[h.value("id","")]=h.value("loaded",Json::object());
  const auto key=Json{{"details_ready",filament_details_ready(data)},{"load_temperature",load_temperature_notice()},{"presence",presence},{"dryer_unit",dryer_unit_},{"slot_menu",slot_menu_},{"picker_row",data.value("picker_row","")},{"picker_revision",data.value("revision","")},{"picker_session",data.value("session","")},{"picker",picker_},{"picker_choices",data.value("picker_choices",Json::object())},{"picker_route_source",data.value("picker_route_source","")},{"units",units},{"sources",sources},{"routes",data.value("routes",Json::array())},{"candidates",candidates},{"head",head},{"fresh",fresh_},{"adoption_visible",adoption_visible_},{"adoption",adoption_.candidate()},{"adoption_operation",adoption_.operation()},{"adoptable",adoption_.can_confirm(data)},{"colour_save_ready",colour_save_ready_},{"catalogue",data.value("filament_catalogue",Json::array())},{"profile_draft",profile_draft_},{"source_colour",source_colour_},{"brand_picker",brand_picker_},{"brand_page",brand_page_},{"source_brand",source_brand_},{"source_material",source_material_},{"brands",data.value("brands",Json::array())},{"filament_position",data.value("filament_position",Json::object())},{"source_notice",source_notice_},{"source_editor",source_editor_},{"source_valid",source_editor_valid()},{"unit",unit_preview_.draft()},{"draft",unit_preview_.assignments()},{"slot",unit_preview_.slot()},{"remove",remove_confirm_},{"quick_assign",quick_assign_},{"draft_valid",unit_preview_.valid(data)},{"idle",AceUnitPreview::idle(data)}}.dump();
  if(layout_==key&&width_==width&&height_==height)return;
  const int scroll=pending_scroll_>=0?pending_scroll_:fn<int(*)(void*)>(lv_obj_get_scroll_y)(pane_);pending_scroll_=-1;
  const auto view=source_editor_.is_object()?(brand_picker_?"brands:":"source:")+source_editor_.value("id",""):
   unit_preview_.active()?"unit":!dryer_unit_.empty()?"dryer:"+dryer_unit_:adoption_visible_?"adoption":picker_?"picker":"overview";
  if(view_!=view){widgets_.clear();fn<void(*)(void*)>(lv_obj_clean)(pane_);view_=view;}
  RenderFrame render(*this,scroll);layout_=key;width_=width;height_=height;
  if(picker_&&!data.value("picker_route_source","").empty()){
   const auto choices=data.value("picker_choices",Json::object()).value(data.value("picker_route_source",""),Json::array());
   header_title("Choose tool route",12,0,width-180,30);
   picker_header(width);
   button(pane_,"picker-back","Back to slots",12,40,width-24,38);int y=84;
   for(const auto&route:choices){button(pane_,"choose:"+route.value("id",""),route.value("label",route.value("id","")),12,y,width-24,44);y+=50;}
   fn<void(*)(void*)>(lv_obj_update_layout)(pane_);fn<void(*)(void*,int,int)>(lv_obj_scroll_to_y)(pane_,scroll,0);return;
  }
  if(!picker_&&adoption_visible_&&adoption_.active()){render_adoption(width);fn<void(*)(void*)>(lv_obj_update_layout)(pane_);fn<void(*)(void*,int,int)>(lv_obj_scroll_to_y)(pane_,scroll,0);return;}
  if(!dryer_unit_.empty()){render_dryer(width);return;}
  if(source_editor_.is_object()){render_source(width);fn<void(*)(void*)>(lv_obj_update_layout)(pane_);fn<void(*)(void*,int,int)>(lv_obj_scroll_to_y)(pane_,scroll,0);return;}
  if(unit_preview_.active()){render_unit(width);fn<void(*)(void*)>(lv_obj_update_layout)(pane_);fn<void(*)(void*,int,int)>(lv_obj_scroll_to_y)(pane_,scroll,0);return;}
  int y=0;
  if(picker_){header_title("Choose filament source",12,0,width-180,32);picker_header(width);y=44;}
  // Status feedback uses existing headings so updates never shift targets.
  if(!picker_&&!adoption_.operation().is_null()){
   button(pane_,"adopt-status","ACE registration: "+adoption_.operation().value("state","unknown")+" - View",12,y,width-24,46);y+=52;
  }
  if(!picker_)for(const auto&candidate:candidates){
   auto name=candidate.value("name","New ACE unit"),device=candidate.value("device_label","");
   if(!device.empty()&&device!=name)name+=" - "+device;
   button(pane_,"adopt:"+candidate.value("id",""),"Adopt "+name,12,y,width-24,46,!adoption_.pending());y+=52;
  }
  for(const auto&unit:units){
   const auto id=unit.value("id","");auto*box=panel(pane_,12,y,width-24,204,"unit:"+id);
   label(box,unit.value("name",id)+(!fresh_?" - status unavailable":unit.value("connected",false)?" - connected":" - disconnected"),8,6,width-(picker_?180:330),28);
   if(!picker_){
    auto*control=button(box,"dryer:"+id,"Dryer ?",width-284,4,124,32);
    auto*caption=fn<void*(*)(void*,int)>(lv_obj_get_child)(control,0);rect(caption,32,4,86,24);
    // Neutral sun + question mark: unknown is not the confirmed-off gray state.
    sun(control,8,7,0xffeeeeeeU);
    button(box,"unit:"+id,"Edit unit",width-150,4,112,32);
   }
   const int slot_width=(width-56)/4;
   for(int slot=0;slot<4;++slot){Json source;
    for(const auto&s:sources)if(s.value("kind","")=="ace"&&s.value("unit","")==id&&s.value("slot",-1)==slot){source=s;break;}
    const int x=8+slot*(slot_width+4);auto*card=panel(box,x,42,slot_width,154,"slot:"+std::to_string(slot)+(source.is_null()?":unavailable":":"+source.value("id","")));
    if(source.is_null()){label(card,"Slot "+std::to_string(slot+1)+"\nUnavailable",6,8,slot_width-12,80);continue;}
    source_card(card,source,head,slot_width,154,"Slot "+std::to_string(slot+1));
   }
   y+=212;
  }
  // External sources share the ACE slot grid, ordered by physical head.
  Json external=Json::array();
  for(unsigned index=0;index<4;++index){
   const auto physical_head="h"+std::to_string(index);bool assigned=false;
   for(const auto&other:sources)if(other.value("kind","")=="ace"&&other.value("head","")==physical_head)assigned=true;
   if(assigned)continue;
   for(const auto&source:sources)if(source.value("kind","")=="external"&&source.value("head","")==physical_head){external.push_back(source);break;}
  }
  if(!external.empty()){
   auto*box=panel(pane_,12,y,width-24,204,"external");label(box,fresh_?"External":"External - status unavailable",8,6,width-40,28);const int sw=(width-56)/4;
   for(std::size_t i=0;i<external.size();++i){auto*card=panel(box,8+int(i)*(sw+4),42,sw,154,"source:"+external[i].value("id",""));source_card(card,external[i],head,sw,154,external[i].value("name",external[i].value("head","")));}
   y+=212;
  }
  if(units.empty()&&y==0)label(pane_,picker_?"No filament sources available":"No ACE units registered",12,0,width-24,28);
  fn<void(*)(void*)>(lv_obj_update_layout)(pane_);
  fn<void(*)(void*,int,int)>(lv_obj_scroll_to_y)(pane_,scroll,0);
 }
private:
 template<class F>static F fn(std::uintptr_t a){
#ifdef WMP_NATIVE_TEST
  return reinterpret_cast<F>(test_resolve(a));
#else
  return reinterpret_cast<F>(a);
#endif
 }
 static bool valid(void*p){return p&&fn<bool(*)(void*)>(lv_obj_is_valid)(p);}
 void fit_open_lists(){
  // Vendor dropdowns are reparented to the screen and positioned against its
  // edges. Keep our selectors inside the content, below the dialog actions.
  fn<void(*)(void*)>(lv_obj_update_layout)(pane_);
  std::int16_t bounds[4];fn<void(*)(void*,void*)>(lv_obj_get_coords)(pane_,bounds);
  const int left=bounds[0]+4,top=bounds[1]+38,right=bounds[2]-4,bottom=bounds[3]-4;
  if(right<=left||bottom<=top)return;
  for(const auto&binding:bindings_){
   if(binding.action!="material-dropdown"&&binding.action!="profile-dropdown"&&binding.action.compare(0,14,"slot-dropdown:")!=0)continue;
   auto*object=binding.object;if(!valid(object)||!fn<bool(*)(void*)>(lv_dropdown_is_open)(object))continue;
   auto*list=fn<void*(*)(void*)>(lv_dropdown_get_list)(object);if(!valid(list)||list==object)continue;
   fn<void(*)(void*)>(lv_obj_update_layout)(list);
   std::int16_t box[4];fn<void(*)(void*,void*)>(lv_obj_get_coords)(list,box);
   const int w=std::min(int(box[2]-box[0]+1),right-left+1),h=std::min(int(box[3]-box[1]+1),bottom-top+1);
   const int x=std::max(left,std::min(int(box[0]),right-w+1)),y=std::max(top,std::min(int(box[1]),bottom-h+1));
   if(x!=box[0]||y!=box[1]||w!=box[2]-box[0]+1||h!=box[3]-box[1]+1){
    auto*parent=fn<void*(*)(void*)>(lv_obj_get_parent)(list);std::int16_t origin[4];fn<void(*)(void*,void*)>(lv_obj_get_content_coords)(parent,origin);
    fn<void(*)(void*,int,int)>(lv_obj_set_size)(list,w,h);
    fn<void(*)(void*,int,int)>(lv_obj_set_pos)(list,x-origin[0],y-origin[1]);
   }
  }
 }
 void retire_widgets(){
  std::vector<void*>obsolete;
  for(auto it=widgets_.begin();it!=widgets_.end();){if(it->second.frame!=frame_){obsolete.push_back(it->second.object);it=widgets_.erase(it);}else ++it;}
  for(auto*object:obsolete){if(object==slot_menu_object_)slot_menu_object_=nullptr;if(valid(object))fn<void(*)(void*)>(lv_obj_del)(object); }
 }
 void*widget(void*parent,std::uintptr_t factory,const std::string&key){
  auto&entry=widgets_[WidgetKey(parent,factory,key)];
  if(!valid(entry.object)){entry=Widget();entry.object=fn<void*(*)(void*)>(factory)(parent);if(!entry.object)throw std::runtime_error("Filament widget allocation failed");}
  entry.frame=frame_;return entry.object;
 }
 Widget&record(void*object){for(auto&entry:widgets_)if(entry.second.object==object)return entry.second;throw std::runtime_error("Untracked filament widget");}
 static std::string position_key(int x,int y){return std::to_string(x)+":"+std::to_string(y);}
 static void enabled(void*object,bool enable){fn<void(*)(void*,unsigned)>(enable?lv_obj_clear_state:lv_obj_add_state)(object,128);}
 void dropdown(void*object,const std::string&options,unsigned selected){
  auto&entry=record(object);
  if(entry.options!=options){
   if(fn<bool(*)(void*)>(lv_dropdown_is_open)(object)){fn<void(*)(void*)>(lv_dropdown_close)(object);if(choice_armed_==object)choice_armed_=nullptr;}
   fn<void(*)(void*,const char*)>(lv_dropdown_set_options)(object,options.c_str());entry.options=options;
  }
  if(fn<unsigned(*)(void*)>(lv_dropdown_get_selected)(object)!=selected)fn<void(*)(void*,unsigned)>(lv_dropdown_set_selected)(object,selected);
 }
 static void rect(void*p,int x,int y,int w,int h){fn<void(*)(void*,int,int)>(lv_obj_set_size)(p,w,h);fn<void(*)(void*,int,int,int)>(lv_obj_align)(p,1,x,y);}
 void style(void*p,std::uintptr_t address,unsigned selector=0){
  // Stock LVGL appends duplicates and has a six-bit style count. Retained
  // widgets must attach each style/selector only once, not on every refresh.
  if(p!=pane_){auto&styles=record(p).styles;const auto key=std::make_pair(address,selector);
   if(std::find(styles.begin(),styles.end(),key)!=styles.end())return;
   styles.push_back(key);
  }
  fn<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(p,reinterpret_cast<void*>(address),selector);
 }
 void bind(void*p,const std::string&id){
  for(auto&binding:bindings_)if(binding.object==p){binding.action=id;binding.generation=generation_;return;}
  Binding binding;binding.owner=this;binding.object=p;binding.generation=generation_;binding.action=id;bindings_.push_back(std::move(binding));auto*b=&bindings_.back();
  if(!fn<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(p,&event,0,b)){
   bindings_.pop_back();throw std::runtime_error("ACE content callback allocation failed");
  }
 }
 void*panel(void*parent,int x,int y,int w,int h,const std::string&key=""){auto*p=widget(parent,lv_obj_create,"panel:"+(key.empty()?position_key(x,y):key));if(!p)throw std::runtime_error("ACE content allocation failed");style(p,0x463c908);fn<void(*)(void*,unsigned)>(lv_obj_clear_flag)(p,16);rect(p,x,y,w,h);return p;}
 void*label(void*parent,const std::string&t,int x,int y,int w,int h){auto*p=widget(parent,lv_label_create,position_key(x,y));if(!p)throw std::runtime_error("ACE label allocation failed");fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(MyriadPro_Regular_16),0);fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(p,0xffeeeeeeU,0);if(!record(p).text_set||record(p).text!=t){fn<void(*)(void*,const char*)>(lv_label_set_text)(p,t.c_str());record(p).text=t;record(p).text_set=true;}rect(p,x,y,w,h);return p;}
 void header_title(const std::string&text,int x,int y,int width,int height=28){
  auto*object=label(pane_,text,x,y,width,height);
  // Names remain bound to their full IDs; only the one-line title is elided.
  // Wrapping here would put text underneath the header actions/body.
  fn<void(*)(void*,int)>(lv_label_set_long_mode)(object,1);
 }
 void*button(void*parent,const std::string&id,const std::string&t,int x,int y,int w,int h,bool enabled=true){auto*p=widget(parent,lv_btn_create,id+":"+position_key(x,y));if(!p)throw std::runtime_error("ACE button allocation failed");style(p,0x463c8e8);style(p,0x463c8f8,0x20);rect(p,x,y,w,h);label(p,t,6,4,w-12,h-8);center_button_caption(p,fn<void*(*)(void*,int)>(lv_obj_get_child)(p,0),t);bind(p,id);StockAceFilaments::enabled(p,!((!fresh_&&id!="unit-back"&&id!="slot-cancel"&&id!="remove-cancel"&&id!="adopt-cancel"&&id!="adopt-status"&&id!="source-back"&&id!="picker-close"&&id!="picker-back")||!enabled));return p;}
 void source_card(void*card,const Json&s,const std::string&head,int width,int height,const std::string&title){
  auto identity=s.value("identity",Json::object());bool empty=false,loaded=false;
  for(const auto&h:snapshot_.value("heads",Json::array()))if(h.value("id","")==s.value("head","")){const auto state=h.value("loaded",Json::object());loaded=state.value("state","")=="loaded"&&state.value("source","")==s.value("id","");}
  if(s.value("kind","")=="external"){
   // Configured defaults are useful in the loading editor, but they are not
   // evidence of the filament physically present in a standalone head.
   identity=Json::object();
   for(const auto&h:snapshot_.value("heads",Json::array()))if(h.value("id","")==s.value("head","")){
    const auto state=h.value("loaded",Json::object());empty=state.value("state","")=="empty";
    if(loaded)identity=state.value("identity",Json::object());
   }
  }
  if(empty)identity=Json::object();
  label(card,title,6,4,width-12,24);
  std::uint32_t rgb=0;
  const auto*asset=stock_white_filament_asset();
  if(asset&&stock_rgb(identity_display_text(identity,"color",""),rgb)){
   auto*colour=widget(card,lv_img_create,"swatch");
   if(!colour)throw std::runtime_error("Filament swatch allocation failed");
   fn<void(*)(void*,const void*)>(lv_img_set_src)(colour,asset);
   // Keep the native stock swatch size; the vendor image renderer clips
   // the transformed image in this parent when zoomed to half size.
   rect(colour,(width-83)/2,28,83,83);
   fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_img_recolor)(colour,rgb,0);
   fn<void(*)(void*,unsigned char,unsigned)>(lv_obj_set_style_img_recolor_opa)(colour,255,0);
   fn<void(*)(void*,unsigned)>(lv_obj_clear_flag)(colour,2);
  }else{
   auto*circle=panel(card,(width-64)/2,32,64,64);
   // The outline is decoration, just like the image swatch above. Let taps
   // reach the source card so unknown and empty identities remain selectable.
   fn<void(*)(void*,unsigned)>(lv_obj_clear_flag)(circle,2);
   fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_radius)(circle,32,0);
   fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_border_color)(circle,0xff999999U,0);
   fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_border_width)(circle,2,0);
   fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(circle,0,0);
   if(!empty)label(card,"?",(width-12)/2,52,12,24);
  }
  const bool external=s.value("kind","")=="external";
  label(card,empty?"":identity.empty()?"Unknown filament":identity_display_text(identity,"brand","Unknown brand")+(external?"":" "+identity.value("material","Unknown")),6,112,width-12,20);
  const auto assigned=s.value("head","");std::string target="Unassigned";
  if(assigned.size()==2&&assigned[0]=='h'&&assigned[1]>='0'&&assigned[1]<='3')target="Head "+std::to_string(assigned[1]-'0'+1);
  if(empty&&!picker_)button(card,"load-source:"+s.value("id",""),"Load",6,height-40,width-12,34,s.value("available",false)&&filament_details_ready(snapshot_));
  // External cards already name their physical head in the title. Use the
  // second line for material so longer brand/material pairs are not clipped.
  else label(card,external?(identity.empty()?"":identity.value("material","Unknown")):target,6,height-22,width-12,20);
  std::string click="menu:"+s.value("id","");bool eligible=true;
  if(picker_){const auto choices=snapshot_.value("picker_choices",Json::object()).value(s.value("id",""),Json::array());eligible=!choices.empty();click=choices.size()==1?"choose:"+choices[0].value("id",""):"route-source:"+s.value("id","");}
  bind(card,click);
  enabled(card,fresh_&&eligible);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_opa)(card,(picker_?eligible:head.empty()||assigned==head)?255:100,0);
  if(!picker_&&slot_menu_==s.value("id","")){
   auto*menu=panel(card,2,2,width-4,height-4);
   // Observe deletion when changing views: LVGL may reuse this address for
   // another widget before the next menu opens. Validity alone is insufficient.
   bind(menu,"");slot_menu_object_=menu;fn<void(*)(void*,unsigned)>(lv_obj_clear_flag)(menu,1);stock_dialog_backdrop(menu);
   fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(menu,0xff3c3e42U,0);
   fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(menu,255,0);
   button(menu,"edit:"+slot_menu_,"Edit",4,4,width-12,40);
   button(menu,(loaded?"unload-source:":"load-source:")+slot_menu_,loaded?"Unload":"Load",4,50,width-12,40,filament_details_ready(snapshot_)&&!assigned.empty()&&(loaded||(s.value("available",false)&&(s.value("kind","")!="external"||empty))));
   button(menu,"menu-close","Cancel",4,96,width-12,40);
  }
 }
 bool load_position_ready()const{
  return !loading_||snapshot_.value("owner","")!="standalone"||snapshot_.value("filament_position",Json::object()).value("ready",true);
 }
 std::string load_temperature_notice()const{
  if(!loading_||snapshot_.value("owner","")!="standalone"||!source_editor_.is_object())return "";
  const auto original=source_editor_.value("identity",Json::object()),draft=draft_identity();
  for(const auto*key:{"material","nozzle_temp","nozzle_temp_min","nozzle_temp_max"})
   if(original.value(key,Json())!=draft.value(key,Json()))return "Load temperature will be recalculated for the selected material.";
  const auto head=source_editor_.value("head","");
  for(const auto&plan:snapshot_.value("procedures",Json::array()))
   if(plan.value("head","")==head&&plan.value("action","")=="load"&&plan.value("source","")==source_editor_.value("id",""))
    return plan.value("temperature_description","");
  return snapshot_.value("procedure_errors",Json::object()).value(head+":load","");
 }
 bool source_editor_valid()const{
  if(!source_editor_.is_object()||!fresh_||!filament_identity_editable(snapshot_,source_editor_.value("head","")))return false;
  return filament_source_edit_context_matches(snapshot_,source_context_,source_editor_);
 }
 unsigned brands_per_page()const{return 3*unsigned(std::max(3,(height_-106)/48));}
 void render_brand(int width,const std::string&selected,bool editable){
  auto*p=button(pane_,"source-brand",selected,156,44,width-168,46,editable);
  auto*caption=fn<void*(*)(void*,int)>(lv_obj_get_child)(p,0);
  fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(caption,reinterpret_cast<void*>(MyriadPro_Regular_20),0);
  fn<void(*)(void*,int,int)>(lv_obj_set_size)(caption,width-180,26);
  fn<void(*)(void*,int,int,int)>(lv_obj_align)(caption,1,0,10);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_text_align)(caption,0,0);
 }
 void render_brand_picker(int width){
  header_title("Select brand",12,2,width-150);
  header_action("source-back","BACK",width-112,100,true);
  auto*rule=panel(pane_,12,34,width-24,1);stock_dialog_backdrop(rule);
  fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(rule,0xff55575bU,0);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(rule,255,0);
  const unsigned count=brands_per_page(),pages=std::max(1U,unsigned((brand_options_.size()+count-1)/count));
  brand_page_=std::min(brand_page_,pages-1);
  const int cell=(width-40)/3;
  for(unsigned n=0;n<count&&brand_page_*count+n<brand_options_.size();++n){
   const auto&name=brand_options_[brand_page_*count+n];
   auto caption=name;if(caption.size()>18){const auto space=caption.rfind(' ',18);if(space!=std::string::npos)caption[space]='\n';}
   auto*p=button(pane_,"source-brand-choice:"+name,caption,12+(n%3)*(cell+8),44+(n/3)*48,cell,42,!identity_busy_&&source_editor_valid());
   const bool selected=name==identity_display_text(draft_identity(),"brand","Generic");
   fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(p,selected?0xffbf4900U:0xff53555aU,0);
   fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(p,255,0);
  }
  const int bottom=height_-62;
  button(pane_,"source-brand-prev","Previous",12,bottom,150,38,brand_page_>0);
  label(pane_,std::to_string(brand_page_+1)+" / "+std::to_string(pages),width/2-36,bottom+6,72,26);
  button(pane_,"source-brand-next","Next",width-162,bottom,150,38,brand_page_+1<pages);
 }
 void render_material_preview(int width){
  label(pane_,"Material selection - preview",12,0,width-24,28);
  label(pane_,"Current: "+draft_identity().value("material","Unknown"),12,34,width-24,28);
  label(pane_,"Example choices only. Material/profile changes are not connected yet.",12,68,width-24,48);
  const char*examples[]={"PLA","PETG","ABS","ASA","TPU","PA","PC"};
  const int cell=(width-32)/3;
  for(int i=0;i<7;++i)button(pane_,"material-preview-choice",examples[i],12+(i%3)*(cell+4),124+(i/3)*48,cell,40,false);
  button(pane_,"source-back","Back to filament settings",12,280,300,38);
 }
 void picker_header(int width){
  header_action("picker-close","CANCEL",width-140,128,true);
  auto*rule=panel(pane_,12,34,width-24,1);stock_dialog_backdrop(rule);
  fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(rule,0xff55575bU,0);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(rule,255,0);
 }
 void header_action(const std::string&id,const std::string&text,int x,int width,bool enabled){
  auto*object=widget(pane_,lv_obj_create,"action:"+id);if(!object)throw std::runtime_error("Header action allocation failed");
  stock_dialog_backdrop(object);rect(object,x,0,width,34);bind(object,id);
  label(object,text,4,2,width-8,26);
  auto*caption=fn<void*(*)(void*,int)>(lv_obj_get_child)(object,0);
  fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(caption,reinterpret_cast<void*>(MyriadPro_Bold_20),0);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_text_align)(caption,2,0);
  StockAceFilaments::enabled(object,enabled);if(!enabled){fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(caption,0xff888888U,0);}
 }
 void sun(void*parent,int x,int y,std::uint32_t colour){
  const int parts[][4]={{6,6,8,8},{9,0,2,4},{9,16,2,4},{0,9,4,2},{16,9,4,2},{2,2,3,3},{15,2,3,3},{2,15,3,3},{15,15,3,3}};
  for(unsigned i=0;i<9;++i){auto*p=panel(parent,x+parts[i][0],y+parts[i][1],parts[i][2],parts[i][3]);stock_dialog_backdrop(p);
   fn<void(*)(void*,unsigned)>(lv_obj_clear_flag)(p,2);
   fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(p,colour,0);
   fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(p,255,0);
   fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_radius)(p,i?0:4,0);
  }
 }
 void render_dryer(int width){
  std::string name=dryer_unit_;for(const auto&unit:snapshot_.value("units",Json::array()))if(unit.value("id","")==dryer_unit_)name=unit.value("name",dryer_unit_);
  header_title(name+" - Drying",12,2,width-140);header_action("dryer-close","CLOSE",width-112,100,true);
  auto*rule=panel(pane_,12,34,width-24,1);stock_dialog_backdrop(rule);
  fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(rule,0xff55575bU,0);fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(rule,255,0);
  label(pane_,"Humidity: -- %",12,44,width/2-24,28);label(pane_,"Temperature: -- C",width/2,44,width/2-12,28);
  label(pane_,"Status unavailable",12,104,width-24,26);
  label(pane_,"Target",12,148,132,28);button(pane_,"dryer-target","-- C",156,138,168,44,false);
  label(pane_,"Duration",width/2+12,148,100,28);button(pane_,"dryer-duration","-- h",width-172,138,160,44,false);
  button(pane_,"dryer-start","Start",12,202,148,40,false);button(pane_,"dryer-stop","Stop",172,202,148,40,false);
  label(pane_,"Waiting for openACE drying support",12,258,width-24,28);
 }
 void render_source(int width){
  if(brand_picker_){render_brand_picker(width);return;}
  if(material_preview_){render_material_preview(width);return;}
  const auto identity=draft_identity();
  std::string title=source_editor_.value("name",source_editor_.value("id",""));
  if(source_editor_.value("kind","")=="ace"){
   for(const auto&unit:snapshot_.value("units",Json::array()))if(unit.value("id","")==source_editor_.value("unit",""))title=unit.value("name",unit.value("id",""))+" - "+title;
  }else title="External - "+title;
  if(loading_)title="Load filament - "+source_editor_.value("name","");
  header_title(title,12,2,width-244);
  auto*rule=panel(pane_,12,34,width-24,1);stock_dialog_backdrop(rule);
  fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(rule,0xff55575bU,0);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(rule,255,0);
  const bool editable=!identity_busy_&&source_editor_valid();
  label(pane_,"Brand",12,56,136,28);
  label(pane_,"Material",12,112,136,28);
  label(pane_,"Colour",12,168,136,28);
  render_brand(width,identity_display_text(identity,"brand","Generic"),editable);
  auto*materials=widget(pane_,lv_dropdown_create,"material");
  if(!materials)throw std::runtime_error("Material selector allocation failed");
  style(materials,0x463c8e8);rect(materials,156,100,width-168,46);
  fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(materials,reinterpret_cast<void*>(MyriadPro_Regular_20),0);
  fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(materials,reinterpret_cast<void*>(lv_font_montserrat_14),0x20000);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_pad_top)(materials,10,0);
  fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(materials,0xffeeeeeeU,0);
  material_options_.clear();
  for(const auto&name:snapshot_.value("materials",Json::array({"PLA","PETG","ABS","ASA","TPU","PA","PC"})))if(name.is_string())material_options_.push_back(name.get<std::string>());
  const auto current=identity.value("material","");
  if(std::find(material_options_.begin(),material_options_.end(),current)==material_options_.end())material_options_.push_back(current);
  unsigned selected=0;std::string options;
  for(unsigned i=0;i<material_options_.size();++i){if(i)options+="\n";options+=material_options_[i];if(material_options_[i]==current)selected=i;}
  dropdown(materials,options,selected);
  bind(materials,"material-dropdown");enabled(materials,editable);
  const auto colour_text=source_colour_.empty()?identity_display_text(identity,"color",""):source_colour_;
  label(pane_,colour_text,256,168,width-268,28);
  auto*swatch=panel(pane_,156,156,88,48);std::uint32_t colour=0xff888888U;
  stock_rgb(source_colour_.empty()?identity_display_text(identity,"color",""):source_colour_,colour);
  fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(swatch,colour,0);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(swatch,255,0);
  fn<void(*)(void*,unsigned)>(lv_obj_add_flag)(swatch,2);
  bind(swatch,"source-colour");
  enabled(swatch,editable);
  profile_options_.clear();
  if(snapshot_.value("owner","")=="standalone")for(const auto&profile:snapshot_.value("filament_catalogue",Json::array()))if(profile.is_object()&&profile.contains("identity"))profile_options_.push_back(profile);
  if(!profile_options_.empty()){
   label(pane_,"Profile",12,224,136,28);
   auto*profiles=widget(pane_,lv_dropdown_create,"profile");if(!profiles)throw std::runtime_error("Profile selector allocation failed");
   style(profiles,0x463c8e8);rect(profiles,156,212,width-168,46);
   fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(profiles,reinterpret_cast<void*>(MyriadPro_Regular_20),0);
   fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(profiles,reinterpret_cast<void*>(lv_font_montserrat_14),0x20000);
   fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_pad_top)(profiles,10,0);
   fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(profiles,0xffeeeeeeU,0);
   std::string names="Custom";unsigned selected_profile=0;
   for(unsigned i=0;i<profile_options_.size();++i){names+="\n"+profile_options_[i].value("name","");if(profile_options_[i].value("name","")==profile_name_)selected_profile=i+1;}
   dropdown(profiles,names,selected_profile);
   bind(profiles,"profile-dropdown");style_list(profiles);enabled(profiles,editable);
  }

  auto notice=!fresh_?std::string("Printer status unavailable."):!source_editor_valid()?std::string("Filament settings changed. Go back and reopen."):load_position_ready()?source_notice_:snapshot_.value("filament_position",Json::object()).value("reason","Printer position is unavailable.");
  if(fresh_&&source_editor_valid()&&load_position_ready()){
   const auto temperature=load_temperature_notice();
   if(!temperature.empty()){if(!notice.empty())notice+="\n";notice+=temperature;}
  }
  if(!loading_&&draft_identity()!=source_editor_.value("identity",Json::object())){
   if(!notice.empty())notice+="\n";
   notice+="Back discards unsaved changes.";
  }
  const int notice_y=profile_options_.empty()?220:264;
  auto*notice_label=label(pane_,notice,12,notice_y,width-24,std::max(20,fn<int(*)(void*)>(lv_obj_get_content_height)(pane_)-notice_y-8));
  fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(notice_label,reinterpret_cast<void*>(lv_font_montserrat_14),0);
  fn<void(*)(void*,int)>(lv_label_set_long_mode)(notice_label,0);
  header_action("source-back","BACK",width-232,112,true);
  header_action("source-save",loading_&&snapshot_.value("owner","")=="standalone"?"NEXT":"SAVE",width-112,100,identity_ready());
 }
 bool adopted_unit_available()const{
  const auto&op=adoption_.operation();
  if(!fresh_||!op.is_object()||op.value("state","")!="complete"||
     snapshot_.value("owner","")!=op.value("owner","")||snapshot_.value("session","")!=op.value("session",""))return false;
  const auto id=adoption_.candidate().value("logical_name","");if(id.empty())return false;
  unsigned count=0;for(const auto&unit:snapshot_.value("units",Json::array()))if(unit.value("id","")==id)++count;
  return count==1;
 }
 void render_adoption(int width){
  const auto&candidate=adoption_.candidate();const auto&op=adoption_.operation();
  header_title("Adopt "+candidate.value("name","new ACE unit")+"?",12,8,width-260);
  label(pane_,candidate.value("device_label","Device identity unavailable"),12,60,width-24,52);
  label(pane_,op.is_null()?(adoption_.can_confirm(snapshot_)?"Register this unit, then review its slot assignments.":adoption_.unavailable(snapshot_)):op.value("message","Waiting for backend readback."),12,120,width-24,52);
  const int active=op.is_null()?-1:op.value("state","")=="complete"?1:0;
  for(int i=0;i<2;++i){
   label(pane_,i==0?"1. Register and verify ACE unit":"2. Review slot assignments",12,180+i*30,width-24,28);
   auto*p=widget(pane_,lv_label_create,position_key(12,180+i*30));
   fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(p,stage_color(i,active),0);
  }
  button(pane_,"adopt-cancel",op.is_null()?"Cancel":"Back to units",width-248,0,112,40);
  if(op.is_object()&&op.value("state","")=="complete")
   button(pane_,"adopt-review","Review slots",width-128,0,116,40,adopted_unit_available());
  else button(pane_,"adopt-confirm","Adopt",width-128,0,116,40,adoption_.can_confirm(snapshot_));
 }
 void render_unit(int width){
  const auto unit=unit_preview_.draft();const bool valid_draft=unit_preview_.valid(snapshot_);
  auto*name=button(pane_,"unit-name",unit.value("name",unit.value("id","")),12,0,width-240,34,valid_draft);
  auto*caption=fn<void*(*)(void*,int)>(lv_obj_get_child)(name,0);
  fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(caption,reinterpret_cast<void*>(MyriadPro_Bold_20),0);
  fn<void(*)(void*,int)>(lv_label_set_long_mode)(caption,1);
  if(quick_assign_){
   label(pane_,valid_draft?"Assign all four slots to one head":"Printer context changed - reopen unit details",12,48,width-24,28);
   int x=12;for(const auto&h:snapshot_.value("heads",Json::array())){
    const auto id=h.value("id","");button(pane_,"all-head:"+id,h.value("name",id),x,88,120,42,valid_draft);x+=128;
   }
   button(pane_,"slot-cancel","Cancel",width-108,0,96,40);return;
  }
  if(remove_confirm_){
   label(pane_,"Remove this ACE unit?",12,48,width-24,28);
   label(pane_,"Preview only. Removal and new tool numbering are not available.",12,84,width-24,48);
   button(pane_,"remove-cancel","Cancel",width-216,0,96,40);
   button(pane_,"remove-confirm","Remove",width-108,0,96,40,false);
   label(pane_,fresh_?"Current routes using this unit":"Last-known routes using this unit",12,182,width-24,28);
   int y=218;unsigned count=0;
   for(const auto&route:snapshot_.value("routes",Json::array())){
    Json source;unsigned matches=0;
    for(const auto&s:snapshot_.value("sources",Json::array()))if(s.value("id","")==route.value("source","")){source=s;++matches;}
    if(matches!=1||source.value("kind","")!="ace"||source.value("unit","")!=unit.value("id",""))continue;
    auto title=route.value("id","Unknown route");
    if(route.contains("tool")&&route["tool"].is_number_integer())title="T"+std::to_string(route["tool"].get<int>());
    const int slot=source.value("slot",-1);
    title+=" - "+std::string(slot>=0&&slot<4?"Slot "+std::to_string(slot+1):"Unknown slot");
    const auto head=route.value("head",source.value("head",""));
    title+=" - "+std::string(head.size()==2&&head[0]=='h'&&head[1]>='0'&&head[1]<='3'?"Head "+std::to_string(head[1]-'0'+1):"Head unknown");
    label(pane_,title,12,y,width-24,28);y+=34;++count;
   }
   if(!count){label(pane_,"No associated routes reported.",12,y,width-24,28);y+=34;}
   label(pane_,"Resulting T numbers require a backend removal plan.",12,y+8,width-24,48);return;
  }
  label(pane_,valid_draft?"ID: "+unit.value("id",""):"Status changed; reopen unit",12,58,width-160,24);
  auto*remove=button(pane_,"unit-remove","Remove",width-132,54,120,38,valid_draft&&AceUnitPreview::idle(snapshot_));
  fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(remove,0xffa52b2bU,0);
  fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(remove,255,0);
  if(!unit_preview_.slot().empty()){
   label(pane_,"Assign "+unit_preview_.slot()+" to:",12,108,width-24,28);
   int x=12;for(const auto&h:snapshot_.value("heads",Json::array())){
    const auto id=h.value("id","");button(pane_,"assign:"+id,h.value("name",id),x,144,120,38,valid_draft);x+=128;
   }
   button(pane_,"assign:","Unassigned",12,190,160,38,valid_draft);
   button(pane_,"slot-cancel","Cancel",180,190,140,38);
  }else{
   button(pane_,"all-to","All slots to one head",12,108,260,38,valid_draft);
   button(pane_,"distribute","Auto-distribute",280,108,200,38,valid_draft);
   const int sw=(width-40)/4;
   for(int index=0;index<4;++index){Json source;
    for(const auto&s:snapshot_.value("sources",Json::array()))if(s.value("unit","")==unit.value("id","")&&s.value("kind","")=="ace"&&s.value("slot",-1)==index){source=s;break;}
    if(source.is_null())continue;
    const auto id=source.value("id","");auto assigned=unit_preview_.assignments().value(id,"");
    std::string name="Unassigned";if(assigned.size()==2&&assigned[0]=='h')name="Head "+std::to_string(assigned[1]-'0'+1);
    label(pane_,"Slot "+std::to_string(index+1),12+index*(sw+4),154,sw,24);
    auto*choice=widget(pane_,lv_dropdown_create,"slot:"+id);
    if(!choice)throw std::runtime_error("Head selector allocation failed");
    style(choice,0x463c8e8);rect(choice,12+index*(sw+4),182,sw,42);
    fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(choice,reinterpret_cast<void*>(lv_font_montserrat_14),0);
    fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(choice,0xffeeeeeeU,0);
    const unsigned selected=assigned.size()==2&&assigned[0]=='h'&&assigned[1]>='0'&&assigned[1]<='3'?unsigned(assigned[1]-'0'):0;
    dropdown(choice,"Head 1\nHead 2\nHead 3\nHead 4",selected);
    // Unknown assignment is shown separately; no assignment is committed by opening the list.
    if(name=="Unassigned")label(pane_,name,12+index*(sw+4),226,sw,18);
    bind(choice,"slot-dropdown:"+id);enabled(choice,valid_draft);
   }
  }
  button(pane_,"unit-back","Cancel",width-216,0,96,40);
  const bool assignments_unchanged=unit_preview_.assignments()==unit_preview_.unit().value("assignments",Json::object());
  button(pane_,"unit-save","Save",width-108,0,96,40,valid_draft&&assignments_unchanged);
  if(!assignments_unchanged)label(pane_,"Assignment save unavailable",12,76,width-24,22);
 }
 void activate(const std::string&id){
  if(blocked_)return;
  if(picker_){
   if(id=="picker-close"||id=="picker-back"){if(action)action(id=="picker-close"?"close":"source-picker-back");return;}
   if(!fresh_)return;
   const auto choices=snapshot_.value("picker_choices",Json::object());bool allowed=false;
   if(id.compare(0,7,"choose:")==0)for(const auto&list:choices)for(const auto&route:list)if(route.value("id","")==id.substr(7))allowed=true;
   if(id.compare(0,13,"route-source:")==0)allowed=choices.value(id.substr(13),Json::array()).size()>1;
   if(allowed&&action)action(id);
   return;
  }
  if(id=="dryer-close"){dryer_unit_.clear();pending_scroll_=overview_scroll_;layout_.clear();return;}
  if(id.compare(0,6,"dryer:")==0){
   for(const auto&unit:snapshot_.value("units",Json::array()))if(unit.value("id","")==id.substr(6)){dryer_unit_=id.substr(6);overview_scroll_=fn<int(*)(void*)>(lv_obj_get_scroll_y)(pane_);pending_scroll_=0;layout_.clear();return;}
   return;
  }
  if(id.compare(0,6,"dryer-")==0)return; // Unsupported controls never dispatch, even synthetic events.
  if(id=="menu-close"){if(valid(slot_menu_object_))fn<void(*)(void*,unsigned)>(lv_obj_add_flag)(slot_menu_object_,1);slot_menu_.clear();layout_.clear();return;}
  if(id.compare(0,5,"menu:")==0){
   for(const auto&source:snapshot_.value("sources",Json::array()))if(source.value("id","")==id.substr(5)){
    if(valid(slot_menu_object_))fn<void(*)(void*,unsigned)>(lv_obj_add_flag)(slot_menu_object_,1);
    slot_menu_=id.substr(5);layout_.clear();const auto head=source.value("head","");
    if(head.size()==2&&head[0]=='h'&&head[1]>='0'&&head[1]<='3'&&focus_head)focus_head(unsigned(head[1]-'0'));
    return;
   }return;
  }
  if(id.compare(0,12,"load-source:")==0||id.compare(0,14,"unload-source:")==0){
   const bool unloading=id.compare(0,14,"unload-source:")==0;
   const auto source_id=id.substr(unloading?14:12);
   bool direct_load=false;
   if(!unloading&&slot_menu_.empty()&&fresh_){
    unsigned sources=0,empty_heads=0;
    for(const auto&s:snapshot_.value("sources",Json::array()))if(s.value("id","")==source_id){
     ++sources;
     if(s.value("kind","")=="external"&&s.value("available",false))
      for(const auto&h:snapshot_.value("heads",Json::array()))if(h.value("id","")==s.value("head","")&&h.value("loaded",Json::object()).value("state","")=="empty")++empty_heads;
    }
    direct_load=sources==1&&empty_heads==1;
   }
   if(source_id!=slot_menu_&&!direct_load)return;
   slot_menu_.clear();layout_.clear();if(action)action(id);return;
  }
  if(id=="source-back"){if(brand_picker_){brand_picker_=false;pending_scroll_=0;layout_.clear();return;}loading_=false;if(material_preview_){material_preview_=false;pending_scroll_=0;layout_.clear();return;}const int origin=source_origin_head_;source_origin_head_=-1;source_editor_=Json();source_context_=Json();profile_draft_=Json();profile_name_.clear();source_colour_.clear();source_brand_.clear();source_material_.clear();source_notice_.clear();pending_scroll_=overview_scroll_;layout_.clear();if(origin>=0&&fresh_&&action)action("toolhead:"+std::to_string(origin));return;}
  if(id.compare(0,5,"edit:")==0){
   const auto source_id=id.substr(5);Json selected;
   for(const auto&s:snapshot_.value("sources",Json::array()))if(s.value("id","")==source_id){if(selected.is_object())return;selected=s;}
   if(!selected.is_object())return;
   loading_=false;brand_picker_=false;slot_menu_.clear();material_preview_=false;source_editor_=selected;source_context_=snapshot_;profile_draft_=Json();profile_name_.clear();source_colour_.clear();source_brand_.clear();source_material_.clear();source_notice_.clear();overview_scroll_=fn<int(*)(void*)>(lv_obj_get_scroll_y)(pane_);pending_scroll_=0;layout_.clear();return;
  }
  if(id=="material-preview-choice")return; // Disabled even for queued/programmatic clicks.
  if(id.compare(0,7,"source-")==0&&!source_editor_valid())return;
  if(id=="source-brand"){
   if(identity_busy_)return;
   std::vector<std::string> catalogue;
   for(const auto&name:snapshot_.value("brands",Json::array()))if(name.is_string())catalogue.push_back(name.get<std::string>());
   for(const auto&source:snapshot_.value("sources",Json::array()))catalogue.push_back(identity_display_text(source.value("identity",Json::object()),"brand",""));
   brand_options_=brand_choices(catalogue,identity_display_text(draft_identity(),"brand","Generic"));
   const auto selected=std::find(brand_options_.begin(),brand_options_.end(),identity_display_text(draft_identity(),"brand","Generic"));
   brand_picker_=true;brand_page_=selected==brand_options_.end()?0:unsigned(selected-brand_options_.begin())/brands_per_page();
   pending_scroll_=0;layout_.clear();return;
  }
  if(id=="source-brand-next"||id=="source-brand-prev"){
   if(!brand_picker_)return;
   if(id=="source-brand-next"&&(brand_page_+1)*brands_per_page()<brand_options_.size())++brand_page_;
   if(id=="source-brand-prev"&&brand_page_>0)--brand_page_;
   pending_scroll_=0;layout_.clear();return;
  }
  if(id.compare(0,20,"source-brand-choice:")==0){
   if(!brand_picker_||identity_busy_)return;
   const auto name=id.substr(20);const auto begin=brand_options_.begin()+brand_page_*brands_per_page();
   const auto end=begin+std::min(std::size_t(brands_per_page()),std::size_t(brand_options_.end()-begin));
   if(std::find(begin,end,name)==end)return;
   source_brand_=name;colour_save_ready_=true;source_notice_="Unsaved changes";
   brand_picker_=false;pending_scroll_=0;layout_.clear();return;
  }
  if(id=="source-material")return; // Unsupported, including synthetic clicks.
  if(id=="adopt-cancel"){
   adoption_visible_=false;if(!adoption_.pending())adoption_.clear();
   pending_scroll_=overview_scroll_;layout_.clear();return;
  }
  if(id=="adopt-status"){
   if(adoption_.active()){adoption_visible_=true;overview_scroll_=fn<int(*)(void*)>(lv_obj_get_scroll_y)(pane_);pending_scroll_=0;layout_.clear();}return;
  }
  if(id.compare(0,6,"adopt:")==0){
   if(adoption_.pending())return;
   if(adoption_.begin(snapshot_,id.substr(6))){adoption_visible_=true;overview_scroll_=fn<int(*)(void*)>(lv_obj_get_scroll_y)(pane_);pending_scroll_=0;layout_.clear();}return;
  }
  if(id=="adopt-review"){
   if(!adopted_unit_available())return;
   if(unit_preview_.begin(snapshot_,adoption_.candidate().value("logical_name",""))){
    adoption_visible_=false;quick_assign_=false;remove_confirm_=false;pending_scroll_=0;layout_.clear();
   }
   return;
  }
  if(id=="remove-confirm")return; // Preview only; never dispatch a removal.
  if(id=="adopt-confirm"){
   if(!adoption_.can_confirm(snapshot_)||!adopt)return;
   adoption_.confirmed(adopt(adoption_.candidate(),adoption_.context()));layout_.clear();return;
  }
  if(id=="unit-back"){unit_preview_.clear();remove_confirm_=false;quick_assign_=false;pending_scroll_=overview_scroll_;layout_.clear();return;}
  if(id=="slot-cancel"){quick_assign_=false;unit_preview_.cancel_slot();pending_scroll_=detail_scroll_;layout_.clear();return;}
  if(id=="remove-cancel"){remove_confirm_=false;pending_scroll_=detail_scroll_;layout_.clear();return;}
  if(id.compare(0,5,"unit:")==0){if(unit_preview_.begin(snapshot_,id.substr(5))){quick_assign_=false;overview_scroll_=fn<int(*)(void*)>(lv_obj_get_scroll_y)(pane_);pending_scroll_=0;layout_.clear();}return;}
  if(unit_preview_.active()){
   if(!unit_preview_.valid(snapshot_))return;
   if(id=="unit-save"&&unit_preview_.assignments()!=unit_preview_.unit().value("assignments",Json::object()))return;
   if(id.compare(0,5,"slot:")==0){detail_scroll_=fn<int(*)(void*)>(lv_obj_get_scroll_y)(pane_);pending_scroll_=0;unit_preview_.select_slot(id.substr(5));layout_.clear();return;}
   if(id.compare(0,7,"assign:")==0){unit_preview_.assign(snapshot_,id.substr(7));pending_scroll_=detail_scroll_;layout_.clear();return;}
   if(id=="all-to"){detail_scroll_=fn<int(*)(void*)>(lv_obj_get_scroll_y)(pane_);pending_scroll_=0;quick_assign_=true;layout_.clear();return;}
   if(id.compare(0,9,"all-head:")==0){if(quick_assign_&&unit_preview_.all_to(snapshot_,id.substr(9))){quick_assign_=false;pending_scroll_=detail_scroll_;layout_.clear();}return;}
   if(id=="distribute"){unit_preview_.distribute(snapshot_);layout_.clear();return;}
   if(id=="unit-remove"||id=="remove-confirm"){
    if(!AceUnitPreview::idle(snapshot_))return;
    if(id=="unit-remove"){detail_scroll_=fn<int(*)(void*)>(lv_obj_get_scroll_y)(pane_);pending_scroll_=0;remove_confirm_=true;layout_.clear();return;}
   }
  }
  if(action)action(id);
 }
 static void style_list(void*object){
  auto*list=fn<void*(*)(void*)>(lv_dropdown_get_list)(object);if(!list)return;
  fn<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(list,reinterpret_cast<void*>(MyriadPro_Regular_16),0);
  for(unsigned part:{0U,0x40000U,0x40001U,0x40020U,0x40021U}){
   fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(list,0xffeeeeeeU,part);
   fn<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(list,part?0xffbf4900U:0xff3c3e42U,part);
   fn<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(list,255,part);
  }
 }
 std::string interaction_context()const{return Json{{"owner",snapshot_.value("owner","")},{"session",snapshot_.value("session","")},{"revision",snapshot_.value("revision","")},{"identity_revision",snapshot_.value("identity_revision","")}}.dump();}
 static void event(void*e)noexcept{try{
  auto*b=static_cast<Binding*>(fn<void*(*)(void*)>(lv_event_get_user_data)(e));if(!b)return;auto*o=b->owner;
  const int code=fn<int(*)(void*)>(lv_event_get_code)(e);
  if(code==33){if(o->slot_menu_object_==b->object)o->slot_menu_object_=nullptr;if(o->choice_armed_==b->object)o->choice_armed_=nullptr;if(o->pane_==b->object){o->pane_=nullptr;o->layout_.clear();}for(auto it=o->bindings_.begin();it!=o->bindings_.end();++it)if(&*it==b){o->bindings_.erase(it);break;}return;}
  if(code==7&&fn<void*(*)(void*)>(lv_event_get_target)(e)!=b->object)return;
  if(code==0){b->pressed=true;b->pressed_action=b->action;b->pressed_context=o->interaction_context();}
  if(code==7&&b->pressed){b->pressed=false;if(b->pressed_action!=b->action||b->pressed_context!=o->interaction_context())return;}
  if((b->action=="material-dropdown"||b->action=="profile-dropdown"||b->action.compare(0,14,"slot-dropdown:")==0)&&(code==31||code==28)){
   if(b->generation!=o->generation_||!valid(o->pane_)||o->blocked_||!o->fresh_)return;
   for(auto*p=o->pane_;p;p=fn<void*(*)(void*)>(lv_obj_get_parent)(p))if(fn<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return;
   const bool profile=b->action=="profile-dropdown";const bool material=b->action=="material-dropdown"||profile;
   if(material?(!o->source_editor_valid()||o->identity_busy_):!o->unit_preview_.valid(o->snapshot_))return;
   if(code==31){o->choice_armed_=b->object;style_list(b->object);return;}
   if(o->choice_armed_!=b->object)return;
   o->choice_armed_=nullptr;
   const auto selected=fn<unsigned(*)(void*)>(lv_dropdown_get_selected)(b->object);
   if(profile){
    if(selected>0&&selected<=o->profile_options_.size()){o->profile_draft_=o->profile_options_[selected-1].at("identity");o->profile_name_=o->profile_options_[selected-1].value("name","");o->source_brand_.clear();o->source_material_.clear();o->source_colour_.clear();o->colour_save_ready_=true;}
    else {o->profile_draft_=Json();o->profile_name_.clear();}
   }else if(material){
    if(o->profile_draft_.is_object()){o->source_brand_=identity_display_text(o->profile_draft_,"brand","");if(o->profile_draft_.contains("color"))o->source_colour_=identity_display_text(o->profile_draft_,"color","");}
    o->profile_draft_=Json();o->profile_name_.clear();
    if(selected<o->material_options_.size()){o->colour_save_ready_=true;o->source_material_=o->source_editor_.value("identity",Json::object()).value("material","")==o->material_options_[selected]?"":o->material_options_[selected];}
   }else if(selected<4){o->unit_preview_.select_slot(b->action.substr(14));o->unit_preview_.assign(o->snapshot_,"h"+std::to_string(selected));}
   if(material)o->source_notice_=o->draft_identity()!=o->source_editor_.value("identity",Json::object())?"Unsaved changes":"";
   o->layout_.clear();return;
  }
  if(code!=7||b->action.empty()||b->generation!=o->generation_||(!o->fresh_&&b->action!="dryer-close"&&b->action!="unit-back"&&b->action!="slot-cancel"&&b->action!="remove-cancel"&&b->action!="adopt-cancel"&&b->action!="adopt-status"&&b->action!="source-back"&&b->action!="picker-close"&&b->action!="picker-back")||!valid(o->pane_))return;
  for(void*p=o->pane_;p;p=fn<void*(*)(void*)>(lv_obj_get_parent)(p))if(fn<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return;
  auto action=b->action;o->activate(action);
 }catch(...){} }
};
}}
