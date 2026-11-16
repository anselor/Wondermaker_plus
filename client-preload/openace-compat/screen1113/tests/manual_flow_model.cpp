#include "manual_flow.hpp"
#include <fstream>
#include <cassert>
using namespace wmp_openace;
int main(int argc,char**argv){assert(argc==2);std::ifstream in(argv[1]);json status;in>>status;ManualFlowModel m;m.update(status,true,1,Delivery(),"");assert(m.view().visible);assert(m.view().title.find("h0")!=std::string::npos);assert(m.command("prepare").find("OPENACE_LOAD_DIRECT HEAD=\"h0\"")==0);}
