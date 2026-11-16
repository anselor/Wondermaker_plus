#pragma once
#include <string>
namespace wmp_ui { namespace native {
// Decide before the stock function edits its object list, quick-stops or clears
// recovery files. A confirmed other owner may retain the original route.
template<class Last,class Cancel,class Original>
void exclude_with_managed_cancel(const std::string&name,Last last,Cancel cancel,Original original){
 if(!name.empty()&&last(name)&&cancel())return;
 original();
}
}}
