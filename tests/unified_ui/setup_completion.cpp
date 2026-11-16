#include "native/setup_completion.hpp"
#include <cassert>
#include <string>
#include <sys/stat.h>

struct Faults {
 std::string calls;
 int open_error=0,remove_error=0,sync_error=0,close_error=0;
 bool interrupted=false;
 int open_directory(const char*){calls+='o';errno=open_error;return open_error?-1:17;}
 int remove_marker(int fd){assert(fd==17);calls+='u';errno=remove_error;return remove_error?-1:0;}
 int sync_directory(int fd){assert(fd==17);calls+='s';if(interrupted){interrupted=false;errno=EINTR;return -1;}errno=sync_error;return sync_error?-1:0;}
 int close_directory(int fd){assert(fd==17);calls+='c';errno=close_error;return close_error?-1:0;}
};
int main(int argc,char**argv){
 using wmp_ui::native::finish_setup;
 assert(argc==2);
 Faults success;assert(finish_setup(success,"unused")&&success.calls=="ousc");
 Faults missing;missing.remove_error=ENOENT;assert(finish_setup(missing,"unused")&&missing.calls=="ousc");
 Faults open;open.open_error=EACCES;assert(!finish_setup(open,"unused")&&open.calls=="o");
 Faults remove;remove.remove_error=EACCES;assert(!finish_setup(remove,"unused")&&remove.calls=="ouc");
 Faults sync;sync.sync_error=EIO;assert(!finish_setup(sync,"unused")&&sync.calls=="ousc");
 // Retrying after an unlinked but unflushed marker must flush, not accept ENOENT alone.
 sync.calls.clear();sync.remove_error=ENOENT;assert(!finish_setup(sync,"unused")&&sync.calls=="ousc");
 sync.calls.clear();sync.sync_error=0;assert(finish_setup(sync,"unused")&&sync.calls=="ousc");
 Faults interrupted;interrupted.interrupted=true;assert(finish_setup(interrupted,"unused")&&interrupted.calls=="oussc");
 Faults close;close.close_error=EIO;assert(!finish_setup(close,"unused")&&close.calls=="ousc");
 const std::string directory=argv[1],marker=directory+"/need_oobe";
 int fd=::open(marker.c_str(),O_WRONLY|O_CREAT|O_EXCL,0600);assert(fd>=0);assert(::close(fd)==0);
 assert(finish_setup(directory.c_str()));assert(::access(marker.c_str(),F_OK)<0&&errno==ENOENT);
 assert(finish_setup(directory.c_str()));
 // Never treat an invalid/missing parent or a directory at the marker path as completed.
 assert(!finish_setup((directory+"/missing").c_str()));
 assert(::mkdir(marker.c_str(),0700)==0);assert(!finish_setup(directory.c_str()));
 assert(::rmdir(marker.c_str())==0);
}
