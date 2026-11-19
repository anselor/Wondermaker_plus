// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "stock_api.hpp"
namespace wmp_ui { namespace native {
// Vendor maintenance selection and offset-stage result, read and written only
// through the profile's data entries (docs/nozzle-scrub.md). Tests substitute
// plain storage through test_resolve.
struct ScrubVendor {
 volatile unsigned char*rapid;            // is_rapid_mode: 1 Rapid, 0 Accurate
 const volatile unsigned char*selected;   // auto_check_selected[4]; [3] is offset calibration
 const volatile std::uint32_t*heads;      // current_thr_number
 volatile unsigned char*failed;           // knife_pairing_failed
};
template<class T>inline T*nozzle_scrub_vendor_data(std::uintptr_t address){
#ifdef WMP_NATIVE_TEST
 return static_cast<T*>(test_resolve(address));
#else
 return reinterpret_cast<T*>(address);
#endif
}
inline ScrubVendor nozzle_scrub_vendor(){
 return {nozzle_scrub_vendor_data<volatile unsigned char>(is_rapid_mode),nozzle_scrub_vendor_data<const volatile unsigned char>(auto_check_selected),
  nozzle_scrub_vendor_data<const volatile std::uint32_t>(current_thr_number),nozzle_scrub_vendor_data<volatile unsigned char>(knife_pairing_failed)};
}
}}
