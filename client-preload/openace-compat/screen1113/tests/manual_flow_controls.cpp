#define main original_native_renderer_control
#include "native_renderer.cpp"
#undef main
#include "native_management.hpp"
json load(const std::string&path){std::ifstream f(path);json j;f>>j;return j;}
int main(int argc,char**argv){assert(argc==2);std::string directory=argv[1];auto ordinary=load(directory+"/manual_ordinary1084.json"),planned=load(directory+"/manual_planned1084.json");
 ManualFlowModel m;int count=0;auto queue=[&](const std::string&,const std::string&,std::int64_t){return std::uint64_t(++count);};
 m.update(ordinary,true,1,Delivery(),"");auto serial=m.view().serial;
 assert(m.press("prepare",serial,queue));assert(m.press("apply",m.view().serial,queue));assert(count==1);
 Delivery d;d.ticket=1;d.outcome=Delivery::Unknown;d.status_generation=1;
 m.update(ordinary,true,1,d,"");assert(m.view().buttons.empty());
 m.update(ordinary,true,2,d,"");assert(count==1);assert(!m.press("apply",serial,queue));
 assert(m.press("prepare",m.view().serial,queue));assert(count==1);assert(m.press("apply",m.view().serial,queue)&&count==2);
 m.update(ordinary,true,3,Delivery(),"");assert(count==2&&m.view().buttons.empty());
 d.ticket=2;d.status_generation=3;d.outcome=Delivery::Replied;m.update(ordinary,true,4,d,"");
 // Declaring a plan changes context through our exact settled request; never silently rebind a held click.
 assert(m.press("plan",m.view().serial,queue));auto before=m.view().serial;
 auto changed=ordinary;changed["manual_flow"]["context"]=std::string(64,'b');m.update(changed,true,5,Delivery(),"");assert(!m.press("apply",before,queue));
 auto fractional=planned;fractional["manual_flow"]["purge"]["remaining_mm"]=1.5;
 m.update(fractional,true,6,Delivery(),"");assert(m.view().detail.find("fractional")!=std::string::npos);
 try{manual_command(fractional,"done");assert(false);}catch(const std::exception&){}
 auto held=planned;held["manual_flow"]["correction_required"]=true;held["manual_flow"]["operation"]="held";
 ManualFlowModel fresh;fresh.update(held,true,1,Delivery(),"");assert(fresh.view().buttons.empty());
 auto old=ordinary;old.erase("manual_flow");fresh.update(old,true,2,Delivery(),"");assert(!fresh.view().visible);
 auto unsupported=ordinary;unsupported["manual_flow"]["version"]=true;fresh.update(unsupported,true,3,Delivery(),"");assert(fresh.view().buttons.empty());
 // A normal own prepare may change the opaque context/instance without changing
 // the visible destination. Preserve current explicit review, never claim prepared.
 ManualFlowModel own;own.update(planned,true,1,Delivery(),"");
 assert(own.press("prepare",own.view().serial,queue));assert(own.press("apply",own.view().serial,queue));
 Delivery own_reply;own_reply.ticket=count;own_reply.status_generation=1;own_reply.outcome=Delivery::Replied;
 auto own_after=planned;own_after["manual_flow"]["context"]=std::string(64,'c');own.update(own_after,true,2,own_reply,"");
 assert(own.view().detail.find("Preparation returned successfully")==std::string::npos);
 bool current_done=false;for(const auto&b:own.view().buttons)if(b.first=="done")current_done=true;assert(current_done);
 // A change-away-and-back while pending cannot reattach an earlier invitation.
 ManualFlowModel away;away.update(planned,true,1,Delivery(),"");assert(away.press("prepare",away.view().serial,queue));assert(away.press("apply",away.view().serial,queue));
 own_reply.ticket=count;auto other=planned;other["manual_flow"]["head"]="h1";other["manual_flow"]["source"]="h1";
 away.update(other,true,2,Delivery(),"");away.update(planned,true,3,own_reply,"");for(const auto&b:away.view().buttons)assert(b.first!="done");
 // Actual root, worker-snapshot and callback seam: modal/page/display/Stop excludes the physical request.
 for(int boundary=0;boundary<4;++boundary){
  UiChannel channel;Fake ui;NativeScreen screen(ui,channel);View v;v.connected=v.data_current=true;v.session=ordinary["session_id"].get<std::int64_t>();
  auto status=std::make_shared<const json>(ordinary);UiSnapshot snapshot(v,100,Delivery(),1,nullptr,"",status);
  screen.tick(snapshot);assert(screen.material().root()&&!screen.management().root());assert(!ui.objects.at(screen.material().badge()).hidden);ui.event(screen.material().badge(),7);screen.tick(snapshot);
  ui.event(screen.material().manual_button(0),1);ui.event(screen.material().manual_button(0),7);screen.tick(snapshot);
  auto apply=screen.material().manual_button(0);ui.event(apply,1);
  if(boundary==0)ui.modal=true;else if(boundary==1)ui.layout=false;else if(boundary==2)ui.stop={0,0,479,479};else ui.display=(void*)4;
  ui.event(apply,7);assert(!channel.take().ticket);
  screen.tick(snapshot);assert(!screen.material().visible()||boundary==3);
 }
 // A captured old manual-button press cannot become a colour confirmation after mode switch.
 UiChannel channel;Fake ui;NativeScreen screen(ui,channel);View v;v.connected=v.data_current=true;v.session=1;
 UiSnapshot a(v,100,Delivery(),1,nullptr,"",std::make_shared<const json>(ordinary));screen.tick(a);ui.event(screen.material().badge(),7);screen.tick(a);
 auto object=screen.material().manual_button(0);ui.event(object,1);
 a.manual_status.reset();a.view=pending();screen.tick(a);ui.event(object,7);assert(!channel.take().ticket&&ui.commands==0);
}
