// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
namespace wmp_ui { namespace native {
// The original preview constructor queues a global loading popup; its vendor
// colour callback subsequently replaces that popup. Managed preview owns its
// metadata presentation, so suppress only this constructor's popup request.
// Thread-local scope avoids suppressing unrelated worker-thread notifications.
class StockPreviewLoadingScope {
 static bool&managed(){static thread_local bool value=false;return value;}
 bool previous_;
public:
 explicit StockPreviewLoadingScope(bool enabled):previous_(managed()){managed()=enabled;}
 ~StockPreviewLoadingScope(){managed()=previous_;}
 StockPreviewLoadingScope(const StockPreviewLoadingScope&)=delete;
 StockPreviewLoadingScope&operator=(const StockPreviewLoadingScope&)=delete;
 static bool suppress(){return managed();}
};
}}
