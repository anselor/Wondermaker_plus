#pragma once
#include "native_renderer.hpp"
#include "main_layout.hpp"
#include <array>
#include <cstring>
#include <cstdio>
#include <stdexcept>
#include <time.h>
#include "native1113_windows.hpp"
#include "screen_diagnostics.hpp"
namespace wmp_openace {
// Exact static-LVGL ABI for the reviewed ET_EXEC client only. initialize() must
// run OFF the GUI thread before any callback registration. This installs no hook.
class Native1113Port : public NativeUi {
public:
 typedef std::function<std::uint64_t(const std::string&)> Queue;
 explicit Native1113Port(Queue queue):queue_(std::move(queue)){}
 bool initialize()noexcept {
  verified_=false;
#if defined(__aarch64__)
  try {
   if(!profile_file_matches("/proc/self/exe"))return false;
   for(const auto&w:native1113_windows)
    if(std::memcmp(reinterpret_cast<const void*>(w.address),w.bytes,32)){
     screen_diagnostics().address.store(w.address,std::memory_order_relaxed);return false;}
   verified_=true;
  }catch(...){verified_=false;}
#endif
  return verified_;
 }
 static bool profile_file_matches(const char*path)noexcept {
  FILE*f=std::fopen(path,"rb");if(!f)return false;
  unsigned char buf[65536];std::uint64_t hash=UINT64_C(0xcbf29ce484222325);std::size_t size=0,n;
  while((n=std::fread(buf,1,sizeof(buf),f))){size+=n;for(std::size_t i=0;i<n;++i)hash=(hash^buf[i])*UINT64_C(0x100000001b3);}
  bool ok=!std::ferror(f)&&size==61340216&&hash==UINT64_C(0x3ed764ac9cdaa82d);
  std::fclose(f);return ok;
 }
 bool profile1113()const override{return verified_;}
 bool frame(Frame&f,void*own_root)override {
  auto&diagnostic=screen_diagnostics();diagnostic.frame.store(1,std::memory_order_relaxed);
  if(!verified_)return false;
  auto display=call<void*(*)()>(0x6c3374)();
  diagnostic.frame.store(2,std::memory_order_relaxed);if(!display)return false;
  auto layer=call<void*(*)(void*)>(0x696650)(display);
  auto sys=call<void*(*)(void*)>(0x6966b8)(display);
  auto screen=call<void*(*)(void*)>(0x696550)(display);
  diagnostic.frame.store(3,std::memory_order_relaxed);if(!layer||!screen)return false;
  if(own_root&&!find(own_root))own_root=nullptr;
  call<void(*)(void*)>(0x6a3e00)(screen);
  diagnostic.frame.store(4,std::memory_order_relaxed);
  if(call<void*(*)()>(0x6c3374)()!=display||call<void*(*)(void*)>(0x696650)(display)!=layer)return false;
  auto main=*reinterpret_cast<void*volatile*>(0x386cec0);
  auto stop=*reinterpret_cast<void*volatile*>(0x386d038);
  auto print=*reinterpret_cast<void*volatile*>(0x386cec8);
  auto group=*reinterpret_cast<void*volatile*>(0x386d010);
  MainLayout layout;
  layout.main_current=main&&valid(main)&&descendant(main,screen);
  layout.main_visible=layout.main_current&&shown(main);
  layout.stop_owned=layout.main_current&&stop&&valid(stop)&&descendant(stop,main);
  layout.print_owned=layout.main_current&&print&&valid(print)&&descendant(print,main);
  layout.group_owned=layout.main_current&&group&&valid(group)&&descendant(group,main)
    &&layout.stop_owned&&descendant(stop,group);
  layout.stop_visible=layout.stop_owned&&shown(stop);
  layout.print_visible=layout.print_owned&&shown(print);
  layout.group_hidden=layout.group_owned&&call<bool(*)(void*,std::uint32_t)>(0x69f008)(group,1);
  f.display=display;f.layer=layer;f.viewport=coords(screen);
  if(layout.stop_owned)layout.stop=coords(stop);
  if(layout.print_owned)layout.print=coords(print);
  if(layout.group_owned)layout.group=coords(group);
  f.protected_valid=main_protected_regions(layout,f.viewport,f.protection);
  f.foreign_overlay=foreign(layer,own_root)||(sys&&foreign(sys,nullptr));
  const Rect rectangles[]={f.viewport,layout.print,layout.stop,layout.group,f.protection.rectangles[0]};
  for(unsigned i=0;i<5;++i){const auto&r=rectangles[i];const int values[]={r.x1,r.y1,r.x2,r.y2};
   for(unsigned j=0;j<4;++j)diagnostic.geometry[i*4+j].store(values[j],std::memory_order_relaxed);}
  diagnostic.layout_bits.store(int(layout.main_current)|(int(layout.main_visible)<<1)
    |(int(layout.stop_owned)<<2)|(int(layout.print_owned)<<3)|(int(layout.group_owned)<<4)
    |(int(layout.stop_visible)<<5)|(int(layout.print_visible)<<6)|(int(layout.group_hidden)<<7)
    |(int(f.protected_valid)<<8)|(int(f.foreign_overlay)<<9),std::memory_order_relaxed);
  diagnostic.frame.store(5,std::memory_order_relaxed);return true;
 }
 void*create(void*parent,Kind kind,Event cb,void*context,std::uint64_t generation)override {
  require();Binding*b=nullptr;
  for(auto&row:bindings_)if(!row.alive&&!row.in_callback){b=&row;break;}
  if(!b)throw std::runtime_error("native widget binding capacity reached");
  if(kind==Root){auto*d=call<void*(*)()>(0x6c3374)();
   if(!d||call<void*(*)(void*)>(0x696650)(d)!=parent)throw std::runtime_error("native parent layer changed");
  }else owned(parent);
  const auto address=kind==Label?0x6d96ac:kind==Button?0x6d4ca0:0x69ece0;
  void*object=call<void*(*)(void*)>(address)(parent);
  if(!object)throw std::runtime_error("native widget allocation failed");
  *b=Binding();b->owner=this;b->object=object;b->parent=parent;b->callback=cb;
  b->context=context;b->generation=generation;b->kind=kind;b->alive=true;
  try {
   call<void(*)(void*,std::uint32_t)>(0x69ed14)(object,1); // HIDDEN, before first draw.
   for(int code:{1,7,33})if(!call<void*(*)(void*,void(*)(void*),int,void*)>(0x697b38)(object,&native_event,code,b))
    throw std::runtime_error("native event registration failed");
   call<void(*)(void*,std::uint32_t)>(0x69ee58)(object,16); // Actual stock non-scrolling flag.
   for(auto a:{0x6add80,0x6addc0,0x6ade00,0x6ade40,0x6ae2b8})
    call<void(*)(void*,int,int)>(a)(object,0,0); // Owned widget padding/border only.
   return object;
  }catch(...){erase(object);throw;}
 }
 void erase(void*object)override {
  if(!verified_)return;
  auto*b=find(object);if(!b||!b->alive)return;
  const auto generation=b->generation;
  call<void(*)(void*)>(0x6aef1c)(object); // DELETE callback retires binding before reuse.
  if(b->object==object&&b->generation==generation)b->alive=false; // Also retire when registration itself failed before DELETE hook.
 }
 void rect(void*object,Rect desired)override {
  auto&b=owned(object);if(!desired.valid())throw std::runtime_error("invalid widget rectangle");
  NativeArea content{};
  call<void(*)(void*)>(0x6a3e00)(b.parent);
  call<void(*)(void*,NativeArea*)>(0x6a4d5c)(b.parent,&content);
  int sx=call<int(*)(void*)>(0x6a77bc)(b.parent),sy=call<int(*)(void*)>(0x6a7800)(b.parent);
  call<void(*)(void*,int,int)>(0x6a3318)(object,desired.x1-content.x1+sx,desired.y1-content.y1+sy);
  call<void(*)(void*,int,int)>(0x6a3aa4)(object,desired.width(),desired.height());
  call<void(*)(void*)>(0x6a3e00)(object);
  // Requested setter coordinates are NOT assumed to be rendered geometry.
  Rect actual=coords(object);
  if(actual.x1!=desired.x1||actual.y1!=desired.y1||actual.x2!=desired.x2||actual.y2!=desired.y2)
   throw std::runtime_error("native layout differs from protected widget rectangle");
  if(b.label){rect(b.label,desired);}
 }
 void literal_text(void*object,const std::string&text)override {
  auto&b=owned(object);void*label=object;
  if(b.kind==Button){
   if(!b.label){b.label=create(object,Label,nullptr,nullptr,b.generation);hidden(b.label,false);}
   label=b.label;rect(label,coords(object));
  }else if(b.kind!=Label)throw std::runtime_error("text requires an owned label/button");
  call<void(*)(void*,const char*)>(0x6d96e0)(label,text.c_str());
 }
 void hidden(void*object,bool value)override {
  auto&b=owned(object);call<void(*)(void*,std::uint32_t)>(value?0x69ed14:0x69ee58)(object,1);
  if(!value)observe_owned_widgets(b); // Read-only diagnostic postlude, never rendering authority.
 }
 void behind_stock(void*object)override {owned(object);call<void(*)(void*,int)>(0x6af3c4)(object,0);}
 std::uint64_t enqueue(const std::string&command)override{return queue_?queue_(command):0;}
 std::int64_t now_ms()const override {
  struct timespec t{};if(clock_gettime(CLOCK_MONOTONIC,&t))return -1;
  return std::int64_t(t.tv_sec)*1000+t.tv_nsec/1000000;
 }
private:
 struct NativeArea{std::int16_t x1,y1,x2,y2;};
 struct Binding{Native1113Port*owner=nullptr;void*object=nullptr,*parent=nullptr,*label=nullptr;
  Event callback=nullptr;void*context=nullptr;std::uint64_t generation=0;Kind kind=Root;bool alive=false,in_callback=false;};
 std::array<Binding,48>bindings_{};Queue queue_;bool verified_=false;
 template<class F>static F call(std::uintptr_t address){return reinterpret_cast<F>(address);}
 void require()const{if(!verified_)throw std::runtime_error("unsupported native client");}
 Binding*find(void*object){for(auto&b:bindings_)if(b.object==object&&b.alive)return &b;return nullptr;}
 Binding&owned(void*object){require();auto*b=find(object);if(!b)throw std::runtime_error("native widget lifetime ended");return *b;}
 // Called only on the GUI after an existing successful unhide. All tracked
 // descendants come from our live bindings; no arbitrary object is inspected.
 void observe_owned_widgets(const Binding&shown_binding)noexcept{
  try{
   const Binding*root=&shown_binding;
   for(unsigned depth=0;root&&root->kind!=Root&&depth<3;++depth)root=find(root->parent);
   if(!root||root->kind!=Root)return;
   auto&d=screen_diagnostics();for(auto&w:d.widgets)w.clear();
   const Binding*badge=nullptr;
   for(const auto&candidate:bindings_)if(candidate.alive&&candidate.parent==root->object&&candidate.kind==Button){badge=&candidate;break;}
   observe_widget(root->object,d.widgets[0]);
   if(badge){observe_widget(badge->object,d.widgets[1]);
    if(badge->label&&find(badge->label))observe_widget(badge->label,d.widgets[2]);}
   // Root creation verified this parent as the native top layer. Re-check the
   // actual parent before sampling it, rather than following an arbitrary chain.
   void*parent=call<void*(*)(void*)>(0x6af7bc)(root->object);
   if(parent&&parent==root->parent&&valid(parent))observe_widget(parent,d.widgets[3]);
  }catch(...){} // Diagnostics cannot change the renderer's exception/safety path.
 }
 static void observe_widget(void*object,DiagnosticWidget&out){
  const auto r=coords(object);const int values[]={r.x1,r.y1,r.x2,r.y2};
  for(unsigned i=0;i<4;++i)out.geometry[i].store(values[i],std::memory_order_relaxed);
  out.hidden.store(call<bool(*)(void*,std::uint32_t)>(0x69f008)(object,1),std::memory_order_relaxed);
  out.visible.store(call<bool(*)(void*)>(0x6a6198)(object),std::memory_order_relaxed);
  out.opacity.store(call<std::uint8_t(*)(void*,std::uint32_t)>(0x6aaacc)(object,0),std::memory_order_relaxed);
  out.recursive_opacity.store(call<std::uint8_t(*)(void*,std::uint32_t)>(0x6ac4d8)(object,0),std::memory_order_relaxed);
  out.background_opacity.store(call<std::uint8_t(*)(void*,std::uint32_t)>(0x69e868)(object,0),std::memory_order_relaxed);
  out.text_opacity.store(call<std::uint8_t(*)(void*,std::uint32_t)>(0x6a1cc0)(object,0),std::memory_order_relaxed);
  out.font_present.store(call<void*(*)(void*,std::uint32_t)>(0x6a1cf4)(object,0)!=nullptr,std::memory_order_relaxed);
 }
 static Rect coords(void*object){NativeArea a{};call<void(*)(void*,NativeArea*)>(0x6a496c)(object,&a);return Rect(a.x1,a.y1,a.x2,a.y2);}
 static bool valid(void*object){return call<bool(*)(void*)>(0x69f284)(object);}
 static bool shown(void*object){
  for(int n=0;object&&n<64;++n){
   if(call<bool(*)(void*,std::uint32_t)>(0x69f008)(object,1))return false;
   object=call<void*(*)(void*)>(0x6af7bc)(object);
  }return !object;
 }
 static bool descendant(void*object,void*ancestor){
  for(int n=0;object&&n<64;++n){if(object==ancestor)return true;object=call<void*(*)(void*)>(0x6af7bc)(object);}return false;
 }
 static bool foreign(void*layer,void*own){
  auto count=call<std::uint32_t(*)(void*)>(0x6af89c)(layer);if(count>256)return true;
  for(std::uint32_t i=0;i<count;++i){void*child=call<void*(*)(void*,int)>(0x6af7e8)(layer,int(i));
   if(child&&child!=own&&shown(child))return true;
  }return false;
 }
 static void native_event(void*event)noexcept {
  try {
   auto*b=static_cast<Binding*>(call<void*(*)(void*)>(0x697a30)(event));
   if(!b||!b->alive||!b->owner||!b->owner->verified_)return;
   auto*target=call<void*(*)(void*)>(0x6979e4)(event);if(target!=b->object)return;
   const auto code=call<int(*)(void*)>(0x6979fc)(event);
   b->in_callback=true;
   if(code==33){b->alive=false;for(auto&p:b->owner->bindings_)if(p.alive&&p.label==target)p.label=nullptr;}
   if(b->callback)try{b->callback(b->context,target,code,b->generation);}catch(...){}
   b->in_callback=false;
  }catch(...){} // Native C dispatch must never receive a C++ exception.
 }
};
}
