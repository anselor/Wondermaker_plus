#include "native1113_port.hpp"
#include <cassert>
int main(int argc,char**argv){
 assert(argc==3);
 assert(wmp_openace::Native1113Port::profile_file_matches(argv[1]));
 assert(!wmp_openace::Native1113Port::profile_file_matches(argv[2]));
 int commands=0;wmp_openace::Native1113Port port([&](const std::string&){++commands;return true;});
 // Host executable is not reviewed ARM client: never call an absolute address.
 assert(!port.initialize()&&!port.profile1113());wmp_openace::Frame frame{};
 assert(!port.frame(frame,nullptr));
 bool refused=false;try{port.create(nullptr,wmp_openace::NativeUi::Root,nullptr,nullptr,1);}catch(...){refused=true;}
 assert(refused&&commands==0);port.erase(nullptr);
}
