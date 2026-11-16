// SPDX-License-Identifier: GPL-3.0-or-later
#include "native/thumbnail.hpp"
#include <cassert>
using namespace wmp_ui;using namespace wmp_ui::native;
int main(int argc,char**argv){
 assert(argc==2);std::string root=argv[1],cached;
 Json metadata={{"modified",1},{"thumbnails",Json::array({{{"relative_path",".thumbs/image.png"},{"width",1},{"height",1}}})}};
 {ThumbnailCache cache;auto image=cache.load(root,"folder/part.gcode",metadata);assert(image.at("width")==1&&image.at("height")==1);cached=image.at("path");assert(::access(cached.c_str(),R_OK)==0);assert(cache.load(root,"folder/part.gcode",metadata)==image);
  auto bad=metadata;bad["thumbnails"][0]["relative_path"]="../../escape.png";assert(cache.load(root,"folder/part.gcode",bad).empty());
  bad["thumbnails"][0]["relative_path"]=".thumbs/escape.png";assert(cache.load(root,"folder/part.gcode",bad).empty());
  bad["thumbnails"][0]["relative_path"]=".thumbs/oversized.png";assert(cache.load(root,"folder/part.gcode",bad).empty());
  bad=metadata;bad["thumbnails"][0]["width"]=999999;assert(cache.load(root,"folder/part.gcode",bad).empty());
  bad=metadata;bad["thumbnails"][0]["relative_path"]=".thumbs/bad.png";assert(cache.load(root,"folder/part.gcode",bad).empty());
  for(int i=2;i<=10;++i){metadata["modified"]=i;assert(!cache.load(root,"folder/part.gcode",metadata).empty());}
  assert(::access(cached.c_str(),F_OK)!=0);cached=cache.load(root,"folder/part.gcode",metadata).at("path");
 }
 assert(::access(cached.c_str(),F_OK)!=0);
}
