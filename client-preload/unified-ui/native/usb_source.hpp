// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "preview.hpp"
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
namespace wmp_ui { namespace native {
// Worker-only inspection beneath the configured USB root. The root itself may
// be a vendor mount symlink; selected path components must not be symlinks.
inline Json inspect_usb_source(const std::string&root,const std::string&path){
 if(root.empty()||root.front()!='/'||!preview_path(path))throw std::runtime_error("Invalid USB source");
 struct Handle{int fd;explicit Handle(int value):fd(value){}~Handle(){if(fd>=0)::close(fd);}};
 Handle current(::open(root.c_str(),O_RDONLY|O_DIRECTORY|O_CLOEXEC));
 if(current.fd<0)throw std::runtime_error("USB root unavailable");
 std::size_t start=0;
 for(;;){
  auto end=path.find('/',start);const bool last=end==std::string::npos;
  const auto part=path.substr(start,last?end:end-start);
  const int next=::openat(current.fd,part.c_str(),O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK|(last?0:O_DIRECTORY));
  if(next<0)throw std::runtime_error("USB file unavailable");
  ::close(current.fd);current.fd=next;
  if(last)break;
  start=end+1;
 }
 struct stat info{};
 if(::fstat(current.fd,&info)||!S_ISREG(info.st_mode)||info.st_size<=0)throw std::runtime_error("USB source is not a nonempty regular file");
 return {{"state","ready"},{"path",path},{"size",info.st_size},{"device",info.st_dev},{"inode",info.st_ino},
         {"modified",info.st_mtim.tv_sec},{"modified_ns",info.st_mtim.tv_nsec}};
}
}}
