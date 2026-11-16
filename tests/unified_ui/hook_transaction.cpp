#include "native/hook_transaction.hpp"
#include <cassert>
#include <array>
#include <cstring>
#include <stdexcept>
#include <vector>
using namespace wmp_ui::native;
struct Memory {
 alignas(64) unsigned char bytes[64*43];
 std::array<bool,43> writable{};
 int calls=0,fail_acquire=-1,fail_restore=-1,failures=0;
 std::vector<std::uintptr_t> flushed;
 Memory(){std::memset(bytes,0x5a,sizeof(bytes));}
 bool protect(std::uintptr_t address,std::size_t size,bool write){
  assert(size==64);auto i=(address-reinterpret_cast<std::uintptr_t>(bytes))/64;
  assert(i<43);
  if(write){if(calls++==fail_acquire)return false;}
  else if(int(i)==fail_restore)return false;
  writable[i]=write;return true;
 }
 void flush(std::uintptr_t address,std::size_t size){
  assert(size==16);auto first=(address-reinterpret_cast<std::uintptr_t>(bytes))/64;
  auto last=(address+15-reinterpret_cast<std::uintptr_t>(bytes))/64;
  assert(writable[first]&&writable[last]);flushed.push_back(address);
 }
 void failure(const char*,std::uintptr_t){++failures;}
 void pristine(){for(auto c:bytes)assert(c==0x5a);}
 void rx(){for(bool w:writable)assert(!w);}
};
static void add_entries(HookTransaction<Memory,42>&t,Memory&m){
 unsigned char jump[16];std::memset(jump,0xe1,16);
 for(unsigned i=0;i<42;++i)
  assert(t.add(reinterpret_cast<std::uintptr_t>(m.bytes)+i*64+56,jump));
}
int main(){
 // Every acquisition failure leaves all 42 original entries unchanged, also
 // when entries cross pages and share protection regions with another hook.
 for(int fail=0;fail<43;++fail){Memory m;m.fail_acquire=fail;
  {HookTransaction<Memory,42>t(m,64);add_entries(t,m);assert(!t.prepare());}
  m.pristine();m.rx();assert(m.flushed.empty());assert(m.failures==1);
 }
 // Fail after each installed prefix, including all hooks before a failed
 // worker creation. Reverse restoration must precede permission restoration.
 for(int prefix=0;prefix<=42;++prefix){Memory m;
  {HookTransaction<Memory,42>t(m,64);add_entries(t,m);assert(t.prepare());
   for(int i=0;i<prefix;++i)assert(t.patch_next());
   assert(t.rollback());}
  m.pristine();m.rx();assert(m.flushed.size()==std::size_t(prefix*2));
  for(int i=0;i<prefix;++i)assert(m.flushed[i]==m.flushed[prefix*2-1-i]);
 }
 // Exception unwinding uses the same rollback, without another RWX request.
 {Memory m;try{HookTransaction<Memory,42>t(m,64);add_entries(t,m);assert(t.prepare());
   assert(t.patch_next());throw std::runtime_error("startup");
  }catch(const std::runtime_error&){}m.pristine();m.rx();assert(m.calls==43);}
 // Successful worker startup commits every patch and returns pages to RX.
 {Memory m;{HookTransaction<Memory,42>t(m,64);add_entries(t,m);assert(t.prepare());
   while(t.patch_next()){}assert(t.commit());}m.rx();assert(m.flushed.size()==42);
  for(unsigned i=0;i<42;++i)for(unsigned j=0;j<16;++j)assert(m.bytes[i*64+56+j]==0xe1);}
 // RX restoration failure is returned and reported, not described as success.
 // It does not prevent other pages being restored, or undo committed hooks.
 for(bool commit:{false,true}){Memory m;m.fail_restore=10;
  {HookTransaction<Memory,42>t(m,64);add_entries(t,m);assert(t.prepare());
   while(t.patch_next()){}assert(!(commit?t.commit():t.rollback()));}
  assert(m.failures==1);for(unsigned i=0;i<43;++i)assert(m.writable[i]==(i==10));
  if(!commit)m.pristine();
 }
}
