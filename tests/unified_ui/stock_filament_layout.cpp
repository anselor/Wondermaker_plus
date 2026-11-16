#include "native/stock_filament_page.hpp"
#include <cassert>
#include <map>
using namespace wmp_ui::native;
struct Fake:StockGeometryPort {
 std::map<void*,void*> parents;std::vector<StockPlacement> writes;
 bool valid(void*p)const override{return parents.count(p);}
 void*parent(void*p)const override{return parents.at(p);}
 void place(void*p,StockRect r)override{writes.push_back({p,r});}
};
int main(){
 int objects[32]{};Fake p;StockFilamentWidgets v;v.content=&objects[0];v.count=4;
 p.parents[v.content]=&objects[31];p.parents[&objects[31]]=nullptr;
 for(unsigned i=0;i<4;++i){auto&s=v.slots[i];int k=1+i*5;
  s.card=&objects[k];s.number=&objects[k+1];s.colour=&objects[k+2];
  s.material=&objects[k+3];s.material_label=&objects[k+4];
  p.parents[s.card]=v.content;p.parents[s.number]=p.parents[s.colour]=p.parents[s.material]=s.card;
  p.parents[s.material_label]=s.material;
 }
 auto plan=external_filament_columns(v,p,670,340);assert(plan.size()==20);assert(p.writes.empty());
 apply_stock_geometry(plan,p);assert(p.writes.size()==20);
 for(unsigned i=0;i<4;++i){const auto&r=plan[i*5].bounds;assert(r.y==40);assert(r.x>=0&&r.x+r.w<=670);assert(r.y+r.h<=340-48);if(i)assert(r.x>=plan[(i-1)*5].bounds.x+plan[(i-1)*5].bounds.w+8);}
 for(auto&w:p.writes)assert(w.object!=v.content&&w.object!=&objects[31]);
 // Keep the stock image's intrinsic 83px bounds; sizing to 70 clips it.
 for(unsigned i=0;i<4;++i){const auto&swatch=plan[i*5+2].bounds;const auto&material=plan[i*5+3].bounds;
  assert(swatch.w==83&&swatch.h==83&&swatch.y+swatch.h<=material.y);
 }
 auto rejects=[&](){try{external_filament_columns(v,p,670,340);assert(false);}catch(const std::runtime_error&){}assert(p.writes.size()==20);};
 p.parents[v.slots[3].colour]=v.content;rejects();p.parents[v.slots[3].colour]=v.slots[3].card;
 auto saved=v.slots[3].material_label;v.slots[3].material_label=v.slots[0].material_label;rejects();v.slots[3].material_label=saved;
 p.parents.erase(v.slots[3].number);rejects();
 v.count=1;assert(external_filament_columns(v,p,670,340).size()==5);
 StockFilamentPage page;
 auto first=page.created(v,&objects[31]);
 assert(!page.apply(p,&objects[31],670,340,false,true)); // stale
 assert(!page.apply(p,&objects[31],670,340,true,false)); // ACE / unknown owner
 assert(!page.apply(p,&objects[30],670,340,true,true)); // other page
 assert(p.writes.size()==20);
 assert(page.apply(p,&objects[31],670,340,true,true));assert(p.writes.size()==25);
 assert(!page.apply(p,&objects[31],670,340,true,true)); // not on every timer
 auto next=page.created(v,&objects[31]); // reused address with new lifetime
 page.deleted(first);assert(page.active());
 assert(page.apply(p,&objects[31],670,340,true,true));assert(p.writes.size()==30);
 page.deleted(next);assert(!page.active());
 assert(!page.apply(p,&objects[31],670,340,true,true));
 page.created(v,&objects[31]);p.parents[v.content]=&objects[30];
 assert(!page.apply(p,&objects[31],670,340,true,true));assert(!page.active());
 p.parents[v.content]=&objects[31];p.writes.resize(20);
 v.count=0;rejects();
}
