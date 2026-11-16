#include "native_renderer.hpp"
#include <cassert>
#include <map>
#include <vector>
#include <fstream>
#include <sstream>
#include <iostream>
using namespace wmp_openace;
struct Fake : NativeUi {
 struct O {void*parent;Event cb;void*ctx;std::uint64_t generation;bool hidden=false;std::string text;Rect r;O(void*p,Event e,void*c,std::uint64_t g):parent(p),cb(e),ctx(c),generation(g){} };
 std::map<void*,O> objects;int next=10,created=0,commands=0;std::int64_t clock=100;
 bool known=true,layout=true,modal=false,throw_text=false;void*display=(void*)1,*layer=(void*)2;
 Rect stop{300,420,479,479};std::string command;
 bool profile1113()const override{return known;}
 bool frame(Frame&f,void*)override {f={display,layer,{0,0,479,479},stop,layout,modal};return display&&layer;}
 void*create(void*p,Kind,Event cb,void*ctx,std::uint64_t g)override{void*h=(void*)(std::uintptr_t)next++;objects.emplace(h,O{p,cb,ctx,g});++created;return h;}
 void erase(void*h)override{auto i=objects.find(h);if(i==objects.end())return;auto o=i->second;objects.erase(i);o.cb(o.ctx,h,33,o.generation);std::vector<void*> children;for(auto&x:objects)if(x.second.parent==h)children.push_back(x.first);for(auto c:children)erase(c);}
 void rect(void*h,Rect r)override{objects.at(h).r=r;assert(!r.overlaps(stop));}
 void literal_text(void*h,const std::string&t)override{if(throw_text)throw 7;objects.at(h).text=t;}
 void hidden(void*h,bool b)override{objects.at(h).hidden=b;}
 void behind_stock(void*)override{}
 std::uint64_t enqueue(const std::string&c)override{++commands;command=c;return commands;}
 std::int64_t now_ms()const override{return clock;}
 void event(void*h,int code){auto o=objects.at(h);o.cb(o.ctx,h,code,o.generation);}
};
View pending(){View v;v.visible=v.connected=v.data_current=v.pending_confirmation=v.confirm_enabled=true;v.tool=3;v.serial=1;v.title="Change T3";v.from_label="Old PLA blue";v.to_label="New PLA gray";v.replacement_label="Actual PLA gray";v.context=std::string(64,'a');return v;}
int main(){
 Fake f; NativeRenderer r(f); auto v=pending();
 r.tick(v,100); f.event(r.badge(),7); r.tick(v,100);
 f.event(r.confirm(),1); f.event(r.confirm(),7); assert(f.commands==1);
 auto failed=v; failed.connected=false; failed.confirm_enabled=false; failed.error="request failed"; failed.serial=2;
 Delivery settled;settled.ticket=1;settled.status_generation=1;settled.outcome=Delivery::Unknown;
 r.tick(failed,100,settled,1);
 auto fresh=v; fresh.serial=3; r.tick(fresh,100,settled,2);
 f.event(r.confirm(),1); f.event(r.confirm(),7);
 if(f.commands!=2){std::cerr<<"confirmation remains disabled after failed request and fresh same-context status: commands="<<f.commands<<"\n";return 9;}
 return 0;
}
