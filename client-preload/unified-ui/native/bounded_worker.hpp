// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <condition_variable>
#include <functional>
#include <map>
#include <mutex>
#include <thread>
namespace wmp_ui { namespace native {
// One executing task and at most four keyed pending tasks. Repeated scheduling
// replaces pending work, never grows a queue or retries a failed transport.
class BoundedWorker {
 std::mutex mutex_;std::condition_variable wake_;bool quit_=false;
 std::map<unsigned,std::function<void()>> pending_;std::thread thread_;
 void run(){for(;;){std::function<void()>work;{std::unique_lock<std::mutex>lock(mutex_);wake_.wait(lock,[this]{return quit_||!pending_.empty();});if(quit_)return;auto next=pending_.begin();work=std::move(next->second);pending_.erase(next);}try{work();}catch(...){}}}
public:
 BoundedWorker():thread_([this]{run();}){}
 void request_stop(){{std::lock_guard<std::mutex>lock(mutex_);quit_=true;pending_.clear();}wake_.notify_all();}
 ~BoundedWorker(){request_stop();thread_.join();}
 bool submit(unsigned key,std::function<void()>work){std::lock_guard<std::mutex>lock(mutex_);if(quit_||key>=4)return false;pending_[key]=std::move(work);wake_.notify_one();return true;}
};
}}
