// Reuse the legacy renderer's NativeUi fake, exercising actual callbacks.
#define main legacy_renderer_original_main
#include "../../client-preload/openace-compat/screen1113/tests/native_renderer.cpp"
#undef main
int main(){
 Fake ui;NativeRenderer renderer(ui);
 ManualFlowView panel;panel.visible=true;panel.serial=1;panel.title="Load";
 panel.detail="Ready";panel.buttons={{"prepare","Prepare"},{"back","Back"}};
 std::vector<std::string> actions;
 auto dispatch=[&](const std::string&id){actions.push_back(id);};
 renderer.tick_manual(panel,100,dispatch);
 ui.event(renderer.badge(),7);renderer.tick_manual(panel,100,dispatch);
 auto root=renderer.root(),first=renderer.manual_button(0),second=renderer.manual_button(1);
 const auto allocations=ui.created;
 ui.event(first,1);
 for(int i=0;i<20;++i)renderer.tick_manual(panel,100,dispatch);
 assert(ui.created==allocations&&renderer.root()==root);
 assert(renderer.manual_button(0)==first&&renderer.manual_button(1)==second);
 ui.event(first,7);assert(actions==std::vector<std::string>{"prepare"});
 ui.event(first,7);assert(actions.size()==1); // No second release dispatch.
 ui.event(first,1);
 std::swap(panel.buttons[0],panel.buttons[1]);++panel.serial;
 renderer.tick_manual(panel,100,dispatch);
 assert(ui.created==allocations&&renderer.manual_button(0)==first);
 ui.event(first,7);assert(actions.size()==1); // Held press cannot become Back.
 // An invalid held press suppresses the overlay; reopening reuses its controls.
 renderer.tick_manual(panel,100,dispatch);ui.event(renderer.badge(),7);
 renderer.tick_manual(panel,100,dispatch);assert(ui.created==allocations);
 ui.event(first,1);ui.event(first,7);
 assert(actions==std::vector<std::string>({"prepare","back"}));
 ui.event(second,1);
 panel.buttons.pop_back();++panel.serial;renderer.tick_manual(panel,100,dispatch);
 assert(ui.created==allocations&&ui.objects.at(second).hidden);
 ui.event(second,7);assert(actions.size()==2);
 panel.buttons.emplace_back("done","Done");++panel.serial;
 renderer.tick_manual(panel,100,dispatch);
 assert(ui.created==allocations&&renderer.manual_button(1)==second);
 ui.event(second,7);assert(actions.size()==2); // Reappearing slot needs new press.
 renderer.tick_manual(panel,100,dispatch);ui.event(renderer.badge(),7);
 renderer.tick_manual(panel,100,dispatch);
 assert(renderer.visible()&&renderer.expanded()&&ui.created==allocations);
 ui.event(second,1);ui.clock=2201;ui.event(second,7);
 assert(actions.size()==2); // Retention does not bypass stale admission.
}
