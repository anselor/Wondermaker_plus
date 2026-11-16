// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "preview.hpp"
#include <fstream>
#include <unistd.h>
#include <limits.h>
#include <cstdlib>
#include <sys/stat.h>
namespace wmp_ui { namespace native {
// Worker-only immutable PNG copies. LVGL's existing PNG decoder reads these;
// no network, metadata parsing, or original file access occurs in GUI callbacks.
class ThumbnailCache {
public:
 ~ThumbnailCache(){for(const auto&path:paths_)::unlink(path.c_str());}
 Json load(const std::string&root,const std::string&file,const Json&metadata){
  auto list=metadata.value("thumbnails",Json::array());if(!list.is_array()||list.size()>32)return Json::object();
  std::vector<Json> candidates;for(const auto&t:list)if(t.is_object()&&t.contains("relative_path")&&t["relative_path"].is_string()&&t.contains("width")&&t["width"].is_number_integer()&&t.contains("height")&&t["height"].is_number_integer()){
   int w=t["width"].get<int>(),h=t["height"].get<int>();if(w>0&&h>0&&w<=800&&h<=800)candidates.push_back(t);
  }
  std::sort(candidates.begin(),candidates.end(),[](const Json&a,const Json&b){return a["width"].get<int>()*a["height"].get<int>()>b["width"].get<int>()*b["height"].get<int>();});
  for(const auto&t:candidates){auto relative=t["relative_path"].get<std::string>();auto slash=file.rfind('/');if(slash!=std::string::npos)relative=file.substr(0,slash+1)+relative;
   if(!preview_path(relative)||relative.size()<4||relative.substr(relative.size()-4)!=".png")continue;
   char canonical_root[PATH_MAX],canonical_file[PATH_MAX];if(!::realpath(root.c_str(),canonical_root)||!::realpath((root+"/"+relative).c_str(),canonical_file))continue;
   auto prefix=std::string(canonical_root)+"/";auto path=std::string(canonical_file);if(path.compare(0,prefix.size(),prefix)!=0)continue;
   auto key=revision(Json{{"path",path},{"file",file},{"modified",metadata.value("modified",Json())},{"thumbnail",t}});
   if(key==key_&&!last_.empty()&&::access(last_.at("path").get<std::string>().c_str(),R_OK)==0)return last_;
   struct stat info{};if(::stat(path.c_str(),&info)||!S_ISREG(info.st_mode)||info.st_size<33||info.st_size>1024*1024)continue;
   std::ifstream in(path,std::ios::binary);if(!in)continue;std::vector<unsigned char>data(1024*1024+1);in.read(reinterpret_cast<char*>(data.data()),data.size());data.resize(std::size_t(in.gcount()));
   if(data.size()<33||data.size()>1024*1024)continue;
   const unsigned char magic[]={137,80,78,71,13,10,26,10};if(!std::equal(magic,magic+8,data.begin())||std::string(data.begin()+12,data.begin()+16)!="IHDR")continue;
   auto word=[&](int i){return (std::uint32_t(data[i])<<24)|(std::uint32_t(data[i+1])<<16)|(std::uint32_t(data[i+2])<<8)|data[i+3];};
   auto w=word(16),h=word(20);if(word(8)!=13||w==0||h==0||w>800||h>800)continue;
   char tmp[]="/tmp/wmp-ui-thumb-XXXXXX.png";int fd=::mkstemps(tmp,4);if(fd<0)continue;
   bool ok=true;std::size_t offset=0;while(offset<data.size()){auto n=::write(fd,data.data()+offset,data.size()-offset);if(n<=0){ok=false;break;}offset+=std::size_t(n);}if(::close(fd))ok=false;
   if(!ok){::unlink(tmp);continue;}
   paths_.push_back(tmp);if(paths_.size()>8){::unlink(paths_.front().c_str());paths_.erase(paths_.begin());}
   key_=key;last_={{"path",std::string(tmp)},{"width",w},{"height",h}};return last_;
  }
  return Json::object();
 }
private:std::string key_;Json last_;std::vector<std::string>paths_;
};
}}
