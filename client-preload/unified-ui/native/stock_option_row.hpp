// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
#include "stock_dialog_backdrop.hpp"
#include <algorithm>
#include <string>
namespace wmp_ui { namespace native {
// Stable full-row touch target. Radio selection is optional: file pickers use
// the same geometry without claiming that a choice is already selected.
struct StockOptionRow {
 void*object=nullptr,*dot=nullptr,*title=nullptr,*detail=nullptr;
 static constexpr int gap=8,min_height=64,min_width=110;
 static void label(void*p,const std::string&text,std::uintptr_t font){
  stock_function<void(*)(void*,const char*)>(lv_label_set_text)(p,text.c_str());
  stock_function<void(*)(void*,const void*,unsigned)>(lv_obj_set_style_text_font)(p,reinterpret_cast<void*>(font),0);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_text_color)(p,0xffeeeeeeU,0);
  stock_function<void(*)(void*,int)>(lv_label_set_long_mode)(p,0);
 }
 static StockOptionRow create(void*parent,const std::string&text,const std::string&description,int x,int y,int width,int height=104,bool radio=true){
  StockOptionRow row;
  row.object=stock_function<void*(*)(void*)>(lv_obj_create)(parent);if(!row.object)return row;
  stock_dialog_backdrop(row.object);
  stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(row.object,0xff4a4d52U,0);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(row.object,255,0);
  stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_radius)(row.object,8,0);
  if(radio){
   auto*ring=stock_function<void*(*)(void*)>(lv_obj_create)(row.object);
   if(!ring){row.close();return row;}
   stock_dialog_backdrop(ring);stock_function<void(*)(void*,unsigned)>(lv_obj_clear_flag)(ring,2);
   stock_object_place(ring,16,12,32,32);
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_radius)(ring,16,0);
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_border_width)(ring,3,0);
   stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_border_color)(ring,0xffeeeeeeU,0);
   row.dot=stock_function<void*(*)(void*)>(lv_obj_create)(ring);
   if(!row.dot){row.close();return row;}
   stock_dialog_backdrop(row.dot);stock_function<void(*)(void*,unsigned)>(lv_obj_clear_flag)(row.dot,2);
   // Child positions start inside the ring's three-pixel border.
   stock_object_place(row.dot,5,5,16,16);
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_radius)(row.dot,8,0);
   stock_function<void(*)(void*,std::uint32_t,unsigned)>(lv_obj_set_style_bg_color)(row.dot,0xffff6600U,0);
   stock_function<void(*)(void*,int,unsigned)>(lv_obj_set_style_bg_opa)(row.dot,255,0);
  }
  row.title=stock_function<void*(*)(void*)>(lv_label_create)(row.object);
  row.detail=stock_function<void*(*)(void*)>(lv_label_create)(row.object);
  if(!row.title||!row.detail){row.close();return row;}
  label(row.title,text,MyriadPro_Regular_22);
  stock_function<void(*)(void*,int)>(lv_label_set_long_mode)(row.title,1); // Ellipsis for long names; never half a line.
  label(row.detail,description,MyriadPro_Regular_22);
  row.layout(x,y,width,height,!description.empty());row.select(false);return row;
 }
 void close(){auto*p=object;object=dot=title=detail=nullptr;if(stock_object_valid(p))stock_function<void(*)(void*)>(lv_obj_del)(p);}
 void layout(int x,int y,int width,int height,bool description=true)const{
  if(!stock_object_valid(object))return;
  width=std::max(int(min_width),width);height=std::max(description?96:min_height,height);
  stock_object_place(object,x,y,width,height);const int left=dot?64:12;
  stock_object_place(title,left,description?8:(height-MyriadPro_Regular_22_line_height)/2,width-left-12,MyriadPro_Regular_22_line_height);
  stock_object_place(detail,left,40,width-left-12,height-48);
  stock_function<void(*)(void*,unsigned)>(description?lv_obj_clear_flag:lv_obj_add_flag)(detail,1);
 }
 void select(bool selected)const{if(stock_object_valid(dot))stock_function<void(*)(void*,unsigned)>(selected?lv_obj_clear_flag:lv_obj_add_flag)(dot,1);}
};
}}
