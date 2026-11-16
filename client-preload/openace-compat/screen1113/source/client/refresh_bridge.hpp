#pragma once
#include <cstdint>
namespace wmp_openace {
// Portable callback boundary only. No hooks, LVGL objects, layout access or network.
// A native integration must construct this only AFTER exact loaded-profile checks.
class RefreshBridge {
public:
    typedef void (*Callback)(void*);
    RefreshBridge(Callback stock, Callback notify, bool verified_profile)
        :stock_(stock),notify_(notify),verified_(verified_profile) {}
    Callback select(Callback requested,std::uint32_t period,void* userdata,Callback wrapper) const noexcept {
        return verified_ && stock_ && wrapper && requested==stock_ && period==100 && !userdata
            ?wrapper:requested;
    }
    // The original refresh always runs first, on its original timer argument.
    // Exceptions may not unwind through the future native C callback boundary.
    void invoke(void* timer) const noexcept {
        if(!stock_)return;
        try {stock_(timer);} catch(...) {return;}
        if(verified_ && notify_)try {notify_(timer);} catch(...) {}
    }
private:
    Callback stock_,notify_;bool verified_;
};
}
