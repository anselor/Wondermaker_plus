// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "preview.hpp"
#include <cstdio>
#include <functional>
#include <memory>
#include <set>
#include <sys/stat.h>
#include <limits.h>
#include <unistd.h>
#include <fcntl.h>
namespace wmp_ui { namespace native {
// Read-only fallback for absent slicer metadata. No inferred default tool or
// fabricated material/usage values. Runs on the cancellable preview worker.
inline Json inspect_file_tools(const std::string&root,const std::string&file,const std::function<bool()>&current,const Json&cached=Json()){
 if(!preview_path(file))throw std::runtime_error("Invalid print path");
 char base[PATH_MAX],resolved[PATH_MAX];
 if(!::realpath(root.c_str(),base)||!::realpath((root+"/"+file).c_str(),resolved))throw std::runtime_error("Print file is unavailable");
 const auto prefix=std::string(base)+"/";if(std::string(resolved).compare(0,prefix.size(),prefix)!=0)throw std::runtime_error("Print file is outside the gcode directory");
 const int fd=::open(resolved,O_RDONLY|O_NONBLOCK|O_NOFOLLOW|O_CLOEXEC);if(fd<0)throw std::runtime_error("Cannot read print file");
 FILE*opened=::fdopen(fd,"rb");if(!opened){::close(fd);throw std::runtime_error("Cannot read print file");}
 std::unique_ptr<FILE,int(*)(FILE*)>stream(opened,::fclose);
 struct stat before{},after{},path_after{};if(::fstat(::fileno(stream.get()),&before)||!S_ISREG(before.st_mode)||before.st_size<=0)throw std::runtime_error("Print file is not a nonempty regular file");
 const Json binding=Json::array({before.st_dev,before.st_ino,before.st_size,before.st_mtim.tv_sec,before.st_mtim.tv_nsec});
 if(cached.is_object()&&cached.value("filename","")==file&&cached.value("wmp_scan_stat",Json())==binding&&current()){
  if(::stat(resolved,&path_after)||Json::array({path_after.st_dev,path_after.st_ino,path_after.st_size,path_after.st_mtim.tv_sec,path_after.st_mtim.tv_nsec})!=binding)throw std::runtime_error("Print file changed during inspection");
  return cached;
 }
 std::set<unsigned>tools;std::string line;bool comment=false,overflow=false;
 auto consume=[&]{
  auto first=line.find_first_not_of(" \t\r");if(first==std::string::npos){line.clear();return;}
  auto text=line.substr(first);for(char&c:text)if(c>='a'&&c<='z')c=char(c-'a'+'A');
  auto end=text.find_first_of(" \t\r");auto command=text.substr(0,end);
  if(overflow&&(command=="START_PRINT"||(command.size()>=2&&command[0]=='T'&&((command[1]>='0'&&command[1]<='9')||command[1]=='{'))))throw std::runtime_error("Cannot inspect an oversized tool selection command");
  if(command.size()>=2&&command[0]=='T'&&((command[1]>='0'&&command[1]<='9')||command[1]=='{')){
   if(command.size()!=2||command[1]<'0'||command[1]>'3')throw std::runtime_error("Unsupported tool command; review the sliced tool selection");
   tools.insert(unsigned(command[1]-'0'));
  }
  if(command=="START_PRINT"&&end!=std::string::npos){
   std::size_t at=end;while((at=text.find_first_not_of(" \t\r",at))!=std::string::npos){auto stop=text.find_first_of(" \t\r",at);auto token=text.substr(at,stop==std::string::npos?stop:stop-at);
    if(token.compare(0,13,"INITIAL_TOOL=")==0){if(token.size()!=14||token[13]<'0'||token[13]>'3')throw std::runtime_error("Cannot determine INITIAL_TOOL");tools.insert(unsigned(token[13]-'0'));}
    if(stop==std::string::npos)break;
    at=stop;
   }
  }
  line.clear();
 };
 char buffer[65536];for(;;){if(!current())throw std::runtime_error("Preview selection changed");auto count=::fread(buffer,1,sizeof(buffer),stream.get());
  for(std::size_t i=0;i<count;++i){const char c=buffer[i];if(c=='\n'){consume();comment=overflow=false;}else if(c==';'||c=='#')comment=true;else if(!comment){if(line.size()<4096)line+=c;else overflow=true;}}
  if(count<sizeof(buffer)){if(::ferror(stream.get()))throw std::runtime_error("Print file read failed");break;}
 }
 consume();
 auto same=[&](const struct stat&s){return s.st_dev==before.st_dev&&s.st_ino==before.st_ino&&s.st_size==before.st_size&&s.st_mtim.tv_sec==before.st_mtim.tv_sec&&s.st_mtim.tv_nsec==before.st_mtim.tv_nsec;};
 if(!current()||::fstat(::fileno(stream.get()),&after)||::stat(resolved,&path_after)||!same(after)||!same(path_after))throw std::runtime_error("Print file changed during inspection");
 if(tools.empty())throw std::runtime_error("No explicit tool selection found in the print file");
 Json indices=Json::array();for(auto tool:tools)indices.push_back(tool);
 return {{"filename",file},{"size",before.st_size},{"modified",double(before.st_mtim.tv_sec)+double(before.st_mtim.tv_nsec)/1.e9},{"wmp_used_tools",indices},{"wmp_scan_stat",binding}};
}
}}
