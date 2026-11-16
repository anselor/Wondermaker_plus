#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace wmp_ui { namespace native {
// Startup-only transaction. No entry is changed until every affected page is
// writable. Keep those permissions until commit/rollback so rollback itself
// never needs a fallible writable-protection syscall. Published trampolines
// are deliberately outside this owner: an in-flight callback may use one.
template<class Ops, std::size_t Capacity=41> class HookTransaction {
 struct Entry {std::uintptr_t address;unsigned char saved[16],replacement[16];};
 Ops&ops_;std::size_t page_size_,count_=0,pages_count_=0,writable_=0,changed_=0;
 std::array<Entry,Capacity> entries_{};
 std::array<std::uintptr_t,Capacity*2> pages_{};
 bool prepared_=false,finished_=false;
 bool restore_permissions()noexcept {
  bool ok=true;
  while(writable_){const auto page=pages_[--writable_];
   if(!ops_.protect(page,page_size_,false)){ops_.failure("restore RX",page);ok=false;}}
  return ok;
 }
public:
 HookTransaction(Ops&ops,std::size_t page_size):ops_(ops),page_size_(page_size){}
 ~HookTransaction(){if(!finished_)rollback();}
 HookTransaction(const HookTransaction&)=delete;
 HookTransaction&operator=(const HookTransaction&)=delete;
 bool add(std::uintptr_t address,const void*replacement)noexcept {
  if(prepared_||finished_||count_==Capacity||page_size_<16)return false;
  auto&e=entries_[count_++];e.address=address;
  std::memcpy(e.saved,reinterpret_cast<void*>(address),16);
  std::memcpy(e.replacement,replacement,16);
  const auto first=address-address%page_size_,last=(address+15)-(address+15)%page_size_;
  for(auto page=first;;page+=page_size_){
   bool known=false;for(std::size_t i=0;i<pages_count_;++i)if(pages_[i]==page)known=true;
   if(!known)pages_[pages_count_++]=page;
   if(page==last)break;
  }
  return true;
 }
 bool prepare()noexcept {
  if(prepared_||finished_)return false;
  for(;writable_<pages_count_;++writable_)
   if(!ops_.protect(pages_[writable_],page_size_,true)){
    ops_.failure("acquire RWX",pages_[writable_]);return false;}
  prepared_=true;return true;
 }
 bool patch_next()noexcept {
  if(!prepared_||finished_||changed_==count_)return false;
  auto&e=entries_[changed_++];std::memcpy(reinterpret_cast<void*>(e.address),e.replacement,16);
  ops_.flush(e.address,16);return true;
 }
 bool commit()noexcept {
  if(!prepared_||finished_||changed_!=count_)return false;
  finished_=true;return restore_permissions();
 }
 bool rollback()noexcept {
  if(finished_)return true;
  while(changed_){auto&e=entries_[--changed_];
   std::memcpy(reinterpret_cast<void*>(e.address),e.saved,16);ops_.flush(e.address,16);}
  finished_=true;return restore_permissions();
 }
};
}}
