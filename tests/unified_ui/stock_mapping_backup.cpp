#include "native/stock_mapping_backup.hpp"
#include <cassert>
using wmp_ui::native::suppress_stock_mapping_backup;
int main(){
 for(unsigned head=0;head<4;++head){
  const auto i=std::to_string(head);
  const auto command="SAVE_VARIABLE VARIABLE=box_modify_t"+i+"_backup VALUE="+i;
  assert(suppress_stock_mapping_backup(0x63dc20,command,true));
  assert(!suppress_stock_mapping_backup(0x63dc20,command,false));
  assert(!suppress_stock_mapping_backup(0x63dc1c,command,true));
  assert(!suppress_stock_mapping_backup(0,command,true));
  assert(!suppress_stock_mapping_backup(0x63dc20,command+"\nG28",true));
  assert(!suppress_stock_mapping_backup(0x63dc20,command+"\n",true));
  assert(!suppress_stock_mapping_backup(0x63dc20,"SAVE_VARIABLE VARIABLE=box_modify_t"+i+"_backup VALUE="+std::to_string((head+1)%4),true));
 }
 assert(!suppress_stock_mapping_backup(0x63dc20,"SAVE_VARIABLE VARIABLE=box_modify_t0 VALUE=0",true));
 assert(!suppress_stock_mapping_backup(0x63dc20,"SAVE_VARIABLE VARIABLE=box_modify_t4_backup VALUE=4",true));
 assert(!suppress_stock_mapping_backup(0x63dc20,"CANCEL_PRINT",true));
}
