// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "profile1113.hpp"
namespace wmp_ui { namespace native {
#ifdef WMP_NATIVE_TEST
void* test_stock_colour_picker(void*,int);
void* test_resolve(std::uintptr_t);
#endif
// Caller arms the existing colour/close hooks before constructing this modal.
// Only the constructor's temporary selected-colour byte changes; no vendor
// filament record or head mapping is written. Custom RGB has no selected tile.
inline void* open_stock_colour_picker(void*parent,int selected){
#ifdef WMP_NATIVE_TEST
 return test_stock_colour_picker(parent,selected);
#elif defined(__aarch64__)
 auto&colour=*reinterpret_cast<volatile unsigned char*>(0x3862f60);
 const auto saved=colour;colour=selected>=0?static_cast<unsigned char>(selected):255;
 reinterpret_cast<void(*)(void*)>(draw_colour_picker)(parent);colour=saved;
 return *reinterpret_cast<void*volatile*>(0x3862bc0);
#else
 (void)parent;(void)selected;return nullptr;
#endif
}
}}
