#include "native/calibration_cancel_worker.hpp"
#include <cassert>
#include <chrono>
using namespace wmp_ui;using namespace wmp_ui::native;
struct Http:wmp_openace::HttpPort{
 std::mutex mutex;std::condition_variable wake;bool entered=false,released=false,lost=false,mismatch=false,identification=false;unsigned calls=0;Json payload;
 std::string get(const std::string&)override{assert(false);return {};}
 std::string post(const std::string&path,const std::string&body)override{
  std::unique_lock<std::mutex>lock(mutex);assert(path==(identification?"/printer/wmp/identification/cancel":"/printer/wmp/calibration/cancel"));
  ++calls;payload=Json::parse(body);entered=true;wake.notify_all();wake.wait(lock,[this]{return released;});
  if(lost)throw std::runtime_error("reply lost");
  auto result=payload;result["state"]="requested";if(mismatch){if(identification)result["request"]=std::string(32,'f');else result["ticket"]="9";}
  return Json{{"result",result}}.dump();
 }
 void wait(){std::unique_lock<std::mutex>lock(mutex);assert(wake.wait_for(lock,std::chrono::seconds(3),[this]{return entered;}));}
 void release(){std::lock_guard<std::mutex>lock(mutex);released=true;wake.notify_all();}
};
int main(){
 const Json binding={{"session",std::string(32,'a')},{"request",std::string(32,'b')},{"ticket","1"}};
 for(bool identification:{false,true})for(unsigned mode=0;mode<3;++mode){
  auto request=binding;if(identification)request.erase("ticket");
  Http http;http.identification=identification;http.lost=mode==1;http.mismatch=mode==2;
  CalibrationCancelWorker worker(http);
  assert(!worker.request(Json::object()));
  auto send=[&](const Json&r){return identification?worker.request_identification(r):worker.request(r);};
  assert(send(request));http.wait();
  assert(send(request)&&http.calls==1); // no duplicate POST
  auto other=request;other["request"]=std::string(32,'c');assert(!send(other));
  assert(worker.result()["delivery_pending"]==true);
  http.release();
  const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
  while(worker.result()["delivery_pending"]==true&&std::chrono::steady_clock::now()<deadline)std::this_thread::yield();
  assert(worker.result()["delivery_pending"]==false);
  assert(worker.result()["acknowledged"]==(mode==0));
  if(mode)assert(worker.result()["message"].get<std::string>().find("unconfirmed")!=std::string::npos);
  for(unsigned i=0;i<10;++i)assert(send(request));
  assert(http.calls==1); // a timeout/mismatched receipt never retries/falls back
 }
}
