// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include "../model.hpp"
#include <array>
#include <list>
#include <string>
#include <vector>
#include <functional>
#include <algorithm>
namespace wmp_ui { namespace native {
// Adds only the missing brand selector to each existing stock filament card.
// Widgets inherit the vendor button styles and font, and die with their cards.
class StockBrandControls {
public:
 void retire(){for(auto&row:rows_){row.armed=false;row.fresh=false;}current_.fill(nullptr);}
 std::function<bool(unsigned)> begin;
 std::function<void(unsigned,const std::string&)> choose;
 void update(unsigned head,void*card,const std::string&brand,
             const std::vector<std::string>&catalogue,bool fresh){
  if(head>=4)return;
  Row*row=current_[head];
  if(!row||row->card!=card){
   if(!fresh)return;
   rows_.push_back({this,head,card,nullptr,{},false,false});row=&rows_.back();
   row->object=stock_function<void*(*)(void*)>(lv_dropdown_create)(card);
   if(!row->object){rows_.pop_back();return;}
   current_[head]=row;
   stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(row->object,reinterpret_cast<void*>(0x463c8e8),0);
   stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(row->object,reinterpret_cast<void*>(0x463c8f8),0x20);
   stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(row->object,reinterpret_cast<void*>(lv_font_montserrat_14),0);
   stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(row->object,0xffeeeeeeU,0);
   if(!stock_function<void*(*)(void*,void(*)(void*),int,void*)>(lv_obj_add_event_cb)(row->object,&event,0,row)){
    stock_function<void(*)(void*)>(lv_obj_del)(row->object);current_[head]=nullptr;rows_.pop_back();return;
   }
  }
  row->fresh=fresh;
  if(!fresh){row->armed=false;stock_function<void(*)(void*,unsigned)>(lv_obj_add_state)(row->object,128);return;}
  stock_function<void(*)(void*,unsigned)>(lv_obj_clear_state)(row->object,128);
  const int width=stock_function<int(*)(void*)>(lv_obj_get_content_width)(card);
  const int height=stock_function<int(*)(void*)>(lv_obj_get_content_height)(card);
  // Material ends at Y164. Preserve an eight-pixel gap and a four-pixel
  // bottom inset even if a vendor style unexpectedly adds card padding.
  if(width<64||height<212){
   row->armed=false;stock_function<void(*)(void*,unsigned)>(lv_obj_add_flag)(row->object,1);return;
  }
  stock_function<void(*)(void*,unsigned)>(lv_obj_clear_flag)(row->object,1);
  stock_function<void(*)(void*,int,int)>(lv_obj_set_size)(row->object,width-16,36);
  stock_function<void(*)(void*,int,int,int)>(lv_obj_align)(row->object,1,8,height-40);
  if(stock_function<bool(*)(void*)>(lv_dropdown_is_open)(row->object))return;
  const auto options=brand_choices(catalogue,brand);
  if(options!=row->options){
   row->options=options;std::string text;
   for(const auto&value:options){if(!text.empty())text+='\n';text+=value;}
   stock_function<void(*)(void*,const char*)>(lv_dropdown_set_options)(row->object,text.c_str());
  }
  auto selected=std::find(options.begin(),options.end(),brand);
  stock_function<void(*)(void*,unsigned)>(lv_dropdown_set_selected)(row->object,selected==options.end()?0:unsigned(selected-options.begin()));
 }
private:
 struct Row{StockBrandControls*owner;unsigned head;void*card;void*object;std::vector<std::string>options;bool armed;bool fresh;};
 std::list<Row>rows_;std::array<Row*,4>current_{{nullptr,nullptr,nullptr,nullptr}};
 static void event(void*e)noexcept{
  try{
   auto*row=static_cast<Row*>(stock_function<void*(*)(void*)>(lv_event_get_user_data)(e));if(!row)return;
   auto*owner=row->owner;int code=stock_function<int(*)(void*)>(lv_event_get_code)(e);
   if(code==33){
    if(owner->current_[row->head]==row)owner->current_[row->head]=nullptr;
    for(auto it=owner->rows_.begin();it!=owner->rows_.end();++it)if(&*it==row){owner->rows_.erase(it);break;}
   }else if(owner->current_[row->head]!=row){return;
   }else if(code==31){ // Stock dropdown sends READY as its list opens.
    row->armed=row->fresh&&owner->begin&&owner->begin(row->head);
    if(!row->armed){stock_function<void(*)(void*)>(lv_dropdown_close)(row->object);return;}
    auto*list=stock_function<void*(*)(void*)>(lv_dropdown_get_list)(row->object);
    if(list){
     stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(list,reinterpret_cast<void*>(MyriadPro_Regular_16),0);
     stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_add_style)(list,reinterpret_cast<void*>(0x463c908),0);
     stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(list,0xff3c3e42U,0);
     stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(list,255,0);
     stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(list,0xffeeeeeeU,0);
    }
   }else if(code==28&&row->armed){ // VALUE_CHANGED, verified in stock dropdown.
    row->armed=false;unsigned index=stock_function<unsigned(*)(void*)>(lv_dropdown_get_selected)(row->object);
    if(row->fresh&&index<row->options.size()&&owner->choose)owner->choose(row->head,row->options[index]);
   }
  }catch(...){}
 }
};
}}
