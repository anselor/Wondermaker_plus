// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_progress_panel.hpp"
namespace wmp_ui { namespace native {
inline Json resume_progress_view(const Json&data){
 Json view={{"title","Resuming paused print"},{"steps",Json::array()}};
 if(!data.value("fresh",false)){view["instruction"]="Waiting for printer status...";return view;}
 const auto phase=data.value("resume_progress",Json::object()).value("phase","");
 if(phase.empty()){view["instruction"]="Preparing to resume...";return view;}
 if(phase=="toolchange"){view["instruction"]="Retrying tool change...";return view;}
 const bool preheating=phase=="preheating";
 const int active=phase=="checking"?0:(phase=="heating"||preheating)?1:phase=="returning"?2:-1;
 if(active<0)return view;
 const char*steps[]={"Check printer","Heat bed and nozzle","Return to print"};
 for(int i=0;i<3;++i)view["steps"].push_back({{"label",steps[i]},{"state",i==active?"running":i<active&&!preheating?"complete":"pending"}});
 if(active==1){
  std::string temperatures;
  for(const auto&head:data.value("heads",Json::array())){
   const auto target=head.value("target",0.0);const auto id=head.value("id","");
   if(target>0&&id.size()==2&&id[0]=='h'&&id[1]>='0'&&id[1]<='3'){
    if(!temperatures.empty())temperatures+='\n';
    temperatures+="Head "+std::to_string(id[1]-'0'+1)+": "+std::to_string(int(head.value("actual",0.0)))+" / "+std::to_string(int(target))+" C";
   }
  }
  view["heading"]="Heating bed and nozzles";
  view["value"]=temperatures;
 }
 return view;
}
// The vendor owns the containing popup and its removal. The shared panel is
// its child; deletion clears all retained widgets. No command or busy flag.
class StockResumeProgress {
 StockProgressPanel panel_;
public:
 void update(const Json&data){
 if(data.value("owner","")!="standalone"){panel_.close();return;}
 if(panel_.attached()){panel_.update(resume_progress_view(data));return;}
 auto fn_valid=button_caption_fn<bool(*)(void*)>(lv_obj_is_valid);
 auto*top=button_caption_fn<void*(*)(void*)>(lv_disp_get_layer_top)(nullptr);
 if(!fn_valid(top))return;
 struct Item{void*node;unsigned depth;};Item pending[64];unsigned count=1,visited=0;pending[0]={top,0};
 while(count&&visited++<64){
  const auto item=pending[--count];auto*n=item.node;
  if(!fn_valid(n)||button_caption_fn<bool(*)(void*,unsigned)>(lv_obj_has_flag)(n,1))continue;
  if(button_caption_fn<bool(*)(void*,const void*)>(lv_obj_check_type)(n,reinterpret_cast<const void*>(lv_label_class))){
   const char*raw=button_caption_fn<const char*(*)(void*)>(lv_label_get_text)(n);
   const std::string old=raw?raw:"";
   if(old=="Resuming print..."){
    auto*parent=button_caption_fn<void*(*)(void*)>(lv_obj_get_parent)(n);
    // The stock label sits in a short animation/content row. Use the
    // containing popup so all three steps fit at the readable text size.
    for(unsigned depth=0;depth<3&&fn_valid(parent);++depth){
     if(button_caption_fn<int(*)(void*)>(lv_obj_get_content_height)(parent)>=240)break;
     auto*ancestor=button_caption_fn<void*(*)(void*)>(lv_obj_get_parent)(parent);
     if(!fn_valid(ancestor)||ancestor==top)break;
     parent=ancestor;
    }
    const int width=button_caption_fn<int(*)(void*)>(lv_obj_get_content_width)(parent);
    const int height=button_caption_fn<int(*)(void*)>(lv_obj_get_content_height)(parent);
    if(panel_.attach(parent,0,0,width,height))panel_.update(resume_progress_view(data));
    return;
   }
  }
  if(item.depth>=4)continue;
  const auto children=button_caption_fn<unsigned(*)(void*)>(lv_obj_get_child_cnt)(n);
  for(unsigned i=0;i<children&&count<64;++i)pending[count++]={button_caption_fn<void*(*)(void*,int)>(lv_obj_get_child)(n,int(i)),item.depth+1};
 }
 }
};
}}
