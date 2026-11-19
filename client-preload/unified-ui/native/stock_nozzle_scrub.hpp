// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "nozzle_scrub_view.hpp"
#include "stock_header_action.hpp"
#include "stock_option_row.hpp"
#include "stock_progress_panel.hpp"
#include <functional>
#include <string>
namespace wmp_ui { namespace native {
// The per-head rows of a ScrubView, display only, at the top of the panel's
// choices container, filled column by column in one or two 284 px columns:
// one 36 px row per head with "Head N" at x 0, the mark at x 96 and the
// centre span at x 136 of its column, all in MyriadPro_Regular_22. The client's fonts
// have no U+2713 or U+2717 glyph, so the check and the cross are drawn
// lines; the measuring mark is U+2026, which MyriadPro_Regular_22 has.
// GUI-thread only. Every widget is created by create(); update() only
// changes text, visibility and positions.
class StockScrubReadings {
 struct Row{void*name=nullptr,*span=nullptr,*measuring=nullptr,*check=nullptr,*cross=nullptr;};
 struct Point{std::int16_t x,y;};
 static constexpr int kRows=4,kNameX=0,kMarkX=96,kSpanX=136,kNameW=88,kSpanW=140,kMarkTop=2,kMarkSize=24,kColumnW=284;
 static constexpr std::uint32_t kText=0xffeeeeeeU,kPassed=0xff44cc66U,kFlagged=0xffff6666U,kMeasuring=0xffff6600U;
 void*root_=nullptr;Row rows_[kRows];std::vector<ScrubRow>rendered_;unsigned columns_=0;bool valid_=false;
 static void shown(void*p,bool show){stock_function<void(*)(void*,unsigned)>(show?lv_obj_clear_flag:lv_obj_add_flag)(p,1);}
 static void text(void*p,const std::string&s){stock_function<void(*)(void*,const char*)>(lv_label_set_text)(p,s.c_str());}
 static void*label(void*parent,int x,int y,int w,std::uint32_t colour){
  auto*l=stock_function<void*(*)(void*)>(lv_label_create)(parent);if(!l)return nullptr;
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(l,reinterpret_cast<void*>(MyriadPro_Regular_22),0);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(l,colour,0);
  stock_function<void(*)(void*,int)>(lv_label_set_long_mode)(l,0);
  stock_object_place(l,x,y,w,MyriadPro_Regular_22_line_height);return l;
 }
 // The points stay referenced by LVGL, so they are static.
 static void*line(void*parent,const Point*points,std::uint16_t count,int x,int y,std::uint32_t colour){
  auto*l=stock_function<void*(*)(void*)>(lv_line_create)(parent);if(!l)return nullptr;
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_line_width)(l,4,0);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_line_color)(l,colour,0);
  stock_function<void(*)(void*,const Point*,std::uint16_t)>(lv_line_set_points)(l,points,count);
  stock_object_place(l,x,y,kMarkSize,kMarkSize);return l;
 }
public:
 static constexpr int row_height=nozzle_scrub_row_height;
 StockScrubReadings()=default;
 StockScrubReadings(const StockScrubReadings&)=delete;
 StockScrubReadings&operator=(const StockScrubReadings&)=delete;
 // Widgets are deleted with parent; this only forgets them.
 void release(){root_=nullptr;for(auto&r:rows_)r=Row();rendered_.clear();columns_=0;valid_=false;}
 // Row i of count rows in columns columns: column-major.
 void place(unsigned count,unsigned columns){
  const unsigned per_column=std::max(1U,unsigned((count+columns-1)/columns));
  stock_object_place(root_,0,0,int(columns)*kColumnW,std::max(1,nozzle_scrub_rows_height(count,columns)));
  for(unsigned i=0;i<unsigned(kRows);++i){
   const auto&r=rows_[i];const int x=int(i/per_column)*kColumnW,y=int(i%per_column)*row_height;
   stock_object_place(r.name,x+kNameX,y,kNameW,MyriadPro_Regular_22_line_height);stock_object_place(r.span,x+kSpanX,y,kSpanW,MyriadPro_Regular_22_line_height);
   stock_object_place(r.measuring,x+kMarkX,y,kSpanX-kMarkX,MyriadPro_Regular_22_line_height);
   for(auto*mark:{r.check,r.cross})stock_object_place(mark,x+kMarkX,y+kMarkTop,kMarkSize,kMarkSize);
  }
 }
 bool create(void*parent){
  release();if(!stock_object_valid(parent))return false;
  root_=stock_function<void*(*)(void*)>(lv_obj_create)(parent);if(!root_)return false;
  stock_dialog_backdrop(root_);stock_function<void(*)(void*,unsigned)>(lv_obj_clear_flag)(root_,2);
  stock_object_place(root_,0,0,kColumnW,kRows*row_height);shown(root_,false);
  // Within the 24 px mark box with the 4 px line width.
  static const Point check[]={{2,12},{9,19},{22,4}},cross[]={{4,4},{20,20},{12,12},{20,4},{4,20}};
  for(int i=0;i<kRows;++i){
   auto&r=rows_[i];const int y=i*row_height;
   r.name=label(root_,kNameX,y,kNameW,kText);r.span=label(root_,kSpanX,y,kSpanW,kText);
   r.measuring=label(root_,kMarkX,y,kSpanX-kMarkX,kMeasuring);
   r.check=line(root_,check,3,kMarkX,y+kMarkTop,kPassed);r.cross=line(root_,cross,5,kMarkX,y+kMarkTop,kFlagged);
   if(!r.name||!r.span||!r.measuring||!r.check||!r.cross){release();return false;}
   text(r.measuring,"\xe2\x80\xa6");
  }
  return true;
 }
 // Shows rows, up to four, in columns columns (1 or 2); an empty list hides them.
 void update(const std::vector<ScrubRow>&rows,unsigned columns=1){
  columns=columns==2?2:1;
  if(!stock_object_valid(root_)||(valid_&&rows==rendered_&&columns==columns_))return;
  if(!valid_||columns!=columns_||rows.size()!=rendered_.size())place(unsigned(rows.size()),columns);
  shown(root_,!rows.empty());
  for(int i=0;i<kRows;++i){
   const auto&r=rows_[i];const bool used=unsigned(i)<rows.size();
   for(auto*p:{r.name,r.span})shown(p,used);
   const ScrubMark mark=used?rows[i].mark:ScrubMark::None;
   shown(r.measuring,mark==ScrubMark::Measuring);shown(r.check,mark==ScrubMark::Passed);shown(r.cross,mark==ScrubMark::Flagged);
   if(!used)continue;
   if(!valid_||unsigned(i)>=rendered_.size()||rendered_[i].name!=rows[i].name)text(r.name,rows[i].name);
   if(!valid_||unsigned(i)>=rendered_.size()||rendered_[i].span!=rows[i].span)text(r.span,rows[i].span);
  }
  rendered_=rows;columns_=columns;valid_=true;
 }
};
// Guided nozzle scrub screen. GUI-thread only. StockProgressPanel draws the
// title, the numbered steps, the heading, temperature, instruction and note
// of a ScrubView. This class adds the header actions, the two Prepare or
// Recheck options and the Calibrate rows (StockScrubReadings), and reports
// taps; it sends nothing to the printer. Every widget is
// created by created(); update() only changes text, colours, visibility and
// the option row width.
class StockNozzleScrub {
 // Header action: caption inside the 40 px bar; the 64 px hit area deliberately extends below the visible bar.
 static constexpr int kActionW=116,kActionH=64,kBarH=40,kRowH=104;
 StockProgressPanel panel_;
 void*root_=nullptr,*cancel_=nullptr,*confirm_=nullptr,*back_=nullptr;StockOptionRow options_[2];StockScrubReadings readings_;
 ScrubView view_{};bool rendered_=false;
 static void shown(void*p,bool show){stock_function<void(*)(void*,unsigned)>(show?lv_obj_clear_flag:lv_obj_add_flag)(p,1);}
 bool tappable(void*p){return p&&stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(p,&pressed,7,this);}
 void*action(const char*s,int x){auto*b=stock_header_action(root_,s,x,0,kActionW,kActionH,kBarH);return tappable(b)?b:nullptr;}
 // What the panel and the actions show. Whole degrees are drawn, so a
 // temperature change below one degree is no change.
 static bool same(const ScrubView&a,const ScrubView&b){
  return a.state==b.state&&a.head==b.head&&a.heads==b.heads&&same_actions(a,b)&&a.heading==b.heading&&a.body==b.body&&a.note==b.note
   &&nozzle_scrub_degrees(a.actual)==nozzle_scrub_degrees(b.actual)&&nozzle_scrub_degrees(a.target)==nozzle_scrub_degrees(b.target)&&a.rows==b.rows;
 }
 static bool decisions(const ScrubView&v){return v.state==ScrubState::Prepare||v.state==ScrubState::Recheck;}
 static bool same_options(const ScrubView&a,const ScrubView&b){
  for(unsigned i=0;i<2;++i)if(a.option_title[i]!=b.option_title[i]||a.option_detail[i]!=b.option_detail[i])return false;
  return a.first_selected==b.first_selected;
 }
 static bool same_actions(const ScrubView&a,const ScrubView&b){
  return decisions(a)==decisions(b)&&(!decisions(a)||same_options(a,b))&&a.brush==b.brush&&a.confirm_visible==b.confirm_visible
   &&a.confirm_enabled==b.confirm_enabled&&a.cancel_visible==b.cancel_visible&&a.back_visible==b.back_visible;
 }
 void release(){root_=cancel_=confirm_=back_=nullptr;for(auto&o:options_)o=StockOptionRow();readings_.release();rendered_=false;}
 void close(){panel_.close();auto*p=root_;release();if(stock_object_valid(p))stock_function<void(*)(void*)>(lv_obj_del)(p);}
 void actions(){
  const auto&v=view_;
  shown(cancel_,v.cancel_visible);shown(confirm_,v.confirm_visible);shown(back_,v.back_visible);
  stock_header_action_caption(confirm_,"CONFIRM",v.confirm_enabled,kBarH);
  // The panel hides the choices container outside Prepare and Recheck and
  // sizes it on update; the rows take its full width.
  int width=0;
  if(decisions(v)){auto*choices=panel_.choices_parent();
   stock_function<void(*)(void*)>(lv_obj_update_layout)(choices);width=stock_function<int(*)(void*)>(lv_obj_get_width)(choices);}
  for(unsigned i=0;i<2;++i){
   // The choices container holds the Calibrate rows outside Prepare and Recheck.
   if(stock_object_valid(options_[i].object))shown(options_[i].object,decisions(v));
   if(decisions(v)&&stock_object_valid(options_[i].object)){
    StockOptionRow::label(options_[i].title,v.option_title[i],MyriadPro_Regular_22);
    stock_function<void(*)(void*,int)>(lv_label_set_long_mode)(options_[i].title,1);
    StockOptionRow::label(options_[i].detail,v.option_detail[i],MyriadPro_Regular_22);
   }
   options_[i].select(v.first_selected==(i==0));
   // In Recheck the options follow the per-head rows.
   const int top=nozzle_scrub_rows_height(v.rows.size(),nozzle_scrub_row_columns(v));
   if(width>=StockOptionRow::min_width)options_[i].layout(0,top+int(i)*(kRowH+StockOptionRow::gap),width,kRowH);
  }
 }
public:
 std::function<void()> on_confirm,on_cancel,on_back;
 std::function<void(bool first)> on_select; // The first or the second option row.
 StockNozzleScrub()=default;
 StockNozzleScrub(const StockNozzleScrub&)=delete;
 StockNozzleScrub&operator=(const StockNozzleScrub&)=delete;
 bool visible()const{
  auto*screen=stock_function<void*(*)(void*)>(lv_disp_get_scr_act)(nullptr);auto*p=root_;
  for(unsigned i=0;p&&i<20;++i){if(!stock_object_valid(p)||stock_function<bool(*)(void*,unsigned)>(lv_obj_has_flag)(p,1))return false;if(p==screen)return true;p=stock_function<void*(*)(void*)>(lv_obj_get_parent)(p);}return false;
 }
 // Builds the screen over the whole of page; nullptr dismisses it.
 void created(void*page){
  close();if(!stock_object_valid(page))return;
  const int w=stock_function<int(*)(void*)>(lv_obj_get_width)(page),h=stock_function<int(*)(void*)>(lv_obj_get_height)(page);
  root_=stock_function<void*(*)(void*)>(lv_obj_create)(page);if(!root_)return;
  if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(root_,&deleted,33,this)){close();return;}
  stock_dialog_backdrop(root_);stock_object_place(root_,0,0,w,h);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(root_,0xff3c3f43U,0);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(root_,255,0);shown(root_,false);
  if(!panel_.attach(root_,0,0,w,h)){close();return;}
  // After the panel, so the actions lie above its title row.
  cancel_=action("CANCEL",w-2*kActionW-StockOptionRow::gap);confirm_=action("CONFIRM",w-kActionW);back_=action("BACK",w-kActionW);
  auto*choices=panel_.choices_parent();
  if(choices){
   options_[0]=StockOptionRow::create(choices,"Wire brush","Scrub each heated nozzle by hand. Have a wire brush ready.",0,0,400,kRowH);
   options_[1]=StockOptionRow::create(choices,"Printed blob","Every head must be loaded with filament.",0,kRowH+StockOptionRow::gap,400,kRowH);
  }
  if(!cancel_||!confirm_||!back_||!tappable(options_[0].object)||!tappable(options_[1].object)||!readings_.create(choices))close();
 }
 // No widget work when the view is unchanged.
 void update(const ScrubView&view){
  if(!stock_object_valid(root_)||!panel_.attached()){close();return;}
  if(rendered_&&same(view,view_))return;
  const bool redraw=!rendered_||!same_actions(view,view_);
  view_=view;panel_.update(nozzle_scrub_panel_view(view));
  if(redraw)actions();
  readings_.update(view.rows,nozzle_scrub_row_columns(view));
  if(!rendered_)shown(root_,true);
  rendered_=true;
 }
private:
 static void deleted(void*e)noexcept{try{
  auto*o=static_cast<StockNozzleScrub*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));
  if(o&&stock_function<void*(*)(void*)>(lv_event_get_target)(e)==o->root_)o->release();
 }catch(...){} }
 static void pressed(void*e)noexcept{try{
  auto*o=static_cast<StockNozzleScrub*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));
  if(!o||!o->rendered_||!o->visible())return;
  auto*target=stock_function<void*(*)(void*)>(lv_event_get_target)(e);const auto&v=o->view_;
  if(target==o->confirm_&&v.confirm_visible&&v.confirm_enabled&&o->on_confirm)o->on_confirm();
  else if(target==o->cancel_&&v.cancel_visible&&o->on_cancel)o->on_cancel();
  else if(target==o->back_&&v.back_visible&&o->on_back)o->on_back();
  else if(decisions(v)&&o->on_select)for(unsigned i=0;i<2;++i)if(target==o->options_[i].object)o->on_select(i==0);
 }catch(...){} }
};
}}
