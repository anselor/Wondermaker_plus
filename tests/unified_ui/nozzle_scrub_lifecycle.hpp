// SPDX-License-Identifier: GPL-3.0-or-later
// Guided nozzle scrub lifecycle cases. Included by native_lifecycle.cpp after
// its fake LVGL, RuntimeReceiptTest, Port and Http; run by nozzle_scrub_lifecycle().
#pragma once
#include "native/stock_nozzle_scrub.hpp"
#include <atomic>
#include <chrono>
#include <mutex>
#include <thread>
// The fake gives every node 800x480. The progress panel reads the height of
// its wrapping labels after a layout update; this hook gives a label that
// nobody sized one line of its font. Real wrapping of every state's text is
// covered by test_progress_panel_real_font_fit (scrub-state-* fixtures).
void scrub_measure(fake::Node*n){
 if(!n->is_label||n->height_fixed||n->label_long_mode!=0)return;
 n->h=n->font_address==MyriadPro_Bold_24?MyriadPro_Bold_24_line_height:n->font_address==MyriadPro_Bold_20?MyriadPro_Bold_20_line_height:MyriadPro_Regular_22_line_height;
}
struct ScrubLayout{ScrubLayout(){fake::layout_hook=&scrub_measure;}~ScrubLayout(){fake::layout_hook={};}};
struct ScrubRect{int x,y,w,h;};
ScrubRect scrub_rect(const fake::Node*n){ScrubRect r{n->x,n->y,n->w,n->h};for(auto*p=n->parent;p;p=p->parent){r.x+=p->x;r.y+=p->y;}return r;}
bool scrub_under(const fake::Node*n,const fake::Node*root){for(auto*p=n->parent;p;p=p->parent)if(p==root)return true;return false;}
bool scrub_shown(const fake::Node*n,const fake::Node*root){for(auto*p=n;p&&p!=root;p=p->parent)if(!p->live||(p->flags&1))return false;return n->live&&scrub_under(n,root);}
bool scrub_clickable(const fake::Node*n){for(const auto&cb:n->callbacks)if(cb.code==7)return true;return false;}
// Views as nozzle_scrub_view produces them, with the head and head count given.
ScrubView scrub_view(ScrubState state,unsigned head=3,unsigned heads=4,const std::string&calibrate="height"){
 const auto n=std::to_string(head+1),m=std::to_string(heads);
 ScrubView v{state,head,heads,true,true,true,true,false,"","","",0,0,{"",""},{"",""},true,{},{},false};
 switch(state){
  case ScrubState::Prepare:v.heading="How will the nozzles be cleaned?";
   v.option_title[0]="Wire brush";v.option_detail[0]="Scrub each heated nozzle by hand. Have a wire brush ready.";
   v.option_title[1]="Printed blob";v.option_detail[1]="Every head must be loaded with filament.";break;
  case ScrubState::Recheck:v.heading="Heads 2 and 4 may not be clean";v.body="Their measurements did not repeat, which usually means residue on the nozzle.";
   v.option_title[0]="Clean again";v.option_detail[0]="Scrub the flagged heads, then measure again.";
   v.option_title[1]="Save anyway";v.option_detail[1]="Keep the offsets as measured.";v.flagged={1,3};
   for(unsigned i=0;i<heads;++i)v.rows.push_back({"Head "+std::to_string(i+1),i%2?"0.041 mm":"0.012 mm",i%2?ScrubMark::Flagged:ScrubMark::Passed});
   break;
  case ScrubState::ReturnPrompt:v.heading="Ready to clean the nozzles.";v.body="Press Confirm to start.";break;
  case ScrubState::Mounting:v.heading="Mounting head "+n+"...";v.confirm_enabled=false;break;
  case ScrubState::Heating:v.heading="Heating head "+n+"...";v.confirm_enabled=false;v.actual=126.6;v.target=160;break;
  case ScrubState::Scrub:v.heading="Scrub the nozzle on head "+n;v.body="Brush the nozzle tip until it is clean, then press Confirm.";v.note="The nozzle is hot.";break;
  case ScrubState::Cooled:v.heading="Head "+n+" has cooled.";v.body="Press Confirm to reheat.";break;
  case ScrubState::Cancelling:v.confirm_visible=v.confirm_enabled=v.cancel_visible=false;
   v.heading="Cancelling...";v.body="Cooling and returning head "+n+" to its dock. Offsets are unchanged.";break;
  case ScrubState::Failed:v.confirm_visible=v.confirm_enabled=v.cancel_visible=false;v.back_visible=true;
   v.body="Head "+n+" did not reach 160 \xc2\xb0""C. Heaters were switched off and calibration stopped.";break;
  case ScrubState::Calibrate:v.confirm_visible=v.confirm_enabled=v.cancel_visible=false;v.note="Keep the door closed.";
   if(calibrate=="homing")v.heading="Homing...";
   else if(calibrate=="mounting"){v.heading="Head "+n+" of "+m;v.body="Mounting head "+n+"...";}
   else if(calibrate=="position"){v.heading="Head "+n+" of "+m;v.body="Measuring nozzle position...";}
   else if(calibrate=="height"){v.heading="Head "+n+" of "+m;v.body="Measuring nozzle height...";}
   else if(calibrate=="docking")v.heading="Returning head "+n+" to its dock...";
   else if(calibrate=="measuring")v.heading="Measuring head "+n+" of "+m+"...";
   else v.heading="Measuring nozzle offsets...";
   for(unsigned i=0;i<heads;++i)v.rows.push_back({"Head "+std::to_string(i+1),"",ScrubMark::None});
   break;
  default:v.confirm_visible=v.confirm_enabled=v.cancel_visible=false;break;
 }
 return v;
}
struct ScrubFixture{
 StockNozzleScrub view;fake::Node*page=fake::make(fake::screen);unsigned confirms=0,cancels=0,backs=0;std::vector<bool>selects;
 ScrubFixture(){view.on_confirm=[this]{++confirms;};view.on_cancel=[this]{++cancels;};view.on_back=[this]{++backs;};view.on_select=[this](bool first){selects.push_back(first);};view.created(page);}
 ~ScrubFixture(){if(page->live)fake::del(page);}
 fake::Node*label(const std::string&text)const{for(auto&n:fake::nodes)if(!text.empty()&&n->text==text&&scrub_shown(n.get(),page))return n.get();return nullptr;}
 fake::Node*any(const std::string&text)const{for(auto&n:fake::nodes)if(n->live&&n->text==text&&scrub_under(n.get(),page))return n.get();return nullptr;}
 std::vector<fake::Node*>targets()const{std::vector<fake::Node*>out;for(auto&n:fake::nodes)if(scrub_clickable(n.get())&&scrub_shown(n.get(),page))out.push_back(n.get());return out;}
};
// Full-screen attach of the progress panel: steps column 200 px, then the
// instruction column; both start below the 48 px title row.
const int kScrubStepsWidth=200,kScrubBodyTop=48,kScrubBodyHeight=432,kScrubTextX=kScrubStepsWidth+16+8,kScrubTextWidth=800-kScrubStepsWidth-16-16;
void nozzle_scrub_prepare_layout(){
 ScrubFixture f;auto v=scrub_view(ScrubState::Prepare,0);f.view.update(v);assert(f.view.visible());
 assert(f.label("Nozzle offset calibration")&&f.label("How will the nozzles be cleaned?"));
 const char*steps[]={"1. Prepare","2. Head 1","3. Head 2","4. Head 3","5. Head 4","6. Calibrate"};
 for(auto*s:steps)assert(f.label(s));
 assert(f.label("1. Prepare")->text_color==0xffff6600U&&f.label("2. Head 1")->text_color==0xffeeeeeeU&&f.label("6. Calibrate")->text_color==0xffeeeeeeU);
 for(int i=0;i<6;++i){const auto r=scrub_rect(f.label(steps[i]));assert(r.x<kScrubStepsWidth&&r.x+r.w<=kScrubStepsWidth&&(i==0||r.y-scrub_rect(f.label(steps[i-1])).y==MyriadPro_Regular_22_line_height+8));}
 auto*brush=f.label("Wire brush"),*blob=f.label("Printed blob");assert(brush&&blob);
 assert(f.label("Scrub each heated nozzle by hand. Have a wire brush ready.")&&f.label("Every head must be loaded with filament."));
 auto*brush_row=brush->parent,*blob_row=blob->parent;assert(scrub_clickable(brush_row)&&scrub_clickable(blob_row));
 fake::send(blob_row,7);assert(f.selects==std::vector<bool>({false}));
 fake::send(brush_row,7);assert(f.selects==std::vector<bool>({false,true}));
 // The selected option carries the filled mark; the view, not the tap, moves it.
 auto marked=[&](fake::Node*row){auto*ring=row->children.at(0);assert(scrub_shown(ring,f.page)&&ring->children.size()==1);return scrub_shown(ring->children[0],f.page);};
 assert(marked(brush_row)&&!marked(blob_row));
 v.brush=false;v.first_selected=false;f.view.update(v);assert(!marked(brush_row)&&marked(blob_row));
 assert(f.label("CANCEL")&&f.label("CONFIRM")&&!f.label("BACK"));
 assert(scrub_rect(f.label("CANCEL")->parent).x<scrub_rect(f.label("CONFIRM")->parent).x);
 fake::send(f.label("CONFIRM")->parent,7);fake::send(f.label("CANCEL")->parent,7);assert(f.confirms==1&&f.cancels==1&&f.backs==0);
}
void nozzle_scrub_recheck_layout(){
 ScrubFixture f;auto v=scrub_view(ScrubState::Recheck,0);f.view.update(v);assert(f.view.visible());
 assert(f.label(v.heading)&&f.label(v.body)&&f.label("Clean again")&&f.label("Save anyway"));
 assert(f.label("Scrub the flagged heads, then measure again.")&&f.label("Keep the offsets as measured."));
 assert(!f.label("Wire brush")&&!f.label("Printed blob"));
 assert(f.label("CANCEL")&&f.label("CONFIRM")&&!f.label("BACK"));
 assert(f.label("3. Head 2")->text_color==0xffff6666U&&f.label("5. Head 4")->text_color==0xffff6666U);
 assert(f.label("2. Head 1")->text_color!=0xffff6666U&&f.label("4. Head 3")->text_color!=0xffff6666U);
 auto*clean=f.label("Clean again")->parent,*save=f.label("Save anyway")->parent;
 auto marked=[&](fake::Node*row){auto*ring=row->children.at(0);return scrub_shown(ring->children.at(0),f.page);};
 assert(marked(clean)&&!marked(save));
 v.first_selected=false;f.view.update(v);assert(!marked(clean)&&marked(save));
 fake::send(save,7);fake::send(clean,7);assert(f.selects==std::vector<bool>({false,true}));
}
// Re-check: the readings of every head in two columns above the options; the
// options keep their size and gaps.
void nozzle_scrub_recheck_readings(){
 ScrubFixture f;f.view.update(scrub_view(ScrubState::Recheck,0));
 const auto body=scrub_rect(f.label("Their measurements did not repeat, which usually means residue on the nozzle."));
 const auto clean=scrub_rect(f.label("Clean again")->parent),save=scrub_rect(f.label("Save anyway")->parent);
 const char*names[]={"Head 1","Head 2","Head 3","Head 4"};ScrubRect r[4];
 for(int i=0;i<4;++i){auto*l=f.label(names[i]);assert(l&&l->font_address==MyriadPro_Regular_22);r[i]=scrub_rect(l);
  assert(r[i].y>=body.y+body.h&&r[i].y+r[i].h<=clean.y&&r[i].x>=kScrubTextX&&r[i].x+r[i].w<=800);}
 // Column-major: heads 1 and 2 on the left, 3 and 4 on the right.
 assert(r[0].x==r[1].x&&r[2].x==r[3].x&&r[2].x>r[0].x+200&&r[0].y==r[2].y&&r[1].y==r[3].y&&r[1].y==r[0].y+36);
 assert(f.label("0.041 mm")&&f.label("0.012 mm"));
 int marks=0,crosses=0;for(auto&n:fake::nodes)if(n->line_point_count&&scrub_shown(n.get(),f.page)){++marks;if(n->line_color==0xffff6666U)++crosses;
  const auto m=scrub_rect(n.get());assert(m.y+m.h<=clean.y&&m.x+m.w<=800);}
 assert(marks==4&&crosses==2);
 // Options: full width, at least 64 px high, 8 px apart, on the screen.
 assert(clean.h>=64&&save.h>=64&&clean.w>=110&&save.y>=clean.y+clean.h+8&&save.y+save.h<=480&&clean.x==kScrubTextX&&clean.w==kScrubTextWidth);
 auto targets=f.targets();assert(targets.size()==4);
 // Back to Prepare: no rows, the options at the top of the container.
 f.view.update(scrub_view(ScrubState::Prepare,0));
 for(auto*name:names)assert(!f.label(name));
 assert(scrub_rect(f.label("Wire brush")->parent).y<clean.y);
}
void nozzle_scrub_recheck_touch_targets(){
 ScrubFixture f;f.view.update(scrub_view(ScrubState::Recheck,0));
 auto targets=f.targets();assert(targets.size()==4);
 for(std::size_t i=0;i<targets.size();++i){
  const auto a=scrub_rect(targets[i]);assert(a.w>=110&&a.h>=64&&a.x>=0&&a.y>=0&&a.x+a.w<=800&&a.y+a.h<=480);
  for(std::size_t j=i+1;j<targets.size();++j){const auto b=scrub_rect(targets[j]);
   assert(b.x>=a.x+a.w+8||a.x>=b.x+b.w+8||b.y>=a.y+a.h+8||a.y>=b.y+b.h+8);}
 }
 for(auto*option:{"Clean again","Save anyway"}){const auto r=scrub_rect(f.label(option)->parent);assert(r.x==kScrubTextX&&r.w==kScrubTextWidth&&r.h>=64);}
}
void nozzle_scrub_three_heads_has_five_steps(){
 ScrubFixture f;f.view.update(scrub_view(ScrubState::Mounting,1,3));
 for(auto*s:{"1. Prepare","2. Head 1","3. Head 2","4. Head 3","5. Calibrate"})assert(f.label(s));
 assert(f.label("1. Prepare")->text_color==0xff888888U&&f.label("2. Head 1")->text_color==0xff888888U);
 assert(f.label("3. Head 2")->text_color==0xffff6600U&&f.label("5. Calibrate")->text_color==0xffeeeeeeU);
 for(auto&n:fake::nodes)if(scrub_shown(n.get(),f.page))assert(n->text.find("Head 4")==std::string::npos&&n->text.find("6.")!=0);
}
// Every touch target, invisible hit area included, is at least 110 x 64 px,
// on the screen, and at least 8 px from every other target.
void nozzle_scrub_touch_targets_meet_minimum(){
 ScrubFixture f;
 auto check=[&](std::vector<fake::Node*>targets,std::size_t expected){
  assert(targets.size()==expected);
  for(std::size_t i=0;i<targets.size();++i){
   const auto a=scrub_rect(targets[i]);assert(a.w>=110&&a.h>=64&&a.x>=0&&a.y>=0&&a.x+a.w<=800&&a.y+a.h<=480);
   for(std::size_t j=i+1;j<targets.size();++j){const auto b=scrub_rect(targets[j]);
    assert(b.x>=a.x+a.w+8||a.x>=b.x+b.w+8||b.y>=a.y+a.h+8||a.y>=b.y+b.h+8);}
  }
 };
 f.view.update(scrub_view(ScrubState::Prepare,0));check(f.targets(),4);
 // Header actions: top right, caption inside the 40 px bar.
 for(auto*caption:{"CANCEL","CONFIRM"}){const auto r=scrub_rect(f.label(caption)->parent);assert(r.w==116&&r.h==64&&r.y==0);
  const auto c=scrub_rect(f.label(caption));assert(c.y>=0&&c.y+c.h<=40&&c.h==MyriadPro_Bold_20_line_height&&f.label(caption)->font_address==MyriadPro_Bold_20);}
 assert(scrub_rect(f.label("CONFIRM")->parent).x+116==800);
 assert(scrub_rect(f.label("CONFIRM")->parent).x-(scrub_rect(f.label("CANCEL")->parent).x+116)>=8);
 // Option rows: the full width of the panel's choices container, inside the instruction column.
 int previous=0;
 for(auto*option:{"Wire brush","Printed blob"}){auto*row=f.label(option)->parent;const auto r=scrub_rect(row),c=scrub_rect(row->parent);
  assert(r.x==c.x&&r.w==c.w&&r.x==kScrubTextX&&r.w==kScrubTextWidth&&r.h>=64&&r.y>=64+8);
  assert(previous==0||r.y>=previous+8);previous=r.y+r.h;
  bool mark=false;for(auto*child:row->children)if(child->text.empty()&&child->w>=28&&child->h>=28)mark=true;assert(mark);}
 f.view.update(scrub_view(ScrubState::Scrub));check(f.targets(),2);
 f.view.update(scrub_view(ScrubState::Failed));check(f.targets(),1);
 assert(f.targets()[0]==f.label("BACK")->parent&&scrub_rect(f.label("BACK")->parent).x+116==800);
 const auto back=scrub_rect(f.label("BACK")->parent);assert(back.w==116&&back.h==64&&back.y==0);
}
// The panel view of a state is the one the scrub-state-* cases of
// tests/fixtures/progress_panel_views.json lay out with the client's fonts.
void nozzle_scrub_panel_view_matches_the_fit_cases(){
 const Json done=Json::array({{{"label","Prepare"},{"state","complete"}},{{"label","Head 1"},{"state","complete"}},{{"label","Head 2"},{"state","complete"}},{{"label","Head 3"},{"state","complete"}}});
 auto steps=[&](const char*head,const char*calibrate){auto s=done;s.push_back({{"label","Head 4"},{"state",head}});s.push_back({{"label","Calibrate"},{"state",calibrate}});return s;};
 auto heating=scrub_view(ScrubState::Heating);
 assert(nozzle_scrub_panel_view(heating)==Json({{"decisions",false},{"heading","Heating head 4..."},{"instruction",""},{"note",""},{"steps",steps("running","pending")},
  {"steps_width",200},{"title","Nozzle offset calibration"},{"title_width",540},{"value","127 / 160 \xc2\xb0""C"}}));
 auto failed=scrub_view(ScrubState::Failed);failed.body="Head 4 could not be moved into position.";failed.note="The nozzle may still be hot.";
 assert(nozzle_scrub_panel_view(failed)==Json({{"decisions",false},{"heading",""},{"instruction",failed.body},{"note",failed.note},{"steps",steps("failed","pending")},
  {"steps_width",200},{"title","Nozzle offset calibration"},{"title_width",540}}));
 const auto prepare=nozzle_scrub_panel_view(scrub_view(ScrubState::Prepare,0));
 assert(prepare["decisions"]==true&&prepare["choices_height"]==216&&prepare["heading"]=="How will the nozzles be cleaned?"&&!prepare.contains("value"));
 const auto calibrate=nozzle_scrub_panel_view(scrub_view(ScrubState::Calibrate));
 assert(calibrate["decisions"]==true&&calibrate["choices_height"]==144);
 assert(calibrate["heading"]=="Head 4 of 4"&&calibrate["instruction"]=="Measuring nozzle height..."&&calibrate["note"]=="Keep the door closed."&&calibrate["steps"]==steps("complete","running"));
 // Every state fits the panel at the screen size without scrolling (one-line labels here).
 ScrubFixture f;
 for(auto s:{ScrubState::Prepare,ScrubState::ReturnPrompt,ScrubState::Mounting,ScrubState::Heating,ScrubState::Scrub,ScrubState::Cooled,ScrubState::Cancelling,ScrubState::Failed,ScrubState::Calibrate}){
  f.view.update(scrub_view(s));
  for(auto&n:fake::nodes)if(!n->text.empty()&&scrub_shown(n.get(),f.page)){const auto r=scrub_rect(n.get());assert(r.x>=0&&r.y>=0&&r.x+r.w<=800&&r.y+r.h<=480);}
 }
}
void nozzle_scrub_heating_text(){
 ScrubFixture f;f.view.update(scrub_view(ScrubState::Heating));
 // The temperature is the panel's own bold value label, below the heading.
 auto*temperature=f.label("127 / 160 \xc2\xb0""C"),*heading=f.label("Heating head 4...");assert(temperature&&heading&&temperature!=heading);
 assert(temperature->font_address==MyriadPro_Bold_24&&heading->font_address==MyriadPro_Bold_24&&scrub_rect(temperature).y>scrub_rect(heading).y);
 assert(scrub_rect(temperature).x==kScrubTextX&&scrub_rect(temperature).w==kScrubTextWidth);
 auto*confirm=f.label("CONFIRM")->parent;
 assert((confirm->state&128)&&f.label("CONFIRM")->text_color==0xff888888U);
 fake::send(confirm,7);assert(f.confirms==0);
 f.view.update(scrub_view(ScrubState::Scrub));assert(!(confirm->state&128)&&f.label("CONFIRM")->text_color==0xffeeeeeeU);
 assert(!f.label("127 / 160 \xc2\xb0""C"));
 fake::send(confirm,7);assert(f.confirms==1);
}
void nozzle_scrub_calibrate_has_no_actions(){
 ScrubFixture f;f.view.update(scrub_view(ScrubState::Calibrate));
 assert(f.targets().empty()&&!f.label("CANCEL")&&!f.label("CONFIRM")&&!f.label("BACK"));
 assert(f.label("Head 4 of 4")&&f.label("Measuring nozzle height...")&&f.label("Keep the door closed."));
 assert(f.label("6. Calibrate")->text_color==0xffff6600U&&f.label("5. Head 4")->text_color==0xff888888U);
 for(auto*caption:{"CANCEL","CONFIRM","BACK"})fake::send(f.any(caption)->parent,7);
 // The option rows are hidden with the panel's choices container and take no tap.
 for(auto*option:{"Wire brush","Printed blob"}){assert(!f.label(option));fake::send(f.any(option)->parent,7);}
 assert(f.confirms==0&&f.cancels==0&&f.backs==0&&f.selects.empty());
}
// Calibrate: one display-only row per head below the instruction, above the
// note. The mark is a drawn line, a green check or a red cross, or an
// ellipsis while the head is measured.
void nozzle_scrub_calibrate_readings(){
 ScrubFixture f;auto v=scrub_view(ScrubState::Calibrate,2,4,"position");
 v.rows={{"Head 1","0.006 mm",ScrubMark::Passed},{"Head 2","0.013 mm",ScrubMark::Flagged},{"Head 3","0.002 mm",ScrubMark::Measuring},{"Head 4","",ScrubMark::None}};
 f.view.update(v);assert(f.view.visible());
 const auto instruction=scrub_rect(f.label("Measuring nozzle position...")),note=scrub_rect(f.label("Keep the door closed."));
 const char*names[]={"Head 1","Head 2","Head 3","Head 4"};int previous=instruction.y+instruction.h;
 for(auto*name:names){
  auto*l=f.label(name);assert(l&&l->font_address==MyriadPro_Regular_22);const auto r=scrub_rect(l);
  assert(r.x>=kScrubTextX&&r.y>=previous&&r.y+r.h<=note.y&&r.h>=MyriadPro_Regular_22_line_height);previous=r.y+r.h;
 }
 for(auto*spread:{"0.006 mm","0.013 mm","0.002 mm"}){auto*l=f.label(spread);assert(l&&l->font_address==MyriadPro_Regular_22);}
 const auto row_y=[&](int i){return scrub_rect(f.label(names[i])).y;};
 assert(scrub_rect(f.label("0.006 mm")).y==row_y(0)&&scrub_rect(f.label("0.002 mm")).y==row_y(2));
 assert(scrub_rect(f.label("0.006 mm")).x>scrub_rect(f.label("Head 1")).x+scrub_rect(f.label("Head 1")).w);
 auto*measuring=f.label("\xe2\x80\xa6");assert(measuring&&measuring->font_address==MyriadPro_Regular_22&&scrub_rect(measuring).y==row_y(2));
 const auto marks=[&]{std::vector<fake::Node*>out;for(auto&n:fake::nodes)if(n->line_point_count&&scrub_shown(n.get(),f.page))out.push_back(n.get());
  std::sort(out.begin(),out.end(),[](fake::Node*a,fake::Node*b){return scrub_rect(a).y<scrub_rect(b).y;});return out;};
 auto shown=marks();assert(shown.size()==2);
 assert(shown[0]->line_point_count==3&&shown[0]->line_color==0xff44cc66U);   // check
 assert(shown[1]->line_point_count==5&&shown[1]->line_color==0xffff6666U);   // cross
 for(int i=0;i<2;++i){const auto m=scrub_rect(shown[i]);assert(m.y>=row_y(i)&&m.y<row_y(i)+MyriadPro_Regular_22_line_height);
  assert(m.x>scrub_rect(f.label(names[i])).x+scrub_rect(f.label(names[i])).w&&m.x<scrub_rect(f.label("0.006 mm")).x);}
 assert(f.targets().empty());
 for(auto&n:fake::nodes)if(scrub_shown(n.get(),f.page)&&(!n->text.empty()||n->line_point_count)){const auto r=scrub_rect(n.get());assert(r.x>=0&&r.y>=0&&r.x+r.w<=800&&r.y+r.h<=480);}
 // A flag on a head being measured turns its mark into the cross at once.
 auto flagged=v;flagged.rows[2]={"Head 3","0.021 mm",ScrubMark::Flagged};f.view.update(flagged);
 assert(!f.label("\xe2\x80\xa6")&&f.label("0.021 mm")&&!f.label("0.002 mm"));
 shown=marks();assert(shown.size()==3&&shown[2]->line_point_count==5&&shown[2]->line_color==0xffff6666U);
 // An unchanged view writes nothing.
 const auto writes=fake::text_writes;const auto count=fake::nodes.size();f.view.update(flagged);assert(fake::text_writes==writes&&fake::nodes.size()==count);
 // Other states have no rows; the option rows return on Prepare.
 f.view.update(scrub_view(ScrubState::Scrub,3));
 for(auto*name:names)assert(!f.label(name));
 assert(marks().empty()&&!f.label("0.006 mm"));
 f.view.update(scrub_view(ScrubState::Prepare,0));assert(f.label("Wire brush")&&!f.label("Head 1")&&marks().empty());
 f.view.update(v);assert(!f.label("Wire brush")&&f.label("Head 4")&&marks().size()==2);
 // Three heads: three rows.
 f.view.update(scrub_view(ScrubState::Calibrate,0,3,"position"));
 assert(f.label("Head 3")&&!f.label("Head 4")&&marks().empty());
}
void nozzle_scrub_failed_shows_back_only(){
 ScrubFixture f;const auto v=scrub_view(ScrubState::Failed,1);f.view.update(v);
 assert(f.label("BACK")&&!f.label("CANCEL")&&!f.label("CONFIRM")&&f.label(v.body));
 assert(!f.label("Wire brush")&&scrub_rect(f.label(v.body)).y<100); // no heading: the error takes its place
 fake::send(f.any("CONFIRM")->parent,7);fake::send(f.any("CANCEL")->parent,7);fake::send(f.label("BACK")->parent,7);
 assert(f.backs==1&&f.confirms==0&&f.cancels==0);
 // A failure that may leave a heated nozzle says so in the panel's note, below the error.
 auto hot=v;hot.note="The nozzle may still be hot.";f.view.update(hot);
 assert(f.label(hot.note)&&f.label(hot.note)->text_color==0xffffbb66U&&scrub_rect(f.label(hot.note)).y>scrub_rect(f.label(v.body)).y);
 f.view.update(v);assert(!f.label(hot.note));
 // The step that failed is the current one.
 assert(f.label("3. Head 2")&&f.label("2. Head 1")->text_color==0xff888888U);
 // It is drawn in the panel's failed colour.
 assert(f.label("3. Head 2")->text_color==0xffff6666U&&f.label("4. Head 3")->text_color==0xffeeeeeeU);
}
void nozzle_scrub_update_is_idempotent(){
 ScrubFixture f;auto v=scrub_view(ScrubState::Heating);f.view.update(v);
 auto count=fake::nodes.size();auto writes=fake::text_writes;
 f.view.update(v);assert(fake::nodes.size()==count&&fake::text_writes==writes);
 // Less than a degree changes nothing that is drawn.
 v.actual=127.4;f.view.update(v);assert(fake::nodes.size()==count&&fake::text_writes==writes);
 auto*confirm=f.label("CONFIRM")->parent;const auto disables=confirm->disable_writes;
 // A whole-degree change rewrites the value label only.
 v.actual=150;f.view.update(v);assert(fake::nodes.size()==count&&fake::text_writes==writes+1&&f.label("150 / 160 \xc2\xb0""C"));
 assert(confirm->disable_writes==disables); // a temperature poll leaves the actions alone
 for(auto s:{ScrubState::Prepare,ScrubState::Scrub,ScrubState::Failed,ScrubState::Calibrate})f.view.update(scrub_view(s));
 assert(fake::nodes.size()==count);
 f.view.update(scrub_view(ScrubState::Prepare,0));assert(f.label("Wire brush")&&!f.label("Clean again"));
 f.view.update(scrub_view(ScrubState::Recheck,0));assert(fake::nodes.size()==count&&f.label("Clean again")&&f.label("Save anyway")&&!f.label("Wire brush"));
 f.view.update(scrub_view(ScrubState::Prepare,0));assert(fake::nodes.size()==count&&f.label("Wire brush")&&f.label("Printed blob")&&!f.label("Clean again"));
}
void nozzle_scrub_dismiss_releases_widgets(){
 ScrubFixture f;f.view.update(scrub_view(ScrubState::Prepare,0));
 auto*confirm=f.label("CONFIRM")->parent,*cancel=f.label("CANCEL")->parent,*row=f.label("Printed blob")->parent;
 f.view.created(nullptr);assert(f.page->children.empty()&&!f.view.visible());
 for(auto*n:{confirm,cancel,row})fake::send(n,7);
 const auto count=fake::nodes.size();f.view.update(scrub_view(ScrubState::Scrub));
 assert(fake::nodes.size()==count&&f.confirms==0&&f.cancels==0&&f.selects.empty());
 // The stock UI cleans the page under the screen: nothing is left to act on.
 f.view.created(f.page);f.view.update(scrub_view(ScrubState::Scrub));auto*cleaned=f.label("CONFIRM")->parent;
 fake::clean(f.page);fake::send(cleaned,7);f.view.update(scrub_view(ScrubState::Scrub));
 assert(f.confirms==0&&!f.view.visible()&&f.page->children.empty());
 // A page deleted by the stock UI releases the panel the same way.
 f.view.created(f.page);f.view.update(scrub_view(ScrubState::Scrub));auto*again=f.label("CONFIRM")->parent;
 fake::del(f.page);fake::send(again,7);f.view.update(scrub_view(ScrubState::Scrub));assert(f.confirms==0&&!f.view.visible());
 // No page: nothing is built and nothing is shown.
 f.view.created(nullptr);f.view.update(scrub_view(ScrubState::Scrub));assert(!f.view.visible());
}
// Guided nozzle scrub wiring: Maintenance START, Prepare, the held vendor
// worker and its sequenced commands. The stock START handler, the stock
// command sender and the vendor selection bytes are test doubles.
struct OldClientPort:Port{bool profile1113()const override{return false;}};
struct ScrubRun{
 static int&delegated(){static int n=0;return n;}
 static bool&enqueues(){static bool v=true;return v;}
 static Runtime*&live(){static Runtime*r=nullptr;return r;}
 static std::mutex&sent_mutex(){static std::mutex m;return m;}
 static std::vector<std::string>&sent_store(){static std::vector<std::string>v;return v;}
 static void stock_start(void*){++delegated();if(enqueues())live()->stock_calibration_enqueued();}
 // A wrapped command carrying this hex text is not sent: the stock sender throws.
 static std::string&refused_hex(){static std::string v;return v;}
 static std::string hex(const std::string&command){std::string out;constexpr char digits[]="0123456789abcdef";for(unsigned char c:command){out+=digits[c>>4];out+=digits[c&15];}return out;}
 static void stock_send(std::string command){
  if(!refused_hex().empty()&&command.find("HEX="+refused_hex()+" ")!=std::string::npos)throw std::runtime_error("send");
  std::lock_guard<std::mutex>lock(sent_mutex());sent_store().push_back(command);}
 static std::vector<std::string>sent(){std::lock_guard<std::mutex>lock(sent_mutex());return sent_store();}
 static std::string wrapped(const std::string&command,unsigned sequence,const std::string&request){
  std::string hex;constexpr char digits[]="0123456789abcdef";for(unsigned char c:command){hex+=digits[c>>4];hex+=digits[c&15];}
  return "_WMP_CALIBRATION_COMMAND HEX="+hex+" SESSION="+std::string(32,'a')+" REQUEST="+request+" SEQUENCE="+std::to_string(sequence);
 }
 Http wire;std::unique_ptr<Port>clock;wmp_openace::UiChannel ch;Runtime r;Json ready;fake::Node*page,*start;std::thread worker;std::atomic<bool>returned{false};bool withheld_rapid=false,withheld_park=false;
 ScrubRun(const Json&data,unsigned char rapid,std::array<unsigned char,4>selected,unsigned heads=1,bool supported=true)
  :clock(supported?new Port:new OldClientPort),r(wire,*clock,ch),page(fake::make(fake::screen)),start(fake::make(page)){
  ready=data;ready["fresh"]=true;ready["owner"]="standalone";ready["job"]={{"state","idle"}};
  ready["calibration_session"]=std::string(32,'a');ready["calibration_failed"]="";ready["calibration_active"]=false;
  for(auto key:{"filament_operation","toolhead_operation","operation"})ready.erase(key);
  ready["calibration_attempt_protocol"]=1;
  ready["nozzle_scrub"]={{"protocol",1},{"head",-1},{"phase","idle"},{"target",160.0},{"error",""}};
  ready["calibration_progress"]={{"protocol",1},{"head",-1},{"phase","idle"}};
  status();RuntimeReceiptTest::scrub_vendor(r,rapid,selected,heads);
  delegated()=0;enqueues()=true;live()=&r;refused_hex().clear();{std::lock_guard<std::mutex>lock(sent_mutex());sent_store().clear();}
  wmp_openace::runtime.store(&r);wmp_openace::original_maintenance_event.store(&stock_start);wmp_openace::original_command_sender.store(&stock_send);
  fake::bind(start,&wmp_openace::unified_maintenance_event,7,nullptr);
 }
 ~ScrubRun(){
  if(worker.joinable())worker.join();
  wmp_openace::runtime.store(nullptr);wmp_openace::original_maintenance_event.store(nullptr);wmp_openace::original_command_sender.store(nullptr);live()=nullptr;
  if(panel())fake::del(panel());
  fake::del(page);
  // The vendor bytes are shared test storage: back to the values no case offers Prepare with.
  RuntimeReceiptTest::scrub_vendor(r,1,{{0,0,0,0}},4);RuntimeReceiptTest::scrub_failed_byte(r,0);
 }
 // Scrub and progress status written without a request belong to the current
 // calibration request: the backend has admitted the run.
 void status(){auto data=ready;
  for(const auto*key:{"nozzle_scrub","calibration_progress","nozzle_touch"})if(data.contains(key)&&data[key].is_object()&&!data[key].contains("request"))data[key]["request"]=request();
  RuntimeReceiptTest::scrub_status(r,data);}
 void head(double actual,double target,const char*phase){
  for(auto&h:ready["heads"]){if(h.value("id","")=="h0"){h["actual"]=actual;h["target"]=target;}}
  ready["nozzle_scrub"]={{"phase",phase},{"head",0},{"target",160.0}};status();
 }
 fake::Node*panel()const{for(auto&n:fake::nodes)if(n->live&&n->text=="Nozzle offset calibration"&&scrub_under(n.get(),fake::screen))return n->parent->parent;return nullptr;}
 fake::Node*label(const std::string&text)const{auto*root=panel();if(!root||(root->flags&1))return nullptr;
  for(auto&n:fake::nodes)if(!text.empty()&&n->text==text&&scrub_shown(n.get(),root))return n.get();
  return nullptr;}
 void tap(const std::string&text){auto*l=label(text);assert(l);fake::send(l->parent,7);}
 ScrubState state(){return RuntimeReceiptTest::scrub_flow_view(r).state;}
 // GUI ticks until the condition holds; the vendor worker runs on its own thread.
 template<class F>void until(F done){
  const auto limit=std::chrono::steady_clock::now()+std::chrono::seconds(10);
  while(!done()){assert(std::chrono::steady_clock::now()<limit);r.gui_step();std::this_thread::sleep_for(std::chrono::milliseconds(1));}
 }
 // The vendor offset stage: G28, then one RAPID_MODE per head, then the park.
 void run_worker(unsigned heads=1){
  worker=std::thread([this,heads]{
   r.run_stock_calibration_worker([&]{
    wmp_openace::forward_stock_command(offset_home,"G28");
    withheld_rapid=r.withhold_offset_send(offset_rapid);withheld_park=r.withhold_offset_send(offset_park);
    for(unsigned i=0;i<heads;++i)wmp_openace::forward_stock_command(offset_rapid,"RAPID_MODE T="+std::to_string(i));
    wmp_openace::forward_stock_command(offset_park,"PARK_CURRENT_TOOL");
   });
   returned.store(true);
  });
 }
 std::string request(){return RuntimeReceiptTest::calibration_request(r);}
};
void maintenance_start_in_accurate_mode_opens_prepare(const Json&data){
 ScrubRun t(data,0,{{0,0,0,1}},4);
 fake::send(t.start,7);
 assert(ScrubRun::delegated()==0&&!t.r.stock_calibration_reserved());
 assert(t.label("How will the nozzles be cleaned?")&&t.label("Wire brush")&&t.label("Printed blob")&&t.label("5. Head 4"));
 assert(t.panel()->parent==fake::screen&&!(t.label("CONFIRM")->parent->state&128));
 assert(RuntimeReceiptTest::scrub_rapid(t.r)==0&&ScrubRun::sent().empty());
}
void prepare_blob_delegates_start_unchanged(const Json&data){
 ScrubRun t(data,0,{{0,0,0,1}},4);
 fake::send(t.start,7);t.tap("Printed blob");t.r.gui_step();t.tap("CONFIRM");
 assert(ScrubRun::delegated()==0&&t.panel()); // acted on by the next GUI tick, not inside the tap
 t.r.gui_step();
 assert(ScrubRun::delegated()==1&&!t.panel()&&RuntimeReceiptTest::scrub_rapid(t.r)==0);
 assert(t.r.stock_calibration_reserved()&&t.state()==ScrubState::Idle);
 t.run_worker(4);t.until([&]{return t.returned.load();});
 const auto request=t.request();
 assert((ScrubRun::sent()==std::vector<std::string>{ScrubRun::wrapped("G28",0,request),ScrubRun::wrapped("RAPID_MODE T=0",1,request),
  ScrubRun::wrapped("RAPID_MODE T=1",2,request),ScrubRun::wrapped("RAPID_MODE T=2",3,request),ScrubRun::wrapped("RAPID_MODE T=3",4,request),
  ScrubRun::wrapped("PARK_CURRENT_TOOL",5,request)}));
 assert(!t.panel());
}
void prepare_brush_sets_rapid_and_delegates_once(const Json&data){
 {ScrubRun t(data,0,{{1,0,0,1}},4);
  fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();
  assert(ScrubRun::delegated()==1&&RuntimeReceiptTest::scrub_rapid(t.r)==1&&!t.panel());
  assert(t.r.stock_calibration_reserved()&&t.state()==ScrubState::StockChecks);
  t.r.gui_step();t.r.gui_step();assert(ScrubRun::delegated()==1&&t.state()==ScrubState::StockChecks&&!t.panel());
  // A worker that ends before the offset stage leaves nothing bound.
  t.r.run_stock_calibration_worker([]{});t.r.gui_step();assert(t.state()==ScrubState::Idle&&!t.panel());
 }
 // The stock handler declines to enqueue: the binding is lost.
 {ScrubRun t(data,0,{{0,0,0,1}},4);ScrubRun::enqueues()=false;
  fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();
  assert(ScrubRun::delegated()==1&&!t.r.stock_calibration_reserved()&&t.state()==ScrubState::Idle);
 }
 // The START button is gone when CONFIRM is handled: nothing is written or sent.
 {ScrubRun t(data,0,{{0,0,0,1}},4);
  fake::send(t.start,7);t.tap("CONFIRM");fake::del(t.start);t.r.gui_step();
  assert(ScrubRun::delegated()==0&&RuntimeReceiptTest::scrub_rapid(t.r)==0&&t.state()==ScrubState::Idle&&!t.panel());
  t.start=fake::make(t.page);
 }
}
void prepare_cancel_changes_nothing(const Json&data){
 ScrubRun t(data,0,{{1,1,0,1}},4);
 fake::send(t.start,7);auto*panel=t.panel();t.tap("CANCEL");
 assert(panel->live&&t.panel()==panel); // not deleted inside its own tap
 t.r.gui_step();
 assert(!panel->live&&!t.panel()&&ScrubRun::delegated()==0&&RuntimeReceiptTest::scrub_rapid(t.r)==0);
 assert(!t.r.stock_calibration_reserved()&&t.state()==ScrubState::Idle&&ScrubRun::sent().empty());
 fake::send(t.start,7);assert(ScrubRun::delegated()==0&&t.label("How will the nozzles be cleaned?"));
}
void rapid_mode_start_is_untouched(const Json&data){
 {ScrubRun t(data,1,{{0,0,0,1}},4);
  fake::send(t.start,7);assert(ScrubRun::delegated()==1&&!t.panel()&&t.r.stock_calibration_reserved()&&t.state()==ScrubState::Idle);
  assert(RuntimeReceiptTest::scrub_rapid(t.r)==1);}
 // Offset row not ticked: the stale mode byte does not matter.
 {ScrubRun t(data,0,{{1,0,1,0}},4);
  fake::send(t.start,7);assert(ScrubRun::delegated()==1&&!t.panel()&&RuntimeReceiptTest::scrub_rapid(t.r)==0);}
}
void stale_status_keeps_confirm_disabled(const Json&data){
 {ScrubRun t(data,0,{{0,0,0,1}},4);
  fake::send(t.start,7);assert(t.label("CONFIRM"));
  t.clock->now+=2001;t.r.gui_step();
  auto*confirm=t.label("CONFIRM")->parent;assert(confirm->state&128);
  fake::send(confirm,7);t.r.gui_step();t.r.gui_step();
  assert(ScrubRun::delegated()==0&&t.panel()&&RuntimeReceiptTest::scrub_rapid(t.r)==0&&t.state()==ScrubState::Prepare);
  t.status();t.r.gui_step();assert(!(confirm->state&128));
  t.tap("CONFIRM");t.r.gui_step();assert(ScrubRun::delegated()==1&&RuntimeReceiptTest::scrub_rapid(t.r)==1);
 }
 // Stale when START is pressed: refused by the existing gate, nothing offered.
 {ScrubRun t(data,0,{{0,0,0,1}},4);
  t.clock->now+=2001;fake::send(t.start,7);
  assert(ScrubRun::delegated()==0&&!t.panel()&&t.state()==ScrubState::Idle&&RuntimeReceiptTest::scrub_rapid(t.r)==0);
 }
}
void unsupported_profile_never_offers(const Json&data){
 ScrubRun t(data,0,{{0,0,0,1}},4,false);
 fake::send(t.start,7);
 assert(ScrubRun::delegated()==1&&!t.panel()&&t.state()==ScrubState::Idle&&RuntimeReceiptTest::scrub_rapid(t.r)==0);
}
// The scrub and progress status come from one backend module, which also
// registers the scrub commands. Without either status the clean is not offered.
void backend_without_scrub_support_never_offers(const Json&data){
 for(const auto*key:{"nozzle_scrub","calibration_progress"})
  for(const auto&absent:{Json{{"phase","unavailable"}},Json::object(),Json{{"protocol",2},{"head",-1},{"phase","idle"}}}){
   ScrubRun t(data,0,{{0,0,0,1}},4);t.ready[key]=absent;t.status();
   fake::send(t.start,7);
   assert(ScrubRun::delegated()==1&&!t.panel()&&t.state()==ScrubState::Idle&&RuntimeReceiptTest::scrub_rapid(t.r)==0);
   assert(t.r.stock_calibration_reserved()&&ScrubRun::sent().empty());
  }
}
void worker_hold_sends_sequenced_scrub_commands(const Json&data){
 ScrubRun t(data,0,{{0,0,0,1}},1);
 fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();
 assert(t.r.stock_calibration_reserved()&&!t.panel());
 const auto request=t.request();
 t.run_worker();
 t.until([&]{return ScrubRun::sent().size()>=2;});
 assert(!t.returned.load()&&t.state()==ScrubState::Mounting);
 t.r.gui_step();assert(t.label("Mounting head 1...")&&t.panel()->parent==fake::screen);
 t.head(100,160,"heating");t.until([&]{return t.state()==ScrubState::Heating;});
 t.r.gui_step();assert(t.label("Heating head 1...")&&t.label("100 / 160 \xc2\xb0""C"));
 t.head(158,160,"heating");t.until([&]{return ScrubRun::sent().size()>=3;});
 t.r.gui_step();assert(t.state()==ScrubState::Scrub&&t.label("Scrub the nozzle on head 1")&&!t.returned.load());
 // Held with no new status: the worker stays held and sends nothing more.
 std::this_thread::sleep_for(std::chrono::milliseconds(300));assert(!t.returned.load()&&ScrubRun::sent().size()==3);
 t.tap("CONFIRM");t.until([&]{return t.returned.load();});
 assert((ScrubRun::sent()==std::vector<std::string>{
  ScrubRun::wrapped("G28",0,request),ScrubRun::wrapped("_WMP_SCRUB_HEAD T=0",1,request),
  ScrubRun::wrapped("_WMP_SCRUB_ATTENTION VALUE=1",2,request),ScrubRun::wrapped("_WMP_SCRUB_ATTENTION VALUE=0",3,request),
  ScrubRun::wrapped("_WMP_SCRUB_COOL T=0",4,request),ScrubRun::wrapped("RAPID_MODE T=0",5,request),
  ScrubRun::wrapped("PARK_CURRENT_TOOL",6,request)}));
 // The screen leaves with the worker; the flow is free for the next run.
 t.r.gui_step();assert(!t.panel()&&t.state()==ScrubState::Idle&&!t.r.stock_calibration_reserved());
 assert(!t.r.withhold_offset_send(offset_rapid));
}
// While the flow has the case light signal on, a touch anywhere (the
// display's inactive time) or a door opening sends one release through the
// held worker. The touch is still delivered.
void attention_released_by_touch_or_door(const Json&data){
 for(const bool door:{false,true}){
  ScrubRun t(data,0,{{0,0,0,1}},1);t.ready["doors"]=0;t.status();
  fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();
  const auto request=t.request();
  t.run_worker();
  t.until([&]{return ScrubRun::sent().size()>=2;});
  t.head(158,160,"heating");t.until([&]{return ScrubRun::sent().size()>=3;});
  t.r.gui_step();assert(t.state()==ScrubState::Scrub&&ScrubRun::sent()[2]==ScrubRun::wrapped("_WMP_SCRUB_ATTENTION VALUE=1",2,request));
  // Nothing releases it without a touch or an opening.
  for(int i=0;i<5;++i)t.r.gui_step();
  std::this_thread::sleep_for(std::chrono::milliseconds(300));assert(ScrubRun::sent().size()==3);
  if(door){t.ready["doors"]=2;t.status();}else fake::inactive_ms=0;
  t.until([&]{return ScrubRun::sent().size()>=4;});
  fake::inactive_ms=3600000;
  assert(ScrubRun::sent()[3]==ScrubRun::wrapped("_WMP_SCRUB_ATTENTION VALUE=0",3,request)&&t.state()==ScrubState::Scrub);
  for(int i=0;i<5;++i)t.r.gui_step();
  std::this_thread::sleep_for(std::chrono::milliseconds(300));assert(ScrubRun::sent().size()==4);
  // CONFIRM still acts and sends no second release.
  t.tap("CONFIRM");t.until([&]{return t.returned.load();});
  assert((ScrubRun::sent()==std::vector<std::string>{
   ScrubRun::wrapped("G28",0,request),ScrubRun::wrapped("_WMP_SCRUB_HEAD T=0",1,request),
   ScrubRun::wrapped("_WMP_SCRUB_ATTENTION VALUE=1",2,request),ScrubRun::wrapped("_WMP_SCRUB_ATTENTION VALUE=0",3,request),
   ScrubRun::wrapped("_WMP_SCRUB_COOL T=0",4,request),ScrubRun::wrapped("RAPID_MODE T=0",5,request),
   ScrubRun::wrapped("PARK_CURRENT_TOOL",6,request)}));
  t.r.gui_step();
 }
}
// The touch is a decrease of the display's inactive time between two GUI
// ticks, read in LVGL's own clock. An inactive time that does not decrease
// is no touch, however far the screen runtime's clock has moved.
void attention_touch_uses_one_clock(const Json&data){
 fake::inactive_ms=10000;
 ScrubRun t(data,0,{{0,0,0,1}},1);t.ready["doors"]=0;t.status();
 fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();
 const auto request=t.request();
 t.run_worker();
 t.until([&]{return ScrubRun::sent().size()>=2;});
 t.head(158,160,"heating");t.until([&]{return ScrubRun::sent().size()>=3;});
 t.r.gui_step();assert(t.state()==ScrubState::Scrub&&ScrubRun::sent()[2]==ScrubRun::wrapped("_WMP_SCRUB_ATTENTION VALUE=1",2,request));
 // 60 s later on the runtime clock; the LVGL tick did not advance (a wall-clock step back).
 t.clock->now+=60000;t.status();
 for(int i=0;i<5;++i)t.r.gui_step();
 std::this_thread::sleep_for(std::chrono::milliseconds(300));assert(ScrubRun::sent().size()==3);
 fake::inactive_ms=12000;for(int i=0;i<5;++i)t.r.gui_step();
 std::this_thread::sleep_for(std::chrono::milliseconds(300));assert(ScrubRun::sent().size()==3);
 // A touch: the inactive time drops.
 fake::inactive_ms=5;t.until([&]{return ScrubRun::sent().size()>=4;});
 assert(ScrubRun::sent()[3]==ScrubRun::wrapped("_WMP_SCRUB_ATTENTION VALUE=0",3,request));
 fake::inactive_ms=3600000;
 t.tap("CONFIRM");t.until([&]{return t.returned.load();});t.r.gui_step();
}
void worker_released_on_session_change(const Json&data){
 ScrubRun t(data,0,{{0,0,0,1}},2);
 fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();
 const auto request=t.request();
 std::atomic<bool>home_sent{false},proceed{false};bool withheld_rapid=false,withheld_park=false,withheld_home=true,withheld_save=true;
 t.worker=std::thread([&]{
  t.r.run_stock_calibration_worker([&]{
   wmp_openace::forward_stock_command(offset_home,"G28");home_sent.store(true);
   while(!proceed.load())std::this_thread::sleep_for(std::chrono::milliseconds(1));
   withheld_rapid=t.r.withhold_offset_send(offset_rapid);withheld_park=t.r.withhold_offset_send(offset_park);
   withheld_home=t.r.withhold_offset_send(offset_home);withheld_save=t.r.withhold_offset_send(0x4b869c);
   wmp_openace::forward_stock_command(offset_rapid,"RAPID_MODE T=0");wmp_openace::forward_stock_command(offset_park,"PARK_CURRENT_TOOL");
   wmp_openace::forward_stock_command(0x4b869c,"SAVE_CONFIG");
  });
  t.returned.store(true);
 });
 t.until([&]{return ScrubRun::sent().size()>=2;});assert(!home_sent.load());
 t.ready["calibration_session"]=std::string(32,'b');t.status();
 t.until([&]{return home_sent.load();}); // released without a tap
 assert(RuntimeReceiptTest::scrub_outcome(t.r)==ScrubOutcome::Skip);
 t.r.gui_step();assert(t.label("Printer restarted. Calibration stopped.")&&t.label("BACK")&&!t.label("CONFIRM")&&!t.label("CANCEL"));
 // BACK leaves the screen on the next GUI tick; the outcome stays for the worker.
 auto*panel=t.panel();t.tap("BACK");assert(panel->live);
 t.r.gui_step();assert(!panel->live&&!t.panel());
 t.r.gui_step();assert(!t.panel()&&RuntimeReceiptTest::scrub_outcome(t.r)==ScrubOutcome::Skip);
 proceed.store(true);t.until([&]{return t.returned.load();});
 assert(withheld_rapid&&withheld_park&&!withheld_home&&!withheld_save);
 assert((ScrubRun::sent()==std::vector<std::string>{ScrubRun::wrapped("G28",0,request),ScrubRun::wrapped("_WMP_SCRUB_HEAD T=0",1,request),
  ScrubRun::wrapped("SAVE_CONFIG",2,request)}));
 t.r.gui_step();assert(t.state()==ScrubState::Idle&&!t.panel());
}
void worker_released_when_screen_is_torn_down_or_runtime_stops(const Json&data){
 // The stock UI deletes the screen while the worker is held: same as CANCEL.
 {ScrubRun t(data,0,{{0,0,0,1}},1);
  fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();const auto request=t.request();
  t.run_worker();t.until([&]{return ScrubRun::sent().size()>=2&&t.panel();});
  fake::del(t.panel());
  t.until([&]{return ScrubRun::sent().size()>=3;});
  assert(ScrubRun::sent()[2]==ScrubRun::wrapped("_WMP_SCRUB_END",2,request)&&!t.returned.load()&&t.state()==ScrubState::Cancelling&&!t.panel());
  t.head(28,0,"ended");t.until([&]{return t.returned.load();});
  assert(ScrubRun::sent().size()==3); // RAPID_MODE and the park are withheld
  t.r.gui_step();assert(t.state()==ScrubState::Idle);
 }
 // Runtime shutdown ends the wait whatever the flow state.
 {ScrubRun t(data,0,{{0,0,0,1}},1);
  fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();
  t.run_worker();t.until([&]{return ScrubRun::sent().size()>=2;});
  RuntimeReceiptTest::scrub_shutdown(t.r);t.worker.join();assert(t.returned.load()&&ScrubRun::sent().size()==2);
 }
}
void refused_brush_start_restores_accurate_mode(const Json&data){
 // The stock handler enqueues no worker.
 {ScrubRun t(data,0,{{0,0,0,1}},4);ScrubRun::enqueues()=false;
  fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();
  assert(ScrubRun::delegated()==1&&!t.r.stock_calibration_reserved()&&RuntimeReceiptTest::scrub_rapid(t.r)==0);
  fake::send(t.start,7);assert(ScrubRun::delegated()==1&&t.label("How will the nozzles be cleaned?"));
 }
 // Admission refuses the re-sent START.
 {ScrubRun t(data,0,{{0,0,0,1}},4);
  fake::send(t.start,7);t.tap("CONFIRM");
  t.ready["calibration_active"]=true;t.status();t.r.gui_step();
  assert(ScrubRun::delegated()==0&&!t.r.stock_calibration_reserved()&&RuntimeReceiptTest::scrub_rapid(t.r)==0&&t.state()==ScrubState::Idle);
  t.r.gui_step();RuntimeReceiptTest::close_maintenance_notice(t.r);
  t.ready["calibration_active"]=false;t.status();
  fake::send(t.start,7);assert(ScrubRun::delegated()==0&&t.label("How will the nozzles be cleaned?"));
 }
 // A worker was enqueued for the bound request: the byte stays rapid for it.
 {ScrubRun t(data,0,{{0,0,0,1}},4);
  fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();
  assert(t.r.stock_calibration_reserved()&&RuntimeReceiptTest::scrub_rapid(t.r)==1);
  t.r.run_stock_calibration_worker([]{});t.r.gui_step();assert(RuntimeReceiptTest::scrub_rapid(t.r)==1);
 }
}
void second_start_while_prepare_open_does_not_double_start(const Json&data){
 ScrubRun t(data,0,{{0,0,0,1}},4);
 fake::send(t.start,7);fake::send(t.start,7);
 assert(ScrubRun::delegated()==0&&t.label("How will the nozzles be cleaned?"));
 unsigned panels=0;for(auto&n:fake::nodes)if(n->live&&n->text=="Nozzle offset calibration")++panels;
 assert(panels==1);
 // START again after CONFIRM was tapped but before it was handled: the newer Prepare wins.
 t.tap("CONFIRM");fake::send(t.start,7);t.r.gui_step();
 assert(ScrubRun::delegated()==0&&!t.r.stock_calibration_reserved()&&t.label("How will the nozzles be cleaned?"));
 t.tap("CONFIRM");t.r.gui_step();t.r.gui_step();
 assert(ScrubRun::delegated()==1&&t.r.stock_calibration_reserved()&&!t.panel());
 // The run is reserved: another START is refused by admission and offers nothing.
 fake::send(t.start,7);assert(ScrubRun::delegated()==1&&!t.panel());
 t.r.gui_step();RuntimeReceiptTest::close_maintenance_notice(t.r);
 t.r.run_stock_calibration_worker([]{});
}
void throwing_scrub_send_does_not_escape_the_worker(const Json&data){
 // Every send throws: HEAD, then END once, then the worker returns normally.
 {ScrubRun t(data,0,{{0,0,0,1}},1);
  fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();
  std::vector<std::string>tried;bool threw=false,withheld=false;
  t.r.run_stock_calibration_worker([&]{
   try{t.r.nozzle_scrub_at_offset_stage([&](const std::string&command){tried.push_back(command);throw std::runtime_error("send");});}
   catch(...){threw=true;}
   withheld=t.r.withhold_offset_send(offset_rapid)&&t.r.withhold_offset_send(offset_park);
  });
  assert(!threw&&withheld&&(tried==std::vector<std::string>{"_WMP_SCRUB_HEAD T=0","_WMP_SCRUB_END"}));
  t.r.gui_step();assert(t.label("Calibration stopped. Check the printer before trying again.")&&t.label("BACK"));
  t.tap("BACK");t.r.gui_step();assert(!t.panel()&&t.state()==ScrubState::Idle);
 }
 // One send throws while the nozzle is heating: END is sent and the worker waits for it.
 {ScrubRun t(data,0,{{0,0,0,1}},2);
  fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();
  std::mutex m;std::vector<std::string>sent;bool threw=false,withheld=false;
  auto count=[&]{std::lock_guard<std::mutex>lock(m);return sent.size();};
  t.worker=std::thread([&]{
   t.r.run_stock_calibration_worker([&]{
    try{t.r.nozzle_scrub_at_offset_stage([&](const std::string&command){
     if(command=="_WMP_SCRUB_HEAT T=1")throw std::runtime_error("send");
     std::lock_guard<std::mutex>lock(m);sent.push_back(command);});}
    catch(...){threw=true;}
    withheld=t.r.withhold_offset_send(offset_rapid)&&t.r.withhold_offset_send(offset_park);
   });
   t.returned.store(true);
  });
  t.until([&]{return count()>=1;});
  t.head(100,160,"heating"); // head 1 mounted and heating: the flow queues the preheat of head 2
  t.until([&]{return count()>=2;});
  assert(!t.returned.load()&&t.state()==ScrubState::Cancelling);
  t.head(28,0,"ended");t.until([&]{return t.returned.load();});
  assert(!threw&&withheld&&(sent==std::vector<std::string>{"_WMP_SCRUB_HEAD T=0","_WMP_SCRUB_END"}));
 }
 // The ATTENTION send after the last CONFIRM throws in the stock sender: the
 // next command that leaves is END, COOL is not sent and probing is skipped.
 {ScrubRun t(data,0,{{0,0,0,1}},1);
  fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();const auto request=t.request();
  t.run_worker();t.until([&]{return ScrubRun::sent().size()>=2;});
  t.head(158,160,"heating");t.until([&]{return ScrubRun::sent().size()>=3;});
  t.r.gui_step();assert(t.state()==ScrubState::Scrub);
  ScrubRun::refused_hex()=ScrubRun::hex("_WMP_SCRUB_ATTENTION VALUE=0");
  t.tap("CONFIRM");t.until([&]{return ScrubRun::sent().size()>=4;});
  assert(t.state()==ScrubState::Cancelling&&!t.returned.load());
  t.r.gui_step();assert(t.label("Cancelling..."));
  t.head(28,0,"ended");t.until([&]{return t.returned.load();});
  // The refused send used sequence 3.
  assert((ScrubRun::sent()==std::vector<std::string>{ScrubRun::wrapped("G28",0,request),ScrubRun::wrapped("_WMP_SCRUB_HEAD T=0",1,request),
   ScrubRun::wrapped("_WMP_SCRUB_ATTENTION VALUE=1",2,request),ScrubRun::wrapped("_WMP_SCRUB_END",4,request)}));
  assert(t.withheld_rapid&&t.withheld_park);
 }
 // END is refused as well: the worker returns and the screen says the nozzle may be hot.
 {ScrubRun t(data,0,{{0,0,0,1}},1);
  fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();
  t.run_worker();t.until([&]{return ScrubRun::sent().size()>=2&&t.label("CANCEL");});
  ScrubRun::refused_hex()=ScrubRun::hex("_WMP_SCRUB_END");
  t.tap("CANCEL");t.until([&]{return t.returned.load();});
  assert(ScrubRun::sent().size()==2&&t.withheld_rapid&&t.withheld_park);
  t.r.gui_step();assert(t.label("Calibration stopped. Check the printer before trying again.")&&t.label("The nozzle may still be hot.")&&t.label("BACK"));
 }
}
void worker_released_when_status_stays_stale(const Json&data){
 ScrubRun t(data,0,{{0,0,0,1}},1);
 fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();const auto request=t.request();
 t.status();t.run_worker();t.until([&]{return ScrubRun::sent().size()>=2;});t.r.gui_step();
 // No status from here on. Nothing happens for 120 s.
 RuntimeReceiptTest::scrub_advance(t.r,t.clock->now,2001);t.r.gui_step();
 RuntimeReceiptTest::scrub_advance(t.r,t.clock->now,119000);t.r.gui_step();
 std::this_thread::sleep_for(std::chrono::milliseconds(300));
 assert(t.state()==ScrubState::Mounting&&!t.returned.load()&&ScrubRun::sent().size()==2);
 RuntimeReceiptTest::scrub_advance(t.r,t.clock->now,1000);
 t.until([&]{return ScrubRun::sent().size()>=3;});
 assert(ScrubRun::sent()[2]==ScrubRun::wrapped("_WMP_SCRUB_END",2,request)&&t.state()==ScrubState::Cancelling&&!t.returned.load());
 // END is never reported either: the worker is released 60 s later.
 RuntimeReceiptTest::scrub_advance(t.r,t.clock->now,59000);t.r.gui_step();
 std::this_thread::sleep_for(std::chrono::milliseconds(300));assert(!t.returned.load());
 RuntimeReceiptTest::scrub_advance(t.r,t.clock->now,1000);
 t.until([&]{return t.returned.load();});
 assert(t.withheld_rapid&&t.withheld_park&&ScrubRun::sent().size()==3);
 assert(!t.r.stock_calibration_reserved());
 t.r.gui_step();assert(t.label("Printer status was lost. Calibration stopped.")&&t.label("BACK"));
 t.tap("BACK");t.r.gui_step();assert(!t.panel()&&t.state()==ScrubState::Idle);
}
// The previous attempt failed in this Klipper session. Its failure stays in
// status until the backend admits the new attempt's first command, which is
// after the hook holds the worker.
void brush_retry_after_failed_attempt_runs_the_scrub(const Json&data){
 ScrubRun t(data,0,{{0,0,0,1}},1);
 const std::string old(32,'d');
 t.ready["nozzle_scrub"]={{"protocol",1},{"head",2},{"phase","failed"},{"target",160.0},{"error","Head 3 did not mount."},{"request",old}};
 t.ready["calibration_progress"]={{"protocol",1},{"head",-1},{"phase","idle"},{"request",old}};
 t.ready["calibration_failed"]="Command failed: _WMP_SCRUB_HEAD T=2";
 t.ready["calibration_attempt"]={{"protocol",1},{"session",std::string(32,'a')},{"request",old},{"state","failed"},{"error","Command failed: _WMP_SCRUB_HEAD T=2"},{"offsets","stopped"}};
 t.status();
 fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();
 assert(t.r.stock_calibration_reserved());const auto request=t.request();assert(request!=old);
 t.run_worker();t.until([&]{return ScrubRun::sent().size()>=2;});
 for(unsigned i=0;i<5;++i){t.r.gui_step();std::this_thread::sleep_for(std::chrono::milliseconds(20));}
 assert(t.state()==ScrubState::Mounting&&t.label("Mounting head 1...")&&!t.label("Head 3 did not mount."));
 assert(!t.returned.load()&&RuntimeReceiptTest::scrub_outcome(t.r)==ScrubOutcome::None);
 assert((ScrubRun::sent()==std::vector<std::string>{ScrubRun::wrapped("G28",0,request),ScrubRun::wrapped("_WMP_SCRUB_HEAD T=0",1,request)}));
 // The backend admits the homing: status is now about this request.
 t.ready["nozzle_scrub"]={{"protocol",1},{"head",-1},{"phase","idle"},{"target",160.0},{"error",""}};
 t.ready["calibration_progress"]={{"protocol",1},{"head",-1},{"phase","homing"}};
 t.ready["calibration_failed"]="";t.ready["calibration_active"]=true;
 t.ready["calibration_attempt"]={{"protocol",1},{"session",std::string(32,'a')},{"request",request},{"state","pending"},{"error",""},{"offsets","none"}};
 t.status();t.r.gui_step();assert(t.state()==ScrubState::Mounting&&!t.returned.load());
 t.head(100,160,"heating");t.until([&]{return t.state()==ScrubState::Heating;});
 t.head(158,160,"heating");t.until([&]{return ScrubRun::sent().size()>=3;});
 t.r.gui_step();assert(t.state()==ScrubState::Scrub&&t.label("Scrub the nozzle on head 1"));
 t.tap("CONFIRM");t.until([&]{return t.returned.load();});
 assert(!t.withheld_rapid&&!t.withheld_park);
 assert((ScrubRun::sent()==std::vector<std::string>{
  ScrubRun::wrapped("G28",0,request),ScrubRun::wrapped("_WMP_SCRUB_HEAD T=0",1,request),
  ScrubRun::wrapped("_WMP_SCRUB_ATTENTION VALUE=1",2,request),ScrubRun::wrapped("_WMP_SCRUB_ATTENTION VALUE=0",3,request),
  ScrubRun::wrapped("_WMP_SCRUB_COOL T=0",4,request),ScrubRun::wrapped("RAPID_MODE T=0",5,request),
  ScrubRun::wrapped("PARK_CURRENT_TOOL",6,request)}));
}
// A START event while the run is reserved leaves the flow and its binding alone.
void start_during_reserved_run_does_not_reopen_prepare(const Json&data){
 ScrubRun t(data,0,{{1,0,0,1}},1);
 fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();
 assert(t.r.stock_calibration_reserved()&&t.state()==ScrubState::StockChecks&&!t.panel());
 const auto request=t.request();
 // The mode selection reads Accurate again during the earlier stages.
 RuntimeReceiptTest::scrub_vendor(t.r,0,{{1,0,0,1}},1);
 fake::send(t.start,7);
 assert(ScrubRun::delegated()==1&&t.state()==ScrubState::StockChecks&&!t.label("How will the nozzles be cleaned?"));
 assert(t.r.stock_calibration_reserved()&&t.request()==request);
 t.r.gui_step();RuntimeReceiptTest::close_maintenance_notice(t.r);
 assert(t.state()==ScrubState::StockChecks);
 // The scrub is still bound to the run: the worker is held at the offset stage.
 t.status();t.run_worker();
 t.until([&]{return ScrubRun::sent().size()>=2&&t.label("CANCEL");});
 assert(t.state()==ScrubState::ReturnPrompt&&!t.returned.load());
 assert(ScrubRun::sent()[1]==ScrubRun::wrapped("_WMP_SCRUB_ATTENTION VALUE=1",1,request));
 t.tap("CANCEL");t.until([&]{return ScrubRun::sent().size()>=4;});
 t.ready["nozzle_scrub"]={{"protocol",1},{"head",-1},{"phase","ended"},{"target",160.0},{"error",""}};t.status();
 t.until([&]{return t.returned.load();});
}
// The offset stage ended early (docs/nozzle-scrub.md, mechanism A).
// Runs the scrub of a one-head offsets-only brush run up to Calibrate. The
// worker must already be running; five commands have been sent on return.
void scrub_to_calibrate(ScrubRun&t){
 t.until([&]{return ScrubRun::sent().size()>=2;});
 t.head(158,160,"heating");t.until([&]{return ScrubRun::sent().size()>=3;});
 t.r.gui_step();assert(t.state()==ScrubState::Scrub);
 t.tap("CONFIRM");t.until([&]{return ScrubRun::sent().size()>=5;});
 assert(t.state()==ScrubState::Calibrate);
}
void skip_outcome_withholds_rapid_and_park_sends(const Json&data){
 // Combined run cancelled on the return prompt: the worker's own save follows.
 ScrubRun t(data,0,{{1,0,0,1}},2);
 fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();const auto request=t.request();
 t.worker=std::thread([&]{
  t.r.run_stock_calibration_worker([&]{
   wmp_openace::forward_stock_command(offset_home,"G28");
   for(unsigned i=0;i<2;++i)wmp_openace::forward_stock_command(offset_rapid,"RAPID_MODE T="+std::to_string(i));
   wmp_openace::forward_stock_command(offset_park,"PARK_CURRENT_TOOL");
   wmp_openace::forward_stock_command(0x4b869c,"SAVE_CONFIG");
  });
  t.returned.store(true);
 });
 t.until([&]{return ScrubRun::sent().size()>=2&&t.label("CANCEL");});
 assert(t.state()==ScrubState::ReturnPrompt);
 t.tap("CANCEL");t.until([&]{return ScrubRun::sent().size()>=4;});
 assert(!t.returned.load()&&t.state()==ScrubState::Cancelling);
 t.ready["nozzle_scrub"]={{"phase","ended"},{"head",-1},{"target",160.0}};t.status();
 t.until([&]{return t.returned.load();});
 // The withheld sends used no sequence number: the save is the next stage.
 assert((ScrubRun::sent()==std::vector<std::string>{ScrubRun::wrapped("G28",0,request),
  ScrubRun::wrapped("_WMP_SCRUB_ATTENTION VALUE=1",1,request),ScrubRun::wrapped("_WMP_SCRUB_ATTENTION VALUE=0",2,request),
  ScrubRun::wrapped("_WMP_SCRUB_END",3,request),ScrubRun::wrapped("SAVE_CONFIG",4,request)}));
}
// A brush run whose first scrub command fails while the vendor byte is set.
// The worker stops after the scrub hook until released, then sends the
// probing and park commands. Records the byte after each send.
struct FailedScrub{
 ScrubRun t;std::atomic<bool>home_done{false},proceed{false};int after_rapid=-1,after_park=-1;std::string request;
 FailedScrub(const Json&data):t(data,0,{{1,0,0,1}},1){
  fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();request=t.request();
  t.worker=std::thread([this]{
   t.r.run_stock_calibration_worker([this]{
    RuntimeReceiptTest::scrub_failed_byte(t.r,1);
    wmp_openace::forward_stock_command(offset_home,"G28");home_done.store(true);
    while(!proceed.load())std::this_thread::sleep_for(std::chrono::milliseconds(1));
    wmp_openace::forward_stock_command(offset_rapid,"RAPID_MODE T=0");after_rapid=RuntimeReceiptTest::scrub_failed_byte(t.r);
    wmp_openace::forward_stock_command(offset_park,"PARK_CURRENT_TOOL");after_park=RuntimeReceiptTest::scrub_failed_byte(t.r);
   });
   t.returned.store(true);
  });
  t.until([&]{return ScrubRun::sent().size()>=2&&t.label("CONFIRM");});
  t.tap("CONFIRM");t.until([&]{return ScrubRun::sent().size()>=4;}); // G28, ATTENTION 1, ATTENTION 0, HEAD
 }
 // The backend latched the failure of the HEAD command.
 void fail(const Json&attempt){
  t.ready["nozzle_scrub"]={{"phase","failed"},{"head",0},{"target",160.0},{"error","Head 1 did not mount."}};
  t.ready["calibration_failed"]="Command failed: _WMP_SCRUB_HEAD T=0";
  if(!attempt.is_null())t.ready["calibration_attempt"]=attempt;
  t.status();t.until([&]{return home_done.load();});
  assert(RuntimeReceiptTest::scrub_outcome(t.r)==ScrubOutcome::Skip);
 }
 Json attempt(bool available)const{return {{"protocol",1},{"session",std::string(32,'a')},{"request",request},{"state","failed"},{"error","x"},{"offsets","stopped"},{"early_save_available",available}};}
 void finish(){proceed.store(true);t.until([&]{return t.returned.load();});
  // The probing and park sends are withheld whatever happens to the byte.
  assert(ScrubRun::sent().size()==4);}
};
void failed_byte_cleared_when_early_save_available(const Json&data){
 FailedScrub f(data);f.fail(f.attempt(true));f.finish();
 assert(f.after_rapid==1&&f.after_park==0);
}
void failed_byte_not_cleared_when_early_save_unavailable(const Json&data){
 // The backend will refuse the save: the vendor's own failure path must run.
 {FailedScrub f(data);f.fail(f.attempt(false));f.finish();assert(f.after_rapid==1&&f.after_park==1);}
 // No attempt status, or a backend that does not report the key.
 {FailedScrub f(data);f.fail(Json());f.finish();assert(f.after_park==1);}
 {FailedScrub f(data);auto attempt=f.attempt(true);attempt.erase("early_save_available");f.fail(attempt);f.finish();assert(f.after_park==1);}
 // The attempt of another request.
 {FailedScrub f(data);auto attempt=f.attempt(true);attempt["request"]=std::string(32,'d');f.fail(attempt);f.finish();assert(f.after_park==1);}
 {FailedScrub f(data);auto attempt=f.attempt(true);attempt["session"]=std::string(32,'b');f.fail(attempt);f.finish();assert(f.after_park==1);}
 // Status that is no longer fresh at the park send.
 {FailedScrub f(data);f.fail(f.attempt(true));RuntimeReceiptTest::scrub_advance(f.t.r,f.t.clock->now,2001);f.finish();assert(f.after_park==1);}
 // A cancelled scrub with the byte set by an unrelated error: not cleared.
 {ScrubRun t(data,0,{{0,0,0,1}},1);
  fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();
  int after_park=-1;
  t.worker=std::thread([&]{
   t.r.run_stock_calibration_worker([&]{
    RuntimeReceiptTest::scrub_failed_byte(t.r,1);
    wmp_openace::forward_stock_command(offset_home,"G28");
    wmp_openace::forward_stock_command(offset_rapid,"RAPID_MODE T=0");
    wmp_openace::forward_stock_command(offset_park,"PARK_CURRENT_TOOL");after_park=RuntimeReceiptTest::scrub_failed_byte(t.r);
   });
   t.returned.store(true);
  });
  t.until([&]{return ScrubRun::sent().size()>=2&&t.label("CANCEL");});
  t.tap("CANCEL");t.until([&]{return ScrubRun::sent().size()>=3;});
  t.head(28,0,"ended");t.until([&]{return t.returned.load();});
  assert(after_park==1&&ScrubRun::sent().size()==3);
 }
}
void failed_byte_cleared_at_park_only_when_skipping(const Json&data){
 // The scrub completed and nothing failed: both sends are forwarded and the byte is not written.
 {ScrubRun t(data,0,{{0,0,0,1}},1);
  fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();const auto request=t.request();
  RuntimeReceiptTest::scrub_failed_byte(t.r,0);
  t.run_worker();scrub_to_calibrate(t);t.until([&]{return t.returned.load();});
  assert(!t.withheld_rapid&&!t.withheld_park&&RuntimeReceiptTest::scrub_failed_byte(t.r)==0);
  assert(ScrubRun::sent().size()==7&&ScrubRun::sent()[6]==ScrubRun::wrapped("PARK_CURRENT_TOOL",6,request));
 }
 // The vendor byte is set but the backend latched no failure: after a bounded
 // wait the park is forwarded and the byte is left for the vendor worker.
 {ScrubRun t(data,0,{{0,0,0,1}},1);
  fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();const auto request=t.request();
  RuntimeReceiptTest::scrub_failure_wait(t.r,50);
  t.worker=std::thread([&]{
   t.r.run_stock_calibration_worker([&]{
    wmp_openace::forward_stock_command(offset_home,"G28");
    wmp_openace::forward_stock_command(offset_rapid,"RAPID_MODE T=0");
    RuntimeReceiptTest::scrub_failed_byte(t.r,1);
    wmp_openace::forward_stock_command(offset_park,"PARK_CURRENT_TOOL");
   });
   t.returned.store(true);
  });
  scrub_to_calibrate(t);t.until([&]{return t.returned.load();});
  assert(RuntimeReceiptTest::scrub_failed_byte(t.r)==1&&RuntimeReceiptTest::scrub_outcome(t.r)==ScrubOutcome::Proceed);
  assert(ScrubRun::sent().size()==7&&ScrubRun::sent()[6]==ScrubRun::wrapped("PARK_CURRENT_TOOL",6,request));
 }
 // Probing failure: the vendor byte is set before status reports the latched
 // failure. The park send waits for it, is withheld and clears the byte.
 {ScrubRun t(data,0,{{1,0,0,1}},2);
  fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();const auto request=t.request();
  std::atomic<bool>probing{false},parking{false};
  t.worker=std::thread([&]{
   t.r.run_stock_calibration_worker([&]{
    wmp_openace::forward_stock_command(offset_home,"G28");
    wmp_openace::forward_stock_command(offset_rapid,"RAPID_MODE T=0");
    probing.store(true);
    // The vendor loop ends when the failed byte is set: no send for head 2.
    while(RuntimeReceiptTest::scrub_failed_byte(t.r)!=1)std::this_thread::sleep_for(std::chrono::milliseconds(1));
    parking.store(true);
    wmp_openace::forward_stock_command(offset_park,"PARK_CURRENT_TOOL");
    wmp_openace::forward_stock_command(0x4b869c,"SAVE_CONFIG");
   });
   t.returned.store(true);
  });
  t.until([&]{return ScrubRun::sent().size()>=2&&t.label("CONFIRM");});
  t.tap("CONFIRM");t.until([&]{return t.state()==ScrubState::Mounting;});
  for(unsigned head=0;head<2;++head){
   for(auto&h:t.ready["heads"])if(h.value("id","")=="h"+std::to_string(head)){h["actual"]=158;h["target"]=160;}
   t.ready["nozzle_scrub"]={{"phase","heating"},{"head",head},{"target",160.0}};t.status();
   t.until([&]{return t.state()==ScrubState::Scrub;});t.r.gui_step();
   t.tap("CONFIRM");t.until([&]{return t.state()!=ScrubState::Scrub;});
  }
  t.until([&]{return probing.load();});
  assert(t.state()==ScrubState::Calibrate&&RuntimeReceiptTest::scrub_outcome(t.r)==ScrubOutcome::Proceed);
  const auto before=ScrubRun::sent();
  assert(before.back().find("HEX="+ScrubRun::hex("RAPID_MODE T=0")+" ")!=std::string::npos);
  RuntimeReceiptTest::scrub_failed_byte(t.r,1);
  while(!parking.load())std::this_thread::sleep_for(std::chrono::milliseconds(1));
  std::this_thread::sleep_for(std::chrono::milliseconds(100));t.r.gui_step();
  assert(!t.returned.load()&&ScrubRun::sent()==before); // held at the park send
  t.ready["calibration_failed"]="Calibration head changed or tool change failed: fail_flag=-2";
  t.ready["calibration_attempt"]={{"protocol",1},{"session",std::string(32,'a')},{"request",request},{"state","failed"},{"error","x"},{"offsets","stopped"},{"early_save_available",true}};t.status();
  t.until([&]{return t.returned.load();});
  assert(RuntimeReceiptTest::scrub_outcome(t.r)==ScrubOutcome::Skip&&RuntimeReceiptTest::scrub_failed_byte(t.r)==0);
  const auto sent=ScrubRun::sent();
  assert(sent.size()==before.size()+1&&sent.back().find("HEX="+ScrubRun::hex("SAVE_CONFIG")+" ")!=std::string::npos);
 }
 // A run without a brush scrub is untouched: no wait, no write, park forwarded.
 {ScrubRun t(data,1,{{0,0,0,1}},1);
  fake::send(t.start,7);assert(ScrubRun::delegated()==1&&t.r.stock_calibration_reserved());
  RuntimeReceiptTest::scrub_failed_byte(t.r,1);
  t.run_worker();t.until([&]{return t.returned.load();});
  assert(!t.withheld_rapid&&!t.withheld_park&&RuntimeReceiptTest::scrub_failed_byte(t.r)==1&&ScrubRun::sent().size()==3);
 }
}
// The saving text and the start of every text shown after the save's restart
// (the unified result layout).
const std::string kSaving="Saving calibration settings...\nRestarting Klipper...",kRestarted="Restarting Klipper... Done.\n";
// Result screen after the offset stage stopped.
struct ResultPanel{
 StockCalibrationStatus view;fake::Node*page;const std::string session=std::string(32,'a'),next=std::string(32,'b'),request=std::string(32,'c');Json state;
 ResultPanel():page(fake::make(fake::screen)){
  view.created(page);view.begin(session,request);
  state={{"fresh",true},{"calibration_session",session},{"calibration_failed",""},{"maintenance_save_requested",false},{"calibration_attempt_protocol",1},
   {"calibration_attempt",{{"protocol",1},{"session",session},{"request",request},{"state","pending"},{"error",""},{"offsets","none"}}},
   {"calibration_progress",{{"protocol",1},{"head",-1},{"phase","idle"},{"request",request}}},
   {"maintenance_scrub_heads",4}}; // a wire-brush run; other runs set 0
 }
 ~ResultPanel(){fake::del(page);}
 void progress(int head,const char*phase){state["calibration_progress"]={{"protocol",1},{"head",head},{"phase",phase},{"request",request}};}
 bool under(const fake::Node*n)const{for(auto*p=n->parent;p;p=p->parent)if(p==page)return true;return false;}
 bool shows(const std::string&text){view.update(state);for(auto&n:fake::nodes)if(n->live&&n->text==text&&under(n.get()))return true;return false;}
 bool mentions(const std::string&part){view.update(state);for(auto&n:fake::nodes)if(n->live&&n->text.find(part)!=std::string::npos&&under(n.get()))return true;return false;}
 bool empty(){view.update(state);return page->children.empty();}
 void stop(const std::string&failure={}){state["calibration_attempt"]["offsets"]="stopped";state["calibration_failed"]=failure;
  if(!failure.empty()){state["calibration_attempt"]["state"]="failed";state["calibration_attempt"]["error"]=failure;}}
 void saved(){state["maintenance_save_requested"]=true;assert(shows(kSaving));
  // Klipper restarted: a new session, no attempt, and the durable receipt.
  state["calibration_session"]=next;state["calibration_failed"]="";state["calibration_attempt"]=Json::object();
  state["calibration_save_result"]={{"protocol",1},{"session",session},{"request",request},{"state","confirmed"},{"error",""}};}
};
const char*const kCheck="\n\nCheck the printer before trying again.";
void result_text_offsets_stopped_saved(){
 const std::string saved=kRestarted+"Offset calibration stopped. Earlier results were saved.";
 // Scrub cancelled on a combined run.
 {ResultPanel p;assert(p.empty());p.stop();p.saved();assert(p.shows(saved));}
 // Scrub failure: the raw failure text is not shown and the printer is to be checked.
 {ResultPanel p;p.stop("Command failed: _WMP_SCRUB_HEAD T=1 mount failed");
  assert(p.shows(std::string("Offset calibration stopped. Offsets are unchanged.")+kCheck));
  p.saved();assert(p.shows(saved+kCheck)&&!p.mentions("_WMP"));}
 // Probing failure: offsets of earlier heads may have been stored, so the
 // existing failure text stays until the save is confirmed.
 {ResultPanel p;p.state["calibration_progress"]["head"]=1;p.state["calibration_progress"]["phase"]="position";assert(p.empty());
  p.progress(-1,"idle");p.stop("Tool change failed during calibration: fail_flag=-2");
  assert(p.mentions("Calibration stopped.\n\nTool change failed during calibration: fail_flag=-2")&&!p.mentions("unchanged"));
  p.saved();assert(p.shows(saved+kCheck));}
 // A restart after the save without a confirmed receipt: the save is not verified.
 {ResultPanel p;p.stop();p.saved();p.state["calibration_save_result"]["state"]="unconfirmed";
  assert(p.mentions(kRestarted+"Saved calibration settings could not be verified.")&&!p.mentions("Earlier results"));}
}
// The header action reads DONE on a result and BACK while the page waits for
// status or for the save; stale status after a save request keeps the saving text.
void result_action_done_on_results(){
 {ResultPanel p;p.stop();p.state["maintenance_save_requested"]=true;assert(p.shows(kSaving)&&p.mentions("BACK")&&!p.mentions("DONE"));
  p.state["fresh"]=false;p.state["maintenance_save_requested"]=false;assert(p.shows(kSaving));
  p.state["fresh"]=true;p.state["maintenance_save_requested"]=true;
  p.saved();assert(p.shows(kRestarted+"Offset calibration stopped. Earlier results were saved.")&&p.mentions("DONE")&&!p.mentions("BACK"));}
 {ResultPanel p;p.state["fresh"]=false;assert(p.shows("Waiting for printer status...")&&p.mentions("BACK")&&!p.mentions("DONE"));}
 // A result while the vendor worker still runs (a save may follow) keeps BACK;
 // DONE once the worker has returned. Without the key the worker is taken as returned.
 {ResultPanel p;p.stop();p.state["maintenance_worker_returned"]=false;
  assert(p.shows("Offset calibration stopped. Offsets are unchanged.")&&p.mentions("BACK")&&!p.mentions("DONE"));
  p.state["maintenance_worker_returned"]=true;assert(p.mentions("DONE")&&!p.mentions("BACK"));
  p.state.erase("maintenance_worker_returned");assert(p.mentions("DONE")&&!p.mentions("BACK"));}
}
void result_text_offsets_stopped_nothing_saved(){
 const std::string unchanged="Offset calibration stopped. Offsets are unchanged.";
 // Scrub cancelled on an offsets-only run: the worker sends no save.
 {ResultPanel p;p.stop();assert(p.shows(unchanged));}
 // Stale status and the attempt of another run decide nothing.
 {ResultPanel p;p.stop();p.state["fresh"]=false;assert(!p.mentions("Offset calibration stopped"));}
 {ResultPanel p;p.stop();p.state["calibration_attempt"]["request"]=std::string(32,'d');assert(p.empty());}
 // Only the three protocol values are projected.
 Json attempt={{"protocol",1},{"session",std::string(32,'a')},{"request",std::string(32,'c')},{"state","failed"},{"error","x"},
  {"next",3},{"earlier_results",true},{"offset_stage",true}};
 for(const auto*value:{"none","measured","stopped"}){
  attempt["offsets"]=value;const auto projected=calibration_attempt_result(attempt);
  assert(projected.size()==6&&projected["offsets"]==value);
 }
 // early_save_available is projected only as a boolean; anything else reads as false.
 for(const bool value:{true,false}){
  attempt["offsets"]="stopped";attempt["early_save_available"]=value;const auto projected=calibration_attempt_result(attempt);
  assert(projected.size()==7&&projected["early_save_available"].is_boolean()&&projected.value("early_save_available",!value)==value);
 }
 for(const auto&bad:{Json(1),Json("true"),Json(),Json::object()}){
  attempt["early_save_available"]=bad;const auto projected=calibration_attempt_result(attempt);
  assert(!projected.contains("early_save_available")&&!projected.value("early_save_available",false));
 }
 attempt.erase("early_save_available");
 for(const auto&bad:{Json("other"),Json(1),Json()}){attempt["offsets"]=bad;assert(!calibration_attempt_result(attempt).contains("offsets"));}
}
void successful_run_text_unchanged(){
 for(const auto*offsets:{"none","measured"}){
  ResultPanel p;p.state["calibration_attempt"]["offsets"]=offsets;assert(p.empty());
  p.saved();assert(p.shows(kRestarted+"Calibration settings saved."));
 }
 // A failure outside the offset stage keeps the existing text and never confirms.
 ResultPanel p;p.state["calibration_failed"]="PID failed";p.state["calibration_attempt"]["state"]="failed";p.state["calibration_attempt"]["error"]="PID failed";
 assert(p.mentions("Calibration stopped.\n\nPID failed\n\nInspect the printer before retrying."));
 p.state["calibration_session"]=p.next;p.state["calibration_failed"]="";
 p.state["calibration_save_result"]={{"protocol",1},{"session",p.session},{"request",p.request},{"state","confirmed"},{"error",""}};
 assert(p.mentions("Printer restarted. Calibration result could not be confirmed.")&&!p.mentions("saved."));
}
// A stopped brush run whose save was refused or failed: no restart follows.
void stopped_run_with_refused_save_shows_failure_not_saving(){
 const std::string unchanged="Offset calibration stopped. Offsets are unchanged. Earlier results were not saved.";
 const std::string gate="Restart not admitted: Finish or stop calibration before restarting";
 const auto refuse=[&](ResultPanel&p){p.state["calibration_save_result"]={{"protocol",1},{"session",p.session},{"request",p.request},{"state","unconfirmed"},{"error",gate}};};
 // Scrub failure, early save refused.
 {ResultPanel p;p.stop("Command failed: _WMP_SCRUB_HEAD T=1 mount failed");p.state["maintenance_save_requested"]=true;
  assert(p.shows(kSaving));
  refuse(p);assert(p.shows(unchanged+kCheck)&&!p.mentions(kSaving)&&p.view.result_shown());}
 // Scrub cancelled on a combined run, ordinary save refused: the attempt fails with the save's error.
 {ResultPanel p;p.stop();p.state["maintenance_save_requested"]=true;assert(p.shows(kSaving));
  refuse(p);assert(p.shows(unchanged+kCheck)&&!p.mentions(kSaving));
  p.state["calibration_attempt"]["state"]="failed";p.state["calibration_attempt"]["error"]=gate;p.state["calibration_failed"]=gate;
  assert(p.shows(unchanged+kCheck)&&!p.mentions(kSaving));}
 // Probing failure, early save refused: the failure text with the attempt's error.
 {ResultPanel p;p.progress(1,"position");assert(p.empty());
  p.progress(-1,"idle");p.stop("Tool change failed during calibration: fail_flag=-2");p.state["maintenance_save_requested"]=true;
  assert(p.shows(kSaving));
  refuse(p);assert(p.shows("Calibration stopped.\n\nTool change failed during calibration: fail_flag=-2\n\nInspect the printer before retrying."));}
 // Probing had started and no failure of the attempt was seen: the save's own error is the reason.
 {ResultPanel p;p.progress(1,"position");assert(p.empty());p.progress(-1,"idle");p.stop();p.state["maintenance_save_requested"]=true;
  refuse(p);assert(p.shows("Calibration stopped.\n\n"+gate+"\n\nInspect the printer before retrying."));}
}
void stopped_run_with_pending_save_keeps_saving(){
 for(const auto*value:{"pending","saved"}){
  ResultPanel p;p.stop("Command failed: _WMP_SCRUB_HEAD T=1 mount failed");p.state["maintenance_save_requested"]=true;
  p.state["calibration_save_result"]={{"protocol",1},{"session",p.session},{"request",p.request},{"state",value},{"error",""}};
  assert(p.shows(kSaving));
 }
 // No result yet, and the result of another request, decide nothing.
 {ResultPanel p;p.stop();p.state["maintenance_save_requested"]=true;
  p.state["calibration_save_result"]={{"protocol",1},{"session",""},{"request",""},{"state","unconfirmed"},{"error",""}};
  assert(p.shows(kSaving));
  p.state["calibration_save_result"]={{"protocol",1},{"session",p.session},{"request",p.request},{"state","unconfirmed"},{"error",""}};
  assert(p.shows(kSaving));
  p.state["calibration_save_result"]={{"protocol",1},{"session",p.session},{"request",std::string(32,'d')},{"state","unconfirmed"},{"error","x"}};
  assert(p.shows(kSaving));}
}
// Printed blob and Rapid runs have no scrub: the stock result texts, with the backend's reason.
void other_run_failure_shows_upstream_text(const Json&data,bool blob){
 const std::string reason=blob?"Command failed: NOZZLE_PREPARE S=160 T=1":"Command failed: RAPID_MODE T=0";
 const std::string stopped="Calibration stopped.\n\n"+reason+"\n\nInspect the printer before retrying.";
 for(const bool keyed:{true,false}){
  ResultPanel p;if(keyed)p.state["maintenance_scrub_heads"]=0;else p.state.erase("maintenance_scrub_heads");
  p.stop(reason);assert(p.shows(stopped)&&!p.mentions("Offset calibration stopped"));
  // The failure text ranks above a requested save, as upstream.
  p.state["maintenance_save_requested"]=true;assert(p.shows(stopped));
  p.state["calibration_save_result"]={{"protocol",1},{"session",p.session},{"request",p.request},{"state","unconfirmed"},{"error","x"}};assert(p.shows(stopped));
  // A restart, even with a confirmed receipt, reports the failure as upstream does.
  p.state["calibration_session"]=p.next;p.state["calibration_failed"]="";p.state["calibration_attempt"]=Json::object();
  p.state["calibration_save_result"]["state"]="confirmed";p.state["calibration_save_result"]["error"]="";
  assert(p.shows(kRestarted+"Saved calibration settings could not be verified.\nCheck the saved settings before retrying.\n\nPrevious error: "+reason)&&!p.mentions("Earlier results"));
 }
 // A stopped stage without a failure shows nothing of its own.
 {ResultPanel p;p.state["maintenance_scrub_heads"]=0;p.stop();assert(p.empty());
  p.state["maintenance_save_requested"]=true;assert(p.shows(kSaving));}
 // Runtime: the run started from Maintenance START.
 ScrubRun t(data,blob?0:1,{{0,0,0,1}},1);
 fake::send(t.start,7);
 if(blob){t.tap("Printed blob");t.r.gui_step();t.tap("CONFIRM");t.r.gui_step();}
 assert(ScrubRun::delegated()==1);
 auto*result=fake::make(fake::screen);t.r.stock_calibration_created(result);
 const auto shown=[&](const std::string&text){t.r.update_stock_calibration();
  for(auto&n:fake::nodes)if(n->live&&n->text==text)for(auto*q=n->parent;q;q=q->parent)if(q==result)return true;
  return false;};
 t.ready["calibration_attempt"]={{"protocol",1},{"session",std::string(32,'a')},{"request",t.request()},{"state","failed"},{"error",reason},{"offsets","stopped"}};
 t.ready["calibration_failed"]=reason;t.ready["printer_state"]="ready";t.status();
 assert(shown(stopped));
 t.r.stock_calibration_created(nullptr);fake::del(result);
}
void blob_run_failure_shows_upstream_text_with_reason(const Json&data){other_run_failure_shows_upstream_text(data,true);}
void rapid_run_failure_shows_upstream_text_with_reason(const Json&data){other_run_failure_shows_upstream_text(data,false);}
// The "Cancelling..." screen of a cancelled combined run goes once the result
// page shows an outcome; it does not stay through the save and the restart.
void finished_screen_is_dismissed_when_result_is_shown(const Json&data){
 ScrubRun t(data,0,{{1,0,0,1}},2);std::atomic<bool>save{false};
 fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();const auto request=t.request();
 t.worker=std::thread([&]{
  t.r.run_stock_calibration_worker([&]{
   wmp_openace::forward_stock_command(offset_home,"G28");
   for(unsigned i=0;i<2;++i)wmp_openace::forward_stock_command(offset_rapid,"RAPID_MODE T="+std::to_string(i));
   wmp_openace::forward_stock_command(offset_park,"PARK_CURRENT_TOOL");
   while(!save.load())std::this_thread::sleep_for(std::chrono::milliseconds(1));
   wmp_openace::forward_stock_command(0x4b869c,"SAVE_CONFIG");
  });
  t.returned.store(true);
 });
 t.until([&]{return ScrubRun::sent().size()>=2&&t.label("CANCEL");});
 t.tap("CANCEL");t.until([&]{return ScrubRun::sent().size()>=4;});
 t.ready["nozzle_scrub"]={{"phase","ended"},{"head",-1},{"target",160.0}};t.status();
 t.until([&]{return t.state()==ScrubState::Finished;});
 // No result yet: the screen stays.
 auto*result=fake::make(fake::screen);t.r.stock_calibration_created(result);
 t.r.gui_step();assert(t.label("Cancelling...")&&!t.returned.load());
 t.ready["calibration_attempt"]={{"protocol",1},{"session",std::string(32,'a')},{"request",request},{"state","pending"},{"error",""},{"offsets","stopped"}};
 t.ready["printer_state"]="ready";t.status();t.r.update_stock_calibration();
 bool outcome=false;
 for(auto&n:fake::nodes)if(n->live&&n->text=="Offset calibration stopped. Offsets are unchanged.")for(auto*q=n->parent;q;q=q->parent)if(q==result)outcome=true;
 assert(outcome&&t.label("Cancelling..."));
 t.r.gui_step();assert(!t.returned.load()&&t.state()==ScrubState::Finished);
 assert(!t.label("Cancelling..."));
 // It is not drawn again while the worker goes on to its save.
 t.r.gui_step();assert(!t.label("Cancelling..."));
 save.store(true);t.until([&]{return t.returned.load();});
 t.r.gui_step();assert(!t.panel()||!t.label("Cancelling..."));
 t.r.stock_calibration_created(nullptr);fake::del(result);
}
// An offsets-only run sends no SAVE_CONFIG: the probing macros store the offsets.
// The result is reported for a wire-brush run whose probing reached the last head.
struct BrushResult:ResultPanel{
 BrushResult(unsigned heads=4,int reached=3){
  state["calibration_attempt"]["offsets"]="measured";state["maintenance_scrub_heads"]=heads;
  progress(reached,"docking");
 }
};
const char*const kOffsetsSaved="Nozzle offsets saved.";
void result_text_offsets_only_success(const Json&data){
 const std::string saved=kOffsetsSaved;
 // Shown only after the worker has returned.
 {BrushResult p;assert(p.empty());
  p.state["maintenance_worker_returned"]=true;assert(p.shows(saved)&&!p.mentions(kSaving));
  // The result stays while status is stale.
  p.state["fresh"]=false;assert(p.shows(saved));}
 // Another run's attempt, a stopped stage and a failure do not report success.
 {BrushResult p;p.state["maintenance_worker_returned"]=true;p.state["calibration_attempt"]["request"]=std::string(32,'d');assert(p.empty());}
 {BrushResult p;p.state["maintenance_worker_returned"]=true;p.stop();assert(!p.mentions(saved));}
 {BrushResult p;p.state["maintenance_worker_returned"]=true;
  p.state["calibration_failed"]="RAPID_MODE failed";p.state["calibration_attempt"]["state"]="failed";p.state["calibration_attempt"]["error"]="RAPID_MODE failed";
  assert(p.mentions("Calibration stopped.")&&!p.mentions(saved));}
 // A run that also sends SAVE_CONFIG keeps the existing texts.
 {BrushResult p;p.state["maintenance_worker_returned"]=true;p.saved();assert(p.shows(kRestarted+"Calibration settings saved."));}
 // Runtime: the worker of an offsets-only brush run returns without a save.
 {ScrubRun t(data,0,{{0,0,0,1}},1);
  fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();
  auto*result=fake::make(fake::screen);t.r.stock_calibration_created(result);
  const auto shown=[&](const std::string&text){t.r.update_stock_calibration();
   for(auto&n:fake::nodes)if(n->live&&n->text==text)for(auto*q=n->parent;q;q=q->parent)if(q==result)return true;
   return false;};
  t.run_worker();t.until([&]{return t.state()==ScrubState::Mounting;});
  t.head(25,160,"heating");t.until([&]{return t.state()==ScrubState::Heating;});
  t.head(158,160,"heating");t.until([&]{return t.state()==ScrubState::Scrub;});
  t.ready["calibration_attempt"]={{"protocol",1},{"session",std::string(32,'a')},{"request",t.request()},{"state","pending"},{"error",""},{"offsets","measured"}};
  t.ready["calibration_progress"]={{"protocol",1},{"head",0},{"phase","docking"}};
  t.ready["printer_state"]="ready";t.status();assert(!shown(saved)); // the worker is still held
  t.tap("CONFIRM");t.until([&]{return t.returned.load();});
  assert(shown(saved)&&!shown(kSaving));
  // The next run is not a brush run: nothing carries over.
  t.r.stock_calibration_created(nullptr);fake::del(result);
 }
}
// Rapid Alignment Mode and Printed blob runs keep the stock completion page.
void result_text_unchanged_for_rapid_mode_run(const Json&data){
 {BrushResult p(0);p.state["maintenance_worker_returned"]=true;assert(p.empty());}
 {BrushResult p;p.state.erase("maintenance_scrub_heads");p.state["maintenance_worker_returned"]=true;assert(p.empty());}
 for(const unsigned char rapid:{1,0}){
  ScrubRun t(data,rapid,{{0,0,0,1}},1);
  fake::send(t.start,7);
  if(!rapid){t.tap("Printed blob");t.r.gui_step();t.tap("CONFIRM");t.r.gui_step();}
  assert(ScrubRun::delegated()==1);
  auto*result=fake::make(fake::screen);t.r.stock_calibration_created(result);
  t.ready["calibration_attempt"]={{"protocol",1},{"session",std::string(32,'a')},{"request",t.request()},{"state","pending"},{"error",""},{"offsets","measured"}};
  t.ready["calibration_progress"]={{"protocol",1},{"head",0},{"phase","docking"}};
  t.ready["printer_state"]="ready";t.status();
  t.run_worker();t.until([&]{return t.returned.load();});
  t.r.gui_step();t.r.update_stock_calibration();assert(result->children.empty());
  t.r.stock_calibration_created(nullptr);fake::del(result);
 }
}
// Probing that did not reach the last head reports nothing.
void result_text_not_shown_when_probing_stopped_early(){
 for(const int reached:{-1,0,2}){BrushResult p(4,reached);p.state["maintenance_worker_returned"]=true;assert(p.empty());}
 // The last head is remembered once seen.
 {BrushResult p(4,3);assert(p.empty());p.progress(-1,"idle");
  p.state["maintenance_worker_returned"]=true;assert(p.shows(kOffsetsSaved));}
 // Progress published for another request says nothing about this run.
 {BrushResult p(4,3);p.state["calibration_progress"]["request"]=std::string(32,'d');p.state["maintenance_worker_returned"]=true;assert(p.empty());}
 {BrushResult p(4,3);p.state["calibration_progress"]["request"]="";p.state["maintenance_worker_returned"]=true;assert(p.empty());}
 // The same binding decides whether probing had started.
 {ResultPanel p;p.progress(1,"position");p.state["calibration_progress"]["request"]=std::string(32,'d');assert(p.empty());
  p.progress(-1,"idle");p.stop();assert(p.shows("Offset calibration stopped. Offsets are unchanged."));}
 // Offsets not reported as measured.
 {BrushResult p;p.state["calibration_attempt"]["offsets"]="none";p.state["maintenance_worker_returned"]=true;assert(p.empty());}
}
// The last head is complete only when the vendor's final park was admitted
// (progress phase "docking"). Reaching it is not enough.
void result_text_not_shown_when_last_head_fails_after_mounting(){
 for(const auto*phase:{"mounting","position","height"}){
  BrushResult p(4,3);p.progress(3,phase);p.state["maintenance_worker_returned"]=true;assert(p.empty());
  // The backend resets progress when the attempt stops.
  p.progress(-1,"idle");assert(p.empty());
 }
 // An earlier head's park phase is not the last head's.
 {BrushResult p(4,2);p.state["maintenance_worker_returned"]=true;assert(p.empty());}
 {BrushResult p(4,3);p.progress(3,"height");assert(p.empty());p.progress(3,"docking");assert(p.empty());
  p.state["maintenance_worker_returned"]=true;assert(p.shows(kOffsetsSaved));}
}
// Re-check outcome on the result page. The native facts of this run's scrub
// (flagged heads, Save anyway, Cancel, restore outcome) are kept across the
// save's restart; progress measured lists the heads with a completed measurement.
struct RecheckResult:BrushResult{
 RecheckResult(int reached=3,const Json&measured=Json::array({0,1,2,3})):BrushResult(4,reached){
  state["calibration_progress"]["measured"]=measured;state["calibration_progress"]["measuring"]=false;
  state["maintenance_flagged_heads"]=Json::array();state["maintenance_saved_anyway"]=false;
  state["maintenance_recheck_cancelled"]=false;state["maintenance_restore_failed"]=false;
 }
 void save_anyway(const Json&flagged){state["maintenance_saved_anyway"]=true;state["maintenance_flagged_heads"]=flagged;}
 // Cancel: the backend reports the offsets as stopped with the attempt pending.
 void cancelled(bool restore_failed=false){
  state["calibration_attempt"]["offsets"]="stopped";
  state["maintenance_recheck_cancelled"]=true;state["maintenance_restore_failed"]=restore_failed;
 }
};
// The save request is latched from the local flag whatever the status
// freshness or session: a stale moment at the save does not show an
// offsets-only result, and a restart after it reports the save.
void result_save_latched_from_the_local_flag(){
 {RecheckResult p;p.cancelled();p.state["fresh"]=false;p.state["maintenance_save_requested"]=true;p.state["maintenance_worker_returned"]=true;
  assert(p.shows(kSaving)&&!p.mentions("Offsets are unchanged"));
  // The restart; the receipt is not confirmed.
  p.state["fresh"]=true;p.state["maintenance_save_requested"]=false;p.state["calibration_session"]=p.next;p.state["calibration_attempt"]=Json::object();
  assert(p.mentions(kRestarted+"Saved calibration settings could not be verified."));}
 // Fresh status of another session with the local flag set also latches it.
 {ResultPanel p;p.state["calibration_session"]=p.next;p.state["maintenance_save_requested"]=true;p.view.update(p.state);
  p.state["maintenance_save_requested"]=false;assert(p.mentions(kRestarted+"Saved calibration settings could not be verified."));}
}
void result_text_save_anyway_names_flagged_heads(){
 // Offsets-only run.
 for(const auto&c:std::vector<std::pair<Json,std::string>>{{Json::array({1}),"Head 2"},{Json::array({1,3}),"Heads 2 and 4"},{Json::array({0,1,3}),"Heads 1, 2 and 4"}}){
  RecheckResult p;p.save_anyway(c.first);assert(p.empty());
  p.state["maintenance_worker_returned"]=true;assert(p.shows("Nozzle offsets saved. "+c.second+" may not be clean.")&&p.view.result_shown());
 }
 // Combined run: the save is confirmed after the restart.
 {RecheckResult p;p.save_anyway(Json::array({1}));p.state["maintenance_worker_returned"]=true;p.saved();
  assert(p.shows(kRestarted+"Calibration settings saved. Head 2 may not be clean."));}
 {RecheckResult p;p.save_anyway(Json::array({1,3}));p.state["maintenance_worker_returned"]=true;p.saved();
  assert(p.shows(kRestarted+"Calibration settings saved. Heads 2 and 4 may not be clean."));}
 // No flagged head named: the plain texts.
 {RecheckResult p;p.save_anyway(Json::array());p.state["maintenance_worker_returned"]=true;assert(p.shows(kOffsetsSaved));}
 {RecheckResult p;p.state["maintenance_flagged_heads"]=Json::array({1});p.state["maintenance_worker_returned"]=true;assert(p.shows(kOffsetsSaved));}
 // Other runs carry no re-check facts.
 {RecheckResult p;p.save_anyway(Json::array({1}));p.state["maintenance_scrub_heads"]=0;p.state["maintenance_worker_returned"]=true;p.saved();
  assert(p.shows(kRestarted+"Calibration settings saved."));}
}
void result_text_recheck_cancelled(){
 const std::string unchanged="Offset calibration cancelled. Offsets are unchanged.",restore="Offsets could not be restored. Run the calibration again.";
 // Offsets-only run: shown once the worker has returned.
 for(const bool failed:{false,true}){
  RecheckResult p;p.cancelled(failed);assert(!p.mentions("cancelled")&&!p.mentions("restored"));
  p.state["maintenance_worker_returned"]=true;assert(p.shows(failed?restore:unchanged)&&p.view.result_shown());
  // The result stays while status is stale.
  p.state["fresh"]=false;assert(p.shows(failed?restore:unchanged));
 }
 // Combined run: saving, then the confirmed save.
 {RecheckResult p;p.cancelled();p.saved();assert(p.shows(kRestarted+"Offset calibration cancelled. Earlier results were saved."));}
 {RecheckResult p;p.cancelled(true);p.saved();assert(p.shows(kRestarted+"Earlier results were saved. "+restore));}
 // A restart after the save without a confirmed receipt: the save is not verified.
 {RecheckResult p;p.cancelled();p.saved();p.state["calibration_save_result"]["state"]="unconfirmed";
  assert(p.mentions(kRestarted+"Saved calibration settings could not be verified.")&&!p.mentions("cancelled"));}
 {RecheckResult p;p.cancelled(true);p.saved();p.state["calibration_save_result"]["state"]="unconfirmed";
  assert(p.shows(kRestarted+"Saved calibration settings could not be verified.\nCheck the saved settings before retrying.\n\n"+restore));}
 // A failure of the attempt keeps the existing failure texts.
 {RecheckResult p;p.cancelled();p.state["maintenance_worker_returned"]=true;p.stop("Command failed: _WMP_SCRUB_END");
  assert(p.mentions("Calibration stopped.")&&!p.mentions("cancelled"));}
 // Other runs carry no re-check facts.
 {RecheckResult p;p.cancelled();p.state["maintenance_scrub_heads"]=0;p.state["maintenance_worker_returned"]=true;assert(!p.mentions("cancelled"));}
}
void cancelled_text_survives_the_restart(){
 for(const bool failed:{false,true}){
  const std::string text=kRestarted+(failed?"Earlier results were saved. Offsets could not be restored. Run the calibration again.":"Offset calibration cancelled. Earlier results were saved.");
  // The cancelled attempt was never seen before the restart: the native facts decide.
  RecheckResult p;p.state["maintenance_recheck_cancelled"]=true;p.state["maintenance_restore_failed"]=failed;
  p.state["maintenance_save_requested"]=true;assert(p.shows(kSaving));
  p.saved();p.state.erase("calibration_progress");p.state.erase("nozzle_touch");assert(p.shows(text));
  p.state["maintenance_worker_returned"]=true;assert(p.shows(text));
 }
}
// The offset stage stopped after probing had started, with no failure, no
// cancel and no save requested (stale status during the re-check ends the scrub).
void result_text_stopped_after_probing(){
 const std::string changed="Offsets were changed and may not be reliable. Run the calibration again.";
 // Offsets-only run: shown once the worker has returned.
 {ResultPanel p;p.progress(1,"position");assert(p.empty());p.progress(-1,"idle");p.stop();assert(p.empty());
  p.state["maintenance_worker_returned"]=true;assert(p.shows("Offset calibration stopped. "+changed)&&p.view.result_shown());
  p.state["fresh"]=false;assert(p.shows("Offset calibration stopped. "+changed));}
 {RecheckResult p;p.stop();assert(p.empty());p.state["maintenance_worker_returned"]=true;assert(p.shows("Offset calibration stopped. "+changed));}
 // Combined run: saving, then the confirmed save.
 {ResultPanel p;p.progress(1,"position");assert(p.empty());p.progress(-1,"idle");p.stop();p.saved();
  assert(p.shows(kRestarted+"Offset calibration stopped. Earlier results were saved. "+changed));}
 {RecheckResult p;p.stop();p.saved();assert(p.shows(kRestarted+"Offset calibration stopped. Earlier results were saved. "+changed));}
 // A restart after the save without a confirmed receipt: the save is not verified.
 {RecheckResult p;p.stop();p.saved();p.state["calibration_save_result"]["state"]="unconfirmed";
  assert(p.mentions(kRestarted+"Saved calibration settings could not be verified.")&&!p.mentions("may not be reliable"));}
 // Stopped before probing: the existing texts.
 {ResultPanel p;p.stop();p.state["maintenance_worker_returned"]=true;assert(p.shows("Offset calibration stopped. Offsets are unchanged."));}
 {ResultPanel p;p.stop();p.saved();assert(p.shows(kRestarted+"Offset calibration stopped. Earlier results were saved."));}
 // A failure of the attempt keeps the existing failure text.
 {RecheckResult p;p.state["maintenance_worker_returned"]=true;p.stop("Command failed: _WMP_SCRUB_END");
  assert(p.mentions("Calibration stopped.")&&!p.mentions("may not be reliable"));}
 // Other runs carry no wire-brush result.
 {RecheckResult p;p.stop();p.state["maintenance_scrub_heads"]=0;p.state["maintenance_worker_returned"]=true;assert(!p.mentions("may not be reliable"));}
}
// After a partial re-measurement the last probed head is not the last head of
// the run: every head of the run measured for this request is the condition.
void offsets_saved_after_partial_remeasure(){
 {RecheckResult p(1);p.state["maintenance_worker_returned"]=true;assert(p.shows(kOffsetsSaved));}
 {RecheckResult p(1);assert(p.empty());p.progress(-1,"idle");p.state["maintenance_worker_returned"]=true;assert(p.shows(kOffsetsSaved));}
 // A head without a completed measurement.
 {RecheckResult p(1,Json::array({0,2,3}));p.state["maintenance_worker_returned"]=true;assert(p.empty());}
 {RecheckResult p(3,Json::array({0,1,2}));p.state["maintenance_worker_returned"]=true;assert(p.empty());}
 // The final park was not admitted.
 {RecheckResult p(1);p.progress(1,"height");p.state["calibration_progress"]["measured"]=Json::array({0,1,2,3});
  p.state["maintenance_worker_returned"]=true;assert(p.empty());}
 // Progress of another request.
 {RecheckResult p(1);p.state["calibration_progress"]["request"]=std::string(32,'d');p.state["maintenance_worker_returned"]=true;assert(p.empty());}
}
// The backend refuses the bound attempt while the worker is held (its first
// command was refused, or the cool-down at admission failed): the flow stops
// and the worker returns without waiting for the stale-status bounds.
void refused_bound_attempt_releases_the_worker(const Json&data){
 ScrubRun t(data,0,{{0,0,0,1}},1);
 fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();const auto request=t.request();
 t.run_worker();t.until([&]{return ScrubRun::sent().size()>=2;});
 t.r.gui_step();assert(t.state()==ScrubState::Mounting&&t.label("Mounting head 1...")&&!t.returned.load());
 t.ready["calibration_attempt"]={{"protocol",1},{"session",std::string(32,'a')},{"request",request},{"state","refused"},
  {"error","Calibration head changed or tool change failed: fail_flag=-2"},{"offsets","none"}};
 t.status();t.until([&]{return t.returned.load();});
 assert(RuntimeReceiptTest::scrub_outcome(t.r)==ScrubOutcome::Skip&&t.withheld_rapid&&t.withheld_park);
 assert((ScrubRun::sent()==std::vector<std::string>{ScrubRun::wrapped("G28",0,request),ScrubRun::wrapped("_WMP_SCRUB_HEAD T=0",1,request)}));
 assert(!t.r.stock_calibration_reserved());
 t.r.gui_step();assert(t.label("Calibration did not start.")&&t.label("BACK")&&!t.label("CONFIRM")&&!t.label("CANCEL")&&!t.label("fail_flag"));
 // Scrub status for this request was published: a heater may be on.
 assert(t.label("The nozzle may still be hot."));
 t.tap("BACK");t.r.gui_step();assert(!t.panel()&&t.state()==ScrubState::Idle);
}
// Result panel, bound to this run's attempt (backend at attempt protocol 1).
// A failure the previous attempt left in calibration_failed is not this run's.
const char*const kOldFailure="Command failed: _WMP_SCRUB_HEAD T=2";
struct RetryResult:ResultPanel{
 // Status as a retry finds it: the global failure and the attempt record are the previous run's.
 RetryResult(){
  state["calibration_failed"]=kOldFailure;
  state["calibration_attempt"]={{"protocol",1},{"session",session},{"request",std::string(32,'d')},{"state","failed"},{"error",kOldFailure},{"offsets","stopped"}};
  state["calibration_progress"]={{"protocol",1},{"head",-1},{"phase","idle"},{"request",std::string(32,'d')}};
 }
 // The backend admits this run's first command: its attempt replaces the old one and the latch is cleared.
 void admitted(const char*offsets="none"){
  state["calibration_failed"]="";
  state["calibration_attempt"]={{"protocol",1},{"session",session},{"request",request},{"state","pending"},{"error",""},{"offsets",offsets}};
  state["calibration_progress"]={{"protocol",1},{"head",-1},{"phase","idle"},{"request",request}};
 }
};
void retry_does_not_show_previous_attempt_failure(){
 RetryResult p;assert(p.empty()&&!p.view.result_shown());
 // Stale status and a repeated poll change nothing.
 p.state["fresh"]=false;assert(!p.mentions("Calibration stopped")&&!p.mentions(kOldFailure));
 p.state["fresh"]=true;assert(p.empty());
 p.admitted();assert(p.empty()&&!p.view.result_shown());
 // The old failure is not remembered for the restart text either.
 p.state["calibration_session"]=p.next;p.state["calibration_attempt"]=Json::object();
 assert(p.mentions("Printer restarted. Calibration result could not be confirmed.")&&!p.mentions("Previous error"));
}
void retry_success_shows_saved_text(){
 // Combined run: the save is confirmed after the restart.
 {RetryResult p;assert(p.empty());p.admitted();assert(p.empty());p.saved();assert(p.shows(kRestarted+"Calibration settings saved."));}
 // The receipt arrives while status still shows the previous attempt.
 {RetryResult p;assert(p.empty());p.state["maintenance_save_requested"]=true;assert(p.shows(kSaving));}
 // Wire-brush offsets-only run: the last head was probed and the worker returned.
 {RetryResult p;p.state["maintenance_scrub_heads"]=4;assert(p.empty());
  p.admitted("measured");p.progress(3,"docking");assert(p.empty());
  p.state["maintenance_worker_returned"]=true;assert(p.shows(kOffsetsSaved)&&p.view.result_shown());}
}
void bound_page_shows_own_attempt_failure(){
 const std::string own="Tool change failed during calibration: fail_flag=-2";
 // This run's attempt fails: its own error is shown, not the previous one.
 {RetryResult p;assert(p.empty());p.admitted();assert(p.empty());
  p.state["calibration_attempt"]["state"]="failed";p.state["calibration_attempt"]["error"]=own;p.state["calibration_failed"]=own;
  assert(p.shows("Calibration stopped.\n\n"+own+"\n\nInspect the printer before retrying.")&&p.view.result_shown());
  // Remembered when another attempt replaces the record and the latch is cleared.
  p.state["calibration_failed"]="";p.state["calibration_attempt"]["request"]=std::string(32,'e');p.state["calibration_attempt"]["state"]="pending";
  assert(p.mentions(own));
  p.state["calibration_session"]=p.next;assert(p.mentions("Previous error: "+own));}
 // The failed attempt is the first status seen for this run and the global string is another text.
 {RetryResult p;assert(p.empty());
  p.state["calibration_attempt"]={{"protocol",1},{"session",p.session},{"request",p.request},{"state","failed"},{"error",own},{"offsets","none"}};
  assert(p.mentions(own)&&!p.mentions(kOldFailure));}
 // A bound page takes no failure from the global string, whatever it says.
 {RetryResult p;p.admitted();assert(p.empty());p.state["calibration_failed"]="Earlier PID failure";assert(p.empty());}
 // The attempt of another session with this request is not this run's.
 {RetryResult p;p.admitted();p.state["calibration_attempt"]["session"]=p.next;p.state["calibration_failed"]="x";assert(p.empty());}
}
// This run's attempt was refused before the backend cleared its latch: the
// global string is still the previous run's failure.
void refused_attempt_does_not_latch_previous_failure(){
 const std::string own="Calibration command is already running";
 const auto refused=[&](RetryResult&p){
  p.state["calibration_attempt"]={{"protocol",1},{"session",p.session},{"request",p.request},{"state","refused"},{"error",own},{"offsets","none"}};
  assert(p.mentions("Calibration did not start.")&&p.mentions(own)&&!p.mentions(kOldFailure));
  // A repeated poll does not take it either.
  assert(p.mentions("Calibration did not start.")&&!p.mentions(kOldFailure));};
 // Status goes stale.
 {RetryResult p;refused(p);p.state["fresh"]=false;
  assert(p.shows("Waiting for printer status...")&&!p.mentions(kOldFailure)&&!p.mentions("Calibration stopped"));
  p.state["fresh"]=true;assert(p.mentions("Calibration did not start.")&&!p.mentions(kOldFailure));}
 // The session changes.
 {RetryResult p;refused(p);p.state["calibration_session"]=p.next;p.state["calibration_attempt"]=Json::object();
  assert(p.mentions("Printer restarted. Calibration result could not be confirmed.")&&!p.mentions("Previous error")&&!p.mentions(kOldFailure));}
 // Another attempt replaces the record while the latch is still set.
 {RetryResult p;refused(p);p.state["calibration_attempt"]["request"]=std::string(32,'e');p.state["calibration_attempt"]["state"]="pending";
  assert(!p.mentions("Calibration stopped")&&!p.mentions(kOldFailure));}
}
void unbound_page_still_uses_global_failure(){
 const std::string session(32,'a'),request(32,'c');
 const auto text=[](fake::Node*page,const std::string&part){for(auto&n:fake::nodes)if(n->live&&n->text.find(part)!=std::string::npos)for(auto*p=n->parent;p;p=p->parent)if(p==page)return true;return false;};
 Json state={{"fresh",true},{"calibration_session",session},{"calibration_failed",kOldFailure},{"calibration_attempt_protocol",1},
  {"calibration_attempt",{{"protocol",1},{"session",session},{"request",std::string(32,'d')},{"state","failed"},{"error",kOldFailure},{"offsets","stopped"}}}};
 // No request: the setup-guide page.
 {StockCalibrationStatus view;auto*page=fake::make(fake::screen);view.created(page,true);
  view.update(state);assert(text(page,std::string("Calibration stopped.\n\n")+kOldFailure)&&view.result_shown());fake::del(page);}
 (void)request;
}
// Runtime: a brush retry in the same Klipper session. The previous failure
// neither hides the Calibrate step nor replaces this run's result.
void brush_retry_result_is_this_runs(const Json&data){
 ScrubRun t(data,0,{{0,0,0,1}},1);
 const std::string old(32,'d');
 t.ready["calibration_failed"]=kOldFailure;
 t.ready["calibration_attempt"]={{"protocol",1},{"session",std::string(32,'a')},{"request",old},{"state","failed"},{"error",kOldFailure},{"offsets","stopped"}};
 t.ready["printer_state"]="ready";t.status();
 fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();assert(t.r.stock_calibration_reserved());const auto request=t.request();
 auto*result=fake::make(fake::screen);t.r.stock_calibration_created(result);
 const auto shown=[&](const std::string&text){t.r.update_stock_calibration();
  for(auto&n:fake::nodes)if(n->live&&n->text.find(text)!=std::string::npos)for(auto*q=n->parent;q;q=q->parent)if(q==result)return true;
  return false;};
 assert(!shown("Calibration stopped"));
 t.run_worker();t.until([&]{return ScrubRun::sent().size()>=2;});
 t.ready["calibration_failed"]="";
 t.ready["calibration_attempt"]={{"protocol",1},{"session",std::string(32,'a')},{"request",request},{"state","pending"},{"error",""},{"offsets","none"}};
 t.head(158,160,"heating");t.until([&]{return t.state()==ScrubState::Scrub;});
 t.r.gui_step();assert(t.label("Scrub the nozzle on head 1")&&!shown("Calibration stopped"));
 t.ready["calibration_attempt"]["offsets"]="measured";
 t.ready["calibration_progress"]={{"protocol",1},{"head",0},{"phase","docking"}};t.status();
 t.tap("CONFIRM");t.until([&]{return t.returned.load();});
 assert(shown(kOffsetsSaved)&&!shown("Calibration stopped"));
 t.r.stock_calibration_created(nullptr);fake::del(result);
}
// A one-head brush run that reaches the vendor's final park send (re-check).
// The worker sends G28 and RAPID_MODE T=0, then waits for park before
// PARK_CURRENT_TOOL and, on a combined run, SAVE_CONFIG. The failed byte is
// recorded after the park send.
struct RecheckRun{
 ScrubRun t;const bool combined;std::string request;std::atomic<bool>park{false};std::atomic<int>after_park{-1};
 static std::array<unsigned char,4>selected(bool combined){return {{static_cast<unsigned char>(combined?1:0),0,0,1}};}
 RecheckRun(const Json&data,bool combined=false):t(data,0,selected(combined),1),combined(combined){
  fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();request=t.request();
  t.worker=std::thread([this]{
   t.r.run_stock_calibration_worker([this]{
    wmp_openace::forward_stock_command(offset_home,"G28");
    wmp_openace::forward_stock_command(offset_rapid,"RAPID_MODE T=0");
    while(!park.load())std::this_thread::sleep_for(std::chrono::milliseconds(1));
    wmp_openace::forward_stock_command(offset_park,"PARK_CURRENT_TOOL");after_park.store(RuntimeReceiptTest::scrub_failed_byte(t.r));
    if(this->combined)wmp_openace::forward_stock_command(0x4b869c,"SAVE_CONFIG");
   });
   t.returned.store(true);
  });
  // The scrub of head 1, then the vendor's RAPID_MODE.
  if(combined){t.until([&]{return ScrubRun::sent().size()>=2&&t.label("CONFIRM");});t.tap("CONFIRM");}
  t.until([&]{return t.state()==ScrubState::Mounting&&ScrubRun::sent().size()>=(this->combined?4U:2U);});
  t.head(158,160,"heating");t.until([&]{return t.state()==ScrubState::Scrub;});
  t.r.gui_step();t.tap("CONFIRM");t.until([&]{return ScrubRun::sent().size()>=first();});
  assert(t.state()==ScrubState::Calibrate&&ScrubRun::sent().back()==ScrubRun::wrapped("RAPID_MODE T=0",first()-1,request));
 }
 // Commands sent up to and including the vendor's RAPID_MODE.
 std::size_t first()const{return combined?8:6;}
 std::string at(std::size_t i)const{const auto sent=ScrubRun::sent();return i<sent.size()?sent[i]:std::string();}
 std::string wrapped(const std::string&command,std::size_t sequence)const{return ScrubRun::wrapped(command,unsigned(sequence),request);}
 // Status after the measurement: head 1 measured, the heater cooled, flagged heads as given.
 void measured(const Json&flagged){
  for(auto&h:t.ready["heads"])if(h.value("id","")=="h0"){h["actual"]=28;h["target"]=0;}
  t.ready["nozzle_scrub"]={{"phase","heating"},{"head",0},{"target",160.0}};
  t.ready["calibration_progress"]={{"protocol",1},{"head",0},{"phase","docking"},{"measured",Json::array({0})},{"measuring",false}};
  if(!flagged.is_null())t.ready["nozzle_touch"]={{"protocol",2},{"flagged",flagged},{"restore","none"}};
  t.status();t.r.gui_step();
 }
 // The worker reaches its park send with head 1 flagged; the Re-check screen is up.
 void to_recheck(){
  measured(Json::array({0}));park.store(true);
  t.until([&]{return ScrubRun::sent().size()>=first()+1&&t.state()==ScrubState::Recheck&&t.label("Clean again");});
  assert(at(first())==wrapped("_WMP_SCRUB_ATTENTION VALUE=1",first()));
 }
 // Clean again from Re-check: the repeat scrub of head 1, then its RAPID_MODE.
 void clean_again(){
  t.tap("CONFIRM");t.until([&]{return t.state()==ScrubState::Mounting&&ScrubRun::sent().size()>=first()+3;});
  t.r.gui_step();assert(t.state()==ScrubState::Mounting); // the cooled status of the first scrub acknowledges nothing
  t.head(158,160,"heating");t.until([&]{return t.state()==ScrubState::Scrub&&ScrubRun::sent().size()>=first()+4;});
  t.r.gui_step();t.tap("CONFIRM");t.until([&]{return ScrubRun::sent().size()>=first()+7;});
  assert(t.state()==ScrubState::Remeasure);
  const std::size_t n=first();
  assert(at(n+1)==wrapped("_WMP_SCRUB_ATTENTION VALUE=0",n+1)&&at(n+2)==wrapped("_WMP_SCRUB_HEAD T=0",n+2));
  assert(at(n+3)==wrapped("_WMP_SCRUB_ATTENTION VALUE=1",n+3)&&at(n+4)==wrapped("_WMP_SCRUB_ATTENTION VALUE=0",n+4));
  assert(at(n+5)==wrapped("_WMP_SCRUB_COOL T=0",n+5)&&at(n+6)==wrapped("RAPID_MODE T=0",n+6));
 }
 Json result(){return RuntimeReceiptTest::scrub_result(t.r);}
};
void park_send_holds_worker_while_recheck_is_shown(const Json&data){
 RecheckRun r(data);r.to_recheck();
 r.t.r.gui_step();
 assert(r.t.label("Head 1 may not be clean")&&r.t.label("Clean again")&&r.t.label("Save anyway")&&r.t.label("CANCEL")&&r.t.label("CONFIRM"));
 // Held: nothing more is sent and the park is not forwarded.
 for(unsigned i=0;i<3;++i){std::this_thread::sleep_for(std::chrono::milliseconds(100));r.t.r.gui_step();}
 assert(!r.t.returned.load()&&ScrubRun::sent().size()==r.first()+1&&r.after_park.load()==-1);
 // Released by Save anyway.
 r.t.tap("Save anyway");r.t.r.gui_step();r.t.tap("CONFIRM");r.t.until([&]{return r.t.returned.load();});
 assert(ScrubRun::sent().size()==r.first()+3&&r.at(r.first()+2)==r.wrapped("PARK_CURRENT_TOOL",r.first()+2));
}
void save_anyway_forwards_the_park_and_the_save(const Json&data){
 RecheckRun r(data,true);r.to_recheck();
 r.t.tap("Save anyway");r.t.r.gui_step();
 assert(RuntimeReceiptTest::scrub_flow_view(r.t.r).state==ScrubState::Recheck&&!r.t.returned.load());
 r.t.tap("CONFIRM");r.t.until([&]{return r.t.returned.load();});
 const std::size_t n=r.first();
 assert(ScrubRun::sent().size()==n+4&&r.at(n+1)==r.wrapped("_WMP_SCRUB_ATTENTION VALUE=0",n+1));
 assert(r.at(n+2)==r.wrapped("PARK_CURRENT_TOOL",n+2)&&r.at(n+3)==r.wrapped("SAVE_CONFIG",n+3)&&r.after_park.load()==0);
 assert((r.result()==Json{{"flagged",Json::array({0})},{"saved_anyway",true},{"cancelled",false},{"restore_failed",false}}));
}
void clean_again_sends_scrub_and_rapid_commands_in_sequence_then_parks(const Json&data){
 RecheckRun r(data);r.to_recheck();r.clean_again();
 // The re-measurement runs, then completes with no head flagged.
 r.t.ready["calibration_progress"]={{"protocol",1},{"head",0},{"phase","position"},{"measured",Json::array()},{"measuring",true}};r.t.status();
 for(unsigned i=0;i<3;++i){r.t.r.gui_step();std::this_thread::sleep_for(std::chrono::milliseconds(20));}
 assert(!r.t.returned.load()&&r.t.state()==ScrubState::Remeasure);
 r.t.ready["calibration_progress"]={{"protocol",1},{"head",0},{"phase","docking"},{"measured",Json::array({0})},{"measuring",false}};
 r.t.ready["nozzle_touch"]["flagged"]=Json::array();r.t.status();
 r.t.until([&]{return r.t.returned.load();});
 const std::size_t n=r.first();
 assert(ScrubRun::sent().size()==n+8&&r.at(n+7)==r.wrapped("PARK_CURRENT_TOOL",n+7)&&r.after_park.load()==0);
 assert((r.result()==Json{{"flagged",Json::array()},{"saved_anyway",false},{"cancelled",false},{"restore_failed",false}}));
}
void recheck_cancel_sends_restore_and_end_then_withholds_the_park(const Json&data){
 for(const auto*restore:{"done","failed"}){
  RecheckRun r(data);r.to_recheck();
  r.t.tap("CANCEL");r.t.until([&]{return ScrubRun::sent().size()>=r.first()+4;});
  const std::size_t n=r.first();
  assert(r.at(n+1)==r.wrapped("_WMP_SCRUB_ATTENTION VALUE=0",n+1)&&r.at(n+2)==r.wrapped("_WMP_OFFSETS_RESTORE",n+2)&&r.at(n+3)==r.wrapped("_WMP_SCRUB_END",n+3));
  assert(r.t.state()==ScrubState::Cancelling&&!r.t.returned.load());
  r.t.ready["nozzle_touch"]["restore"]=restore;r.t.ready["nozzle_scrub"]={{"phase","ended"},{"head",-1},{"target",160.0}};r.t.status();
  r.t.until([&]{return r.t.returned.load();});
  assert(ScrubRun::sent().size()==n+4&&r.after_park.load()==0&&RuntimeReceiptTest::scrub_outcome(r.t.r)==ScrubOutcome::Skip);
  assert((r.result()==Json{{"flagged",Json::array()},{"saved_anyway",false},{"cancelled",true},{"restore_failed",std::string(restore)=="failed"}}));
 }
}
// Runtime: the re-check outcome reaches the result page of an offsets-only run.
void recheck_outcome_shown_on_the_result_page(const Json&data){
 for(const auto*choice:{"Save anyway","CANCEL","CANCEL failed"}){
  RecheckRun r(data);
  auto*result=fake::make(fake::screen);r.t.r.stock_calibration_created(result);
  const auto shown=[&](const std::string&text){r.t.r.update_stock_calibration();
   for(auto&n:fake::nodes)if(n->live&&n->text==text)for(auto*q=n->parent;q;q=q->parent)if(q==result)return true;
   return false;};
  r.t.ready["calibration_attempt"]={{"protocol",1},{"session",std::string(32,'a')},{"request",r.request},{"state","pending"},{"error",""},{"offsets","measured"}};
  r.t.ready["printer_state"]="ready";r.to_recheck();
  if(std::string(choice)=="Save anyway"){
   r.t.tap("Save anyway");r.t.r.gui_step();r.t.tap("CONFIRM");r.t.until([&]{return r.t.returned.load();});
   assert(shown("Nozzle offsets saved. Head 1 may not be clean."));
  }else{
   const bool failed=std::string(choice)!="CANCEL";
   r.t.tap("CANCEL");r.t.until([&]{return ScrubRun::sent().size()>=r.first()+4;});
   r.t.ready["calibration_attempt"]["offsets"]="stopped";r.t.ready["nozzle_touch"]["restore"]=failed?"failed":"done";
   r.t.ready["nozzle_scrub"]={{"phase","ended"},{"head",-1},{"target",160.0}};r.t.status();
   r.t.until([&]{return r.t.returned.load();});r.t.r.gui_step();
   assert(shown(failed?"Offsets could not be restored. Run the calibration again.":"Offset calibration cancelled. Offsets are unchanged."));
  }
  r.t.r.stock_calibration_created(nullptr);fake::del(result);
 }
}
// The park is forwarded at once, as without a re-check.
void park_forwarded_without_hold(RecheckRun&r){
 r.park.store(true);r.t.until([&]{return r.t.returned.load();});
 assert(ScrubRun::sent().size()==r.first()+1&&r.at(r.first())==r.wrapped("PARK_CURRENT_TOOL",r.first())&&r.after_park.load()==0);
 assert((r.result()==Json{{"flagged",Json::array()},{"saved_anyway",false},{"cancelled",false},{"restore_failed",false}}));
}
void no_flags_no_hold(const Json&data){
 RecheckRun r(data);r.measured(Json::array());park_forwarded_without_hold(r);
}
void stale_status_at_park_does_not_hold(const Json&data){
 RecheckRun r(data);r.measured(Json::array({0}));
 RuntimeReceiptTest::scrub_advance(r.t.r,r.t.clock->now,2001);r.t.r.gui_step();
 park_forwarded_without_hold(r);
}
void backend_without_nozzle_touch_does_not_hold(const Json&data){
 RecheckRun r(data);r.measured(Json());park_forwarded_without_hold(r);
}
void recheck_released_when_runtime_stops_or_screen_is_torn_down(const Json&data){
 // The stock UI deletes the Re-check screen: same as CANCEL.
 {RecheckRun r(data);r.to_recheck();
  fake::del(r.t.panel());r.t.until([&]{return ScrubRun::sent().size()>=r.first()+4;});
  assert(r.at(r.first()+2)==r.wrapped("_WMP_OFFSETS_RESTORE",r.first()+2)&&r.at(r.first()+3)==r.wrapped("_WMP_SCRUB_END",r.first()+3));
  r.t.ready["nozzle_touch"]["restore"]="done";r.t.ready["nozzle_scrub"]={{"phase","ended"},{"head",-1},{"target",160.0}};r.t.status();
  r.t.until([&]{return r.t.returned.load();});
  assert(ScrubRun::sent().size()==r.first()+4&&r.after_park.load()==0);
 }
 // Runtime shutdown ends the hold; nothing more is sent and the park is withheld.
 {RecheckRun r(data);r.to_recheck();
  RuntimeReceiptTest::scrub_shutdown(r.t.r);r.t.worker.join();
  assert(r.t.returned.load()&&ScrubRun::sent().size()==r.first()+1&&r.after_park.load()==0);
 }
}
// Runtime shutdown while a re-measurement's RAPID_MODE runs: the hold ends,
// nothing more is sent and the park is withheld, so no partial re-measurement
// is completed by the vendor's park and save.
void shutdown_during_remeasure_withholds_the_park(const Json&data){
 RecheckRun r(data);r.to_recheck();r.clean_again();
 RuntimeReceiptTest::scrub_shutdown(r.t.r);r.t.worker.join();
 assert(r.t.returned.load()&&ScrubRun::sent().size()==r.first()+7&&r.after_park.load()==0);
 assert((r.result()==Json{{"flagged",Json::array()},{"saved_anyway",false},{"cancelled",true},{"restore_failed",true}}));
}
// Runtime shutdown outside the re-check leaves the sends as without it.
// First pass: the scrub is complete; the worker's RAPID_MODE and park are forwarded.
void first_pass_shutdown_forwards_rapid_and_park(const Json&data){
 ScrubRun t(data,0,{{0,0,0,1}},1);
 fake::send(t.start,7);t.tap("CONFIRM");t.r.gui_step();const auto request=t.request();
 std::atomic<bool>home_done{false},proceed{false};
 t.worker=std::thread([&]{
  t.r.run_stock_calibration_worker([&]{
   wmp_openace::forward_stock_command(offset_home,"G28");home_done.store(true);
   while(!proceed.load())std::this_thread::sleep_for(std::chrono::milliseconds(1));
   wmp_openace::forward_stock_command(offset_rapid,"RAPID_MODE T=0");
   wmp_openace::forward_stock_command(offset_park,"PARK_CURRENT_TOOL");
  });
  t.returned.store(true);
 });
 t.until([&]{return ScrubRun::sent().size()>=2;});
 t.head(158,160,"heating");t.until([&]{return t.state()==ScrubState::Scrub;});
 t.r.gui_step();t.tap("CONFIRM");t.until([&]{return home_done.load();});
 assert(t.state()==ScrubState::Calibrate&&ScrubRun::sent().size()==5);
 RuntimeReceiptTest::scrub_shutdown(t.r);proceed.store(true);t.worker.join();
 assert(ScrubRun::sent().size()==7&&ScrubRun::sent()[5]==ScrubRun::wrapped("RAPID_MODE T=0",5,request)&&ScrubRun::sent()[6]==ScrubRun::wrapped("PARK_CURRENT_TOOL",6,request));
}
// No head flagged: the park after a shutdown is forwarded.
void no_flag_park_after_shutdown_is_forwarded(const Json&data){
 RecheckRun r(data);r.measured(Json::array());
 RuntimeReceiptTest::scrub_shutdown(r.t.r);park_forwarded_without_hold(r);
}
// The scrub screen was removed while the worker measured (not held, nothing
// cancelled). The Re-check screen is created again: the worker is never held
// waiting for a choice without a screen.
void recheck_screen_shown_again_after_the_screen_was_left(const Json&data){
 RecheckRun r(data);r.t.r.gui_step();assert(r.t.panel());
 fake::del(r.t.panel());r.t.r.gui_step();
 assert(!r.t.panel()&&r.t.state()==ScrubState::Calibrate&&!r.t.returned.load());
 r.to_recheck();
 r.t.tap("Save anyway");r.t.r.gui_step();r.t.tap("CONFIRM");r.t.until([&]{return r.t.returned.load();});
 assert(r.at(r.first()+2)==r.wrapped("PARK_CURRENT_TOOL",r.first()+2));
}
// A re-measurement fails: the vendor byte is set while the worker is held at
// the park send, before status reports the failure. The existing decisions
// run once the hold ends: the park is withheld and the byte is cleared for
// the early save.
void failed_byte_decision_is_made_after_the_hold(const Json&data){
 RecheckRun r(data,true);r.to_recheck();r.clean_again();
 RuntimeReceiptTest::scrub_failed_byte(r.t.r,1);
 for(unsigned i=0;i<3;++i){r.t.r.gui_step();std::this_thread::sleep_for(std::chrono::milliseconds(100));}
 assert(!r.t.returned.load()&&r.t.state()==ScrubState::Remeasure);
 r.t.ready["calibration_failed"]="Calibration head changed or tool change failed: fail_flag=-2";
 r.t.ready["calibration_attempt"]={{"protocol",1},{"session",std::string(32,'a')},{"request",r.request},{"state","failed"},{"error","x"},{"offsets","stopped"},{"early_save_available",true}};
 r.t.status();r.t.until([&]{return r.t.returned.load();});
 const std::size_t n=r.first();
 assert(r.after_park.load()==0&&RuntimeReceiptTest::scrub_outcome(r.t.r)==ScrubOutcome::Skip);
 assert(ScrubRun::sent().size()==n+8&&r.at(n+7)==r.wrapped("SAVE_CONFIG",n+7));
 assert((r.result()==Json{{"flagged",Json::array()},{"saved_anyway",false},{"cancelled",false},{"restore_failed",false}}));
}
void nozzle_scrub_lifecycle(const Json&data){
 ScrubLayout layout;
 nozzle_scrub_prepare_layout();nozzle_scrub_recheck_layout();nozzle_scrub_recheck_touch_targets();nozzle_scrub_three_heads_has_five_steps();nozzle_scrub_touch_targets_meet_minimum();
 nozzle_scrub_panel_view_matches_the_fit_cases();nozzle_scrub_heating_text();nozzle_scrub_calibrate_has_no_actions();nozzle_scrub_calibrate_readings();nozzle_scrub_recheck_readings();
 nozzle_scrub_failed_shows_back_only();nozzle_scrub_update_is_idempotent();nozzle_scrub_dismiss_releases_widgets();
 maintenance_start_in_accurate_mode_opens_prepare(data);prepare_blob_delegates_start_unchanged(data);
 prepare_brush_sets_rapid_and_delegates_once(data);prepare_cancel_changes_nothing(data);rapid_mode_start_is_untouched(data);
 stale_status_keeps_confirm_disabled(data);unsupported_profile_never_offers(data);
 worker_hold_sends_sequenced_scrub_commands(data);attention_released_by_touch_or_door(data);attention_touch_uses_one_clock(data);worker_released_on_session_change(data);
 skip_outcome_withholds_rapid_and_park_sends(data);failed_byte_cleared_at_park_only_when_skipping(data);
 failed_byte_cleared_when_early_save_available(data);failed_byte_not_cleared_when_early_save_unavailable(data);
 result_text_offsets_stopped_saved();result_action_done_on_results();result_save_latched_from_the_local_flag();result_text_offsets_stopped_nothing_saved();successful_run_text_unchanged();
 brush_retry_after_failed_attempt_runs_the_scrub(data);start_during_reserved_run_does_not_reopen_prepare(data);
 result_text_offsets_only_success(data);result_text_unchanged_for_rapid_mode_run(data);result_text_not_shown_when_probing_stopped_early();
 result_text_not_shown_when_last_head_fails_after_mounting();
 result_text_save_anyway_names_flagged_heads();result_text_recheck_cancelled();cancelled_text_survives_the_restart();
 offsets_saved_after_partial_remeasure();result_text_stopped_after_probing();
 backend_without_scrub_support_never_offers(data);
 worker_released_when_screen_is_torn_down_or_runtime_stops(data);
 refused_brush_start_restores_accurate_mode(data);second_start_while_prepare_open_does_not_double_start(data);
 throwing_scrub_send_does_not_escape_the_worker(data);worker_released_when_status_stays_stale(data);
 refused_bound_attempt_releases_the_worker(data);
 retry_does_not_show_previous_attempt_failure();retry_success_shows_saved_text();
 bound_page_shows_own_attempt_failure();refused_attempt_does_not_latch_previous_failure();unbound_page_still_uses_global_failure();
 brush_retry_result_is_this_runs(data);
 stopped_run_with_refused_save_shows_failure_not_saving();stopped_run_with_pending_save_keeps_saving();
 blob_run_failure_shows_upstream_text_with_reason(data);rapid_run_failure_shows_upstream_text_with_reason(data);
 finished_screen_is_dismissed_when_result_is_shown(data);
 park_send_holds_worker_while_recheck_is_shown(data);save_anyway_forwards_the_park_and_the_save(data);
 clean_again_sends_scrub_and_rapid_commands_in_sequence_then_parks(data);recheck_cancel_sends_restore_and_end_then_withholds_the_park(data);
 no_flags_no_hold(data);stale_status_at_park_does_not_hold(data);backend_without_nozzle_touch_does_not_hold(data);
 recheck_released_when_runtime_stops_or_screen_is_torn_down(data);failed_byte_decision_is_made_after_the_hold(data);
 shutdown_during_remeasure_withholds_the_park(data);recheck_screen_shown_again_after_the_screen_was_left(data);
 no_flag_park_after_shutdown_is_forwarded(data);first_pass_shutdown_forwards_rapid_and_park(data);
 recheck_outcome_shown_on_the_result_page(data);
}
