#include "native1113_port.hpp"
extern "C" int wmp_native_ui_probe_only(){
 wmp_openace::Native1113Port port(wmp_openace::Native1113Port::Queue{});
 return port.initialize()?1:0;
}
