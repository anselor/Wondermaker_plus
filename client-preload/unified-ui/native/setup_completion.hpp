#pragma once
#include <cerrno>
#include <fcntl.h>
#include <unistd.h>

namespace wmp_ui { namespace native {
struct SetupCompletionFilesystem {
 int open_directory(const char* path){return ::open(path,O_RDONLY|O_DIRECTORY|O_CLOEXEC);}
 int remove_marker(int directory){return ::unlinkat(directory,"need_oobe",0);}
 int sync_directory(int directory){return ::fsync(directory);}
 int close_directory(int directory){return ::close(directory);}
};

// Report completion only after the directory entry removal is durable. Sync
// even if already absent: a prior attempt may have unlinked then failed fsync.
template<class Filesystem>
bool finish_setup(Filesystem& fs,const char* directory){
 const int fd=fs.open_directory(directory);
 if(fd<0)return false;
 const bool removed=fs.remove_marker(fd)==0||errno==ENOENT;
 bool synced=false;
 if(removed){
  int result;
  do{result=fs.sync_directory(fd);}while(result<0&&errno==EINTR);
  synced=result==0;
 }
 const bool closed=fs.close_directory(fd)==0;
 return removed&&synced&&closed;
}
inline bool finish_setup(const char* directory){
 SetupCompletionFilesystem fs;
 return finish_setup(fs,directory);
}
}}
