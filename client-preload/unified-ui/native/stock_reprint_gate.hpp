// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <string>
namespace wmp_ui { namespace native {
// GUI-thread state for the completed/stopped stock popups. The caller must
// validate LVGL lifetime/visibility and the file path before arming. Requests
// carry a generation so a queued callback cannot borrow a newer popup's file.
class StockReprintGate {
public:
 enum class Action { Delegate, Consume, Review };
 struct Request { std::uint64_t generation=0; std::string path; };
 void begin(int kind) {
  ++generation_;kind_=kind;button_=nullptr;path_.clear();claimed_=false;
 }
 bool arm(void*button,const std::string&path,bool valid_context) {
  if(!is_reprint_kind(kind_)||!button||path.empty()||!valid_context)return false;
  button_=button;path_=path;return true;
 }
 Action event(int kind,int code,void*target,void*current_reprint_button,
              bool live_context,Request&request) {
  request=Request{};
  if(!is_reprint_kind(kind))return Action::Delegate;
  // Non-click events have no vendor action. Stale popup clicks must never
  // reach the vendor prefix, including when button storage has been reused.
  if(code!=7)return Action::Consume;
  if(kind!=kind_||!live_context)return Action::Consume;
  if(button_&&current_reprint_button!=button_)return Action::Consume;
  // Preserve the current popup's ordinary OK/Close action. The adapter must
  // establish membership in this popup before passing live_context=true.
  if(target!=current_reprint_button){invalidate();return Action::Delegate;}
  if(!button_||target!=button_||claimed_||path_.empty())return Action::Consume;
  claimed_=true;request.generation=generation_;request.path=path_;
  return Action::Review;
 }
 bool pending(const Request&request)const {
  return claimed_&&request.generation&&request.generation==generation_&&request.path==path_;
 }
 bool take(const Request&request){if(!pending(request))return false;invalidate();return true;}
 void invalidate(){begin(0);}
private:
 static bool is_reprint_kind(int kind){return kind==5||kind==6;}
 std::uint64_t generation_=0;int kind_=0;void*button_=nullptr;
 std::string path_;bool claimed_=false;
};
}}
