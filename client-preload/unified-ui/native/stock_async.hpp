// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <memory>
namespace wmp_ui { namespace native {
// Verified stock LVGL returns 1 on successful queueing and 0 on allocation
// failure. Ownership moves to the callback only after successful queueing.
template<class T>bool queue_stock_async(int(*schedule)(void(*)(void*),void*),
                                      void(*callback)(void*),std::unique_ptr<T> data){
 if(schedule(callback,data.get())!=1)return false;
 data.release();return true;
}
}}
