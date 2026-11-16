#include "refresh_bridge.hpp"
#include <cassert>
#include <stdexcept>
using wmp_openace::RefreshBridge;
int order=0;void* argument=nullptr;
void stock(void* p){assert(order==0);order=1;argument=p;}
void notify(void* p){assert(order==1 && p==argument);order=2;}
void other(void*){}void wrapper(void*){}
void raising(void*){throw std::runtime_error("entry boundary");}
int main(){
 int timer=0,data=0;RefreshBridge good(stock,notify,true),unknown(stock,notify,false);
 assert(good.select(stock,100,nullptr,wrapper)==wrapper);
 assert(good.select(stock,101,nullptr,wrapper)==stock);
 assert(good.select(stock,100,&data,wrapper)==stock);
 assert(good.select(other,100,nullptr,wrapper)==other);
 assert(unknown.select(stock,100,nullptr,wrapper)==stock);
 good.invoke(&timer);assert(order==2 && argument==&timer);
 order=0;unknown.invoke(&timer);assert(order==1);
 order=0;RefreshBridge(stock,raising,true).invoke(&timer);assert(order==1);
 order=0;RefreshBridge(raising,notify,true).invoke(&timer);assert(order==0);
}
