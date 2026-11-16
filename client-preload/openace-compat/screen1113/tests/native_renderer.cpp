#include "native_renderer.hpp"
#include <cassert>
#include <map>
#include <vector>
#include <fstream>
#include <sstream>
#include <iostream>
using namespace wmp_openace;
struct Fake : NativeUi {
 struct O {void*parent;Event cb;void*ctx;std::uint64_t generation;bool hidden=true;std::string text;Rect r;O(void*p,Event e,void*c,std::uint64_t g):parent(p),cb(e),ctx(c),generation(g){} };
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
int main(int argc,char**argv){
 if(argc==2){std::ifstream in(argv[1]);std::ostringstream text;text<<in.rdbuf();
  ScreenModel model;if(!model.update(text.str(),true,100))return 2;
  Fake fake;NativeRenderer renderer(fake);renderer.tick(model.view(),100);
  if(!renderer.badge())return 3;
  fake.event(renderer.badge(),7);renderer.tick(model.view(),100);
  if(!renderer.confirm())return 4;
  fake.event(renderer.confirm(),1);fake.event(renderer.confirm(),7);
  if(fake.commands!=1)return 5;
  std::cout<<fake.command;return 0;
 }

 Fake f;NativeRenderer r(f);auto v=pending();r.tick(v,100);assert(f.created==2 && r.visible()&&!r.expanded());
 auto badge=r.badge();assert(!f.objects.at(badge).hidden);f.event(badge,7);assert(r.expanded());r.tick(v,100);assert(r.confirm());
 assert(!f.objects.at(r.root()).r.overlaps(f.stop));
 f.event(r.confirm(),1);f.event(r.confirm(),7);assert(f.commands==1 && f.command=="OPENACE_CONFIRM_CHANGE TOOL=3 CONFIRM=1 EXPECT_CONTEXT="+std::string(64,'a'));
 f.event(r.confirm(),7);assert(f.commands==1); // No repeated delivery before backend refresh.
 auto oldroot=r.root();auto old=f.objects.at(oldroot);f.erase(oldroot);assert(!r.root());
 r.tick(v,100);assert(r.root() && r.root()!=oldroot);
 old.cb(old.ctx,oldroot,7,old.generation);assert(!r.expanded() && f.commands==1);
 // Session/layer replacement abandons old handles without touching a possibly new native layer.
 auto prior_root=r.root();f.layer=(void*)3;r.tick(v,100);assert(!r.expanded());assert(!f.objects.count(prior_root));
 auto deleted_badge=r.badge();f.erase(deleted_badge);r.tick(v,100);assert(r.badge()&&r.badge()!=deleted_badge);
 f.modal=true;r.tick(v,100);assert(!r.visible() && f.objects.at(r.root()).hidden && f.commands==1);
 f.event(r.badge(),7);assert(!r.expanded() && f.commands==1);
 f.modal=false;f.layout=false;r.tick(v,100);assert(!r.visible() && f.objects.at(r.root()).hidden);
 f.event(r.badge(),7);assert(!r.expanded() && f.commands==1);
 f.layout=true;f.stop={0,0,479,479};r.tick(v,100);assert(!r.visible());
 f.stop={300,420,479,479};r.tick(v,100);f.event(r.badge(),7);r.tick(v,100);auto button=r.confirm();
 f.event(button,1);v.serial=2;v.context=std::string(64,'b');r.tick(v,100);f.event(button,7);assert(f.commands==1);
 // Only a newly pressed current display can queue the new context.
 f.event(r.confirm(),1);f.clock=2201;f.event(r.confirm(),7);assert(f.commands==1);
 f.clock=100;r.tick(v,100);v.confirm_enabled=false;r.tick(v,100);f.event(r.confirm(),1);f.event(r.confirm(),7);assert(f.commands==1);
 v.visible=false;r.tick(v,100);assert(!r.visible() && !r.root());
 Fake unknown;unknown.known=false;NativeRenderer passthrough(unknown);passthrough.tick(pending(),100);assert(unknown.created==0);
 Fake broken;NativeRenderer safe(broken);safe.tick(pending(),100);broken.throw_text=true;safe.tick(pending(),100);assert(!safe.visible());
 return 0;
}
