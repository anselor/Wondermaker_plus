#define main renderer_prior_contract
#include "native_renderer.cpp"
#undef main
#include "native_management.hpp"
#include "main_layout.hpp"
using namespace wmp_openace;
static MainLayout observed_idle(){
 MainLayout x;x.main_current=x.main_visible=x.stop_owned=x.print_owned=x.group_owned=true;
 x.print_visible=x.group_hidden=true;x.stop={705,111,757,150};
 x.group={506,111,757,150};x.print={115,171,365,448};return x;
}
struct ActualUi:Fake{
 MainLayout layout_state=observed_idle();
 bool frame(Frame&f,void*)override{
  f={display,layer,{0,0,799,479},Rect(),false,modal};
  f.protected_valid=known&&main_protected_regions(layout_state,f.viewport,f.protection);return display&&layer;
 }
 void rect(void*h,Rect r)override{
  Frame f{};assert(frame(f,nullptr)&&f.protected_valid&&!f.protection.overlaps(r));objects.at(h).r=r;
 }
 void stop_inside(Rect region){
  layout_state.stop_visible=true;layout_state.print_visible=false;layout_state.group_hidden=false;
  layout_state.stop={region.x1+50,region.y1+50,region.x1+100,region.y1+89};
  Frame f{};Rect alternative;assert(frame(f,nullptr)&&NativeRenderer::available_region(f,true,alternative));
  assert(f.protection.overlaps(region)); // A new placement exists, but the old drawn root is unsafe.
 }
};
int main(int argc,char**argv){
 assert(argc==2);Rect view{0,0,799,479},panel;auto x=observed_idle();ProtectedRegions protected_bounds;
 assert(main_protected_regions(x,view,protected_bounds)&&protected_bounds.count==2);
 Frame frame{(void*)1,(void*)2,view,protected_bounds,true,false};
 assert(NativeRenderer::available_region(frame,true,panel));
 assert(panel.width()>=240&&panel.height()>=260);
 assert(!panel.overlaps(x.group)&&!panel.overlaps(x.print)&&!panel.overlaps(x.stop));
 Rect badge;assert(NativeRenderer::available_region(frame,false,badge)&&!protected_bounds.overlaps(badge));
 frame.protection=ProtectedRegions(x.group,Rect());assert(!NativeRenderer::available_region(frame,true,panel));
 frame.protection=protected_bounds;frame.protection.count=3;assert(!NativeRenderer::available_region(frame,true,panel));
 frame.protection=ProtectedRegions(Rect(0,0,399,479),Rect(400,0,799,479));assert(!NativeRenderer::available_region(frame,true,panel));
 // Setup really opens on the observed screen; every rendered object stays outside both controls.
 std::ifstream input(argv[1]);std::ostringstream text;text<<input.rdbuf();auto data=std::make_shared<const json>(json::parse(text.str()));
 ActualUi ui;UiChannel channel;NativeScreen screen(ui,channel);View idle;idle.connected=idle.data_current=true;idle.session=data->at("session_id");
 UiSnapshot snapshot{idle,100,Delivery(),1,nullptr,""};screen.tick(snapshot);auto&r=screen.management();
 assert(r.visible()&&!ui.objects.at(r.badge()).hidden);ui.event(r.badge(),7);snapshot.management=data;screen.tick(snapshot);
 assert(channel.management_open()&&r.visible()&&ui.objects.at(r.root()).r.height()>=260);
 ui.modal=true;screen.tick(snapshot);assert(!r.visible()&&ui.objects.at(r.root()).hidden);ui.modal=false;screen.tick(snapshot);assert(r.visible());
 ui.event(r.button(0),1);ui.stop_inside(ui.objects.at(r.root()).r);ui.event(r.button(0),7);
 assert(!r.visible()&&ui.objects.at(r.root()).hidden&&!channel.take().ticket&&ui.commands==0);
 // Material confirmation must not use a newly possible placement to excuse overlap at click time.
 ActualUi material_ui;NativeRenderer material(material_ui);material.tick(pending(),100);
 material_ui.event(material.badge(),7);material.tick(pending(),100);assert(material.visible()&&material.expanded());
 material_ui.event(material.confirm(),1);material_ui.stop_inside(material_ui.objects.at(material.root()).r);material_ui.event(material.confirm(),7);
 assert(!material.visible()&&material_ui.objects.at(material.root()).hidden&&material_ui.commands==0);
 // The same rule applies to physical manual-load controls.
 ActualUi manual_ui;NativeRenderer manual(manual_ui);ManualFlowView manual_view;manual_view.visible=true;manual_view.serial=1;manual_view.title="Manual load";manual_view.buttons.emplace_back("done","Done");int actions=0;
 auto action=[&](const std::string&){++actions;};manual.tick_manual(manual_view,100,action);manual_ui.event(manual.badge(),7);manual.tick_manual(manual_view,100,action);
 assert(manual.visible()&&manual.expanded()&&!manual_ui.objects.at(manual.badge()).hidden);
 manual_ui.event(manual.manual_button(0),1);manual_ui.stop_inside(manual_ui.objects.at(manual.root()).r);manual_ui.event(manual.manual_button(0),7);
 assert(!manual.visible()&&manual_ui.objects.at(manual.root()).hidden&&actions==0&&manual_ui.commands==0);
}
