#pragma once
#include "native_renderer.hpp"
#include "management_panel.hpp"
#include "worker_bridge.hpp"
#include "screen_diagnostics.hpp"
#include <array>
namespace wmp_openace {
// Fixed setup view only. Shares the existing port and channel; no HTTP, native
// command builder, printer operation or independent persistence owner.
class NativeManagementRenderer {
public:
 NativeManagementRenderer(NativeUi&ui,UiChannel&channel,bool owns_observation=true):ui_(ui),channel_(channel),owns_observation_(owns_observation){}
 void deactivate()noexcept{
  try{observation_open(false);model_.close();drop();}catch(...){abandon();}
 }
 void tick(const UiSnapshot&snapshot)noexcept{
  auto&diagnostic=screen_diagnostics();
  diagnostic.renderer_exception.store(0,std::memory_order_relaxed);
  try{
   diagnostic.renderer.store(DiagnosticRenderer::Profile,std::memory_order_relaxed);
   if(!ui_.profile1113()||snapshot.view.session<0){
    if(snapshot.view.session<0)diagnostic.renderer.store(DiagnosticRenderer::Session,std::memory_order_relaxed);
    deactivate();return;}
   const auto now=ui_.now_ms();
   bool current=snapshot.view.connected&&snapshot.view.data_current&&snapshot.received_at_ms>=0
      &&now>=snapshot.received_at_ms&&now-snapshot.received_at_ms<=2000;
   model_.update(snapshot.management,current,snapshot.status_generation,snapshot.delivery,snapshot.delivery_message);
   snapshot_at_=snapshot.received_at_ms;current_=current;
   Frame frame{};
   diagnostic.renderer.store(DiagnosticRenderer::Frame,std::memory_order_relaxed);
   if(!ui_.frame(frame,root_)){drop();return;}
   if(display_!=frame.display||layer_!=frame.layer){drop();display_=frame.display;layer_=frame.layer;}
   if(damaged_)drop();
   Rect region;
   if((diagnostic.renderer.store(DiagnosticRenderer::Protection,std::memory_order_relaxed),!frame.protected_valid)
       ||(diagnostic.renderer.store(DiagnosticRenderer::Foreign,std::memory_order_relaxed),frame.foreign_overlay)
       ||(diagnostic.renderer.store(DiagnosticRenderer::Viewport,std::memory_order_relaxed),!frame.viewport.valid())
       ||(diagnostic.renderer.store(DiagnosticRenderer::Stop,std::memory_order_relaxed),!frame.protection.valid())
       ||(diagnostic.renderer.store(DiagnosticRenderer::Region,std::memory_order_relaxed),!NativeRenderer::available_region(frame,model_.opened(),region))){
    suppress();return;}
   diagnostic.renderer.store(DiagnosticRenderer::Create,std::memory_order_relaxed);
   if(!root_){root_=make(frame.layer,NativeUi::Root);badge_=make(root_,NativeUi::Button);}
   if(!root_||!badge_){drop();return;}
   region_=region;ui_.behind_stock(root_);
   diagnostic.renderer.store(DiagnosticRenderer::RootRect,std::memory_order_relaxed);
   ui_.rect(root_,region);ui_.hidden(root_,false);visible_=true;
   diagnostic.renderer.store(DiagnosticRenderer::BadgeRect,std::memory_order_relaxed);
   ui_.rect(badge_,Rect(region.x1,region.y1,region.x2,region.y1+43));
   diagnostic.renderer.store(DiagnosticRenderer::Text,std::memory_order_relaxed);
   ui_.literal_text(badge_,model_.opened()?"openACE setup — close":"openACE setup");
   ui_.hidden(badge_,false);
   diagnostic.renderer.store(DiagnosticRenderer::Visible,std::memory_order_relaxed);
   if(!model_.opened()){if(detail_)ui_.hidden(detail_,true);for(auto b:buttons_)if(b)ui_.hidden(b,true);return;}
   const auto&panel=model_.view();if(panel.buttons.size()>buttons_.size())throw std::runtime_error("Setup page exceeds fixed native controls");
   if(!detail_)detail_=make(root_,NativeUi::Label);
   const int rows=int((panel.buttons.size()+2)/3),grid_y=region.y2-rows*44+1;
   ui_.rect(detail_,Rect(region.x1,region.y1+48,region.x2,grid_y-5));
   ui_.literal_text(detail_,panel.title+"\n"+panel.detail);ui_.hidden(detail_,false);
   for(std::size_t i=0;i<buttons_.size();++i){
    if(i>=panel.buttons.size()){if(buttons_[i])ui_.hidden(buttons_[i],true);continue;}
    if(!buttons_[i])buttons_[i]=make(root_,NativeUi::Button);
    const int cell=region.width()/3,x=region.x1+int(i%3)*cell,y=grid_y+int(i/3)*44;
    ui_.rect(buttons_[i],Rect(x,y,i%3==2?region.x2:x+cell-3,y+39));
    ui_.literal_text(buttons_[i],panel.buttons[i].second);ui_.hidden(buttons_[i],false);
   }
  }catch(...){diagnostic.renderer_exception.store(1,std::memory_order_relaxed);try{suppress();}catch(...){abandon();}}
 }
 void*root()const{return root_;}void*badge()const{return badge_;}void*button(std::size_t i)const{return buttons_.at(i);}
 bool visible()const{return visible_;}const ManagementPanel&panel()const{return model_.view();}
private:
 NativeUi&ui_;UiChannel&channel_;bool owns_observation_;ManagementPanelModel model_;
 // Unified stock-content management owns polling independently of this renderer.
 void observation_open(bool value){if(owns_observation_)channel_.set_management_open(value);}
 void*display_=nullptr,*layer_=nullptr,*root_=nullptr,*badge_=nullptr,*detail_=nullptr;
 std::array<void*,9>buttons_{};Rect region_;std::uint64_t generation_=1,pressed_serial_=0,pressed_generation_=0;
 void*pressed_=nullptr;std::int64_t snapshot_at_=-1;bool visible_=false,current_=false,damaged_=false;
 void*make(void*parent,NativeUi::Kind kind){return ui_.create(parent,kind,&event,this,generation_);}
 void abandon(){++generation_;root_=badge_=detail_=pressed_=nullptr;buttons_.fill(nullptr);visible_=damaged_=false;pressed_generation_=0;}
 void drop(){if(root_)ui_.erase(root_);abandon();}
 void suppress(){if(root_)ui_.hidden(root_,true);visible_=false;pressed_generation_=0;}
 bool safe_now(){
  Frame frame{};auto now=ui_.now_ms();
  return current_&&snapshot_at_>=0&&now>=snapshot_at_&&now-snapshot_at_<=2000
    &&ui_.frame(frame,root_)&&frame.display==display_&&frame.layer==layer_
    &&frame.protected_valid&&!frame.foreign_overlay&&!frame.protection.overlaps(region_);
 }
 static void event(void*context,void*object,int code,std::uint64_t generation)noexcept{
  auto*self=static_cast<NativeManagementRenderer*>(context);
  try{self->on_event(object,code,generation);}catch(...){try{self->suppress();}catch(...){self->abandon();}}
 }
 void on_event(void*object,int code,std::uint64_t generation){
  if(generation!=generation_)return;
  if(code==33){
   if(object==root_){abandon();return;}
   if(object==badge_)badge_=nullptr;
   if(object==detail_)detail_=nullptr;
   for(auto&b:buttons_)if(b==object)b=nullptr;
   damaged_=true;pressed_generation_=0;return;
  }
  if(!visible_||damaged_)return;
  if(object==badge_&&code==7){
   // Badge opens data observation only. No management action before fresh status.
   Frame frame{};if(!ui_.frame(frame,root_)||frame.display!=display_||frame.layer!=layer_
      ||!frame.protected_valid||frame.foreign_overlay||frame.protection.overlaps(region_)){suppress();return;}
   if(model_.opened()){model_.close();observation_open(false);}
   else{model_.open();observation_open(true);}pressed_generation_=0;return;
  }
  if(!model_.opened())return;
  if(code==1){pressed_=object;pressed_serial_=model_.view().serial;pressed_generation_=generation_;return;}
  if(code!=7)return;
  bool pressed=pressed_==object&&pressed_generation_==generation_&&pressed_serial_==model_.view().serial;
  pressed_generation_=0;if(!pressed)return;
  if(!safe_now()){suppress();return;}
  const auto&panel=model_.view();
  for(std::size_t i=0;i<panel.buttons.size();++i)if(buttons_[i]==object){
   auto id=panel.buttons[i].first;
   model_.press(id,pressed_serial_,[&](const json&request,const std::string&command,std::int64_t session){return channel_.enqueue_management(request,command,session);});
   if(!model_.opened())observation_open(false);
   return;
  }
 }
};
// At most ONE root exists across the two fixed views; a material alert has
// priority and disowns any unsent setup request by closing its observation page.
class NativeScreen {
public:
 NativeScreen(NativeUi&ui,UiChannel&channel,bool management_enabled=true):channel_(channel),material_(ui),management_(ui,channel,management_enabled),management_enabled_(management_enabled){}
 void tick(const UiSnapshot&snapshot)noexcept{
  if(snapshot.manual_status){manual_.update(*snapshot.manual_status,snapshot.view.connected&&snapshot.view.data_current,snapshot.status_generation,snapshot.delivery,snapshot.delivery_message);}
  else{manual_.update(json::object(),false,snapshot.status_generation,snapshot.delivery,"");}
  auto panel=manual_.view();
  if(panel.visible){
   screen_diagnostics().mode.store(1,std::memory_order_relaxed);
   management_.deactivate();
   if(snapshot.view.visible){panel.detail="From: "+snapshot.view.from_label+"\nTo: "+snapshot.view.to_label+"\n"+panel.detail;
    if(snapshot.view.confirm_enabled&&panel.buttons.size()<4)panel.buttons.emplace_back("confirm_colour","Confirm loaded colour");}
   auto signature=std::to_string(panel.serial)+snapshot.view.context+std::to_string(snapshot.view.serial);
   if(signature!=manual_signature_){manual_signature_=signature;++manual_serial_;}panel.serial=manual_serial_;
   const View confirmation=snapshot.view;
   material_.tick_manual(panel,snapshot.received_at_ms,[this,confirmation](const std::string&id){
    if(id=="confirm_colour"){channel_.enqueue("OPENACE_CONFIRM_CHANGE TOOL="+std::to_string(confirmation.tool)+" CONFIRM=1 EXPECT_CONTEXT="+confirmation.context);return;}
    manual_.press(id,manual_.view().serial,[&](const std::string&action,const std::string&command,std::int64_t session){return channel_.enqueue_manual(action,command,session);});
   });return;
  }
  if(snapshot.view.visible){screen_diagnostics().mode.store(2,std::memory_order_relaxed);management_.deactivate();material_.tick(snapshot.view,snapshot.received_at_ms,snapshot.delivery,snapshot.status_generation);}
  else{screen_diagnostics().mode.store(3,std::memory_order_relaxed);material_.deactivate();if(management_enabled_)management_.tick(snapshot);else management_.deactivate();}
 }
 NativeManagementRenderer&management(){return management_;}
 NativeRenderer&material(){return material_;}const ManualFlowView&manual_view()const{return manual_.view();}
private:UiChannel&channel_;NativeRenderer material_;NativeManagementRenderer management_;ManualFlowModel manual_;bool management_enabled_;std::string manual_signature_;std::uint64_t manual_serial_=0;
};
}
