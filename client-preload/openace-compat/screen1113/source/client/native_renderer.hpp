#pragma once
#include "openace_view.hpp"
#include "delivery.hpp"
#include "manual_flow.hpp"
#include <array>
#include <algorithm>
namespace wmp_openace {
struct Rect {
 int x1,y1,x2,y2;
 Rect(int a=0,int b=0,int c=-1,int d=-1):x1(a),y1(b),x2(c),y2(d){}
 int width()const{return x2-x1+1;}int height()const{return y2-y1+1;}
 bool valid()const{return width()>0 && height()>0;}
 bool overlaps(const Rect&o)const{return valid()&&o.valid()&&x1<=o.x2&&x2>=o.x1&&y1<=o.y2&&y2>=o.y1;}
};
// Exact protected footprints, not a bounding hull that blocks empty space.
// The native idle page protects Print and the whole reserved Stop group.
struct ProtectedRegions {
 std::array<Rect,2> rectangles;unsigned count;
 ProtectedRegions():count(0){}
 ProtectedRegions(Rect first):rectangles{{first,Rect()}},count(1){}
 ProtectedRegions(Rect first,Rect second):rectangles{{first,second}},count(2){}
 bool valid()const{if(count<1||count>rectangles.size())return false;
  for(unsigned i=0;i<count;++i){if(!rectangles[i].valid())return false;}
  return true;}
 bool overlaps(const Rect&r)const{if(!valid())return true;
  for(unsigned i=0;i<count;++i){if(rectangles[i].overlaps(r))return true;}
  return false;}
};
struct Frame {void*display;void*layer;Rect viewport;ProtectedRegions protection;bool protected_valid,foreign_overlay;};
// GUI-thread port. All geometry is absolute screen coordinates. Adapter must
// requery display/layer and validate real Stop ownership before returning true.
struct NativeUi {
 enum Kind {Root,Label,Button};
 typedef void(*Event)(void*,void*,int,std::uint64_t);
 virtual ~NativeUi(){}
 virtual bool profile1113()const=0;
 virtual bool frame(Frame&,void* owned_root)=0;
 virtual void*create(void*parent,Kind,Event,void*context,std::uint64_t generation)=0;
 // Delete only a still-live object created by this port; DELETE retires its binding.
 virtual void erase(void*)=0;
 virtual void rect(void*,Rect)=0;
 virtual void literal_text(void*,const std::string&)=0;
 virtual void hidden(void*,bool)=0;
 virtual void behind_stock(void*)=0;
 // Nonblocking bounded worker queue only. Never HTTP/run_gcode/native action.
 virtual std::uint64_t enqueue(const std::string&)=0;
 virtual std::int64_t now_ms()const=0;
};
class NativeRenderer {
public:
 explicit NativeRenderer(NativeUi&ui):ui_(ui){}
 ~NativeRenderer(){try{drop();}catch(...){}}
 void tick(const View&view,std::int64_t snapshot_at,const Delivery&delivery=Delivery(),std::uint64_t status_generation=0)noexcept {
  try {
   if(manual_mode_)pressed_generation_=0;
   manual_mode_=false;for(auto b:extra_)if(b)ui_.hidden(b,true);
   if(!ui_.profile1113()){drop();return;}
   Frame f{};
   if(!ui_.frame(f,root_)){drop();return;}
   if(display_!=f.display || layer_!=f.layer){drop();display_=f.display;layer_=f.layer;}
   if(damaged_)drop();
   if(view.approved || !view.pending_confirmation)queued_=false;
   if(queued_ && delivery.ticket==queued_ticket_ && delivery.outcome!=Delivery::None
      && status_generation>delivery.status_generation && view.connected && view.data_current)
    queued_=false;
   current_=view;snapshot_at_=snapshot_at;frame_=f;
   if(!view.visible){drop();return;}
   Rect region;
   if(!f.protected_valid || !f.viewport.valid() || !f.protection.valid() || f.foreign_overlay
      || !place(f,expanded_,region)) {suppress();return;}
   if(!root_){
    root_=make(f.layer,NativeUi::Root);if(!root_)return;
    badge_=make(root_,NativeUi::Button);if(!badge_){drop();return;}
   }
   ui_.behind_stock(root_);ui_.rect(root_,region);region_=region;
   ui_.hidden(root_,false);visible_=true;
   ui_.rect(badge_,Rect(region.x1,region.y1,region.x2,region.y1+43));
   ui_.literal_text(badge_,expanded_?"Filament change — close":view.title+" — details");
   ui_.hidden(badge_,false);
   if(expanded_){
    if(!detail_)detail_=make(root_,NativeUi::Label);
    if(!confirm_)confirm_=make(root_,NativeUi::Button);
    if(!detail_||!confirm_){drop();return;}
    ui_.hidden(detail_,false);ui_.hidden(confirm_,false);
    ui_.rect(detail_,Rect(region.x1,region.y1+48,region.x2,region.y2-51));
    ui_.literal_text(detail_,"From: "+view.from_label+"\nTo: "+view.to_label+"\nExpected: "+view.expected_label
      +"\nLoaded: "+view.replacement_label+"\n"+view.message+(view.error.empty()?"":"\n"+view.error));
    ui_.rect(confirm_,Rect(region.x1,region.y2-43,region.x2,region.y2));
    ui_.literal_text(confirm_,eligible()?"Confirm loaded filament colour":"Confirmation unavailable");
   } else {if(detail_)ui_.hidden(detail_,true);if(confirm_)ui_.hidden(confirm_,true);}
  }catch(...){try{suppress();}catch(...){abandon();}}
 }
 void tick_manual(const ManualFlowView&panel,std::int64_t at,const std::function<void(const std::string&)>&action)noexcept{
  try{
   if(!ui_.profile1113()||!panel.visible){drop();return;}
   Frame f{};if(!ui_.frame(f,root_)){drop();return;}
   if(display_!=f.display||layer_!=f.layer){drop();display_=f.display;layer_=f.layer;}
   if(damaged_)drop();
   if(!manual_mode_)pressed_generation_=0;
   manual_mode_=true;manual_actions_=panel.buttons;manual_dispatch_=action;current_.serial=panel.serial;snapshot_at_=at;
   Rect region;if(!f.protected_valid||f.foreign_overlay||!f.viewport.valid()||!f.protection.valid()||!place(f,expanded_,region)){suppress();return;}
   if(!root_){root_=make(f.layer,NativeUi::Root);badge_=make(root_,NativeUi::Button);}
   if(!root_||!badge_){drop();return;}
   ui_.behind_stock(root_);ui_.rect(root_,region);region_=region;ui_.hidden(root_,false);visible_=true;
   ui_.rect(badge_,Rect(region.x1,region.y1,region.x2,region.y1+43));ui_.literal_text(badge_,expanded_?"Filament — close":panel.title+" — details");ui_.hidden(badge_,false);
   if(!expanded_){if(detail_)ui_.hidden(detail_,true);if(confirm_)ui_.hidden(confirm_,true);for(auto b:extra_)if(b)ui_.hidden(b,true);return;}
   if(panel.buttons.size()>4)throw std::runtime_error("Too many manual controls");
   if(!detail_)detail_=make(root_,NativeUi::Label);
   ui_.rect(detail_,Rect(region.x1,region.y1+48,region.x2,region.y2-94));ui_.literal_text(detail_,panel.detail);ui_.hidden(detail_,false);
   for(std::size_t i=0;i<4;++i){void*&button=i?extra_[i-1]:confirm_;
    if(i>=panel.buttons.size()){if(button)ui_.hidden(button,true);continue;}
    if(!button)button=make(root_,NativeUi::Button);
    int width=region.width()/2,x=region.x1+int(i%2)*width,y=region.y2-87+int(i/2)*44;
    ui_.rect(button,Rect(x,y,i%2?region.x2:x+width-3,y+39));ui_.literal_text(button,panel.buttons[i].second);ui_.hidden(button,false);
   }
  }catch(...){try{suppress();}catch(...){abandon();}}
 }
 void*manual_button(std::size_t i)const{return i?extra_.at(i-1):confirm_;}
 void*root()const{return root_;}void*badge()const{return badge_;}void*confirm()const{return confirm_;}
 bool expanded()const{return expanded_;}bool visible()const{return visible_;}
 void deactivate()noexcept{try{drop();}catch(...){abandon();}}
 static bool available_region(const Frame&f,bool expanded,Rect&out){return place(f,expanded,out);}
private:
 NativeUi&ui_;Frame frame_{};View current_;std::int64_t snapshot_at_=-1;
 void*display_=nullptr,*layer_=nullptr,*root_=nullptr,*badge_=nullptr,*detail_=nullptr,*confirm_=nullptr;
 std::uint64_t generation_=1,pressed_serial_=0,pressed_generation_=0,queued_ticket_=0;
 std::array<void*,3>extra_{};bool manual_mode_=false;void*manual_pressed_=nullptr;
 std::vector<std::pair<std::string,std::string>>manual_actions_;std::function<void(const std::string&)>manual_dispatch_;
 bool expanded_=false,visible_=false,queued_=false,damaged_=false;Rect region_;
 void*make(void*parent,NativeUi::Kind kind){return ui_.create(parent,kind,&event,this,generation_);}
 void abandon(){++generation_;root_=badge_=detail_=confirm_=nullptr;expanded_=visible_=queued_=damaged_=false;pressed_generation_=0;extra_.fill(nullptr);manual_pressed_=nullptr;}
 void drop(){void*old=root_;if(old)ui_.erase(old);abandon();}
 void suppress(){if(root_)ui_.hidden(root_,true);visible_=false;expanded_=false;pressed_generation_=0;}
 bool eligible()const {
  const auto now=ui_.now_ms();
  return !queued_ && current_.confirm_enabled && current_.connected && current_.data_current
   && current_.pending_confirmation && !current_.approved && current_.tool>=0&&current_.tool<=31
   && current_.context.size()==64 && std::all_of(current_.context.begin(),current_.context.end(),
      [](char c){return(c>='0'&&c<='9')||(c>='a'&&c<='f');})
   && snapshot_at_>=0 && now>=snapshot_at_ && now-snapshot_at_<=2000;
 }
 static bool place(const Frame&f,bool expanded,Rect&out){
  const auto&v=f.viewport;
  if(!v.valid()||!f.protection.valid())return false;
  std::array<Rect,16>candidates,next;unsigned count=1;
  candidates[0]=Rect(v.x1+8,v.y1+8,v.x2-8,v.y2-8);
  if(!candidates[0].valid())return false;
  for(unsigned obstacle=0;obstacle<f.protection.count;++obstacle){
   const auto&s=f.protection.rectangles[obstacle];
   if(s.x1<v.x1||s.y1<v.y1||s.x2>v.x2||s.y2>v.y2)return false;
   // Preserve the original eight-coordinate clearance from each control.
   const Rect blocked(s.x1-7,s.y1-7,s.x2+7,s.y2+7);unsigned next_count=0;
   for(unsigned i=0;i<count;++i){const auto&c=candidates[i];
    if(!c.overlaps(blocked)){if(next_count==next.size())return false;next[next_count++]=c;continue;}
    const Rect pieces[]={Rect(c.x1,c.y1,c.x2,std::min(c.y2,blocked.y1-1)),
     Rect(c.x1,std::max(c.y1,blocked.y2+1),c.x2,c.y2),
     Rect(c.x1,c.y1,std::min(c.x2,blocked.x1-1),c.y2),
     Rect(std::max(c.x1,blocked.x2+1),c.y1,c.x2,c.y2)};
    for(const auto&r:pieces)if(r.valid()){if(next_count==next.size())return false;next[next_count++]=r;}
   }
   candidates=next;count=next_count;
  }
  for(unsigned i=0;i<count;++i){auto r=candidates[i];
   if(r.width()>=(expanded?240:140)&&r.height()>=(expanded?260:44)&&!f.protection.overlaps(r)){
    if(!expanded){r.x2=std::min(r.x2,r.x1+239);r.y2=r.y1+43;}out=r;return true;
   }
  }return false;
 }
 static void event(void*context,void*object,int code,std::uint64_t generation)noexcept {
  try{static_cast<NativeRenderer*>(context)->on_event(object,code,generation);}catch(...){}
 }
 void on_event(void*object,int code,std::uint64_t generation){
  if(generation!=generation_)return;
  if(code==33){if(object==root_){abandon();return;}else if(object==badge_)badge_=nullptr;
    else if(object==detail_)detail_=nullptr;else if(object==confirm_)confirm_=nullptr;
    if(object!=root_)damaged_=true;
    return;}
  if(!visible_||damaged_)return;
  if(object==badge_ && code==7){Frame live{};Rect r;
   if(!ui_.frame(live,root_)||live.display!=display_||live.layer!=layer_||live.foreign_overlay
     ||!live.protected_valid||live.protection.overlaps(region_)||!place(live,!expanded_,r)){suppress();return;}
   expanded_=!expanded_;pressed_generation_=0;return;
  }
  if(manual_mode_){
   if(!expanded_)return;
   if(code==1){manual_pressed_=object;pressed_serial_=current_.serial;pressed_generation_=generation_;return;}
   if(code!=7)return;
   bool pressed=manual_pressed_==object&&pressed_generation_==generation_&&pressed_serial_==current_.serial;pressed_generation_=0;
   auto now=ui_.now_ms();Frame live{};Rect r;
   if(!pressed||snapshot_at_<0||now<snapshot_at_||now-snapshot_at_>2000||!ui_.frame(live,root_)||live.display!=display_||live.layer!=layer_||!live.protected_valid||live.foreign_overlay||live.protection.overlaps(region_)||!place(live,true,r)){suppress();return;}
   for(std::size_t i=0;i<manual_actions_.size();++i)if(manual_button(i)==object){if(manual_dispatch_)manual_dispatch_(manual_actions_[i].first);return;}
   return;
  }
  if(object!=confirm_||!expanded_)return;
  if(code==1){pressed_serial_=current_.serial;pressed_generation_=generation_;return;}
  if(code!=7)return;
  const bool pressed=pressed_generation_==generation_&&pressed_serial_==current_.serial;
  pressed_generation_=0;if(!pressed||!eligible())return;
  Frame live{};Rect r;
  if(!ui_.frame(live,root_)||live.display!=display_||live.layer!=layer_||!live.protected_valid
    ||live.foreign_overlay||live.protection.overlaps(region_)||!place(live,true,r)){suppress();return;}
  const auto ticket=ui_.enqueue("OPENACE_CONFIRM_CHANGE TOOL="+std::to_string(current_.tool)
       +" CONFIRM=1 EXPECT_CONTEXT="+current_.context);
  if(ticket){queued_ticket_=ticket;queued_=true;}
 }
};
}
